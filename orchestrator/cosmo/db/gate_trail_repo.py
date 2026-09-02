# -*- coding: utf-8 -*-
"""Durable Gate Decision Trail — repository (COS-081).

Async-функции поверх переданной AsyncSession: append выполняется В ТОЙ ЖЕ
транзакции, что и решение gate (решение в PG до возврата API-ответа,
атомарно с обновлением gates). Read-path: trail по gate и по run.

Append-only инвариант: только INSERT и SELECT — UPDATE/DELETE отсутствуют.
"""
from __future__ import annotations

import datetime
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.cosmo.db.models_gate_trail import GateDecisionTrailRow


async def append_gate_decision(
    db: AsyncSession,
    *,
    gate_id: str,
    plan_id: str = "",
    decision: str,
    decided_by: str = "",
    initiator: str = "",
    signature: Optional[str] = None,
    policy_snapshot: Optional[dict[str, Any]] = None,
    run_id: Optional[str] = None,
    batch_id: Optional[str] = None,
    evidence_ids: Optional[list[str]] = None,
    decided_at: Optional[datetime.datetime] = None,
) -> GateDecisionTrailRow:
    """Append-only запись решения. Вызывается ДО commit сессии API-пути —
    строка фиксируется той же транзакцией (write-before-response)."""
    row = GateDecisionTrailRow(
        gate_id=gate_id,
        plan_id=plan_id,
        run_id=run_id,
        batch_id=batch_id,
        decision=decision,
        decided_by=decided_by,
        initiator=initiator,
        signature=signature,
        policy_snapshot=policy_snapshot or {},
        evidence_ids=list(evidence_ids or []),
        decided_at=decided_at or datetime.datetime.utcnow(),
    )
    db.add(row)
    return row


def _to_dict(row: GateDecisionTrailRow) -> dict[str, Any]:
    return {
        "id": row.id,
        "gate_id": row.gate_id,
        "plan_id": row.plan_id,
        "run_id": row.run_id,
        "batch_id": row.batch_id,
        "decision": row.decision,
        "decided_by": row.decided_by,
        "initiator": row.initiator,
        "signature": row.signature,
        "policy_snapshot": row.policy_snapshot,
        "evidence_ids": row.evidence_ids,
        "decided_at": row.decided_at.isoformat() if row.decided_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


async def trail_for_gate(
    db: AsyncSession, gate_id: str, run_id: Optional[str] = None
) -> list[dict[str, Any]]:
    """История решений по gate (новые первыми); опционально в контексте run."""
    stmt = (
        select(GateDecisionTrailRow)
        .where(GateDecisionTrailRow.gate_id == gate_id)
        .order_by(GateDecisionTrailRow.decided_at.desc(), GateDecisionTrailRow.created_at.desc())
    )
    if run_id is not None:
        stmt = stmt.where(GateDecisionTrailRow.run_id == run_id)
    rows = (await db.execute(stmt)).scalars().all()
    return [_to_dict(r) for r in rows]


async def trail_for_run(db: AsyncSession, run_id: str) -> list[dict[str, Any]]:
    """COS-081 read-path: trail всех gate-решений прогона (хронологически)."""
    stmt = (
        select(GateDecisionTrailRow)
        .where(GateDecisionTrailRow.run_id == run_id)
        .order_by(GateDecisionTrailRow.decided_at.asc(), GateDecisionTrailRow.created_at.asc())
    )
    rows = (await db.execute(stmt)).scalars().all()
    return [_to_dict(r) for r in rows]
