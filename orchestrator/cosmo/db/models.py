"""Cosmoport 2.0 — SQLAlchemy 2 Async ORM Models.

Durable Truth: PostgreSQL 16.
Таблицы:
  domains, groups, pipeline_bricks, apps, repo_bindings,
  pipeline_plans, plan_bricks, batches, gates, runs,
  releases, evidence_ledger, cosmo_builds, cosmo_deployments
"""
from __future__ import annotations

import datetime
import uuid
from typing import Optional, Any

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from orchestrator.cosmo.db.enums import (
    batch_status_enum,
    batch_type_enum,
    brick_type_enum,
    evidence_type_enum,
    gate_decision_enum,
    gate_type_enum,
    run_status_enum,
    run_trigger_enum,
)
from orchestrator.cosmo.db.session import Base


def _uid() -> str:
    return uuid.uuid4().hex[:12]


# ---------------------------------------------------------------------------
# Domains (КИТС)
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
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=datetime.datetime.utcnow)

    apps: Mapped[list["Application"]] = relationship(back_populates="domain")
    groups: Mapped[list["Group"]] = relationship(back_populates="domain")
    runs: Mapped[list["Run"]] = relationship(back_populates="domain")
    releases: Mapped[list["Release"]] = relationship(back_populates="domain")

    __table_args__ = (
        Index("ix_domains_rbac_config", "rbac_config", postgresql_using="gin"),
        Index("ix_domains_created_at", "created_at"),
        Index("ix_domains_label", "label"),
        {"comment": "КИТС — бизнес-домены и команды разработки"},
    )


# ---------------------------------------------------------------------------
# Groups (Группы/папки)
# ---------------------------------------------------------------------------


class Group(Base):
    __tablename__ = "groups"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    domain_id: Mapped[str] = mapped_column(String(64), ForeignKey("domains.id"), nullable=False)
    parent_group_id: Mapped[Optional[str]] = mapped_column(String(64), ForeignKey("groups.id"), nullable=True)
    level: Mapped[int] = mapped_column(Integer, default=0)
    name: Mapped[str] = mapped_column(String(255), nullable=False)

    domain: Mapped["Domain"] = relationship(back_populates="groups")
    apps: Mapped[list["Application"]] = relationship(back_populates="group")

    __table_args__ = (
        CheckConstraint("level >= 0 AND level <= 3", name="ck_groups_level"),
        Index("ix_groups_domain_id", "domain_id"),
        Index("ix_groups_parent_group_id", "parent_group_id"),
        {"comment": "Группы приложений с иерархией parent/child"},
    )


# ---------------------------------------------------------------------------
# Pipeline Bricks (Каталог кирпичей)
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
        {"comment": "Каталог Pipeline Bricks — атомарные шаги пайплайнов"},
    )


# ---------------------------------------------------------------------------
# Applications (Приложения Level 0..3)
# ---------------------------------------------------------------------------


class Application(Base):
    __tablename__ = "apps"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    domain_id: Mapped[str] = mapped_column(String(64), ForeignKey("domains.id"), nullable=False)
    level: Mapped[int] = mapped_column(Integer, nullable=False)
    group_id: Mapped[Optional[str]] = mapped_column(String(64), ForeignKey("groups.id"), nullable=True)
    pipeline_plan_id: Mapped[Optional[str]] = mapped_column(String(64), ForeignKey("pipeline_plans.id"), nullable=True)

    domain: Mapped["Domain"] = relationship(back_populates="apps")
    group: Mapped[Optional["Group"]] = relationship(back_populates="apps")
    repo_bindings: Mapped[list["RepositoryBinding"]] = relationship(back_populates="app")
    plan: Mapped[Optional["PipelinePlan"]] = relationship(
        "PipelinePlan",
        foreign_keys=[pipeline_plan_id],
        back_populates="apps",
    )

    __table_args__ = (
        CheckConstraint("level >= 0 AND level <= 3", name="ck_apps_level"),
        Index("ix_apps_domain_id", "domain_id"),
        Index("ix_apps_group_id", "group_id"),
        Index("ix_apps_level", "level"),
        {"comment": "Приложения — Level 0..3 внутри Domain"},
    )


# ---------------------------------------------------------------------------
# Repository Bindings (Привязка к Git)
# ---------------------------------------------------------------------------


