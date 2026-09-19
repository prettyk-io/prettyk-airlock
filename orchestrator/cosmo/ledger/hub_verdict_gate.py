# -*- coding: utf-8 -*-
"""COS-136: promotion-gate по вердиктам PrettyK Hub (Contract A).

Вердикт Hub живёт в ``evidence_ledger`` как запись ``type='decision'`` с
``provenance_json.source == 'prettyk-hub'``. Гейт промоушена читает ПОСЛЕДНИЙ
вердикт на каждый run релиза: ``BLOCK`` — стоп, ``PASS``/``WARN`` — пропуск.
Новый вердикт перекрывает старый, поэтому PASS после BLOCK разблокирует
релиз by construction (никакой отдельной «разблокирующей» мутации не нужно).

Честная граница: гейт смотрит только записи Hub (``source='prettyk-hub'``);
прочие ``decision``-записи ledger на промоушен не влияют.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.cosmo.db.models import EvidenceLedgerEntry

#: Маркер источника в provenance_json.
HUB_SOURCE = "prettyk-hub"
#: Ключ вердикта в provenance_json.
HUB_VERDICT_KEY = "hub_verdict"


async def latest_hub_verdict(
    session: AsyncSession, run_id: str,
) -> str | None:
    """Последний вердикт Hub по прогону (None, если вердикта не было)."""
    stmt = (
        select(EvidenceLedgerEntry)
        .where(EvidenceLedgerEntry.run_id == run_id)
        .where(EvidenceLedgerEntry.type == "decision")
        .where(EvidenceLedgerEntry.provenance_json["source"].astext == HUB_SOURCE)
        .order_by(
            EvidenceLedgerEntry.created_at.desc(),
            EvidenceLedgerEntry.id.desc(),
        )
        .limit(1)
    )
    row = (await session.execute(stmt)).scalars().first()
    if row is None:
        return None
    return (row.provenance_json or {}).get(HUB_VERDICT_KEY)


async def blocked_run_ids(
    session: AsyncSession, run_ids: list[str] | None,
) -> list[str]:
    """Прогоны релиза, чей последний вердикт Hub — ``BLOCK``."""
    blocked: list[str] = []
    for rid in run_ids or []:
        if await latest_hub_verdict(session, rid) == "BLOCK":
            blocked.append(rid)
    return blocked
