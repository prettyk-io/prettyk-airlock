# -*- coding: utf-8 -*-
"""COS-155: PK-C-003.6 — SBOM-инвентарь cosmo-api (syft/grype vs python-inventory).

Слой ledger для self-inventory самой cosmoport-API (НЕ релизного бандла —
для того есть COS-099 ``transfer/sbom.py`` и COS-138 ``ledger/sbom_gate.py``):

  - ``generate_sbom_inventory`` — SBOM (CycloneDX 1.5) + grype-визор.
    syft (CycloneDX) если бинарник доступен, иначе честный
    ``python-inventory`` (``importlib.metadata``); grype через
    ``transfer.sbom.generate_vuln_report`` (offline, нет сети).
  - ``store_sbom_inventory`` — единственный источник истины для чтения:
    упаковка в ``evidence_ledger`` с якорем ``run_id`` (NOT NULL FK).
  - ``latest_sbom_inventory`` — durable read по ``bundle_id`` (latest wins),
    с крипто-проверкой ``content_hash`` документа.

Инварианты (по образцу COS-142 manifest_verifier):
  - ``run_id`` — NOT NULL FK на ``runs.id``; без валидного прогона запись не
    создаётся (422) — нечем якорить durable read;
  - read-path переживает рестарт cosmo-api (in-memory реестра нет);
  - grype отсутствует → ``vuln_summary.available=false`` + ``reason`` (честно,
    НЕ фейковый пустой отчёт).
"""
from __future__ import annotations

import json
import shutil
import subprocess
import uuid
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.cosmo.db.models import EvidenceLedgerEntry, Run
from orchestrator.cosmo.domain.sbom_inventory import (
    BOM_FORMAT,
    PYTHON_INVENTORY_GENERATOR,
    SPEC_VERSION,
    SYFT_GENERATOR,
    SbomInventoryComponent,
    SbomInventoryDocument,
    SbomInventoryRequest,
    SbomInventoryVulnerability,
    SbomVulnSummary,
    normalize_severity,
    parse_grype_report,
    python_inventory_components,
    sbom_inventory_content_hash,
)
from orchestrator.cosmo.ledger.evidence_writer import commit_evidence_entry

#: Маркер источника записи в ``provenance_json``.
SBOM_INVENTORY_SOURCE = "cosmo-sbom-inventory"

#: Маркер типа записи (``provenance_json.sbom_type``).
SBOM_INVENTORY_TYPE = "SBOM_INVENTORY"

#: Контракт, которому подчиняется инвентарь.
SBOM_INVENTORY_CONTRACT = "PK-C-003.6"


class SbomInventoryStoreError(ValueError):
    """Ошибка хранения SBOM-инвентаря (нет прогона-якоря и т.п.)."""


def _generate_syft_document(
    target: str,
    *,
    syft_path: Optional[str] = None,
    timeout: int = 300,
) -> tuple[dict[str, Any], str, str] | None:
    """Попытаться снять реальный SBOM через syft CLI (CycloneDX 1.5).

    Возвращает ``(document, tool_name, tool_version)`` либо ``None``, если
    syft недоступен/упал — тогда честный python-inventory fallback.
    """
    exe = syft_path or shutil.which("syft")
    if not exe:
        return None
    try:
        proc = subprocess.run(
            [exe, target, "-o", "cyclonedx-json"],
            capture_output=True, text=True, timeout=timeout, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0 or not proc.stdout.strip():
        return None
    try:
        doc = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return None
    if not isinstance(doc, dict) or doc.get("bomFormat") != "CycloneDX":
        return None
    tool_name = "syft"
    tool_version = ""
    try:
        ver = subprocess.run(
            [exe, "version"], capture_output=True, text=True, timeout=30,
            check=False,
        )
        if ver.returncode == 0 and ver.stdout.strip():
            tool_version = ver.stdout.strip().splitlines()[0].strip()
    except (OSError, subprocess.TimeoutExpired):
        tool_version = ""
    return doc, tool_name, tool_version


def _components_from_syft(document: dict[str, Any]) -> list[SbomInventoryComponent]:
    """Вытащить components из CycloneDX-документа syft."""
    out: list[SbomInventoryComponent] = []
    for raw in (document.get("components") or []):
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("name") or "").strip()
        if not name:
            continue
        out.append(SbomInventoryComponent(
            type=str(raw.get("type") or "library"),
            name=name,
            version=str(raw.get("version") or ""),
            purl=str(raw.get("purl")) if raw.get("purl") else None,
        ))
    return out


