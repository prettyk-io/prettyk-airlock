"""
LR-006: Pydantic v2 models for Release Types and ReleaseBatch.

ReleaseType — версионируемый профиль релиза (набор шагов, gates, зон).
ReleaseBatch — пакетный запуск релизного ЖЦ по выбранному типу.
"""
from __future__ import annotations

import datetime
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field

StrictModel = ConfigDict(extra="ignore")


class ReleaseTypeStep(BaseModel):
    """Один шаг в профиле типа релиза."""
    model_config = StrictModel

    order: int = Field(..., ge=0, description="Порядковый номер шага")
    name: str = Field(..., min_length=1, description="Название шага")
    brick_type: str = Field(default="build", description="Тип кирпича")
    gate_required: bool = Field(default=True, description="Требуется ли гейт")
    zone: Optional[str] = Field(default=None, description="Зона выполнения (zr/zt/zpe)")


class ReleaseType(BaseModel):
    """Версионируемый профиль типа релиза."""
    model_config = StrictModel

    id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1, description="Название типа (e.g. 'patch', 'minor', 'emergency')")
    description: Optional[str] = None
    version: str = Field(default="1.0.0", description="Версия профиля")
    steps: List[ReleaseTypeStep] = Field(default_factory=list, description="Шаги ЖЦ")
    required_approvals: int = Field(default=2, ge=1, description="Минимальное количество подписей")
    allowed_zones: List[str] = Field(default_factory=lambda: ["zr", "zt", "zpe"])
    is_active: bool = Field(default=True)
    created_at: Optional[datetime.datetime] = None
    updated_at: Optional[datetime.datetime] = None


class ReleaseBatch(BaseModel):
    """Пакетный запуск релизного ЖЦ."""
    model_config = StrictModel

    id: str = Field(..., min_length=1)
    project_id: str = Field(..., min_length=1)
    release_type_id: str = Field(..., min_length=1, description="ID профиля типа релиза")
    name: str = Field(..., min_length=1, description="Название батча")
    status: Literal["draft", "running", "completed", "failed", "cancelled"] = Field(
        default="draft"
    )
    app_ids: List[str] = Field(default_factory=list, description="Приложения в составе пакета")
    run_id: Optional[str] = Field(default=None, description="ID прогона после старта")
    started_at: Optional[datetime.datetime] = None
    finished_at: Optional[datetime.datetime] = None
    created_at: Optional[datetime.datetime] = None


# ══════════════════════════════════════════════════════════════════════════════
# LR-007: Artifact Registry Persistence
# ══════════════════════════════════════════════════════════════════════════════

class ArtifactRecord(BaseModel):
    """Метаданные артефакта в Registry."""
    model_config = StrictModel

    id: str = Field(..., min_length=1)
    registry_provider: Literal["local-oci", "nexus", "t1_sfera", "harbor"] = Field(
        default="local-oci"
    )
    registry_endpoint: str = Field(..., min_length=1)
    namespace: str = Field(default="cosmoport", description="Организация / пространство имён")
    repository: str = Field(..., min_length=1, description="Репозиторий артефакта")
    artifact_name: str = Field(..., min_length=1, description="Имя артефакта")
    artifact_tag: str = Field(default="latest", description="Тег / версия артефакта")
    digest_sha256: str = Field(..., min_length=64, description="SHA-256 дайджест артефакта")
    sbom_ref: Optional[str] = Field(
        default=None, description="Ссылка на SBOM (vault:secret/... или URL)"
    )
    scan_refs: List[str] = Field(
        default_factory=list, description="Ссылки на отчёты сканирования"
    )
    signature_attestation: Optional[str] = Field(
        default=None, description="Ссылка на подпись / attestation"
    )
    secret_ref: Optional[str] = Field(
        default=None, description="Ссылка на креды реестра (vault:secret/...). Raw passwords запрещены!"
    )
    app_id: Optional[str] = Field(default=None, description="Связанное приложение")
    build_id: Optional[str] = Field(default=None, description="Связанная сборка")
    created_at: Optional[datetime.datetime] = None