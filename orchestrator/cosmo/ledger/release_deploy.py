# -*- coding: utf-8 -*-
"""COS-165: durable-след release deploy — decision (success) / alert (fail).

``deploy_release`` ставит ``deployed`` ТОЛЬКО после фактического healthy
контейнера; факт и причина фиксируются в Evidence Ledger (type='decision'
на успех, type='alert' на провал/rollback). Маркеры:
  - success: ``provenance_json.source == 'cosmo-release-deploy'``;
  - fail:    ``provenance_json.source == 'cosmo-release-deploy-failed'``.

Якорь пишется каноническим ``commit_evidence_entry`` (append → seal →
commit → publish_head). ``run_id`` — NOT NULL FK на runs.id: берём первый
run релиза (релиз без прогонов якорить нечем — честная граница COS-142/148).
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json

from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.cosmo.db.models import EvidenceLedgerEntry

DEPLOY_SUCCESS_SOURCE = "cosmo-release-deploy"
DEPLOY_FAILED_SOURCE = "cosmo-release-deploy-failed"


async def record_release_deployed(
    session: AsyncSession,
    *,
    run_id: str,
    release_id: str,
    canonical_refs: list[str],
    container_names: list[str],
) -> str:
    """Durable decision-запись об успешном (healthy) release deploy."""
    from orchestrator.cosmo.ledger.evidence_writer import commit_evidence_entry

    payload = json.dumps(
        {
            "release_id": release_id,
            "canonical_refs": sorted(canonical_refs),
            "container_names": sorted(container_names),
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    entry = EvidenceLedgerEntry(
        run_id=run_id,
        batch_id=None,
        type="decision",
        content_ref=f"release://{release_id}/deploy",
        content_hash=hashlib.sha256(payload.encode("utf-8")).hexdigest(),
        provenance_json={
            "source": DEPLOY_SUCCESS_SOURCE,
            "release_id": release_id,
            "canonical_refs": canonical_refs,
            "container_names": container_names,
            "healthy": True,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    return await commit_evidence_entry(session, entry)


async def record_release_deploy_failed(
    session: AsyncSession,
    *,
    run_id: str,
    release_id: str,
    reason: str,
) -> str:
    """Durable alert-запись о провале (не healthy) release deploy → rollback."""
    from orchestrator.cosmo.ledger.evidence_writer import commit_evidence_entry

    payload = json.dumps(
        {"release_id": release_id, "reason": reason},
        sort_keys=True,
        ensure_ascii=False,
    )
    entry = EvidenceLedgerEntry(
        run_id=run_id,
        batch_id=None,
        type="alert",
        content_ref=f"release://{release_id}/deploy",
        content_hash=hashlib.sha256(payload.encode("utf-8")).hexdigest(),
        provenance_json={
            "source": DEPLOY_FAILED_SOURCE,
            "release_id": release_id,
            "reason": reason,
            "healthy": False,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    return await commit_evidence_entry(session, entry)


__all__ = [
    "DEPLOY_SUCCESS_SOURCE",
    "DEPLOY_FAILED_SOURCE",
    "record_release_deployed",
    "record_release_deploy_failed",
]
