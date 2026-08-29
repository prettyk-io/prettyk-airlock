"""
COS-L5: Pydantic модель Security Gate (Космопорт).

Gate — контрольная точка пайплайна: автоматическая или ручная.
GatePolicy — правила: по типу находки → действие (block/warn/pass).
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator

StrictModel = ConfigDict(extra="ignore")

GateType = Literal["automatic", "manual"]
GateAction = Literal["block", "warn", "pass"]
GateDecision = Literal["pass", "block", "manual_required"]


class GatePolicyRule(BaseModel):
    """Одно правило GatePolicy: finding_type → действие."""
    model_config = StrictModel

    finding_type: str = Field(
        ...,
        min_length=1,
        description="Тип находки (Critical, High, Medium, Low, Info)",
    )
    action: GateAction = Field(
        ...,
        description="Действие при срабатывании",
    )
    max_count: int | None = Field(
        default=None,
        ge=0,
        description="Максимум находок этого типа (None = без лимита)",
    )


class GatePolicy(BaseModel):
    """Политика gate: набор правил."""
    model_config = StrictModel

    rules: list[GatePolicyRule] = Field(
        ...,
        min_length=1,
        description="Список правил (минимум одно)",
    )


class Gate(BaseModel):
    """Контрольная точка пайплайна."""
    model_config = StrictModel

    id: str = Field(..., min_length=1)
    type: GateType = Field(
        default="automatic",
        description="Тип: automatic (автоматический) или manual (ручной)",
    )
    position: int = Field(
        ...,
        ge=0,
        description="Позиция gate в пайплайне (0 = первый)",
    )
    policy: GatePolicy = Field(
        ...,
        description="Политика gate",
    )
    decision: GateDecision | None = Field(
        default=None,
        description="Решение gate (заполняется при прохождении)",
    )
    decided_by: str | None = Field(
        default=None,
        description="Кто принял решение (для manual gate)",
    )
    signature: str | None = Field(
        default=None,
        description="Цифровая подпись решения",
    )
    decided_at: datetime | None = Field(
        default=None,
        description="Время принятия решения",
    )

    @model_validator(mode="after")
    def manual_gate_requires_decider(self) -> "Gate":
        """Ручной gate требует decided_by при решении."""
        if self.type == "manual" and self.decision and not self.decided_by:
            raise ValueError("manual gate требует decided_by при принятии решения")
        return self

    @model_validator(mode="after")
    def decision_requires_type_match(self) -> "Gate":
        """Решение manual_required допустимо только для manual gate."""
        if self.type == "automatic" and self.decision == "manual_required":
            raise ValueError("automatic gate не может иметь решение manual_required")
        return self