class RepositoryBinding(Base):
    __tablename__ = "repo_bindings"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uid)
    app_id: Mapped[str] = mapped_column(String(64), ForeignKey("apps.id"), nullable=False)
    forge_id: Mapped[str] = mapped_column(String(64), nullable=False)
    repo_path: Mapped[str] = mapped_column(String(256), nullable=False)
    default_branch: Mapped[str] = mapped_column(String(128), default="main")
    webhook_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)

    app: Mapped["Application"] = relationship(back_populates="repo_bindings")

    __table_args__ = (
        Index("ix_repo_bindings_app_id", "app_id"),
        {"comment": "Привязки приложений к Git-репозиториям (Gitea/GitLab)"},
    )


# ---------------------------------------------------------------------------
# Pipeline Plans (Скомпилированные планы)
# ---------------------------------------------------------------------------


class PipelinePlan(Base):
    __tablename__ = "pipeline_plans"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    app_id: Mapped[str] = mapped_column(String(64), ForeignKey("apps.id"), nullable=False)
    level: Mapped[str] = mapped_column(String(32), nullable=False, default="app")
    scope_id: Mapped[str] = mapped_column(String(64), nullable=False)
    compiled_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=datetime.datetime.utcnow)
    compiled_hash: Mapped[str] = mapped_column(String(128), nullable=False)

    apps: Mapped[list["Application"]] = relationship(
        "Application",
        foreign_keys=[Application.pipeline_plan_id],
        back_populates="plan",
    )
    bricks: Mapped[list["PlanBrick"]] = relationship(back_populates="plan", cascade="all, delete-orphan")
    batches: Mapped[list["Batch"]] = relationship(back_populates="plan", cascade="all, delete-orphan")
    gates: Mapped[list["Gate"]] = relationship(back_populates="plan", cascade="all, delete-orphan")
    runs: Mapped[list["Run"]] = relationship(back_populates="plan")

    __table_args__ = (
        Index("ix_pipeline_plans_app_id", "app_id"),
        Index("ix_pipeline_plans_compiled_at", "compiled_at"),
        {"comment": "Скомпилированные планы пайплайнов"},
    )


# ---------------------------------------------------------------------------
# Plan Bricks (M:N связь план ↔ кирпичи)
# ---------------------------------------------------------------------------


class PlanBrick(Base):
    __tablename__ = "plan_bricks"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uid)
    plan_id: Mapped[str] = mapped_column(String(64), ForeignKey("pipeline_plans.id"), nullable=False)
    brick_id: Mapped[str] = mapped_column(String(64), ForeignKey("pipeline_bricks.id"), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    plan: Mapped["PipelinePlan"] = relationship(back_populates="bricks")
    brick: Mapped["PipelineBrick"] = relationship()

    __table_args__ = (
        Index("ix_plan_bricks_plan_id", "plan_id"),
        Index("ix_plan_bricks_brick_id", "brick_id"),
        {"comment": "M:N связь кирпичей с планами (сортировка)"},
    )


# ---------------------------------------------------------------------------
# Batches (Пачки шагов)
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
    started_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime, nullable=True)

    plan: Mapped["PipelinePlan"] = relationship(back_populates="batches")
    runs: Mapped[list["Run"]] = relationship(back_populates="batch")

    __table_args__ = (
        Index("ix_batch_plan_id", "plan_id"),
        Index("ix_batches_status", "status"),
        Index("ix_batches_bricks_refs", "bricks_refs", postgresql_using="gin"),
        Index("ix_batches_artifacts", "artifacts", postgresql_using="gin"),
        Index("ix_batches_evidence_refs", "evidence_refs", postgresql_using="gin"),
        {"comment": "Пачки шагов: Build, Static Scan, Deploy, Dynamic Test"},
    )


# ---------------------------------------------------------------------------
# Gates (Security Gates)
# ---------------------------------------------------------------------------


class Gate(Base):
    __tablename__ = "gates"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    plan_id: Mapped[str] = mapped_column(String(64), ForeignKey("pipeline_plans.id"), nullable=False)
    type: Mapped[str] = mapped_column(gate_type_enum, default="automatic")
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    policy_json: Mapped[dict] = mapped_column(JSONB, default=dict)
    decision: Mapped[Optional[str]] = mapped_column(gate_decision_enum, nullable=True)
    decided_by: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    signature: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    decided_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime, nullable=True)

    plan: Mapped["PipelinePlan"] = relationship(back_populates="gates")

    __table_args__ = (
        Index("ix_gates_plan_id", "plan_id"),
        Index("ix_gates_position", "position"),
        Index("ix_gates_policy_json", "policy_json", postgresql_using="gin"),
        {"comment": "Security Gates с политиками и решениями"},
    )