def _vulnerabilities_from_syft(
    document: dict[str, Any],
) -> tuple[list[SbomInventoryVulnerability], SbomVulnSummary]:
    """Вытащить vulnerabilities из CycloneDX (syft/grype-in-sbom).

    CycloneDX 1.5 вкладывает ``vulnerabilities[]`` из grype-плагина syft;
    если раздела нет — честно пустой список. Severity нормализуется через
    общий ``normalize_severity``.
    """
    vulns: list[SbomInventoryVulnerability] = []
    for raw in (document.get("vulnerabilities") or []):
        if not isinstance(raw, dict):
            continue
        vid = str(raw.get("id") or "").strip()
        if not vid:
            continue
        ratings = raw.get("ratings") or []
        sev = ""
        if ratings and isinstance(ratings[0], dict):
            sev = str(ratings[0].get("severity") or "")
        affects = raw.get("affects") or []
        package_name = ""
        installed_version = ""
        if affects and isinstance(affects[0], dict):
            ref = affects[0].get("ref") or ""
            package_name = str(ref)
        vulns.append(SbomInventoryVulnerability(
            id=vid,
            severity=normalize_severity(sev),
            package_name=package_name,
            installed_version=installed_version,
        ))
    counts = {s: 0 for s in ("critical", "high", "medium", "low")}
    for v in vulns:
        if v.severity in counts:
            counts[v.severity] += 1
    summary = SbomVulnSummary(
        available=True,
        total=len(vulns),
        critical=counts["critical"],
        high=counts["high"],
        medium=counts["medium"],
        low=counts["low"],
    )
    return vulns, summary


def generate_sbom_inventory(
    request: SbomInventoryRequest,
    *,
    syft_path: Optional[str] = None,
    grype_path: Optional[str] = None,
    grype_db_dir: Optional[str] = None,
    timeout: int = 300,
) -> tuple[SbomInventoryDocument, list[str]]:
    """Снять SBOM-инвентарь + grype-визор для cosmo-api.

    Возвращает ``(document, warnings)``. Порядок:

      1. syft (CycloneDX) — если доступен, реальный скан ``target``;
      2. иначе честный ``python-inventory`` (``importlib.metadata``);
      3. grype — через ``transfer.sbom.generate_vuln_report`` (offline);
         если недоступен → ``vuln_summary.available=false`` + reason.

    ``warnings`` — диагностика для аудита (не ошибки): недоступность
    инструментов фиксируется маркерами внутри документа, а не исключениями.
    """
    warnings: list[str] = []

    document: SbomInventoryDocument
    vuln_summary: SbomVulnSummary
    vulnerabilities: list[SbomInventoryVulnerability]

    components: list[SbomInventoryComponent]
    generator: str = PYTHON_INVENTORY_GENERATOR
    tool_name: str = ""
    tool_version: str = ""
    metadata_component: dict[str, Any] = {}

    target = request.target or "."
    syft_doc = _generate_syft_document(
        target, syft_path=syft_path, timeout=timeout,
    )
    sbom_payload: dict[str, Any]
    if syft_doc is not None:
        (raw_doc, tool_name, tool_version) = syft_doc
        generator = SYFT_GENERATOR
        components = _components_from_syft(raw_doc)
        sbom_payload = raw_doc
        meta_comp = (raw_doc.get("metadata") or {}).get("component") or {}
        metadata_component = dict(meta_comp) if isinstance(meta_comp, dict) else {}
        # Если syft уже вложил grype-results — берём их; иначе честно пусто,
        # а grype ниже догонит настоящий отчёт.
        vulnerabilities, vuln_summary = _vulnerabilities_from_syft(raw_doc)
    else:
        components = python_inventory_components()
        generator = PYTHON_INVENTORY_GENERATOR
        tool_name = "python-inventory"
        tool_version = ""
        metadata_component = {
            "type": "application",
            "name": request.app_name,
            "version": request.version,
        }
        sbom_payload = {
            "bomFormat": BOM_FORMAT,
            "specVersion": SPEC_VERSION,
            "version": 1,
            "components": [c.model_dump(mode="json") for c in components],
        }
        vulnerabilities = []
        vuln_summary = SbomVulnSummary(available=False, reason="grype not available")
        warnings.append(
            "syft binary not found or failed; python-inventory used"
        )

    # grype-визор: гоним итоговый SBOM через grype (offline). Нет бинарника →
    # честный ``available=false`` с reason (НЕ фейковый пустой список).
    grype_result = _run_grype(
        sbom_payload,
        grype_path=grype_path,
        db_dir=grype_db_dir,
        timeout=timeout,
    )
    if grype_result.source == "grype":
        vulnerabilities, vuln_summary = parse_grype_report(grype_result.report)
    else:
        vuln_summary = SbomVulnSummary(available=False, reason=grype_result.reason)
        warnings.append(f"grype unavailable: {vuln_summary.reason}")

    if metadata_component and not metadata_component.get("name"):
        metadata_component["name"] = request.app_name
        metadata_component["type"] = "application"
        metadata_component["version"] = request.version

    serial = f"urn:uuid:{uuid.uuid4()}"
    document = SbomInventoryDocument(
        serial_number=serial,
        generator=generator,
        tool_name=tool_name,
        tool_version=tool_version,
        metadata=metadata_component,
        components=components,
        vulnerabilities=vulnerabilities,
        vuln_summary=vuln_summary,
    )

    return document, warnings


