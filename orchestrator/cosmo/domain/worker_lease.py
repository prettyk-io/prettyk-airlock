"""
COS-071: WorkerLease — стейт-машина жизненного цикла SonarQube CE воркеров.

Состояния:
  requested → provisioning → ready → running → collecting → publishing → teardown → released

При сбоях → failed с классификацией (INFRA_FAILED / SCAN_FAILED / TIMED_OUT)
и гарантированный teardown ресурсов.

Инварианты:
  - Два run не могут получить один порт одновременно
  - Каждый worker имеет детерминированные Docker labels
  - teardown идемпотентен (повторный вызов не падает)
"""
from __future__ import annotations

import time
import uuid
from enum import Enum
from typing import Literal, Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

StrictModel = ConfigDict(extra="ignore")


# ── Состояния жизненного цикла ─────────────────────────────────────────────

class WorkerState(str, Enum):
    REQUESTED = "requested"          # запрос на создание воркера
    PROVISIONING = "provisioning"    # контейнер создаётся
    READY = "ready"                  # контейнер запущен, SonarQube CE жив
    RUNNING = "running"              # сканирование выполняется
    COLLECTING = "collecting"        # сбор результатов (report-task.txt)
    PUBLISHING = "publishing"        # публикация в evidence ledger
    TEARDOWN = "teardown"            # остановка контейнера, освобождение порта
    RELEASED = "released"            # ресурсы полностью освобождены
    FAILED = "failed"                # сбой на любой стадии


class FailureReason(str, Enum):
    INFRA_FAILED = "infra_failed"          # Docker недоступен / контейнер запускается
    SCAN_FAILED = "scan_failed"            # SonarQube CE вернул ошибку
    TIMED_OUT = "timed_out"                # контейнер не ответил за отведённое время
    CONTAINER_STALE = "container_stale"    # зомби-контейнер без активного run_id


# ── Атомарные переходы ──────────────────────────────────────────────────────

_VALID_TRANSITIONS: dict[WorkerState, frozenset[WorkerState]] = {
    WorkerState.REQUESTED:    frozenset({WorkerState.PROVISIONING, WorkerState.FAILED}),
    WorkerState.PROVISIONING: frozenset({WorkerState.READY, WorkerState.FAILED}),
    WorkerState.READY:        frozenset({WorkerState.RUNNING, WorkerState.FAILED, WorkerState.TEARDOWN}),
    WorkerState.RUNNING:      frozenset({WorkerState.COLLECTING, WorkerState.FAILED, WorkerState.TEARDOWN}),
    WorkerState.COLLECTING:   frozenset({WorkerState.PUBLISHING, WorkerState.FAILED, WorkerState.TEARDOWN}),
    WorkerState.PUBLISHING:   frozenset({WorkerState.TEARDOWN, WorkerState.FAILED}),
    WorkerState.TEARDOWN:     frozenset({WorkerState.RELEASED, WorkerState.FAILED}),
    WorkerState.RELEASED:     frozenset(),
    WorkerState.FAILED:       frozenset({WorkerState.TEARDOWN}),
}

_TERMINAL_STATES = frozenset({WorkerState.RELEASED, WorkerState.FAILED})


# ── WorkerLease модель ──────────────────────────────────────────────────────