# ---------------------------------------------------------------------------
# Runs (Прогоны)
# ---------------------------------------------------------------------------


class Run(Base):
    __tablename__ = "runs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uid)
    plan_id: Mapped[str] = mapped_column(String(64), ForeignKey("pipeline_plans.id"), nullable=False)
    trigger: Mapped[str] = mapped_column(run_trigger_enum, nullable=False)
    initiator_user_id: Mapped[str] = mapped_column(String(128), default="system")
    initiator_role: Mapped[str] = mapped_column(String(64), default="system")
    domain_id: Mapped[str] = mapped_column(String(64), ForeignKey("domains.id"), nullable=False)
    batch_id: Mapped[Optional[str]] = mapped_column(String(64), ForeignKey("batches.id"), nullable=True)
    status: Mapped[str] = mapped_column(run_status_enum, default="pending")
    findings_refs: Mapped[list] = mapped_column(JSONB, default=list)
    started_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=datetime.datetime.utcnow)

    domain: Mapped["Domain"] = relationship(back_populates="runs")
    plan: Mapped["PipelinePlan"] = relationship(back_populates="runs")
    batch: Mapped[Optional["Batch"]] = relationship(back_populates="runs")
    evidence_entries: Mapped[list["EvidenceLedgerEntry"]] = relationship(back_populates="run", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_runs_domain_id", "domain_id"),
        Index("ix_runs_status", "status"),
        Index("ix_runs_created_at", "created_at"),
        Index("ix_runs_findings_refs", "findings_refs", postgresql_using="gin"),
        {"comment": "Прогоны — экземпляры выполнения пайплайнов"},
    )


# ---------------------------------------------------------------------------
# Releases (Релизные бандлы)
# ---------------------------------------------------------------------------


class Release(Base):
    __tablename__ = "releases"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uid)
    domain_id: Mapped[str] = mapped_column(String(64), ForeignKey("domains.id"), nullable=False)
    plan_id: Mapped[str] = mapped_column(String(64), ForeignKey("pipeline_plans.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="draft", nullable=False)
    current_zone: Mapped[str] = mapped_column(String(8), default="zr", nullable=False)
    version: Mapped[str] = mapped_column(String(64), default="1.0.0", nullable=False)
    run_ids: Mapped[list] = mapped_column(JSONB, default=list)
    approvals: Mapped[list] = mapped_column(JSONB, default=list)
    artifacts: Mapped[list] = mapped_column(JSONB, default=list)
    transfer_history: Mapped[list] = mapped_column(JSONB, default=list)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=datetime.datetime.utcnow)

    domain: Mapped["Domain"] = relationship(back_populates="releases")
    plan: Mapped["PipelinePlan"] = relationship()
    deployments: Mapped[list["Deployment"]] = relationship(back_populates="release")

    __table_args__ = (
        Index("ix_releases_domain_id", "domain_id"),
        Index("ix_releases_status", "status"),
        Index("ix_releases_created_at", "created_at"),
        Index("ix_releases_run_ids", "run_ids", postgresql_using="gin"),
        {"comment": "Релизы и межзонный трансфер (ЗР -> ЗТ -> ЗПЭ)"},
    )


# ---------------------------------------------------------------------------
# Evidence Ledger (Журнал улик SHA-256)
# ---------------------------------------------------------------------------


class EvidenceLedgerEntry(Base):
    __tablename__ = "evidence_ledger"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uid)
    run_id: Mapped[str] = mapped_column(String(64), ForeignKey("runs.id"), nullable=False)
    batch_id: Mapped[Optional[str]] = mapped_column(String(64), ForeignKey("batches.id"), nullable=True)
    type: Mapped[str] = mapped_column(evidence_type_enum, nullable=False)
    content_ref: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    content_hash: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    provenance_json: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=datetime.datetime.utcnow)

    run: Mapped["Run"] = relationship(back_populates="evidence_entries")
    batch: Mapped[Optional["Batch"]] = relationship()

    __table_args__ = (
        Index("ix_evidence_run_id", "run_id"),
        Index("ix_evidence_batch_id", "batch_id"),
        Index("ix_evidence_created_at", "created_at"),
        Index("ix_evidence_provenance_json", "provenance_json", postgresql_using="gin"),
        CheckConstraint(
            "type IN ('screenshot','raw_request','raw_response','log','alert','finding','decision')",
            name="ck_evidence_type",
        ),
        {"comment": "Неизменяемый журнал доказательств SHA-256"},
    )


