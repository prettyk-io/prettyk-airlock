# -*- coding: utf-8 -*-
"""COS-097: durable execution handles (Woodpecker pipeline ↔ batch).

Ручки запущенных Woodpecker-пайплайнов персистятся в ОТДЕЛЬНОЙ таблице на
собственном ExecutionBase (тот же приём, что GateTrailBase /
TransferRegistryBase): миграционная цепочка заморожена — новые колонки в
batches запрещены, drift-check shared Base править нельзя.

Зачем: accept-критерий COS-097 «рестарт cosmo-api не теряет факт прогона».
In-memory PipelineHandle BatchExecutor'а теряется при рестарте; эта таблица
— источник восстановления poll-цикла (recover) и честного degraded-следа
(unknown_count / degraded / last raw status), которому тесно в замороженном
batch_status_enum {pending, running, passed, failed, blocked}.

Создаётся idempotent create_all при старте API (lifespan), как gate trail.
"""
from __future__ import annotations

import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class ExecutionBase(DeclarativeBase):
    """Отдельный declarative base для execution-таблиц (вне frozen chain)."""


# Статусы, которые считаем terminal при восстановлении: нечего поллить —
# прогон завершился (или так и не начался после failed submit).
TERMINAL_STORED_STATUSES = frozenset(
    {"success", "failure", "killed", "error", "declined", "skipped",
     "degraded", "submit_failed", "cancelled"}
)


class ExecutionHandleRow(ExecutionBase):
    """Durable handle на запущенный Woodpecker pipeline (batch → pipeline)."""

    __tablename__ = "cosmo_execution_handles"

    batch_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(64), nullable=False)
    plan_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")

    # Woodpecker-специфика (v3.5): числовой repo_id обязателен, number —
    # порядковый номер пайплайна в repo, wp_pipeline_id — pipeline DB id.
    repo_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    repo_owner: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    repo_name: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    branch: Mapped[str] = mapped_column(String(128), nullable=False, default="main")
    wp_number: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    wp_pipeline_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Честный след исполнения: RAW статус Woodpecker (без маппинга), счётчик
    # подряд-неизвестных опросов, флаг degraded и причина — всё, что не
    # влезает в замороженный batch_status_enum без выдумывания PASS.
    last_status: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    unknown_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    degraded: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    evidence_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    details_json: Mapped[dict] = mapped_column(JSONB, default=dict)

    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.utcnow)
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.utcnow,
        onupdate=datetime.datetime.utcnow)

    __table_args__ = (
        Index("ix_exec_handles_run_id", "run_id"),
        Index("ix_exec_handles_degraded", "degraded"),
        {"comment": "COS-097: durable Woodpecker handles + honest degraded trace"},
    )

    def is_terminal(self) -> bool:
        return (self.last_status or "") in TERMINAL_STORED_STATUSES

    def as_handle_dict(self) -> dict:
        """Восстановить PipelineHandle.handle для адаптера после рестарта."""
        return {
            "job_id": self.wp_pipeline_id,
            "number": self.wp_number,
            "repo_id": self.repo_id,
            "repo_owner": self.repo_owner,
            "repo_name": self.repo_name,
            "branch": self.branch,
        }


# ── COS-108: Workspace Run tracking ─────────────────────────────────────

class WorkspaceRunRow(ExecutionBase):
    """Лёгкий трекер workspace-прогонов для IDE (run → Woodpecker pipeline).

    COS-109 SSE-стриминг читает wp_number отсюда по run_id.
    """

    __tablename__ = "cosmo_workspace_runs"

    run_id: Mapped[str] = mapped_column(String(64), primary_key=True, default="")
    repo_owner: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    repo_name: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    branch: Mapped[str] = mapped_column(String(128), nullable=False, default="main")
    commit_sha: Mapped[str] = mapped_column(String(64), nullable=False, default="")

    # Woodpecker pipeline handle
    repo_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    wp_number: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    wp_pipeline_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    tracking_url: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.utcnow)
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.utcnow,
        onupdate=datetime.datetime.utcnow)

    __table_args__ = (
        Index("ix_workspace_runs_status", "status"),
        {"comment": "COS-108: workspace run → Woodpecker pipeline tracker"},
    )
