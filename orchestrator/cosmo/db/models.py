"""
COS-B1: SQLAlchemy ORM модели Cosmoport Domain Model (PostgreSQL-only).

Таблицы:
  domains, apps, groups, repo_bindings,
  pipeline_bricks, pipeline_plans, plan_bricks,
  batches, gates, runs, evidence_ledger
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Column, Integer, String, DateTime, Text, ForeignKey, CheckConstraint, Index
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from orchestrator.cosmo.db.session import Base
from orchestrator.cosmo.db.enums import (
    brick_type_enum, batch_status_enum, batch_type_enum,
    run_trigger_enum, run_status_enum,
    gate_type_enum, gate_decision_enum, evidence_type_enum,
)


def _uid():
    return uuid.uuid4().hex[:12]


# ---------------------------------------------------------------------------
# Domain, Applications, Groups, Repo Bindings
# ---------------------------------------------------------------------------


class Domain(Base):
    __tablename__ = "domains"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    forge_type: Mapped[str] = mapped_column(String(32), default="gitea", nullable=False)
    forge_url: Mapped[str] = mapped_column(String(512), nullable=False)
    forge_token_ref: Mapped[str] = mapped_column(String(128), nullable=False)
    rbac_config: Mapped[dict] = mapped_column(JSONB, default=dict)
    quota_max_runs: Mapped[int] = mapped_column(Integer, default=50)
    quota_max_storage_gb: Mapped[int] = mapped_column(Integer, default=100)
    quota_max_cpu: Mapped[int] = mapped_column(Integer, default=8)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    apps: Mapped[list["Application"]] = relationship(back_populates="domain")
    groups: Mapped[list["Group"]] = relationship(back_populates="domain")
    runs: Mapped[list["Run"]] = relationship(back_populates="domain")

__table_args__ = (
        Index("ix_domains_rbac_config", "rbac_config", postgresql_using="gin"),
        Index("ix_domains_created_at", "created_at"),  # COS-052: list ordering
        Index("ix_domains_label", "label"),            # COS-052: label search
        {"comment": "КИТС — бизнес-домены и команды разработки"},
    )


class Application(Base):
    __tablename__ = "apps"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    domain_id: Mapped[str] = mapped_column(String(64), ForeignKey("domains.id"), nullable=False)
    level: Mapped[int] = mapped_column(Integer, nullable=False)
    group_id: Mapped[str] = mapped_column(String(64), ForeignKey("groups.id"), nullable=True)
    pipeline_plan_id: Mapped[str] = mapped_column(String(64), ForeignKey("pipeline_plans.id"), nullable=True)

    domain: Mapped["Domain"] = relationship(back_populates="apps")
    group: Mapped["Group"] = relationship(back_populates="apps")
    repo_bindings: Mapped[list["RepositoryBinding"]] = relationship(back_populates="app")
    plan: Mapped["PipelinePlan"] = relationship("PipelinePlan", foreign_keys=[pipeline_plan_id])

__table_args__ = (
        CheckConstraint("level >= 0 AND level <= 3", name="ck_apps_level"),
        Index("ix_apps_domain_id", "domain_id"),        # COS-052: foreign key join
        Index("ix_apps_group_id", "group_id"),          # COS-052: group hierarchy traversal
        Index("ix_apps_level", "level"),                # COS-052: level filter
        {"comment": "Приложения — Level 0 (библиотеки), Level 1 (сервисы), Level 2 (группы)"},
    )


class RepositoryBinding(Base):
    __tablename__ = "repo_bindings"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uid)
    app_id: Mapped[str] = mapped_column(String(64), ForeignKey("apps.id"), nullable=False)
    forge_id: Mapped[str] = mapped_column(String(64), nullable=False)
    repo_path: Mapped[str] = mapped_column(String(256), nullable=False)
    default_branch: Mapped[str] = mapped_column(String(128), default="main")
    webhook_id: Mapped[str] = mapped_column(String(128), nullable=True)

    app: Mapped["Application"] = relationship(back_populates="repo_bindings")

    __table_args__ = (
        Index("ix_repo_bindings_app_id", "app_id"),     # COS-052: foreign key join
        {"comment": "Привязки приложений к Git-репозиториям (Gitea/GitLab)"},
    )


class Group(Base):
    __tablename__ = "groups"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    domain_id: Mapped[str] = mapped_column(String(64), ForeignKey("domains.id"), nullable=False)
    parent_group_id: Mapped[str] = mapped_column(String(64), ForeignKey("groups.id"), nullable=True)
    level: Mapped[int] = mapped_column(Integer, default=0)
    name: Mapped[str] = mapped_column(String(255), nullable=False)

    domain: Mapped["Domain"] = relationship(back_populates="groups")
    apps: Mapped[list["Application"]] = relationship(back_populates="group")

    __table_args__ = (
        CheckConstraint("level >= 0 AND level <= 3", name="ck_groups_level"),
        Index("ix_groups_domain_id", "domain_id"),       # COS-052: foreign key join
        Index("ix_groups_parent_group_id", "parent_group_id"),  # COS-052: hierarchy traversal
        {"comment": "Группы приложений с иерархией parent/child"},
    )


# ---------------------------------------------------------------------------
# Pipeline Bricks & Plans
# ---------------------------------------------------------------------------


class PipelineBrick(Base):
    __tablename__ = "pipeline_bricks"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    type: Mapped[str] = mapped_column(brick_type_enum, nullable=False)
    source: Mapped[str] = mapped_column(String(256), nullable=False)
    definition_json: Mapped[dict] = mapped_column(JSONB, default=dict)
    depends_on: Mapped[list] = mapped_column(JSONB, default=list)
    gates: Mapped[list] = mapped_column(JSONB, default=list)

    __table_args__ = (
        Index("ix_pipeline_bricks_definition_json", "definition_json", postgresql_using="gin"),
        Index("ix_pipeline_bricks_depends_on", "depends_on", postgresql_using="gin"),
        Index("ix_pipeline_bricks_gates", "gates", postgresql_using="gin"),
        {"comment": "Каталог Pipeline Bricks \u2014 атомарные шаги пайплайнов"},
    )


class PipelinePlan(Base):
    __tablename__ = "pipeline_plans"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    app_id: Mapped[str] = mapped_column(String(64), ForeignKey("apps.id"), nullable=False)
    level: Mapped[str] = mapped_column(String(32), nullable=False, default="app")
    scope_id: Mapped[str] = mapped_column(String(64), nullable=False)
    compiled_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    compiled_hash: Mapped[str] = mapped_column(String(128), nullable=False)

    app: Mapped["Application"] = relationship("Application", foreign_keys=[app_id])
    bricks: Mapped[list["PlanBrick"]] = relationship(back_populates="plan")
    batches: Mapped[list["Batch"]] = relationship(back_populates="plan")
    gates: Mapped[list["Gate"]] = relationship(back_populates="plan")

    __table_args__ = (
        Index("ix_pipeline_plans_app_id", "app_id"),     # COS-052: foreign key join
        Index("ix_pipeline_plans_compiled_at", "compiled_at"),  # COS-052: list ordering
        {"comment": "Скомпилированные планы пайплайнов"},
    )


class PlanBrick(Base):
    """M:N связь: кирпич в контексте плана (сортировка, override)."""
    __tablename__ = "plan_bricks"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uid)
    plan_id: Mapped[str] = mapped_column(String(64), ForeignKey("pipeline_plans.id"), nullable=False)
    brick_id: Mapped[str] = mapped_column(String(64), ForeignKey("pipeline_bricks.id"), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    plan: Mapped["PipelinePlan"] = relationship(back_populates="bricks")

    __table_args__ = (
        Index("ix_plan_bricks_plan_id", "plan_id"),       # COS-052: foreign key join
        Index("ix_plan_bricks_brick_id", "brick_id"),     # COS-052: brick lookup
        {"comment": "M:N связь кирпичей с планами (сортировка)"},
    )


# ---------------------------------------------------------------------------
# Batches
# ---------------------------------------------------------------------------


class Batch(Base):
    __tablename__ = "batches"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    plan_id: Mapped[str] = mapped_column(String(64), ForeignKey("pipeline_plans.id"), nullable=False)
    type: Mapped[str] = mapped_column(batch_type_enum, nullable=False)
    status: Mapped[str] = mapped_column(batch_status_enum, default="pending")
    bricks_refs: Mapped[list] = mapped_column(JSONB, default=list)
    artifacts: Mapped[list] = mapped_column(JSONB, default=list)
    evidence_refs: Mapped[list] = mapped_column(JSONB, default=list)
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)

    plan: Mapped["PipelinePlan"] = relationship(back_populates="batches")
    run: Mapped["Run"] = relationship(back_populates="batch", uselist=False)

    __table_args__ = (
        Index("ix_batch_plan_id", "plan_id"),
        Index("ix_batches_status", "status"),              # COS-052: status filter
        Index("ix_batches_bricks_refs", "bricks_refs", postgresql_using="gin"),
        Index("ix_batches_artifacts", "artifacts", postgresql_using="gin"),
        Index("ix_batches_evidence_refs", "evidence_refs", postgresql_using="gin"),
        {"comment": "Пачки шагов: Build, Static Scan, Deploy, Dynamic Test"},
    )


# ---------------------------------------------------------------------------
# Gates
# ---------------------------------------------------------------------------


class Gate(Base):
    __tablename__ = "gates"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    plan_id: Mapped[str] = mapped_column(String(64), ForeignKey("pipeline_plans.id"), nullable=False)
    type: Mapped[str] = mapped_column(gate_type_enum, default="automatic")
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    policy_json: Mapped[dict] = mapped_column(JSONB, default=dict)
    decision: Mapped[str] = mapped_column(gate_decision_enum, nullable=True)
    decided_by: Mapped[str] = mapped_column(String(128), nullable=True)
    signature: Mapped[str] = mapped_column(String(512), nullable=True)
    decided_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)

    plan: Mapped["PipelinePlan"] = relationship(back_populates="gates")

    __table_args__ = (
        Index("ix_gates_plan_id", "plan_id"),              # COS-052: foreign key join
        Index("ix_gates_position", "position"),            # COS-052: DAG ordering
        Index("ix_gates_policy_json", "policy_json", postgresql_using="gin"),
        {"comment": "Security Gates с политиками и решениями"},
    )


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------


class Run(Base):
    __tablename__ = "runs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uid)
    plan_id: Mapped[str] = mapped_column(String(64), ForeignKey("pipeline_plans.id"), nullable=False)
    trigger: Mapped[str] = mapped_column(run_trigger_enum, nullable=False)
    initiator_user_id: Mapped[str] = mapped_column(String(128), default="system")
    initiator_role: Mapped[str] = mapped_column(String(64), default="system")
    domain_id: Mapped[str] = mapped_column(String(64), ForeignKey("domains.id"), nullable=False)
    batch_id: Mapped[str] = mapped_column(String(64), ForeignKey("batches.id"), nullable=True)
    status: Mapped[str] = mapped_column(run_status_enum, default="pending")
    findings_refs: Mapped[list] = mapped_column(JSONB, default=list)
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    domain: Mapped["Domain"] = relationship(back_populates="runs")
    batch: Mapped["Batch"] = relationship(back_populates="run")

__table_args__ = (
        Index("ix_runs_domain_id", "domain_id"),            # COS-052: foreign key join
        Index("ix_runs_status", "status"),                  # COS-052: status filter
        Index("ix_runs_created_at", "created_at"),          # COS-052: list ordering
        Index("ix_runs_findings_refs", "findings_refs", postgresql_using="gin"),
        {"comment": "Прогоны — экземпляры выполнения пайплайнов"},
    )


# ---------------------------------------------------------------------------
# Release (COS-036)
# ---------------------------------------------------------------------------


class Release(Base):
    __tablename__ = "releases"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uid)
    domain_id: Mapped[str] = mapped_column(String(64), ForeignKey("domains.id"), nullable=False)
    plan_id: Mapped[str] = mapped_column(String(64), ForeignKey("pipeline_plans.id"), nullable=False)
    run_ids: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    trigger: Mapped[str] = mapped_column(run_trigger_enum, default="manual")
    status: Mapped[str] = mapped_column(String(32), default="draft", nullable=False)
    changelog: Mapped[str] = mapped_column(Text, default="")
    version: Mapped[str] = mapped_column(String(128), default="")
    artifacts: Mapped[list] = mapped_column(JSONB, default=list)
    approvals: Mapped[list] = mapped_column(JSONB, default=list)
    # COS-054: межзонный трансфер
    current_zone: Mapped[str] = mapped_column(String(8), default="zr", nullable=False)
    transfer_history: Mapped[list] = mapped_column(JSONB, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    domain: Mapped["Domain"] = relationship()
    plan: Mapped["PipelinePlan"] = relationship()

    __table_args__ = (
        Index("ix_releases_run_ids", "run_ids", postgresql_using="gin"),
        Index("ix_releases_domain_id", "domain_id"),        # COS-052: foreign key join
        Index("ix_releases_status", "status"),              # COS-052: status filter
        Index("ix_releases_created_at", "created_at"),      # COS-052: list ordering
        {"comment": "Релизные пакеты — связка прошедших gate прогонов (COS-036)"},
    )


# ---------------------------------------------------------------------------
# Evidence Ledger
# ---------------------------------------------------------------------------


class EvidenceLedgerEntry(Base):
    __tablename__ = "evidence_ledger"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uid)
    run_id: Mapped[str] = mapped_column(String(64), ForeignKey("runs.id"), nullable=False)
    batch_id: Mapped[str] = mapped_column(String(64), ForeignKey("batches.id"), nullable=True)
    type: Mapped[str] = mapped_column(evidence_type_enum, nullable=False)
    content_ref: Mapped[str] = mapped_column(String(512), nullable=True)
    content_hash: Mapped[str] = mapped_column(String(128), nullable=True)
    provenance_json: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("ix_evidence_run_id", "run_id"),
        Index("ix_evidence_batch_id", "batch_id"),          # COS-052: foreign key join
        Index("ix_evidence_created_at", "created_at"),      # COS-052: list ordering
        Index("ix_evidence_ledger_provenance_json", "provenance_json", postgresql_using="gin"),
        {"comment": "Неизменяемый журнал доказательств SHA-256"},
    )