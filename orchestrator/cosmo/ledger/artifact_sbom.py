# -*- coding: utf-8 -*-
"""COS-167: PK-C-003.6 / DOCKER_AUDIT — SBOM поверх образа (durable ledger).

Закрывает шаг ``sbom`` профиля ``DOCKER_AUDIT`` (``evidence_required=True``):
после канонического push образа (COS-162/163) снимается SBOM (CycloneDX 1.5)
и привязывается к durable ``ArtifactRecord.sbom_ref``.

Поток:
  1. актуальный ``ArtifactRecord`` читается из ledger (latest wins, COS-163) —
     digest не передаётся клиентом и не выдумывается;
  2. SBOM генерится ``generate_sbom_inventory`` (COS-155): syft → честный
     ``python-inventory`` fallback (НИКОГДА фейковая syft-подпись);
  3. SBOM запечатывается отдельной записью Evidence Ledger
     (``source='cosmo-artifact-sbom'``, ``type='decision'``,
     ``content_hash = sbom_inventory_content_hash``);
  4. ``ArtifactRecord.sbom_ref`` указывает на якорь — durable-перезапись
     (latest wins) той же записи артефакта с проставленным ``sbom_ref``.

Digest-сверка держится by-construction: SBOM-запись несёт ``artifact_digest``
актуального ``ArtifactRecord``, а read-path пересчитывает ``content_hash``
документа (подмена payload ловится).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.cosmo.db.models import EvidenceLedgerEntry
from orchestrator.cosmo.domain.artifact_record import ArtifactRecord
from orchestrator.cosmo.domain.artifact_sbom import ArtifactSbomResponse
from orchestrator.cosmo.domain.sbom_inventory import (
    SbomInventoryDocument,
    SbomInventoryRequest,
    sbom_inventory_content_hash,
)
from orchestrator.cosmo.ledger.artifact_record import (
    latest_artifact_record,
    record_artifact_record,
)
from orchestrator.cosmo.ledger.evidence_writer import commit_evidence_entry
from orchestrator.cosmo.ledger.sbom_inventory import generate_sbom_inventory

#: Маркер источника записи в ``provenance_json``.
ARTIFACT_SBOM_SOURCE = "cosmo-artifact-sbom"

#: Маркер типа записи (``provenance_json.artifact_type``).
ARTIFACT_SBOM_TYPE = "ARTIFACT_SBOM"


class ArtifactSbomError(ValueError):
    """Ошибка генерации/якорения SBOM образа (нет durable-записи и т.п.)."""


def compute_sbom_ref(record: ArtifactRecord) -> str:
    """Канонический ``sbom_ref`` для образа — оci-ссылка на SBOM-якорь.

    ``oci://<qualified>@<digest>#sbom`` — детерминированная строка, читаемая
    после рестарта; digest неподвижен (identity образа).
    """
    return f"oci://{record.qualified_image()}@{record.digest}#sbom"


def generate_artifact_sbom(
    record: ArtifactRecord,
    *,
    syft_path: str | None = None,
    timeout: int = 300,
) -> tuple[SbomInventoryDocument, list[str]]:
    """Снять SBOM поверх образа: syft → python-inventory fallback (COS-155).

    Возвращает ``(document, warnings)``. ``target`` = qualified image ref —
    используется syft'ом, если он доступен; при fallback (python-inventory)
    document честно помечается ``generator=='python-inventory'``.
    """
    request = SbomInventoryRequest(
        bundle_id=f"{record.name}-{record.version}",
        run_id=record.run_id or "unset",  # NOT NULL FK на runs.id в store-пути
        app_name=record.name,
        version=record.version,
        target=f"{record.qualified_image()}@{record.digest}",
    )
    return generate_sbom_inventory(request, syft_path=syft_path, timeout=timeout)


async def store_artifact_sbom(
    session: AsyncSession,
    record: ArtifactRecord,
    document: SbomInventoryDocument,
    sbom_ref: str,
) -> str:
    """Запечатать SBOM образа в Evidence Ledger (durable decision-запись).

    Возвращает entry id. ``run_id`` — NOT NULL FK на ``runs.id``; якорь пишется
    каноническим ``commit_evidence_entry`` (append → seal → commit → publish_head).
    """
    content_hash = sbom_inventory_content_hash(document)
    entry = EvidenceLedgerEntry(
        run_id=record.run_id,
        batch_id=record.batch_id,
        type="decision",
        content_ref=f"oci://{record.qualified_image()}@{record.digest}/sbom/{content_hash[:16]}",
        content_hash=content_hash,
        provenance_json={  # type: ignore[arg-type]
            "source": ARTIFACT_SBOM_SOURCE,
            "artifact_type": ARTIFACT_SBOM_TYPE,
            "name": record.name,
            "version": record.version,
            "artifact_digest": record.digest,
            "canonical_ref": record.canonical_ref(),
            "sbom_ref": sbom_ref,
            "generator": document.generator,
            "tool_name": document.tool_name,
            "tool_version": document.tool_version,
            "document": document.model_dump(mode="json", by_alias=True),
            "content_hash": content_hash,
            "run_id": record.run_id,
            "batch_id": record.batch_id,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    return await commit_evidence_entry(session, entry)


async def anchor_artifact_sbom(
    session: AsyncSession,
    name: str,
    version: str,
    *,
    syft_path: str | None = None,
    timeout: int = 300,
) -> ArtifactSbomResponse:
    """Снять + заякорить SBOM поверх образа, проставив ``ArtifactRecord.sbom_ref``.

    Полный шаг ``sbom`` профиля ``DOCKER_AUDIT``: читает актуальный
    ``ArtifactRecord``, генерирует SBOM, запечатывает его в ledger и
    переписывает запись артефакта со ``sbom_ref`` (latest wins). Возвращает
    response с документом и происхождением.
    """
    record = await latest_artifact_record(session, name, version)
    if record is None:
        raise ArtifactSbomError(
            f"no durable artifact record for '{name}:{version}' to anchor SBOM"
        )
    if not record.run_id:
        raise ArtifactSbomError(
            f"artifact record '{name}:{version}' has no run_id to anchor SBOM"
        )

    document, _warnings = generate_artifact_sbom(
        record, syft_path=syft_path, timeout=timeout,
    )
    sbom_ref = compute_sbom_ref(record)
    content_hash = sbom_inventory_content_hash(document)

    await store_artifact_sbom(session, record, document, sbom_ref)

    # Durable-перезапись записи артефакта со ссылкой на SBOM (latest wins).
    updated = record.model_copy(update={"sbom_ref": sbom_ref})
    await record_artifact_record(session, updated)

    return ArtifactSbomResponse(
        name=name,
        version=version,
        artifact_digest=record.digest,
        canonical_ref=record.canonical_ref(),
        sbom_ref=sbom_ref,
        generator=document.generator,
        tool_name=document.tool_name,
        tool_version=document.tool_version,
        content_hash=content_hash,
        document=document,
    )


def _document_from_provenance(provenance: dict) -> SbomInventoryDocument | None:
    """Реконструировать SBOM-документ из ledger-provenance + crypto-проверка."""
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


async def latest_artifact_sbom(
    session: AsyncSession, name: str, version: str,
) -> SbomInventoryDocument | None:
    """Актуальный SBOM образа из ledger (latest wins, restart-survival).

    Единственный read-path: in-memory реестра нет. ``None`` — SBOM не якорён.
    """
    stmt = (
        select(EvidenceLedgerEntry)
        .where(EvidenceLedgerEntry.type == "decision")
        .where(
            EvidenceLedgerEntry.provenance_json["source"].astext
            == ARTIFACT_SBOM_SOURCE
        )
        .where(
            EvidenceLedgerEntry.provenance_json["artifact_type"].astext
            == ARTIFACT_SBOM_TYPE
        )
        .where(EvidenceLedgerEntry.provenance_json["name"].astext == name)
        .where(EvidenceLedgerEntry.provenance_json["version"].astext == version)
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


async def sbom_ref_for_artifact(
    session: AsyncSession, name: str, version: str,
) -> str | None:
    """``sbom_ref`` актуального образа из ledger (если SBOM заякорён)."""
    record = await latest_artifact_record(session, name, version)
    if record is None:
        return None
    return record.sbom_ref


__all__ = [
    "ARTIFACT_SBOM_SOURCE",
    "ARTIFACT_SBOM_TYPE",
    "ArtifactSbomError",
    "compute_sbom_ref",
    "generate_artifact_sbom",
    "store_artifact_sbom",
    "anchor_artifact_sbom",
    "latest_artifact_sbom",
    "sbom_ref_for_artifact",
]