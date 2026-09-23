# -*- coding: utf-8 -*-
"""COS-168: PK-C-003.6 / DOCKER_AUDIT — Trivy container scan + gate (ledger).

Шаг ``trivy`` профиля ``DOCKER_AUDIT`` (``gates_required=True``): скан образа
(trivy, честный ``unavailable`` при отсутствии инструмента) → durable
gate-вердикт (``pass``/``block``), который читает ``deploy_release``.

Гейт по канону COS-138 Grype-gate:
  1. **digest-сверка** — ``artifact_digest`` конверта = ``scan.artifact_digest``
     и = digest'у durable ``ArtifactRecord`` прогонов релиза. Рассинхрон → 422.
  2. **порог** — ``critical = max(заявленный, наблюдаемый в findings)``;
     ``critical > 0`` → ``BLOCK``/``DENIED``, иначе ``PASS``/``CLEARED``.
  3. **якорь** — decision запечатывается в ``evidence_ledger``
     (``type='decision'``, ``content_hash = sha256(scan)``, ``provenance_json``
     с привязкой ``release_id`` + ``artifact_digest``) через канонический
     ``commit_evidence_entry`` (как COS-138: gates-таблицу НЕ пишем — единый
     источник вердикта для deploy — Evidence Ledger).

Честная граница: гейт смотрит записи ``source='cosmo-trivy-gate'``. Deploy
материализуется ТОЛЬКО при ``PASS``; ``BLOCK``/отсутствие решения → 409.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.cosmo.db.models import (
    EvidenceLedgerEntry,
    Release as ReleaseModel,
)
from orchestrator.cosmo.domain.artifact_record import ArtifactRecord
from orchestrator.cosmo.domain.artifact_scan import (
    TrivyGateAttachRequest,
    TrivyGateAttestationResponse,
    TrivyScanReport,
    observed_severity_count,
    resolve_normalized_digests,
    trivy_scan_content_hash,
)
from orchestrator.cosmo.domain.sbom_scan import normalize_digest
from orchestrator.cosmo.ledger.artifact_record import artifact_records_for_run_ids
from orchestrator.cosmo.ledger.evidence_writer import commit_evidence_entry

#: Маркер источника в ``provenance_json``.
TRIVY_SOURCE = "cosmo-trivy-gate"

#: Версия контракта PK-C-003.6.
TRIVY_CONTRACT = "PK-C-003.6"

_TRIVY_SEV_MAP = {
    "critical": "critical",
    "high": "high",
    "medium": "medium",
    "moderate": "medium",
    "low": "low",
    "negligible": "negligible",
    "unknown": "low",
    "informational": "low",
    "info": "low",
}

Runner = Any  # subprocess.run-совместимый (инъекция в тестах)


class TrivyGateError(ValueError):
    """Нарушение trivy-gate; ``status_code`` — HTTP-маппинг."""

    status_code = 422


class TrivyReleaseNotFoundError(TrivyGateError):
    """Релиз не найден."""

    status_code = 404


class TrivyDigestMismatchError(TrivyGateError):
    """artifact_digest конверта/отчёта/образа не совпадают."""

    status_code = 422


# ══════════════════════════════════════════════════════════════════
# Trivy runner (offline, честный fallback)
# ══════════════════════════════════════════════════════════════════

class TrivyRunResult:
    """Результат прогона trivy. ``source='none'`` — инструмент недоступен (не фейк)."""

    def __init__(self, report: dict[str, Any], source: str,
                 tool_version: str = "", reason: str = ""):
        self.report = report
        self.source = source                 # trivy | none
        self.tool_version = tool_version
        self.reason = reason

    @property
    def available(self) -> bool:
        return self.source == "trivy"


def run_trivy_scan(
    image_ref: str,
    *,
    trivy_path: Optional[str] = None,
    runner: Optional[Runner] = None,
    timeout: int = 600,
) -> TrivyRunResult:
    """Прогнать trivy по образу. Никакой сети: ``--skip-db-update``.

    Нет бинарника/вывод невалиден → ``source='none'`` с reason (честно,
    НИКОГДА фейковый отчёт).
    """
    run = runner or subprocess.run
    exe = trivy_path or shutil.which("trivy")
    if exe is None and runner is not None:
        exe = "trivy"
    if not exe:
        return TrivyRunResult(
            {"status": "unavailable", "tool": "trivy",
             "reason": "trivy binary not found"},
            source="none", reason="trivy binary not found")
    try:
        proc = run(
            [exe, "image", "--skip-db-update", "--format", "json", image_ref],
            capture_output=True, text=True, timeout=timeout, check=False,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            doc = json.loads(proc.stdout)
            if isinstance(doc, dict):
                return TrivyRunResult(doc, source="trivy")
        tail = (proc.stderr or proc.stdout or "")[-200:]
        return TrivyRunResult(
            {"status": "unavailable", "tool": "trivy", "reason": tail},
            source="none", reason=f"trivy failed (rc={proc.returncode}): {tail}")
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
        return TrivyRunResult(
            {"status": "unavailable", "tool": "trivy", "reason": str(exc)},
            source="none", reason=f"trivy unavailable: {exc}")


def parse_trivy_report(
    raw: dict[str, Any], artifact_digest: str,
) -> TrivyScanReport:
    """Разобрать trivy JSON (``Results[].Vulnerabilities[]``) → DTO.

    Severity нормализуется в закрытый набор; counts честно пересчитываются
    из findings (не доверяем полю ``critical_count`` внешнего инструмента).
    """
    from orchestrator.cosmo.domain.artifact_scan import TrivyFinding

    findings: list[TrivyFinding] = []
    for result in (raw.get("Results") or []):
        if not isinstance(result, dict):
            continue
        for vuln in (result.get("Vulnerabilities") or []):
            if not isinstance(vuln, dict):
                continue
            vid = str(vuln.get("VulnerabilityID") or "").strip()
            if not vid:
                continue
            sev = _TRIVY_SEV_MAP.get(
                str(vuln.get("Severity") or "").strip().lower(), "low",
            )
            findings.append(TrivyFinding(
                id=vid,
                severity=sev,
                package_name=str(vuln.get("PkgName") or "unknown"),
                installed_version=str(vuln.get("InstalledVersion") or ""),
                fixed_version=str(vuln.get("FixedVersion")) if vuln.get("FixedVersion") else None,
            ))
    counts = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    for f in findings:
        if f.severity in counts:
            counts[f.severity] += 1
    return TrivyScanReport(
        scanner_version="",
        artifact_digest=artifact_digest,
        critical_count=counts["critical"],
        high_count=counts["high"],
        medium_count=counts["medium"],
        low_count=counts["low"],
        findings=findings,
    )


# ══════════════════════════════════════════════════════════════════
# Gate: verify + attest
# ══════════════════════════════════════════════════════════════════

def _build_provenance(
    rel: ReleaseModel,
    want: str,
    verdict: str,
    clearance: str,
    critical: int,
    scan: TrivyScanReport,
    scan_hash: str,
) -> dict:
    return {
        "source": TRIVY_SOURCE,
        "contract": TRIVY_CONTRACT,
        "release_id": rel.id,
        "run_id": (rel.run_ids or [None])[0],
        "artifact_digest": want,
        "gate_verdict": verdict,
        "clearance": clearance,
        "critical_count": critical,
        "reported_critical_count": scan.critical_count,
        "observed_critical_count": observed_severity_count(scan, "critical"),
        "high_count": scan.high_count,
        "medium_count": scan.medium_count,
        "low_count": scan.low_count,
        "findings_total": len(scan.findings),
        "scanner_version": scan.scanner_version,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    }


async def verify_and_attest_trivy_gate(
    session: AsyncSession,
    release_id: str,
    payload: TrivyGateAttachRequest,
) -> TrivyGateAttestationResponse:
    """Проверить + аттестовать trivy-скан образа релиза.

    Raises:
        TrivyReleaseNotFoundError: релиз не существует.
        TrivyDigestMismatchError: digest'ы конверта/отчёта/образа расходятся.
        TrivyGateError: у релиза нет прогонов/образов — нечем якорить.
    """
    rel = await session.get(ReleaseModel, release_id)
    if rel is None:
        raise TrivyReleaseNotFoundError(f"Release '{release_id}' not found")

    want, scan_digest = resolve_normalized_digests(
        payload.artifact_digest, payload.scan.artifact_digest,
    )
    if want != scan_digest:
        raise TrivyDigestMismatchError(
            f"artifact_digest mismatch: request={want} scan={scan_digest}"
        )

    records = await artifact_records_for_run_ids(
        session, list(rel.run_ids or []),
    )
    pinned = {normalize_digest(r.digest) for r in records}
    if not pinned:
        raise TrivyGateError(
            f"Release '{release_id}' has no durable artifact records to anchor "
            "trivy gate"
        )
    if want not in pinned:
        raise TrivyDigestMismatchError(
            f"artifact_digest {want} does not match release artifact digests "
            f"{sorted(pinned)}"
        )

    critical = max(
        payload.scan.critical_count,
        observed_severity_count(payload.scan, "critical"),
    )
    verdict = "BLOCK" if critical > 0 else "PASS"
    clearance = "DENIED" if critical > 0 else "CLEARED"
    scan_hash = trivy_scan_content_hash(payload.scan)

    run_ids = list(rel.run_ids or [])
    provenance = _build_provenance(
        rel, want, verdict, clearance, critical, payload.scan, scan_hash,
    )
    entry = EvidenceLedgerEntry(
        run_id=run_ids[0],
        batch_id=None,
        type="decision",
        content_ref=f"oci://trivy/{want}",
        content_hash=scan_hash,
        provenance_json=provenance,
    )
    await commit_evidence_entry(session, entry)

    return TrivyGateAttestationResponse(
        accepted=True,
        release_id=release_id,
        artifact_digest=want,
        scan_digest=scan_hash,
        clearance=clearance,
        gate_verdict=verdict,
    )


# ══════════════════════════════════════════════════════════════════
# Read + deploy enforcement
# ══════════════════════════════════════════════════════════════════

async def latest_trivy_gate(
    session: AsyncSession,
    release_id: str,
    artifact_digest: Optional[str] = None,
) -> TrivyGateAttestationResponse | None:
    """Последний durable trivy-вердикт релиза (и digest'а, если задан)."""
    stmt = (
        select(EvidenceLedgerEntry)
        .where(EvidenceLedgerEntry.type == "decision")
        .where(EvidenceLedgerEntry.provenance_json["source"].astext == TRIVY_SOURCE)
        .where(EvidenceLedgerEntry.provenance_json["release_id"].astext == release_id)
    )
    if artifact_digest:
        stmt = stmt.where(
            EvidenceLedgerEntry.provenance_json["artifact_digest"].astext
            == artifact_digest
        )
    stmt = stmt.order_by(
        EvidenceLedgerEntry.created_at.desc(),
        EvidenceLedgerEntry.id.desc(),
    ).limit(1)
    row = (await session.execute(stmt)).scalars().first()
    if row is None:
        return None
    prov = row.provenance_json or {}
    return TrivyGateAttestationResponse(
        accepted=True,
        release_id=release_id,
        artifact_digest=prov.get("artifact_digest", ""),
        scan_digest=row.content_hash or "",
        clearance=prov.get("clearance", "DENIED"),
        gate_verdict=prov.get("gate_verdict", "BLOCK"),
    )


async def trivy_blocker_for_records(
    session: AsyncSession,
    release_id: str,
    records: list[ArtifactRecord],
) -> Optional[str]:
    """Блокер deploy при отсутствии PASS trivy-вердикта для образа.

    Каждый durable-образ релиза обязан иметь PASS trivy-decision (DOCKER_AUDIT).
    Возвращает сообщение блокировки либо ``None`` (можно деплоить).
    """
    for record in records:
        want = normalize_digest(record.digest)
        att = await latest_trivy_gate(session, release_id, want)
        if att is None:
            return (
                f"image {want[:16]}… has no trivy gate decision — "
                "DOCKER_AUDIT requires trivy pass before deploy"
            )
        if att.gate_verdict != "PASS":
            return (
                f"trivy gate is {att.gate_verdict} for image {want[:16]}… — "
                "deploy blocked (critical vulnerabilities)"
            )
    return None


__all__ = [
    "TRIVY_SOURCE",
    "TRIVY_CONTRACT",
    "TrivyGateError",
    "TrivyReleaseNotFoundError",
    "TrivyDigestMismatchError",
    "TrivyRunResult",
    "run_trivy_scan",
    "parse_trivy_report",
    "verify_and_attest_trivy_gate",
    "latest_trivy_gate",
    "trivy_blocker_for_records",
]