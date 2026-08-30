"""
SAN-013: Pydantic v2 модель Deployment (Развертывание приложения в Космопорте).

Развертывание связывает сборку (Build) или релиз (Release) с конкретной зоной
(ЗР / ЗТ / ЗПЭ) и средой выполнения (Bare / Integration).
"""
from __future__ import annotations

import datetime
from typing import Any, Dict, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field

StrictModel = ConfigDict(extra="ignore")

DeploymentStatus = Literal["pending", "running", "success", "failed", "deleted", "rollback"]
DeploymentSegment = Literal["bare", "integration"]
DeploymentZone = Literal["zr", "zt", "zpe"]


class Deployment(BaseModel):
    """Первоклассная сущность Deployment (Развертывание)."""
    model_config = StrictModel

    id: str = Field(..., min_length=1, description="Уникальный идентификатор развертывания (e.g. dep-001)")
    build_id: str = Field(..., min_length=1, description="ID сборки (Build), которая развертывается")
    app_id: str = Field(..., min_length=1, description="ID приложения")
    domain_id: str = Field(default="default", min_length=1, description="ID КИТС-домена")
    release_id: Optional[str] = Field(
        default=None,
        description="Опциональный ID релиза (если деплой в рамках релизного поезда)",
    )
    segment: DeploymentSegment = Field(
        default="bare",
        description="Сегмент развертывания: bare (изолированный стенд) или integration (общий контур)",
    )
    target_zone: DeploymentZone = Field(
        default="zr",
        description="Целевая зона назначения: zr (Разработка), zt (Тестирование), zpe (Пром)",
    )
    status: DeploymentStatus = Field(
        default="pending",
        description="Текущий статус развертывания",
    )
    custom_url: Optional[str] = Field(
        default=None,
        description="Точка входа / URL развернутого приложения (например http://app.zt.kits.bank:8080)",
    )
    operator_id: str = Field(
        default="system",
        min_length=1,
        description="ID оператора или агента, запустившего развертывание",
    )
    started_at: Optional[datetime.datetime] = Field(
        default=None,
        description="Время начала развертывания",
    )
    finished_at: Optional[datetime.datetime] = Field(
        default=None,
        description="Время завершения развертывания",
    )
    env_vars: Dict[str, str] = Field(
        default_factory=dict,
        description="Переменные окружения стенда",
    )
    rollback_from_id: Optional[str] = Field(
        default=None,
        description="ID предыдущего развертывания, если текущий деплой является откатом",
    )

    @property
    def is_active(self) -> bool:
        return self.status == "success"

    @property
    def can_rollback(self) -> bool:
        return self.status in ("success", "failed")
