"""
COS-008: Абстрактный ExecutionAdapter + реализация Woodpecker.

ExecutionAdapter — базовый интерфейс для CI-исполнителей (Woodpecker, Jenkins).
WoodpeckerAdapter — генерация .woodpecker.yml, submit/status/logs/cancel.
"""
from __future__ import annotations

import logging
import os
from abc import ABC, abstractmethod
from enum import Enum
from typing import Any

import requests
import yaml

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 30


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILURE = "failure"
    KILLED = "killed"
    ERROR = "error"


class ExecutionAdapter(ABC):
    """Абстрактный интерфейс CI-исполнителя.

    Реализации: WoodpeckerAdapter, JenkinsAdapter (COS-008).
    """

    @abstractmethod
    def generate_pipeline_yaml(self, batch: dict) -> str:
        """Сгенерировать конфигурацию пайплайна из Batch."""
        raise NotImplementedError

    @abstractmethod
    def submit_run(self, repo_owner: str, repo_name: str, branch: str = "main") -> dict:
        """Создать и запустить пайплайн. Возвращает handle."""
        raise NotImplementedError

    @abstractmethod
    def get_status(self, handle: dict) -> str:
        """Текущий статус пайплайна."""
        raise NotImplementedError

    @abstractmethod
    def get_logs(self, handle: dict, step: int = 0) -> list[str]:
        """Сырые логи выполнения."""
        raise NotImplementedError

    @abstractmethod
    def cancel_run(self, handle: dict) -> bool:
        """Отменить выполнение."""
        raise NotImplementedError


class WoodpeckerAdapter(ExecutionAdapter):
    """Адаптер Woodpecker CI API."""

    def __init__(self, base_url: str | None = None, token: str = ""):
        self._base = (base_url or os.environ.get("COSMO_WOODPECKER_URL", "http://woodpecker:8000")).rstrip("/")
        self._token = token or os.environ.get("COSMO_WOODPECKER_TOKEN", "")
        self._session = requests.Session()
        self._session.headers.update({
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
        })

    def _get(self, path: str, **kwargs: Any):
        return self._session.get(f"{self._base}{path}", timeout=DEFAULT_TIMEOUT, **kwargs)

    def _post(self, path: str, **kwargs: Any):
        return self._session.post(f"{self._base}{path}", timeout=DEFAULT_TIMEOUT, **kwargs)

    def _delete(self, path: str, **kwargs: Any):
        return self._session.delete(f"{self._base}{path}", timeout=DEFAULT_TIMEOUT, **kwargs)

    # ── ExecutionAdapter interface ──

    def generate_pipeline_yaml(self, batch: dict) -> str:
        """Сгенерировать .woodpecker.yml из Batch."""
        bricks = batch.get("bricks", [])
        pipeline: dict[str, Any] = {"pipeline": {}, "steps": {}}

        for i, brick in enumerate(bricks):
            step_name = brick.get("name", f"step-{i}")
            definition = brick.get("definition", {})
            image = definition.get("image", "alpine:latest")
            step_config: dict[str, Any] = {
                "image": image,
                "commands": definition.get("commands", ["echo 'no commands'"]),
            }
            deps = brick.get("depends_on", [])
            if deps:
                step_config["depends_on"] = deps
            env = definition.get("inputs", {})
            if env:
                step_config["environment"] = env
            pipeline["steps"][step_name] = step_config

        return yaml.dump(pipeline, default_flow_style=False, allow_unicode=True)

    def submit_run(self, repo_owner: str, repo_name: str, branch: str = "main") -> dict:
        r = self._post(
            f"/api/repos/{repo_owner}/{repo_name}/pipelines",
            params={"branch": branch},
        )
        r.raise_for_status()
        data = r.json()
        return {
            "job_id": data["id"],
            "number": data["number"],
            "repo_owner": repo_owner,
            "repo_name": repo_name,
        }

    def get_status(self, handle: dict) -> str:
        r = self._get(
            f"/api/repos/{handle['repo_owner']}/{handle['repo_name']}/pipelines/{handle['number']}",
        )
        r.raise_for_status()
        return r.json().get("status", "pending")

    def get_logs(self, handle: dict, step: int = 0) -> list[str]:
        r = self._get(
            f"/api/repos/{handle['repo_owner']}/{handle['repo_name']}/logs/{handle['number']}/{step}",
        )
        r.raise_for_status()
        data = r.json()
        logs = data if isinstance(data, list) else data.get("logs", [])
        return logs if isinstance(logs, list) else []

    def cancel_run(self, handle: dict) -> bool:
        r = self._delete(
            f"/api/repos/{handle['repo_owner']}/{handle['repo_name']}/pipelines/{handle['number']}",
        )
        return r.status_code in (200, 204)

    def close(self) -> None:
        self._session.close()

    def __enter__(self) -> "WoodpeckerAdapter":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()