# ---------------------------------------------------------------------------
# Builds (Первоклассные сборки — SAN-012)
# ---------------------------------------------------------------------------


class Build(Base):
    __tablename__ = "cosmo_builds"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uid)
    app_id: Mapped[str] = mapped_column(String(64), ForeignKey("apps.id"), nullable=False)
    domain_id: Mapped[str] = mapped_column(String(64), ForeignKey("domains.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    commit_sha: Mapped[str] = mapped_column(String(64), nullable=False)
    branch: Mapped[str] = mapped_column(String(128), default="main", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    artifacts: Mapped[list] = mapped_column(JSONB, default=list)
    build_logs: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    meta: Mapped[dict] = mapped_column(JSONB, default=dict)
    started_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime, nullable=True)
    initiator_user_id: Mapped[str] = mapped_column(String(128), default="system", nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=datetime.datetime.utcnow)

    app: Mapped["Application"] = relationship()
    domain: Mapped["Domain"] = relationship()
    deployments: Mapped[list["Deployment"]] = relationship(back_populates="build")

    __table_args__ = (
        Index("ix_builds_app_id", "app_id"),
        Index("ix_builds_domain_id", "domain_id"),
        Index("ix_builds_status", "status"),
        Index("ix_builds_created_at", "created_at"),
        Index("ix_builds_artifacts", "artifacts", postgresql_using="gin"),
        {"comment": "Сборки ПО с фиксацией точного Git Commit SHA"},
    )


# ---------------------------------------------------------------------------
# Deployments (Первоклассные развертывания — SAN-012)
# ---------------------------------------------------------------------------


class Deployment(Base):
    __tablename__ = "cosmo_deployments"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uid)
    app_id: Mapped[str] = mapped_column(String(64), ForeignKey("apps.id"), nullable=False)
    domain_id: Mapped[str] = mapped_column(String(64), ForeignKey("domains.id"), nullable=False)
    build_id: Mapped[str] = mapped_column(String(64), ForeignKey("cosmo_builds.id"), nullable=False)
    release_id: Mapped[Optional[str]] = mapped_column(String(64), ForeignKey("releases.id"), nullable=True)
    segment: Mapped[str] = mapped_column(String(32), default="bare", nullable=False)
    target_zone: Mapped[str] = mapped_column(String(8), default="zr", nullable=False)
    runtime_name: Mapped[str] = mapped_column(String(128), default="docker", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    custom_url: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    operator_id: Mapped[str] = mapped_column(String(128), default="system", nullable=False)
    env_vars: Mapped[dict] = mapped_column(JSONB, default=dict)
    rollback_from_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    started_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=datetime.datetime.utcnow)

    app: Mapped["Application"] = relationship()
    domain: Mapped["Domain"] = relationship()
    build: Mapped["Build"] = relationship(back_populates="deployments")
    release: Mapped[Optional["Release"]] = relationship(back_populates="deployments")

    __table_args__ = (
        Index("ix_deploys_app_id", "app_id"),
        Index("ix_deploys_domain_id", "domain_id"),
        Index("ix_deploys_build_id", "build_id"),
        Index("ix_deploys_target_zone", "target_zone"),
        Index("ix_deploys_status", "status"),
        Index("ix_deploys_created_at", "created_at"),
        {"comment": "Развертывания приложений по зонам безопасности (ЗР/ЗТ/ЗПЭ)"},
    )


# ══════════════════════════════════════════════════════════════════════════════
# Auto-register LR-001..LR-007 models (shared Base)
# ══════════════════════════════════════════════════════════════════════════════
from orchestrator.cosmo.db.models_lr import (  # noqa: E402, F401 — регистрация схем
    ApplicationKitTag,
    ApplicationTeam,
    ArtifactRecord,
    InstanceConfiguration,
    KitsTag,
    Project,
    ProjectTeam,
    ReleaseBatch,
    ReleaseType,
)

# ══════════════════════════════════════════════════════════════════════════════
# Auto-register STACK/CBR scanner models (shared Base)
# ══════════════════════════════════════════════════════════════════════════════
from orchestrator.cosmo.db.models_scanner import (  # noqa: E402, F401
    ScanEvidence,
    ScanFinding,
    ScanResult,
)
