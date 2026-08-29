"""
COS-L4: Pydantic модель Run & Batch (Космопорт).

Run — один запуск пайплайна для Domain.
Batch — группа кирпичей одного типа внутри Run.
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator

StrictModel = ConfigDict(extra="ignore")

RunTrigger = Literal["scheduled", "pre_release", "emergency", "manual"]
BatchStatus = Literal["pending", "running", "passed", "failed", "blocked"]
RunStatus = Literal[
    "draft", "pending", "queued", "running", "succeeded", "failed", "blocked", "cancelled"
]


class Batch(BaseModel):
    """Группа кирпичей одного типа (напр. все SAST-шаги)."""
    model_config = StrictModel

    id: str = Field(..., min_length=1)
    plan_id: str = Field(..., min_length=1)
    type: str = Field(..., min_length=1)
    status: BatchStatus = Field(default="pending")
    bricks: list[str] = Field(
        default_factory=list,
        description="ID кирпичей в этом batch'е",
    )
    artifacts: list[str] = Field(
        default_factory=list,
        description="Ссылки на артефакты",
    )
    evidence: list[str] = Field(
        default_factory=list,
        description="Ссылки на evidence-записи",
    )


class Run(BaseModel):
    """Один запуск пайплайна."""
    model_config = StrictModel

    id: str = Field(..., min_length=1)
    plan_id: str = Field(..., min_length=1)
    trigger: RunTrigger = Field(
        ...,
        description="Тип запуска",
    )
    initiator: str = Field(
        default="system",
        min_length=1,
        description="Кто запустил (system / user_id)",
    )
    domain_id: str = Field(..., min_length=1)
    status: RunStatus = Field(default="pending")
    started_at: datetime | None = Field(default=None)
    finished_at: datetime | None = Field(default=None)
    created_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="Время создания",
    )
    batches: list[Batch] = Field(
        default_factory=list,
        description="Список batch'ей",
    )
    gates: list[str] = Field(
        default_factory=list,
        description="ID gate'ов этого запуска",
    )
    findings: list[str] = Field(
        default_factory=list,
        description="ID находок (findings)",
    )
    evidence_ledger_ref: str | None = Field(
        default=None,
        description="Ссылка на EvidenceLedger (COS-B13)",
    )

    @field_validator("batches")
    @classmethod
    def batches_belong_to_plan(cls, v: list[Batch], info) -> list[Batch]:
        """Все batch'и должны принадлежать тому же plan_id."""
        plan_id = info.data.get("plan_id")
        if plan_id:
            for b in v:
                if b.plan_id != plan_id:
                    raise ValueError(
                        f"Batch {b.id} принадлежит plan {b.plan_id}, "
                        f"а не {plan_id}"
                    )
        return v