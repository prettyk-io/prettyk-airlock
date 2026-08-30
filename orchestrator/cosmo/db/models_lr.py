"""
LR-001..LR-007: SQLAlchemy 2 Async ORM models for Projects, KITS Tags, Teams,
Release Types, ReleaseBatch, Artifact Registry, and Instance Configuration.

Все модели используют DeclarativeBase из orchestrator.cosmo.db.session.
"""
from __future__ import annotations

import datetime
import uuid
from typing import Any, Optional

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from orchestrator.cosmo.db.session import Base


def _uid():
    return uuid.uuid4().hex[:12]


# ══════════════════════════════════════════════════════════════════════════════
# LR-001: Projects
# ══════════════════════════════════════════════════════════════════════════════

class Project(Base):
    """Проект — верхнеуровневая структурная единица КИТС."""
    __tablename__ = "projects"
    __table_args__ = (
        Index("ix_projects_owner_team", "owner_team"),
        Index("ix_projects_created_at", "created_at"),
        {"comment": "Проекты КИТС — структурные единицы"},
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    owner_team: Mapped[str] = mapped_column(String(128), default="core_platform", nullable=False)
    criticality: Mapped[str] = mapped_column(String(32), default="category_2", nullable=False)
    sla_tier: Mapped[str] = mapped_column(String(32), default="gold", nullable=False)
    deployment_model: Mapped[str] = mapped_column(String(32), default="microservices", nullable=False)
    git_repo_root: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    custom_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    application_ids: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    graph_edges: Mapped[list[dict[str, str]]] = mapped_column(JSON, default=list, nullable=False)
    kits_tag_ids: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=datetime.datetime.utcnow)
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow
    )


# ══════════════════════════════════════════════════════════════════════════════
# POST-LUNA-001: ProjectApplication M:N join table
# ══════════════════════════════════════════════════════════════════════════════

class ProjectApplication(Base):
    """M:N связь проектов с приложениями (замена JSON array)."""
    __tablename__ = "project_applications"
    __table_args__ = (
        Index("ix_project_apps_project", "project_id"),
        Index("ix_project_apps_app", "app_id"),
        UniqueConstraint("project_id", "app_id", name="uq_project_app"),
        {"comment": "Проект-Приложение M:N связь (POST-LUNA-001)"},
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uid)
    project_id: Mapped[str] = mapped_column(String(64), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    app_id: Mapped[str] = mapped_column(String(64), ForeignKey("apps.id", ondelete="CASCADE"), nullable=False)
    role: Mapped[str] = mapped_column(String(32), default="owner", nullable=False)  # owner, contributor, consumer
    backfill_source: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)  # projects_json, domain_legacy
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=datetime.datetime.utcnow)


# ══════════════════════════════════════════════════════════════════════════════
# LR-002: KITS Tags
# ══════════════════════════════════════════════════════════════════════════════

class KitsTag(Base):
    """Тег КИТС."""
    __tablename__ = "kits_tags"
    __table_args__ = (
        Index("ix_kits_tags_label", "label"),
        {"comment": "Теги КИТС — семантические метки приложений"},
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    label: Mapped[str] = mapped_column(String(128), nullable=False)
    color: Mapped[str] = mapped_column(String(16), default="#1E88E5", nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=datetime.datetime.utcnow)


class ApplicationKitTag(Base):
    """M:N связь приложений и КИТС-тегов."""
    __tablename__ = "application_kits_tags"
    __table_args__ = (
        Index("ix_app_kits_tag_app_id", "app_id"),
        Index("ix_app_kits_tag_tag_id", "tag_id"),
        UniqueConstraint("app_id", "tag_id", name="uq_app_kits_tag"),
        {"comment": "Many-to-Many связь приложений с тегами КИТС"},
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uid)
    app_id: Mapped[str] = mapped_column(String(64), ForeignKey("apps.id", ondelete="CASCADE"), nullable=False)
    tag_id: Mapped[str] = mapped_column(String(64), ForeignKey("kits_tags.id", ondelete="CASCADE"), nullable=False)


# ══════════════════════════════════════════════════════════════════════════════
# LR-003: Team Inheritance & Overrides
# ══════════════════════════════════════════════════════════════════════════════

class ProjectTeam(Base):
    """Командная структура на уровне проекта."""
    __tablename__ = "project_teams"
    __table_args__ = (
        Index("ix_project_teams_project_id", "project_id"),
        {"comment": "Командная структура проектов с наследованием"},
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uid)
    project_id: Mapped[str] = mapped_column(String(64), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    inherited_members: Mapped[list[dict[str, str]]] = mapped_column(JSON, default=list, nullable=False)
    local_additions: Mapped[list[dict[str, str]]] = mapped_column(JSON, default=list, nullable=False)
    local_exclusions: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    role_overrides: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=datetime.datetime.utcnow)


class ApplicationTeam(Base):
    """Командная структура на уровне приложения."""
    __tablename__ = "application_teams"
    __table_args__ = (
        Index("ix_app_teams_app_id", "app_id"),
        Index("ix_app_teams_project_id", "project_id"),
        {"comment": "Командная структура приложений с наследованием от проекта"},
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uid)
    app_id: Mapped[str] = mapped_column(String(64), ForeignKey("apps.id", ondelete="CASCADE"), nullable=False)
    project_id: Mapped[str] = mapped_column(String(64), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    inherited_from_project: Mapped[list[dict[str, str]]] = mapped_column(JSON, default=list, nullable=False)
    local_members: Mapped[list[dict[str, str]]] = mapped_column(JSON, default=list, nullable=False)
    local_exclusions: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    role_overrides: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=datetime.datetime.utcnow)


# ══════════════════════════════════════════════════════════════════════════════
# LR-006: Release Types & ReleaseBatch
# ══════════════════════════════════════════════════════════════════════════════

class ReleaseType(Base):
    """Версионируемые профили типов релизов."""
    __tablename__ = "release_types"
    __table_args__ = (
        Index("ix_release_types_is_active", "is_active"),
        {"comment": "Версионируемые профили типов релизов (patch, minor, emergency)"},
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    version: Mapped[str] = mapped_column(String(32), default="1.0.0", nullable=False)
    steps_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    required_approvals: Mapped[int] = mapped_column(Integer, default=2, nullable=False)
    allowed_zones: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=datetime.datetime.utcnow)
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow
    )


