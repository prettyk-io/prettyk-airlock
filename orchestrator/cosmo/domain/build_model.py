"""
SAN-012: Pydantic v2 модель Build (Сборка приложения в Космопорте).

Сборка связывает commit SHA в репозитории приложения с артефактами (бинарники, образы, SBOM)
и статусом прохождения компиляции.
"""
from __future__ import annotations

import datetime
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field

StrictModel = ConfigDict(extra="ignore")

BuildStatus = Literal["pending", "running", "success", "failed", "aborted"]


class Build(BaseModel):
    """Первоклассная сущность Build (Сборка)."""
    model_config = StrictModel

    id: str = Field(..., min_length=1, description="Уникальный идентификатор сборки (e.g. bld-001)")
    app_id: str = Field(..., min_length=1, description="ID приложения, к которому относится сборка")
    domain_id: str = Field(default="default", min_length=1, description="ID КИТС-домена")
    title: str = Field(default="", description="Человекочитаемое название сборки")
    commit_sha: str = Field(..., min_length=7, description="Git commit SHA (40 hex символов или short SHA)")
    branch: str = Field(default="main", min_length=1, description="Ветка репозитория")
    status: BuildStatus = Field(default="pending", description="Текущий статус сборки")
    artifacts: List[str] = Field(
        default_factory=list,
        description="Список ссылок на сгенерированные артефакты (образ, tar.gz, sbom)",
    )
    started_at: Optional[datetime.datetime] = Field(
        default=None,
        description="Время старта сборки",
    )
    finished_at: Optional[datetime.datetime] = Field(
        default=None,
        description="Время завершения сборки",
    )
    initiator_user_id: str = Field(
        default="system",
        min_length=1,
        description="ID пользователя или агента, инициировавшего сборку",
    )
    initiator: Optional[str] = Field(
        default=None,
        description="COS-196: клиентский алиас инициатора (initiator_user_id)",
    )
    app_name: Optional[str] = Field(
        default=None,
        description="COS-196: человекочитаемое имя приложения (enrichment для витрины)",
    )
    run_id: Optional[str] = Field(
        default=None,
        description="COS-196: прогон (runs.id), исполняющий сборку",
    )
    evidence_refs: List[str] = Field(
        default_factory=list,
        description="COS-196: id durable-записей Evidence Ledger по прогону сборки",
    )
    build_logs: Optional[str] = Field(
        default="",
        description="Логи процесса сборки",
    )
    meta: Dict[str, Any] = Field(
        default_factory=dict,
        description="Дополнительные метаданные (runner_id, image_tag, dockerfile)",
    )

    @property
    def is_finished(self) -> bool:
        return self.status in ("success", "failed", "aborted")

    @property
    def is_success(self) -> bool:
        return self.status == "success"

    @property
    def duration_seconds(self) -> Optional[float]:
        if self.started_at and self.finished_at:
            return (self.finished_at - self.started_at).total_seconds()
        return None
