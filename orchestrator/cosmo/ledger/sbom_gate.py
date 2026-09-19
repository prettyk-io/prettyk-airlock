# -*- coding: utf-8 -*-
"""COS-138: PK-C-003.6 — supply-chain гейт релизного бандла (SBOM + Grype).

Аттестация релиза по двум внешним отчётам supply-chain контура:

  1. **digest-сверка** — ``artifact_digest`` конверта обязан совпасть с digest'ами
     Syft SBOM и Grype-скана; если релиз фиксирует digest своих артефактов —
     и с ним. Рассинхрон → отказ (422), аттестация не создаётся.
  2. **порог уязвимостей** — ``gate_verdict = BLOCK`` при critical > 0, иначе
     ``PASS``; ``clearance`` = ``DENIED``/``CLEARED``. Critical считается честно:
     ``max(заявленный critical_count, число findings severity='critical')`` —
     отчёт не может «занизить» блокирующую уязвимость.
  3. **крипто-якорь** — аттестация запечатывается в ``evidence_ledger``
     (``type='decision'``, ``content_hash = sha256(SBOM)``, ``provenance_json``
     с привязкой к ``release_id``), якорь — через канонический
     ``commit_evidence_entry`` (цепочка + публикация головы).

Честная граница: гейт смотрит только записи ``source='cosmo-sbom-gate'``;
BLOCK не откатывает уже прошедший релиз — он фиксирует вердикт, который
читает ``GET /api/v1/releases/{release_id}/sbom`` и promotion-контур.
"""
from __future__ import annotations

import hashlib
import json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.cosmo.db.models import (
    EvidenceLedgerEntry,
    Release as ReleaseModel,
)
from orchestrator.cosmo.domain.sbom_scan import (
    GrypeScanReport,
    ReleaseSbomAttachRequest,
    ReleaseSbomAttestationResponse,
    SbomReport,
    normalize_digest,
)
from orchestrator.cosmo.ledger.evidence_writer import commit_evidence_entry

#: Маркер источника в provenance_json.
SBOM_SOURCE = "cosmo-sbom-gate"
#: Версия контракта PK-C-003.6.
SBOM_CONTRACT = "PK-C-003.6"


class SbomGateError(ValueError):
    """Нарушение supply-chain гейта; ``status_code`` — HTTP-маппинг."""

    status_code = 422


class ReleaseNotFoundError(SbomGateError):
    """Релиз не найден."""

    status_code = 404


class DigestMismatchError(SbomGateError):
    """artifact_digest отчётов/конверта/релиза не совпадают."""

    status_code = 422


def _release_artifact_digests(rel: ReleaseModel) -> set[str]:
    """Нормализованные sha256-digest'ы, зафиксированные у артефактов релиза."""
    digests: set[str] = set()
    for art in rel.artifacts or []:
        if isinstance(art, str):
            candidates = [art]
        elif isinstance(art, dict):
            candidates = [
                str(art.get(k, ""))
                for k in ("digest", "sha256", "checksum", "content_hash")
                if art.get(k)
            ]
        else:
            continue
        for cand in candidates:
            norm = normalize_digest(cand)
            if len(norm) == 64 and all(c in "0123456789abcdef" for c in norm):
                digests.add(norm)
    return digests


def _observed_severity(report: GrypeScanReport, severity: str) -> int:
    return sum(1 for f in report.findings if f.severity == severity)


def _provenance_hash(payload: dict) -> str:
    canonical = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _build_provenance(
    rel: ReleaseModel,
    payload: ReleaseSbomAttachRequest,
    sbom: SbomReport,
    sbom_digest: str,
    critical: int,
    verdict: str,
    clearance: str,
) -> dict:
    """Канонический provenance аттестации (до запечатывания хэша)."""
    return {
        "source": SBOM_SOURCE,
        "contract": SBOM_CONTRACT,
        "release_id": rel.id,
        "run_id": (rel.run_ids or [None])[0],
        "artifact_digest": normalize_digest(payload.artifact_digest),
        "sbom_digest": sbom_digest,
        "gate_verdict": verdict,
        "clearance": clearance,
        "critical_count": critical,
        "reported_critical_count": payload.vulnerabilities.critical_count,
        "observed_critical_count": _observed_severity(
            payload.vulnerabilities, "critical",
        ),
        "high_count": payload.vulnerabilities.high_count,
        "medium_count": payload.vulnerabilities.medium_count,
        "low_count": payload.vulnerabilities.low_count,
        "findings_total": len(payload.vulnerabilities.findings),
        "sbom_format": sbom.format,
        "syft_version": sbom.syft_version,
        "grype_version": payload.vulnerabilities.scanner_version,
        "packages_count": sbom.packages_count,
        "packages_listed": len(sbom.packages),
        "packages_consistent": sbom.packages_count == len(sbom.packages),
        "release_artifact_digest": (
            normalize_digest(payload.artifact_digest)
            if _release_artifact_digests(rel) else None
        ),
    }