def _run_grype(
    sbom_payload: dict[str, Any],
    *,
    grype_path: Optional[str] = None,
    db_dir: Optional[str] = None,
    timeout: int = 600,
):
    """Гнать SBOM-payload через grype (offline) — reuse transfer.sbom.

    Возвращает ``VulnReportResult`` (``.source`` — ``grype`` | ``none``,
    ``.reason`` — причина недоступности). gбина отсутствует → честный
    ``source="none"``, НЕ фейковый пустой отчёт.
    """
    from orchestrator.cosmo.transfer.sbom import generate_vuln_report

    return generate_vuln_report(
        sbom_payload, grype_path=grype_path, db_dir=db_dir, timeout=timeout,
    )


def _document_to_provenance(bundle_id: str, doc: SbomInventoryDocument) -> dict[str, Any]:
    """Упаковать документ в provenance-json ledger-записи."""
    payload = doc.model_dump(mode="json", by_alias=True)
    return {
        "source": SBOM_INVENTORY_SOURCE,
        "contract": SBOM_INVENTORY_CONTRACT,
        "sbom_type": SBOM_INVENTORY_TYPE,
        "bundle_id": bundle_id,
        "document": payload,
        "content_hash": sbom_inventory_content_hash(doc),
    }


async def store_sbom_inventory(
    session: AsyncSession,
    bundle_id: str,
    document: SbomInventoryDocument,
    run_id: str,
) -> str:
    """Запечатать SBOM-инвентарь в evidence ledger (якорь ``run_id``).

    ``run_id`` — NOT NULL FK на ``runs.id``: без существующего прогона запись
    не создаётся (``SbomInventoryStoreError`` → route 422). Возвращает
    ``ledger_entry_id``.
    """
    run = await session.get(Run, run_id)
    if run is None:
        raise SbomInventoryStoreError(
            f"run '{run_id}' not found to anchor sbom-inventory entry"
        )

    content_hash = sbom_inventory_content_hash(document)
    provenance = _document_to_provenance(bundle_id, document)

    entry = EvidenceLedgerEntry(
        run_id=run_id,
        batch_id=None,
        type="decision",
        content_ref=f"bundle://{bundle_id}/sbom/{content_hash[:16]}",
        content_hash=content_hash,
        provenance_json=provenance,
    )
    await commit_evidence_entry(session, entry)
    return entry.id


def _document_from_provenance(provenance: dict) -> SbomInventoryDocument | None:
    """Реконструировать SBOM-документ из ledger-provenance + crypto-проверка.

    ``None``, если запись неполна/испорчена или ``content_hash`` не сходится
    с пересчитанным — чтение честно отказывает.
    """
    from pydantic import ValidationError

    try:
        raw_doc = provenance.get("document")
        if not isinstance(raw_doc, dict):
            return None
        document = SbomInventoryDocument.model_validate(raw_doc)
    except (ValidationError, KeyError, TypeError):
        return None
    if sbom_inventory_content_hash(document) != provenance.get("content_hash"):
        return None
    return document


async def latest_sbom_inventory(
    session: AsyncSession, bundle_id: str,
) -> SbomInventoryDocument | None:
    """Актуальный SBOM-инвентарь бандла из ledger (latest wins).

    Единственный read-path: in-memory реестра нет, ответ переживает рестарт
    cosmo-api. ``None`` — инвентарь не якорён.
    """
    stmt = (
        select(EvidenceLedgerEntry)
        .where(EvidenceLedgerEntry.type == "decision")
        .where(
            EvidenceLedgerEntry.provenance_json["source"].astext
            == SBOM_INVENTORY_SOURCE
        )
        .where(
            EvidenceLedgerEntry.provenance_json["sbom_type"].astext
            == SBOM_INVENTORY_TYPE
        )
        .where(
            EvidenceLedgerEntry.provenance_json["bundle_id"].astext == bundle_id
        )
        .order_by(
            EvidenceLedgerEntry.created_at.desc(),
            EvidenceLedgerEntry.id.desc(),
        )
        .limit(1)
    )
    row = (await session.execute(stmt)).scalars().first()
    if row is None:
        return None
    return _document_from_provenance(dict(row.provenance_json or {}))