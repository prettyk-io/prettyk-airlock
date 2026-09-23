# -*- coding: utf-8 -*-
"""COS-169/170: durable promotion packing + landing (Evidence Ledger-only).

Промоушен релиза реализован поверх канона COS-138/152/163/167/168:

  - decision-записи в ``evidence_ledger`` (не новые PG-таблицы — миграционная
    цепочка заморожена) через канонический ``commit_evidence_entry``;
  - ``source='cosmo-promotion-package'`` — пакет (pack, исходная зона);
  - ``source='cosmo-promotion-landing'`` — landing (целевая зона);
  - ``content_hash`` = пакетный digest (pack) / digest принятого пакета
    (landing) — тампер-якорь, сверяемый при чтении (restart-survival,
    latest wins).

Инварианты:
  - **pack idempotent**: тот же состав артефактов (fingerprint) в той же зоне
    → та же revision и digest; повторный pack не пишет дубликат.
  - **gate обязателен**: pack блокируется, если хотя бы у одного образа нет
    ``PASS`` trivy-вердикта или нет SBOM; landing перепроверяет это заново.
  - **digest-matching**: landing принимает только ``incoming_manifest_digest``
    == пакетному digest; рассинхрон → честный ``mismatch`` (422).
  - **линейность зон**: переход только по ``next_zone`` (ЗР→ЗТ→ЗПЭ).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.cosmo.db.models import (
    EvidenceLedgerEntry,
    Release as ReleaseModel,
)
from orchestrator.cosmo.domain.artifact_record import ArtifactRecord
from orchestrator.cosmo.domain.promotion import (
    PromotionLandRequest,
    PromotionLandResponse,
    PromotionPackage,
    PromotionArtifact,
    build_promotion_manifest,
    compute_package_digest,
    promotion_content_fingerprint,
)
from orchestrator.cosmo.domain.release_model import next_zone, TransferRecord
from orchestrator.cosmo.domain.sbom_scan import normalize_digest
from orchestrator.cosmo.ledger.artifact_record import (
    artifact_records_for_run_ids,
    latest_artifact_record,
)
from orchestrator.cosmo.ledger.artifact_scan_gate import latest_trivy_gate
from orchestrator.cosmo.ledger.evidence_writer import commit_evidence_entry

#: Маркеры источника записи в ``provenance_json``.
PROMOTION_PACKAGE_SOURCE = "cosmo-promotion-package"
PROMOTION_LANDING_SOURCE = "cosmo-promotion-landing"

#: Маркеры типа записи (``provenance_json.promotion_type``).
PROMOTION_PACKAGE_TYPE = "PROMOTION_PACKAGE"
PROMOTION_LANDING_TYPE = "PROMOTION_LANDING"


class PromotionError(ValueError):
    """Нарушение промоушена; ``status_code`` — HTTP-маппинг."""

    status_code = 409

    def __init__(self, message: str, *, report: Optional[dict] = None):
        super().__init__(message)
        self.report = report


class PromotionNotFoundError(PromotionError):
    status_code = 404


class PromotionMismatchError(PromotionError):
    status_code = 422


async def _anchor_run_id(session: AsyncSession, release: ReleaseModel) -> str:
    run_ids = list(release.run_ids or [])
    if not run_ids:
        raise PromotionError(
            f"Release '{release.id}' has no runs to anchor promotion evidence")
    return run_ids[0]


def _artifact_dict_for_record(record: ArtifactRecord, trivy_verdict: str) -> dict:
    return {
        "name": record.name,
        "version": record.version,
        "digest": record.digest,
        "canonical_ref": record.canonical_ref(),
        "sbom_ref": record.sbom_ref or "",
        "trivy_verdict": trivy_verdict,
    }


# ══════════════════════════════════════════════════════════════════
# pack — собрать + заякорить idempotent promotion package
# ══════════════════════════════════════════════════════════════════

async def pack_release_promotion(
    session: AsyncSession,
    release: ReleaseModel,
    target_zone: str,
) -> PromotionPackage:
    """Собрать и durable-заякорить promotion-пакет релиза для ``target_zone``.

    Gate обязателен (COS-168/167): у каждого образа релиза должен быть
    ``PASS`` trivy-вердикт и SBOM (``sbom_ref``). Любой BLOCK/отсутствие →
    честный блок (409). Idempotent: тот же состав в той же зоне → тот же
    revision/digest, повторный вызов не пишет новую строку.
    """
    run_ids = list(release.run_ids or [])
    records = await artifact_records_for_run_ids(session, run_ids)
    if not records:
        raise PromotionError(
            f"Release '{release.id}' has no durable artifact records to pack "
            "— build/push must be captured before promotion")

    source_zone = release.current_zone or "zr"
    artifacts: list[PromotionArtifact] = []
    for record in sorted(records, key=lambda r: r.canonical_ref()):
        want = normalize_digest(record.digest)
        gate = await latest_trivy_gate(session, release.id, want)
        if gate is None:
            raise PromotionError(
                f"image {record.canonical_ref()} has no trivy gate decision — "
                "promotion blocked (DOCKER_AUDIT requires trivy pass)")
        if gate.gate_verdict != "PASS":
            raise PromotionError(
                f"trivy gate is {gate.gate_verdict} for image "
                f"{record.canonical_ref()} — promotion blocked")
        if not record.sbom_ref:
            raise PromotionError(
                f"image {record.canonical_ref()} has no SBOM (sbom_ref) — "
                "promotion blocked (PK-C-003.6 requires SBOM)")
        artifacts.append(PromotionArtifact(
            name=record.name,
            version=record.version,
            digest=record.digest,
            canonical_ref=record.canonical_ref(),
            sbom_ref=record.sbom_ref,
            trivy_verdict=gate.gate_verdict,
        ))

    fingerprint = promotion_content_fingerprint(artifacts)
    existing = await latest_promotion_package(session, release.id, target_zone)
    revision = (existing.revision if existing else 0) + 1
    if existing is not None and existing.content_fingerprint == fingerprint:
        # Idempotent no-op: тот же контент уже упакован в этой зоне.
        return existing.model_copy(update={"status": "duplicate"})

    manifest = build_promotion_manifest(
        release.id, source_zone, target_zone, revision, artifacts)
    package_digest = compute_package_digest(manifest)

    run_id = await _anchor_run_id(session, release)
    provenance = {
        "source": PROMOTION_PACKAGE_SOURCE,
        "promotion_type": PROMOTION_PACKAGE_TYPE,
        "release_id": release.id,
        "run_id": run_id,
        "source_zone": source_zone,
        "target_zone": target_zone,
        "revision": revision,
        "artifacts": [a.model_dump(mode="json") for a in artifacts],
        "content_fingerprint": fingerprint,
        "package_digest": package_digest,
        "status": "packed",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    }
    entry = EvidenceLedgerEntry(
        run_id=run_id,
        batch_id=None,
        type="decision",
        content_ref=f"oci://promotion/{release.id}/{target_zone}/{package_digest[:16]}",
        content_hash=package_digest,
        provenance_json=provenance,
    )
    await commit_evidence_entry(session, entry)

    return PromotionPackage(
        release_id=release.id,
        source_zone=source_zone,  # type: ignore[arg-type]
        target_zone=target_zone,  # type: ignore[arg-type]
        revision=revision,
        artifacts=artifacts,
        package_digest=package_digest,
        content_fingerprint=fingerprint,
        status="packed",
    )


# ══════════════════════════════════════════════════════════════════
# land — верифицировать + перевести в целевую зону
# ══════════════════════════════════════════════════════════════════

async def land_release_promotion(
    session: AsyncSession,
    release: ReleaseModel,
    payload: PromotionLandRequest,
    *,
    actor: str,
) -> PromotionLandResponse:
    """Landing пакета в целевой зоне: digest-matching + gate + SBOM → promoted.

    Raises:
        PromotionNotFoundError: пакета нет (не пачился).
        PromotionMismatchError: manifest-digest не совпадает с пакетным.
        PromotionError: gate/SBOM отсутствуют или BLOCK; нелинейный переход.
    """
    target_zone = payload.target_zone
    package = await latest_promotion_package(session, release.id, target_zone)
    if package is None:
        raise PromotionNotFoundError(
            f"No promotion package for release '{release.id}' → '{target_zone}'. "
            "Pack the release first.")

    # 0. idempotent replay: уже promoted в этой зоне → честный duplicate
    # (не пишем второй landing-ряд, не дёргаем линейность повторно).
    prev = await latest_promotion_landing(session, release.id, target_zone)
    if prev is not None and prev.status == "promoted":
        return prev.model_copy(update={"status": "duplicate"})

    # CAS: честный конфликт текущей зоны.
    current = release.current_zone or "zr"
    if payload.expected_current_zone and payload.expected_current_zone != current:
        raise PromotionMismatchError(
            f"Promotion state conflict: release '{release.id}' is in zone "
            f"'{current}', expected '{payload.expected_current_zone}'.")

    # 1. digest-matching (не молчаливый promoted).
    incoming = normalize_digest(payload.incoming_manifest_digest)
    if incoming != package.package_digest:
        raise PromotionMismatchError(
            f"manifest digest mismatch for release '{release.id}': "
            f"incoming {incoming[:16]}… != package "
            f"{package.package_digest[:16]}…", report={
                "status": "mismatch",
                "release_id": release.id,
                "target_zone": target_zone,
                "package_digest": package.package_digest,
                "incoming_manifest_digest": incoming,
            })

    # 2. линейность зон.
    expected_next = next_zone(current)  # type: ignore[arg-type]
    if expected_next is None:
        raise PromotionError(
            f"Release already in final zone '{current}'. No further promotion.")
    if target_zone != expected_next:
        raise PromotionError(
            f"Invalid zone promotion. Strict path is ZR → ZT → ZPE. "
            f"Cannot promote from '{current}' directly to '{target_zone}'. "
            f"Expected next zone: '{expected_next}'.")

    # 3. belt-and-suspenders: перечитать SBOM + trivy gate на landing-момент.
    reasons: list[str] = []
    gate_pass = True
    sbom_present = True
    for art in package.artifacts:
        want = normalize_digest(art.digest)
        gate = await latest_trivy_gate(session, release.id, want)
        if gate is None or gate.gate_verdict != "PASS":
            gate_pass = False
            reasons.append(f"image {art.canonical_ref}: trivy gate not PASS")
        rec = await latest_artifact_record(session, art.name, art.version)
        if rec is None or rec.sbom_ref != art.sbom_ref:
            sbom_present = False
            reasons.append(f"image {art.canonical_ref}: SBOM missing/changed")

    if not gate_pass:
        raise PromotionError(
            f"Promotion blocked for release '{release.id}': trivy gate not "
            f"PASS — {reasons}", report={
                "status": "blocked", "release_id": release.id,
                "target_zone": target_zone,
                "package_digest": package.package_digest, "reasons": reasons})
    if not sbom_present:
        raise PromotionError(
            f"Promotion blocked for release '{release.id}': SBOM missing — "
            f"{reasons}", report={
                "status": "missing", "release_id": release.id,
                "target_zone": target_zone,
                "package_digest": package.package_digest, "reasons": reasons})

    # 4. перевод зоны + аудит-запись + durable evidence.
    run_id = await _anchor_run_id(session, release)
    transfer = TransferRecord(
        from_zone=current,  # type: ignore[arg-type]
        to_zone=target_zone,  # type: ignore[arg-type]
        initiated_by=actor,
        gate_check_passed=True,
        comment="promotion landing (COS-169/170)",
    )
    history = list(release.transfer_history or [])
    history.append(transfer.model_dump(mode="json"))
    release.transfer_history = history
    release.current_zone = target_zone

    provenance = {
        "source": PROMOTION_LANDING_SOURCE,
        "promotion_type": PROMOTION_LANDING_TYPE,
        "release_id": release.id,
        "run_id": run_id,
        "source_zone": current,
        "target_zone": target_zone,
        "package_digest": package.package_digest,
        "manifest_digest": incoming,
        "revision": package.revision,
        "gate_pass": True,
        "sbom_present": True,
        "status": "promoted",
        "initiated_by": actor,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    }
    entry = EvidenceLedgerEntry(
        run_id=run_id,
        batch_id=None,
        type="decision",
        content_ref=f"oci://promotion/{release.id}/{target_zone}/land/{incoming[:16]}",
        content_hash=package.package_digest,
        provenance_json=provenance,
    )
    await commit_evidence_entry(session, entry)

    return PromotionLandResponse(
        release_id=release.id,
        target_zone=target_zone,  # type: ignore[arg-type]
        package_digest=package.package_digest,
        status="promoted",
        gate_pass=True,
        sbom_present=True,
        current_zone=target_zone,  # type: ignore[arg-type]
        reasons=[],
    )


# ══════════════════════════════════════════════════════════════════
# read-through (restart-survival, latest wins)
# ══════════════════════════════════════════════════════════════════

def _package_from_provenance(provenance: dict) -> PromotionPackage | None:
    """Реконструировать пакет из ledger + crypto-проверка (package_digest)."""
    try:
        artifacts = [
            PromotionArtifact.model_validate(a)
            for a in (provenance.get("artifacts") or [])
        ]
        revision = int(provenance["revision"])
        release_id = provenance["release_id"]
        source_zone = provenance["source_zone"]
        target_zone = provenance["target_zone"]
    except (KeyError, TypeError, ValueError):
        return None
    if not artifacts:
        return None
    manifest = build_promotion_manifest(
        release_id, source_zone, target_zone, revision, artifacts)
    package_digest = compute_package_digest(manifest)
    # Тампер-якорь: content_hash обязан совпасть с пересчитанным digest.
    if package_digest != provenance.get("package_digest"):
        return None
    return PromotionPackage(
        release_id=release_id,
        source_zone=source_zone,
        target_zone=target_zone,
        revision=revision,
        artifacts=artifacts,
        package_digest=package_digest,
        content_fingerprint=provenance.get("content_fingerprint", ""),
        status=provenance.get("status", "packed"),
    )


async def latest_promotion_package(
    session: AsyncSession, release_id: str, target_zone: str,
) -> PromotionPackage | None:
    """Актуальный promotion-пакет релиза для зоны (latest wins, durable)."""
    stmt = (
        select(EvidenceLedgerEntry)
        .where(EvidenceLedgerEntry.type == "decision")
        .where(EvidenceLedgerEntry.provenance_json["source"].astext
               == PROMOTION_PACKAGE_SOURCE)
        .where(EvidenceLedgerEntry.provenance_json["release_id"].astext
               == release_id)
        .where(EvidenceLedgerEntry.provenance_json["target_zone"].astext
               == target_zone)
        .order_by(EvidenceLedgerEntry.created_at.desc(),
                  EvidenceLedgerEntry.id.desc())
        .limit(1)
    )
    row = (await session.execute(stmt)).scalars().first()
    if row is None:
        return None
    return _package_from_provenance(dict(row.provenance_json or {}))


async def latest_promotion_landing(
    session: AsyncSession, release_id: str, target_zone: str,
) -> PromotionLandResponse | None:
    """Актуальный landing-отчёт релиза для зоны (latest wins, durable)."""
    stmt = (
        select(EvidenceLedgerEntry)
        .where(EvidenceLedgerEntry.type == "decision")
        .where(EvidenceLedgerEntry.provenance_json["source"].astext
               == PROMOTION_LANDING_SOURCE)
        .where(EvidenceLedgerEntry.provenance_json["release_id"].astext
               == release_id)
        .where(EvidenceLedgerEntry.provenance_json["target_zone"].astext
               == target_zone)
        .order_by(EvidenceLedgerEntry.created_at.desc(),
                  EvidenceLedgerEntry.id.desc())
        .limit(1)
    )
    row = (await session.execute(stmt)).scalars().first()
    if row is None:
        return None
    prov = row.provenance_json or {}
    try:
        return PromotionLandResponse(
            release_id=release_id,
            target_zone=target_zone,
            package_digest=prov.get("package_digest", ""),
            status=prov.get("status", "promoted"),
            gate_pass=prov.get("gate_pass", True),
            sbom_present=prov.get("sbom_present", True),
            current_zone=prov.get("target_zone", target_zone),
            reasons=prov.get("reasons", []),
        )
    except (KeyError, TypeError, ValueError):
        return None


__all__ = [
    "PROMOTION_PACKAGE_SOURCE",
    "PROMOTION_LANDING_SOURCE",
    "PROMOTION_PACKAGE_TYPE",
    "PROMOTION_LANDING_TYPE",
    "PromotionError",
    "PromotionNotFoundError",
    "PromotionMismatchError",
    "pack_release_promotion",
    "land_release_promotion",
    "latest_promotion_package",
    "latest_promotion_landing",
]