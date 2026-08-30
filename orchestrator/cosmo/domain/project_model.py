"""
LR-001 / LR-002 / LR-003: Pydantic v2 domain models for Cosmoport 2.0 Project & Team entities.

Project — верхнеуровневая структурная единица КИТС (не путать с Domain).
  - Project: метаданные, владелец, привязка приложений, граф.
  - KitsTag: теги КИТС с many-to-many связью к приложениям.
  - ProjectTeam: наследуемая командная структура с переопределениями на уровне приложения.
"""
from __future__ import annotations

import datetime
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field

StrictModel = ConfigDict(extra="ignore")

# ── KITS Tags (LR-002) ──────────────────────────────────────────────────────

class KitsTag(BaseModel):
    """Тег КИТС — независимая от Domain семантическая метка."""
    model_config = StrictModel

    id: str = Field(..., min_length=1, description="Уникальный ID тега (e.g. 'kits-payments')")
    label: str = Field(..., min_length=1, description="Человекочитаемое имя")
    color: str = Field(default="#1E88E5", description="HEX-цвет для UI")
    description: Optional[str] = Field(default=None, description="Описание тега")


# ── Project (LR-001) ────────────────────────────────────────────────────────

class ProjectMetadata(BaseModel):
    """Метаданные проекта."""
    model_config = StrictModel

    criticality: Literal["category_1", "category_2", "category_3"] = Field(
        default="category_2", description="Категория КИТС"
    )
    sla_tier: Literal["platinum", "gold", "silver", "bronze"] = Field(
        default="gold", description="SLA уровень"
    )
    deployment_model: Literal["monolith", "microservices", "hybrid"] = Field(
        default="microservices", description="Модель развертывания"
    )
    git_repo_root: Optional[str] = Field(default=None, description="Корневой Git репозиторий")
    custom_metadata: Dict[str, Any] = Field(default_factory=dict, description="Расширяемые поля")


class Project(BaseModel):
    """Проект — верхнеуровневая структурная единица КИТС."""
    model_config = StrictModel

    id: str = Field(..., min_length=1, description="Уникальный идентификатор проекта")
    name: str = Field(..., min_length=1, description="Человекочитаемое имя проекта")
    description: Optional[str] = Field(default=None, description="Описание проекта")
    owner_team: str = Field(
        default="core_platform",
        min_length=1,
        description="Команда-владелец проекта",
    )
    metadata: ProjectMetadata = Field(
        default_factory=ProjectMetadata,
        description="Метаданные проекта (критичность, SLA, модель)",
    )
    application_ids: List[str] = Field(
        default_factory=list,
        description="Список ID приложений, входящих в проект",
    )
    graph_edges: List[Dict[str, str]] = Field(
        default_factory=list,
        description="Рёбра графа приложений: [{source: app_id, target: app_id, type: depends_on|triggers|publishes}]",
    )
    kits_tags: List[str] = Field(
        default_factory=list,
        description="ID тегов КИТС",
    )
    created_at: Optional[datetime.datetime] = None
    updated_at: Optional[datetime.datetime] = None


# ── Team Inheritance (LR-003) ────────────────────────────────────────────────

class TeamRoleOverride(BaseModel):
    """Переопределение роли для конкретного члена команды."""
    model_config = StrictModel

    user_id: str = Field(..., min_length=1, description="ID пользователя")
    original_role: str = Field(..., min_length=1, description="Исходная роль (из Project Team)")
    overridden_role: str = Field(..., min_length=1, description="Переопределённая роль")
    reason: str = Field(default="", description="Причина переопределения")
    source: Literal["project", "app_local"] = Field(
        default="app_local", description="Источник назначения"
    )
    assigned_at: Optional[datetime.datetime] = None


class ProjectTeam(BaseModel):
    """Командная структура на уровне проекта (наследуется приложениями)."""
    model_config = StrictModel

    project_id: str = Field(..., min_length=1)
    inherited_members: List[Dict[str, str]] = Field(
        default_factory=list,
        description="Наследуемые члены: [{user_id, role}]",
    )
    local_additions: List[Dict[str, str]] = Field(
        default_factory=list,
        description="Локальные добавления на уровне проекта",
    )
    local_exclusions: List[str] = Field(
        default_factory=list,
        description="ID пользователей, исключённых из наследования",
    )
    role_overrides: List[TeamRoleOverride] = Field(
        default_factory=list,
        description="Переопределения ролей",
    )


class ApplicationTeam(BaseModel):
    """Командная структура на уровне отдельного приложения."""
    model_config = StrictModel

    app_id: str = Field(..., min_length=1)
    project_id: str = Field(..., min_length=1)
    # Наследуемые от Project Team
    inherited_from_project: List[Dict[str, str]] = Field(default_factory=list)
    # Локальные добавления на уровне приложения
    local_members: List[Dict[str, str]] = Field(default_factory=list)
    # Локальные исключения
    local_exclusions: List[str] = Field(default_factory=list)
    # Переопределения ролей
    role_overrides: List[TeamRoleOverride] = Field(default_factory=list)