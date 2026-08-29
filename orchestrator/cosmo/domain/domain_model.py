"""
COS-L1: Pydantic модель Domain (Космопорт).

Domain — верхнеуровневая сущность: владелец Gitea, RBAC, квота.
Один Domain = один клиент/проект Космопорта.
"""
from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator

StrictModel = ConfigDict(extra="ignore")


class ForgeBinding(BaseModel):
    """Привязка Domain к forge (Gitea/Jenkins)."""
    model_config = StrictModel

    forge_type: Literal["gitea", "jenkins"] = Field(
        default="gitea",
        description="Тип forge: gitea или jenkins",
    )
    url: str = Field(
        ...,
        min_length=1,
        description="URL forge (например http://gitea:3000)",
    )
    token_ref: str = Field(
        ...,
        min_length=1,
        description="Ссылка на токен в секретнице (VAULT/GITEA_TOKEN)",
    )


class DomainQuota(BaseModel):
    """Квоты домена: лимиты на ресурсы."""
    model_config = StrictModel

    max_runs: int = Field(
        default=50,
        ge=1,
        description="Максимум одновременных запусков",
    )
    max_storage_gb: int = Field(
        default=100,
        ge=1,
        description="Максимум места под артефакты (ГБ)",
    )
    max_cpu: int = Field(
        default=8,
        ge=1,
        description="Максимум CPU-ядер на домен",
    )


class Domain(BaseModel):
    """Каноническая модель Domain (COS-L1)."""
    model_config = StrictModel

    id: str = Field(
        ...,
        min_length=1,
        description="Уникальный идентификатор домена",
    )
    label: str = Field(
        ...,
        min_length=1,
        description="Человекочитаемое имя домена",
    )
    forge_binding: ForgeBinding = Field(
        ...,
        description="Привязка к forge",
    )
    rbac_config: dict = Field(
        default_factory=dict,
        description="RBAC-конфигурация домена (5 ролей)",
    )
    quota: DomainQuota = Field(
        default_factory=DomainQuota,
        description="Квоты домена",
    )

    @field_validator("label")
    @classmethod
    def label_not_empty(cls, v: str) -> str:
        """Метка не может быть пустой или только из пробелов."""
        if not v.strip():
            raise ValueError("label не может быть пустым")
        return v.strip()

    @field_validator("quota")
    @classmethod
    def quota_positive(cls, v: DomainQuota) -> DomainQuota:
        """Все значения квоты должны быть положительными."""
        if v.max_runs <= 0:
            raise ValueError("max_runs должен быть > 0")
        if v.max_storage_gb <= 0:
            raise ValueError("max_storage_gb должен быть > 0")
        if v.max_cpu <= 0:
            raise ValueError("max_cpu должен быть > 0")
        return v