class ReleaseBatch(Base):
    """Пакетный запуск релизного ЖЦ."""
    __tablename__ = "release_batches"
    __table_args__ = (
        Index("ix_release_batches_project_id", "project_id"),
        Index("ix_release_batches_status", "status"),
        {"comment": "Пакетные запуски релизного ЖЦ"},
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(64), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    release_type_id: Mapped[str] = mapped_column(String(64), ForeignKey("release_types.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="draft", nullable=False)
    app_ids: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    run_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    started_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=datetime.datetime.utcnow)


# ══════════════════════════════════════════════════════════════════════════════
# LR-007: Artifact Registry Persistence
# ══════════════════════════════════════════════════════════════════════════════

class ArtifactRecord(Base):
    """Артефакты в Registry."""
    __tablename__ = "artifact_records"
    __table_args__ = (
        Index("ix_artifact_records_app_id", "app_id"),
        Index("ix_artifact_records_build_id", "build_id"),
        Index("ix_artifact_records_digest", "digest_sha256"),
        {"comment": "Метаданные артефактов — local-oci / Nexus / Т1-Сфера (Artifactory удалён)"},
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    registry_provider: Mapped[str] = mapped_column(String(32), default="oci", nullable=False)
    registry_endpoint: Mapped[str] = mapped_column(String(512), nullable=False)
    namespace: Mapped[str] = mapped_column(String(128), default="cosmoport", nullable=False)
    repository: Mapped[str] = mapped_column(String(255), nullable=False)
    artifact_name: Mapped[str] = mapped_column(String(255), nullable=False)
    artifact_tag: Mapped[str] = mapped_column(String(128), default="latest", nullable=False)
    digest_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    sbom_ref: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    scan_refs: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    signature_attestation: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    secret_ref: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    app_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    build_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=datetime.datetime.utcnow)


# ══════════════════════════════════════════════════════════════════════════════
# LR-004: Instance Configuration
# ══════════════════════════════════════════════════════════════════════════════

class InstanceConfiguration(Base):
    """Глобальная конфигурация инстанса Cosmoport."""
    __tablename__ = "instance_configuration"
    __table_args__ = (
        {"comment": "Глобальная конфигурация экземпляра Cosmoport"},
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default="cosmo-primary")
    instance_id: Mapped[str] = mapped_column(String(128), default="cosmo-primary", nullable=False)
    network_id: Mapped[str] = mapped_column(String(128), default="kits-core-net", nullable=False)
    platform_label: Mapped[str] = mapped_column(String(255), default="KITS Central Platform", nullable=False)
    zone: Mapped[str] = mapped_column(String(8), default="zr", nullable=False)
    forge_provider_type: Mapped[str] = mapped_column(String(32), default="gitea", nullable=False)
    forge_endpoint_url: Mapped[str] = mapped_column(String(512), nullable=False)
    forge_auth_ref: Mapped[str] = mapped_column(String(512), default="vault:secret/cosmo/forge/credentials", nullable=False)
    prettyk_endpoint_url: Mapped[str] = mapped_column(String(512), default="https://prettyk.io/api/v1", nullable=False)
    prettyk_auth_ref: Mapped[str] = mapped_column(String(512), default="vault:secret/cosmo/prettyk/credentials", nullable=False)
    prettyk_check_timeout_seconds: Mapped[int] = mapped_column(Integer, default=30, nullable=False)
    registry_provider_type: Mapped[str] = mapped_column(String(32), default="oci", nullable=False)
    registry_endpoint_url: Mapped[str] = mapped_column(String(512), nullable=False)
    registry_namespace: Mapped[str] = mapped_column(String(128), default="cosmoport", nullable=False)
    registry_auth_ref: Mapped[str] = mapped_column(String(512), default="vault:secret/cosmo/registry/credentials", nullable=False)
    extra: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=datetime.datetime.utcnow)
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow
    )