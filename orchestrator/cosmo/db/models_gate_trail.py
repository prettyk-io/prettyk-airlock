# -*- coding: utf-8 -*-
"""Durable Gate Decision Trail — ORM models (COS-081).

Append-only журнал решений security gates. Таблица живёт на ОТДЕЛЬНОМ
GateTrailBase — по образцу TransferRegistryBase (COS-070): миграционная
цепочка заморожена, новая таблица создается create_all (bootstrap/lifespan/
тест-фикстуры), alembic-цепочка не правится.

Связи (логические, без FK — cross-Base FK на frozen-цепочку запрещён):
  gate_id  → gates.id            (gate мог быть удалён — trail survives)
  run_id   → runs.id             (опционально: решение в контексте прогона)
  batch_id → batches.id          (опционально)
  evidence_ids → evidence_ledger.id[]  (JSONB список; evidence-link)

Invariant: append-only — строки никогда не UPDATE/DELETE (аудит trail).
"""
from __future__ import annotations

import datetime
from typing import Any, Optional

from sqlalchemy import DateTime, Index, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class GateTrailBase(DeclarativeBase):
    """Отдельный declarative base для gate decision trail (frozen chain safe)."""


def _uid() -> str:
    import uuid
    return uuid.uuid4().hex


class GateDecisionTrailRow(GateTrailBase):
    """Одна запись решения gate (append-only)."""
    __tablename__ = "gate_decision_trail"
    __table_args__ = (
        Index("ix_gdt_gate_id", "gate_id"),
        Index("ix_gdt_plan_id", "plan_id"),
        Index("ix_gdt_run_id", "run_id"),
        Index("ix_gdt_decided_at", "decided_at"),
        {"comment": "Durable gate decision trail (COS-081)"},
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uid)
    gate_id: Mapped[str] = mapped_column(String(64), nullable=False)
    plan_id: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    run_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    batch_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    decision: Mapped[str] = mapped_column(String(32), nullable=False)
    decided_by: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    initiator: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    signature: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    policy_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    evidence_ids: Mapped[list[str]] = mapped_column(JSONB, default=list)
    decided_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.utcnow, nullable=False
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.utcnow, nullable=False
    )