class WorkerLease(BaseModel):
    """COS-071: лиз воркера — запись о контейнере SonarQube CE."""
    model_config = StrictModel

    worker_id: str = Field(
        default_factory=lambda: f"sonar-{uuid.uuid4().hex[:8]}",
        description="Уникальный ID воркера",
    )
    run_id: str = Field(..., min_length=1, description="ID прогона, которому принадлежит воркер")
    provider: Literal["docker"] = Field(default="docker", description="Провайдер контейнеризации")
    container_id: str = Field(default="", description="ID Docker-контейнера")
    scanner_container_id: str = Field(default="", description="ID scanner-контейнера (если запущен через compose)")
    sonar_project_key: str = Field(default="", description="SonarQube projectKey")
    sonar_task_id: str = Field(default="", description="SonarQube ceTaskId из report-task.txt")
    allocated_port: int = Field(default=0, ge=0, description="Выделенный хост-порт")
    resource_labels: dict[str, str] = Field(
        default_factory=dict,
        description="Docker labels (com.prettyk.run_id, com.prettyk.component, ...)",
    )
    lease_expires_at: float = Field(
        default_factory=lambda: time.time() + 3600.0,
        description="Время истечения лиз (Unix timestamp)",
    )
    state: WorkerState = Field(default=WorkerState.REQUESTED, description="Текущее состояние стейт-машины")
    failure_reason: FailureReason | None = Field(default=None, description="Причина сбоя (только для FAILED)")
    failure_detail: str = Field(default="", description="Детали сбоя")
    created_at: float = Field(default_factory=time.time, description="Время создания (Unix timestamp)")
    updated_at: float = Field(default_factory=time.time, description="Последнее обновление (Unix timestamp)")
    history: list[dict] = Field(default_factory=list, description="История переходов состояний")

    # ── Lifecycle ───────────────────────────────────────────────────────────

    def transition(self, target: WorkerState, **kwargs) -> WorkerLease:
        """Атомарный переход с валидацией и записью в history."""
        allowed = _VALID_TRANSITIONS[self.state]
        if target not in allowed:
            raise ValueError(
                f"Invalid transition: {self.state.value} → {target.value} "
                f"(worker {self.worker_id})"
            )

        entry = {
            "from": self.state.value,
            "to": target.value,
            "at": time.time(),
        }
        if kwargs:
            entry.update(kwargs)

        # Pydantic immutable — создаём новый объект с обновлёнными полями
        new_data = self.model_dump()
        new_data["state"] = target
        new_data["updated_at"] = time.time()
        new_data["history"] = list(self.history) + [entry]

        if target == WorkerState.FAILED and "failure_reason" in kwargs:
            new_data["failure_reason"] = kwargs["failure_reason"]
            if "failure_detail" in kwargs:
                new_data["failure_detail"] = kwargs["failure_detail"]

        return WorkerLease.model_validate(new_data)

    # ── Convenience methods ─────────────────────────────────────────────────

    def fail(self, reason: FailureReason, detail: str = "") -> WorkerLease:
        """Перевести воркер в FAILED с указанием причины."""
        return self.transition(WorkerState.FAILED, failure_reason=reason, failure_detail=detail)

    def teardown(self) -> WorkerLease:
        """Запустить teardown (идемпотентно)."""
        if self.state in (WorkerState.TEARDOWN, WorkerState.RELEASED):
            return self  # уже в процессе или завершён
        if self.state == WorkerState.FAILED:
            # FAILED → TEARDOWN разрешён
            pass
        return self.transition(WorkerState.TEARDOWN)

    def release(self) -> WorkerLease:
        """Освободить все ресурсы (терминальное состояние)."""
        if self.state == WorkerState.RELEASED:
            return self
        return self.transition(WorkerState.RELEASED)

    @property
    def is_terminal(self) -> bool:
        return self.state in _TERMINAL_STATES

    @property
    def is_active(self) -> bool:
        return not self.is_terminal

    @property
    def is_stale(self) -> bool:
        """Лиз истёк (превышен lease_expires_at)."""
        return time.time() > self.lease_expires_at

    def renew_lease(self, seconds: float = 3600.0) -> WorkerLease:
        """Продлить лиз (heartbeat)."""
        new_data = self.model_dump()
        new_data["lease_expires_at"] = time.time() + seconds
        new_data["updated_at"] = time.time()
        return WorkerLease.model_validate(new_data)

    # ── Docker labels ───────────────────────────────────────────────────────

    def default_labels(self) -> dict[str, str]:
        """Детерминированные Docker-лейблы для контейнера."""
        return {
            "com.prettyk.run_id": self.run_id,
            "com.prettyk.component": "sonar-ce-worker",
            "com.prettyk.worker_id": self.worker_id,
            "com.prettyk.provider": self.provider,
            **self.resource_labels,
        }

    @staticmethod
    def label_filters(run_id: str | None = None) -> list[str]:
        """Docker label-фильтры для поиска контейнеров по run_id."""
        filters = ["com.prettyk.component=sonar-ce-worker"]
        if run_id:
            filters.append(f"com.prettyk.run_id={run_id}")
        return filters

    # ── Serialization ───────────────────────────────────────────────────────

    def to_summary(self) -> dict:
        """Краткая сводка для API / мониторинга."""
        return {
            "worker_id": self.worker_id,
            "run_id": self.run_id,
            "state": self.state.value,
            "container_id": self.container_id[:12] if self.container_id else "",
            "allocated_port": self.allocated_port,
            "sonar_task_id": self.sonar_task_id,
            "failure_reason": self.failure_reason.value if self.failure_reason else None,
            "age_sec": int(time.time() - self.created_at),
            "is_stale": self.is_stale,
        }

    @field_validator("allocated_port")
    @classmethod
    def port_in_range(cls, v: int) -> int:
        if v != 0 and not (1024 <= v <= 65535):
            raise ValueError(f"Port must be 0 or 1024-65535, got {v}")
        return v

    @model_validator(mode="after")
    def labels_default_if_empty(self) -> WorkerLease:
        if not self.resource_labels:
            self.resource_labels = self.default_labels()
        return self