async def verify_and_attest_release_sbom(
    session: AsyncSession,
    release_id: str,
    payload: ReleaseSbomAttachRequest,
) -> ReleaseSbomAttestationResponse:
    """Проверить и аттестовать SBOM + Grype-скан релизного бандла.

    Raises:
        ReleaseNotFoundError: релиз не существует.
        DigestMismatchError: digest'ы конверта/отчётов/релиза расходятся.
        SbomGateError: у релиза нет прогонов — нечем якорить ledger-запись.
    """
    rel = await session.get(ReleaseModel, release_id)
    if rel is None:
        raise ReleaseNotFoundError(f"Release '{release_id}' not found")

    # 1. digest-сверка: конверт ↔ SBOM ↔ Grype (↔ артефакт релиза)
    want = normalize_digest(payload.artifact_digest)
    sbom_digest_ref = normalize_digest(payload.sbom.artifact_digest)
    grype_digest_ref = normalize_digest(payload.vulnerabilities.artifact_digest)
    if want != sbom_digest_ref or want != grype_digest_ref:
        raise DigestMismatchError(
            "artifact_digest mismatch: request="
            f"{want} sbom={sbom_digest_ref} grype={grype_digest_ref}"
        )

    pinned = _release_artifact_digests(rel)
    if pinned and want not in pinned:
        raise DigestMismatchError(
            f"artifact_digest {want} does not match release artifact digests "
            f"{sorted(pinned)}"
        )

    run_ids = list(rel.run_ids or [])
    if not run_ids:
        raise SbomGateError(
            f"Release '{release_id}' has no runs to anchor SBOM attestation"
        )

    # 2. порог: critical честно = max(заявленный, наблюдаемый в findings)
    critical = max(
        payload.vulnerabilities.critical_count,
        _observed_severity(payload.vulnerabilities, "critical"),
    )
    verdict = "BLOCK" if critical > 0 else "PASS"
    clearance = "DENIED" if critical > 0 else "CLEARED"

    # 3. крипто-якорь: sha256 содержимого SBOM → content_hash ledger
    sbom_digest = hashlib.sha256(
        json.dumps(
            payload.sbom.model_dump(mode="json"),
            sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()

    provenance = _build_provenance(
        rel, payload, payload.sbom, sbom_digest, critical, verdict, clearance,
    )
    provenance["provenance_hash"] = _provenance_hash(provenance)

    entry = EvidenceLedgerEntry(
        run_id=run_ids[0],
        batch_id=None,
        type="decision",
        content_ref=f"release://{release_id}/sbom/{want}",
        content_hash=sbom_digest,
        provenance_json=provenance,
    )
    await commit_evidence_entry(session, entry)

    return ReleaseSbomAttestationResponse(
        accepted=True,
        release_id=release_id,
        artifact_digest=want,
        sbom_digest=sbom_digest,
        clearance=clearance,
        gate_verdict=verdict,
    )


async def latest_sbom_attestation(
    session: AsyncSession, release_id: str,
) -> ReleaseSbomAttestationResponse | None:
    """Последняя аттестация SBOM релиза (None, если аттестации не было)."""
    stmt = (
        select(EvidenceLedgerEntry)
        .where(EvidenceLedgerEntry.type == "decision")
        .where(EvidenceLedgerEntry.provenance_json["source"].astext == SBOM_SOURCE)
        .where(
            EvidenceLedgerEntry.provenance_json["release_id"].astext == release_id
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
    prov = row.provenance_json or {}
    return ReleaseSbomAttestationResponse(
        accepted=True,
        release_id=release_id,
        artifact_digest=prov.get("artifact_digest", ""),
        sbom_digest=prov.get("sbom_digest", row.content_hash),
        clearance=prov.get("clearance", "DENIED"),
        gate_verdict=prov.get("gate_verdict", "BLOCK"),
    )
