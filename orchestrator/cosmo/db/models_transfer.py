# -*- coding: utf-8 -*-
"""Durable Transfer Registry — ORM models (COS-050/053/058 follow-up).

Персистентная версия in-memory TransferRegistry (orchestrator/cosmo/transfer/
registry.py). Таблицы живут на ОТДЕЛЬНОМ TransferRegistryBase, а не на shared
session.Base: миграция e4f5a6b7c8d9 стоит ПОСЛЕ d2e3f4a5b6c7, чей drift-check
верифицирует только shared Base — отдельный Base исключает ложный drift на
fresh-upgrade цепочке.

Таблицы:
  transfer_plans              — TransferPlan snapshot (JSONB) + indexed columns
  transfer_items              — TransferItem snapshot (JSONB) + indexed columns
  transfer_landing_states     — per-item LandingStateMachine state + history
  transfer_received_revisions — глобальный индекс revision_key → item_id
                                (кросс-item idempotency)
"""
from __future__ import annotations

import datetime
from typing import Any, Optional

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class TransferRegistryBase(DeclarativeBase):
    """Отдельный declarative base для transfer registry (см. docstring модуля)."""


# ══════════════════════════════════════════════════════════════════════════════
# transfer_plans
# ══════════════════════════════════════════════════════════════════════════════

class TransferPlanRow(TransferRegistryBase):
    """Durable TransferPlan. payload = plan.model_dump(mode='json') без items
    (items живут в transfer_items как самостоятельные строки)."""
    __tablename__ = "transfer_plans"
    __table_args__ = (
        Index("ix_transfer_plans_release", "release_id"),
        Index("ix_transfer_plans_domain", "domain_id"),
        Index("ix_transfer_plans_status", "status"),
        {"comment": "Durable Transfer Registry: планы передачи (COS-050/058)"},
    )

    plan_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    release_id: Mapped[str] = mapped_column(String(64), nullable=False)
    domain_id: Mapped[str] = mapped_column(String(64), nullable=False)
    correlation_id: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    source_zone: Mapped[str] = mapped_column(String(8), default="zr", nullable=False)
    target_zone: Mapped[str] = mapped_column(String(8), default="zt", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="draft", nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.utcnow, nullable=False
    )


# ══════════════════════════════════════════════════════════════════════════════
# transfer_items
# ══════════════════════════════════════════════════════════════════════════════

class TransferItemRow(TransferRegistryBase):
    """Durable TransferItem. payload = item.model_dump(mode='json')."""
    __tablename__ = "transfer_items"
    __table_args__ = (
        UniqueConstraint("revision_key", "item_id", name="uq_transfer_item_revision"),
        Index("ix_transfer_items_plan", "plan_id"),
        Index("ix_transfer_items_release", "release_id"),
        Index("ix_transfer_items_status", "status"),
        Index("ix_transfer_items_revision_key", "revision_key"),
        {"comment": "Durable Transfer Registry: items передачи (COS-050/058)"},
    )

    item_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    plan_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("transfer_plans.plan_id", ondelete="CASCADE"), nullable=False
    )
    release_id: Mapped[str] = mapped_column(String(64), nullable=False)
    correlation_id: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    artifact_plane: Mapped[str] = mapped_column(String(32), nullable=False)
    package_mode: Mapped[str] = mapped_column(String(32), nullable=False)
    transport_profile: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="draft", nullable=False)
    revision_key: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    retry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.utcnow,
        onupdate=datetime.datetime.utcnow, nullable=False,
    )


# ══════════════════════════════════════════════════════════════════════════════
# transfer_landing_states
# ══════════════════════════════════════════════════════════════════════════════

class TransferLandingStateRow(TransferRegistryBase):
    """Per-item target-side landing state (LandingStateMachine snapshot)."""
    __tablename__ = "transfer_landing_states"
    __table_args__ = (
        Index("ix_transfer_landing_state", "state"),
        {"comment": "Durable Transfer Registry: landing state machines (COS-053)"},
    )

    item_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("transfer_items.item_id", ondelete="CASCADE"),
        primary_key=True,
    )
    state: Mapped[str] = mapped_column(String(32), default="not_received", nullable=False)
    revision_key: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    history: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, nullable=False)
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.utcnow,
        onupdate=datetime.datetime.utcnow, nullable=False,
    )


# ══════════════════════════════════════════════════════════════════════════════
# transfer_received_revisions
# ══════════════════════════════════════════════════════════════════════════════

class TransferReceivedRevisionRow(TransferRegistryBase):
    """Глобальный индекс полученных revision keys (кросс-item idempotency).

    PK = revision_key: повторная регистрация тем же item — no-op,
    тем же ключом другим item — конфликт уровня БД ( UNIQUE индекс не нужен,
    PK сам гарантирует единственность ключа; cross-item конфликт ловит repo).
    """
    __tablename__ = "transfer_received_revisions"
    __table_args__ = (
        Index("ix_transfer_recv_rev_item", "item_id"),
        {"comment": "Durable Transfer Registry: received revision index (idempotency)"},
    )

    revision_key: Mapped[str] = mapped_column(String(128), primary_key=True)
    item_id: Mapped[str] = mapped_column(String(64), nullable=False)
    received_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime, default=datetime.datetime.utcnow, nullable=True
    )
