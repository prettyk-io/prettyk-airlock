# -*- coding: utf-8 -*-
"""COS-008/COS-097: Абстрактный ExecutionAdapter + Woodpecker v3.5.

ExecutionAdapter — базовый интерфейс для CI-исполнителей (Woodpecker, Jenkins).
WoodpeckerAdapter — генерация .woodpecker.yml, submit/status/logs/cancel.

COS-097: контракт приведён к живому Woodpecker v3.5 (верифицировано по
server/router/api.go + server/api/pipeline.go тега v3.5.0):

  - repo-группа маршрутизируется по ЧИСЛОВОМУ ``repo_id`` (middleware
    SetRepo парсит int64, owner/name → 400). Полное имя резолвится через
    GET /api/repos/lookup/{owner}/{name} и кэшируется в адаптере.
  - cancel — POST /api/repos/{repo_id}/pipelines/{number}/cancel.
    DELETE pipelines/{number} в v3.5 УДАЛЯЕТ запись пайплайна (только для
    terminal-статусов) — прототип COS-008 использовал его как cancel, что
    было опасно и честно запрещено сервером.
  - логи — GET /api/repos/{repo_id}/logs/{number}/{stepId}, где stepId —
    DB id шага из workflow-дерева пайплайна (GET pipelines/{number}
    возвращает workflows[].steps[]).
  - submit — POST /api/repos/{repo_id}/pipelines с JSON-телом
    PipelineOptions {branch, variables}; query-параметр branch из
    прототипа сервером игнорируется.

Статус возвращается RAW-строкой без домысливания: маппинг в batch-статусы
и honest unknown/degraded — зона BatchExecutor (COS-097), не адаптера.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from abc import ABC, abstractmethod
from enum import Enum
from typing import Any

import requests
import yaml

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 30
_LOOKUP_TTL_SEC = 300.0

# COS-127: repo.config_file — глобальная настройка репозитория; свап
# выбранного конфига сериализуем в процессе API (cosmo-api — один инстанс).
_CONFIG_SWAP_LOCK = threading.Lock()


class JobStatus(str, Enum):
    """Woodpecker pipeline statuses (model.StatusValue, v3.5)."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILURE = "failure"
    KILLED = "killed"
    ERROR = "error"
    BLOCKED = "blocked"
    DECLINED = "declined"
    SKIPPED = "skipped"

    @classmethod
    def is_known(cls, raw: str) -> bool:
        return raw in cls._value2member_map_

    @classmethod
    def is_terminal(cls, raw: str) -> bool:
        return raw in _TERMINAL_WP_STATUSES


# Terminal по контракту v3.5 (не pending/running/blocked-on-approval).
# blocked/declined — waiting for approval / declined: terminal для нашего
# цикла (прогон не начнётся сам), но НЕ провал: маппинг решает executor.
_TERMINAL_WP_STATUSES = frozenset(
    {"success", "failure", "killed", "error", "declined", "skipped"}
)


class ExecutionAdapter(ABC):
    """Абстрактный интерфейс CI-исполнителя.

    Реализации: WoodpeckerAdapter, JenkinsAdapter (COS-008).
    """

    @abstractmethod
    def generate_pipeline_yaml(self, batch: dict) -> str:
        """Сгенерировать конфигурацию пайплайна из Batch."""
        raise NotImplementedError

    @abstractmethod
    def submit_run(self, repo_owner: str, repo_name: str, branch: str = "main",
                   config_file: str | None = None) -> dict:
        """Создать и запустить пайплайн. Возвращает handle.

        config_file — путь к выбранному конфигу пайплайна (COS-127);
        None → default-конфиг репозитория (backward-compatible).
        """
        raise NotImplementedError

    @abstractmethod
    def get_status(self, handle: dict) -> str:
        """Текущий статус пайплайна (RAW-строка Woodpecker)."""
        raise NotImplementedError

    @abstractmethod
    def get_logs(self, handle: dict, step: int = 0) -> list[str]:
        """Сырые логи выполнения (по порядковому индексу шага)."""
        raise NotImplementedError

    @abstractmethod
    def cancel_run(self, handle: dict) -> bool:
        """Отменить выполнение."""
        raise NotImplementedError


class WoodpeckerAdapter(ExecutionAdapter):
    """Адаптер Woodpecker CI API (v3.5 контракт)."""

    def __init__(self, base_url: str | None = None, token: str = ""):
        self._base = (base_url or os.environ.get("PK_WOODPECKER_URL")
                      or os.environ.get("COSMO_WOODPECKER_URL", "http://woodpecker:8000")).rstrip("/")
        self._token = token or os.environ.get("COSMO_WOODPECKER_TOKEN", "")
        self._session = requests.Session()
        self._session.headers.update({
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
        })
        # COS-097: кэш owner/name → numeric repo_id (lookup-маршрут v3.5).
        self._repo_id_cache: dict[tuple[str, str], tuple[int, float]] = {}
        self._cache_lock = threading.Lock()

    def _get(self, path: str, **kwargs: Any):
        return self._session.get(f"{self._base}{path}", timeout=DEFAULT_TIMEOUT, **kwargs)

    def _post(self, path: str, **kwargs: Any):
        return self._session.post(f"{self._base}{path}", timeout=DEFAULT_TIMEOUT, **kwargs)

    def _patch(self, path: str, **kwargs: Any):
        return self._session.patch(f"{self._base}{path}", timeout=DEFAULT_TIMEOUT, **kwargs)

    # ── COS-097: repo_id resolution (v3.5: только числовой id) ──

    def resolve_repo_id(self, repo_owner: str, repo_name: str) -> int:
        """Числовой repo_id по owner/name (кэш с TTL) либо passthrough числа.

        Woodpecker v3.5 принимает в :repo_id только int — owner/name даёт
        400 от middleware SetRepo. Полное имя резолвим один раз через
        GET /api/repos/lookup/{owner}/{name} и держим в кэше 5 минут.
        """
        if str(repo_owner).isdigit() and repo_name == "":
            return int(repo_owner)
        key = (str(repo_owner), str(repo_name))
        with self._cache_lock:
            hit = self._repo_id_cache.get(key)
        if hit and (time.time() - hit[1]) < _LOOKUP_TTL_SEC:
            return hit[0]

        r = self._get(f"/api/repos/lookup/{repo_owner}/{repo_name}")
        if r.status_code == 404:
            raise LookupError(
                f"Woodpecker repo '{repo_owner}/{repo_name}' not found "
                "(repo не подключён к Woodpecker или forge не настроен)"
            )
        r.raise_for_status()
        data = r.json()
        repo_id = int(data["id"])
        with self._cache_lock:
            self._repo_id_cache[key] = (repo_id, time.time())
        return repo_id

    def _repo_ref(self, handle: dict) -> int:
        """repo_id из handle (submit записывает) или resolve по owner/name."""
        rid = handle.get("repo_id")
        if rid:
            return int(rid)
        return self.resolve_repo_id(handle["repo_owner"], handle["repo_name"])

    # ── ExecutionAdapter interface ──

    def generate_pipeline_yaml(self, batch: dict) -> str:
        """Сгенерировать .woodpecker.yml из Batch.

        Пайплайн кладётся в repo (COS-096 source); эта генерация —
        канонический вид ожидаемой конфигурации для аудита/сверки.
        """
        bricks = batch.get("bricks", [])
        pipeline: dict[str, Any] = {"when": {"event": ["manual"]}, "steps": {}}

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

    def submit_run(self, repo_owner: str, repo_name: str, branch: str = "main",
                   config_file: str | None = None) -> dict:
        """POST /api/repos/{repo_id}/pipelines, тело PipelineOptions.

        Тело (не query): v3.5 CreatePipeline декодирует JSON
        PipelineOptions {branch, variables}; query-параметр игнорируется.

        COS-127: v3.5 не принимает имя конфига в PipelineOptions — конфиг
        берётся из repo.config_file. Поэтому при config_file задан:
          GET repo → original config_file;
          PATCH repo.config_file = выбранный путь;
          POST pipeline (сервер читает конфиг СИНХРОННО в этом запросе);
          PATCH repo.config_file обратно (finally).
        Пустой original → default-порядок Woodpecker (.woodpecker/,
        .woodpecker.yaml, .woodpecker.yml).
        """
        repo_id = self.resolve_repo_id(repo_owner, repo_name)
        if config_file:
            with _CONFIG_SWAP_LOCK:
                original = self._get_repo_config_by_id(repo_id)
                if original == config_file:
                    return self._create_pipeline(repo_id, repo_owner, repo_name, branch)
                self._patch_repo_config(repo_id, config_file)
                try:
                    return self._create_pipeline(repo_id, repo_owner, repo_name, branch)
                finally:
                    try:
                        self._patch_repo_config(repo_id, original)
                    except Exception:  # noqa: BLE001
                        logger.error(
                            "Failed to restore config_file for %s/%s "
                            "(was %r, selected %r) — repo config may be stale",
                            repo_owner, repo_name, original, config_file,
                        )
        return self._create_pipeline(repo_id, repo_owner, repo_name, branch)

    def _create_pipeline(self, repo_id: int, repo_owner: str, repo_name: str,
                         branch: str) -> dict:
        r = self._post(f"/api/repos/{repo_id}/pipelines", json={"branch": branch})
        if r.status_code in (401, 403):
            raise PermissionError(
                f"Woodpecker denied submit for {repo_owner}/{repo_name} "
                f"(HTTP {r.status_code}) — нужен token с push-доступом к repo"
            )
        r.raise_for_status()
        data = r.json()
        return {
            "job_id": data["id"],
            "number": data["number"],
            "repo_id": repo_id,
            "repo_owner": repo_owner,
            "repo_name": repo_name,
            "branch": branch,
        }

    # ── COS-127: repo config_file (выбор pipeline-конфига) ──

    def get_repo_config(self, repo_owner: str, repo_name: str) -> str:
        """Текущий repo.config_file ("" → default-порядок Woodpecker)."""
        return self._get_repo_config_by_id(self.resolve_repo_id(repo_owner, repo_name))

    def _get_repo_config_by_id(self, repo_id: int) -> str:
        r = self._get(f"/api/repos/{repo_id}")
        if r.status_code == 404:
            raise LookupError(f"Woodpecker repo id={repo_id} not found")
        r.raise_for_status()
        return str((r.json() or {}).get("config_file") or "")

    def _patch_repo_config(self, repo_id: int, config_file: str) -> None:
        r = self._patch(f"/api/repos/{repo_id}", json={"config_file": config_file})
        if r.status_code in (401, 403):
            raise PermissionError(
                f"Woodpecker denied repo settings update for id={repo_id} "
                f"(HTTP {r.status_code}) — нужен token с admin-доступом к repo"
            )
        r.raise_for_status()

    def get_pipeline(self, handle: dict) -> dict:
        """Полный pipeline JSON (с workflows[].steps[] деревом)."""
        repo_id = self._repo_ref(handle)
        r = self._get(f"/api/repos/{repo_id}/pipelines/{handle['number']}")
        r.raise_for_status()
        return r.json()

    def get_status(self, handle: dict) -> str:
        """RAW-статус пайплайна (без маппинга — решает executor)."""
        return str(self.get_pipeline(handle).get("status", "pending"))

    def _flatten_steps(self, detail: dict) -> list[dict]:
        """Развёрнутый список шагов из workflows-дерева (v3.5)."""
        steps: list[dict] = []
        for wf in detail.get("workflows") or []:
            for st in wf.get("steps") or []:
                steps.append({
                    "id": st.get("id"),
                    "pid": st.get("pid"),
                    "name": st.get("name") or f"workflow-{wf.get('name')}/step",
                    "state": st.get("state"),
                    "workflow": wf.get("name"),
                })
        return steps

    def get_logs(self, handle: dict, step: int = 0) -> list[str]:
        """Логи одного шага по порядковому индексу (легаси-совместимость).

        v3.5: GET /api/repos/{repo_id}/logs/{number}/{stepId}, где stepId —
        DB id шага; индекс резолвится через workflow-дерево пайплайна.
        """
        detail = self.get_pipeline(handle)
        steps = self._flatten_steps(detail)
        if step >= len(steps):
            return []
        return self._fetch_step_logs(handle, steps[step])

    def _fetch_step_logs(self, handle: dict, step: dict) -> list[str]:
        if step.get("id") is None:
            return []
        repo_id = self._repo_ref(handle)
        r = self._get(f"/api/repos/{repo_id}/logs/{handle['number']}/{step['id']}")
        if r.status_code == 404:
            # Логи шага ещё не записаны / удалены retention-политикой.
            logger.warning("Woodpecker logs 404 for pipeline #%s step %r",
                           handle.get("number"), step.get("name"))
            return []
        r.raise_for_status()
        data = r.json()
        if not isinstance(data, list):
            return []
        lines: list[str] = []
        for entry in data:
            if isinstance(entry, dict):
                lines.append(str(entry.get("line", entry.get("message", ""))))
            else:
                lines.append(str(entry))
        return lines

    def collect_all_logs(self, handle: dict) -> dict[str, list[str]]:
        """COS-097: логи всех шагов пайплайна {step_name: [lines]}.

        Используется evidence-путём: SHA-256 digest собирается из
        реального прогона, а не выдумывается.
        """
        detail = self.get_pipeline(handle)
        out: dict[str, list[str]] = {}
        for step in self._flatten_steps(detail):
            out[str(step["name"])] = self._fetch_step_logs(handle, step)
        return out

    def get_step_logs_by_id(self, handle: dict, step_id: int) -> list[str]:
        """COS-112: логи шага по Woodpecker step ID (не индексу).

        В отличие от get_logs(handle, step=0), который ищет по порядковому
        индексу в уплощённом списке, этот метод находит шаг по его DB id
        из pipeline-дерева. Используется REST-эндпоинтом для постраничного
        чтения логов завершённых шагов.
        """
        detail = self.get_pipeline(handle)
        for step in self._flatten_steps(detail):
            if step.get("id") == step_id:
                return self._fetch_step_logs(handle, step)
        return []

    def cancel_run(self, handle: dict) -> bool:
        """POST /api/repos/{repo_id}/pipelines/{number}/cancel (v3.5).

        ВАЖНО: DELETE pipelines/{number} в v3.5 удаляет запись пайплайна —
        не cancel (прототип COS-008 ошибочно использовал DELETE).
        """
        repo_id = self._repo_ref(handle)
        r = self._post(f"/api/repos/{repo_id}/pipelines/{handle['number']}/cancel")
        return r.status_code in (200, 202, 204)

    # ── COS-133: run lifecycle (detail / cancel / rerun) ──

    def get_pipeline_detail(self, handle: dict) -> dict:
        """Актуальный статус, шаги и тайминги пайплайна.

        v3.5: GET /api/repos/{repo_id}/pipelines/{number} отдаёт
        workflows[].steps[] c state/started/finished/exit_code.
        """
        return self.get_pipeline(handle)

    def cancel_pipeline(self, handle: dict) -> dict:
        """Отмена пайплайна (v3.5 POST .../pipelines/{number}/cancel).

        В отличие от cancel_run(bool) — честный PermissionError при
        auth-отказе и raise_for_status на прочих ошибках, чтобы route
        отдал осмысленный HTTP-код, а не молчаливый False.
        """
        repo_id = self._repo_ref(handle)
        r = self._post(f"/api/repos/{repo_id}/pipelines/{handle['number']}/cancel")
        if r.status_code in (401, 403):
            raise PermissionError(
                f"Woodpecker denied cancel for pipeline #{handle.get('number')} "
                f"(HTTP {r.status_code}) — нужен token с push-доступом к repo"
            )
        r.raise_for_status()
        return {"number": handle.get("number"), "cancelled": True}

    def rerun_pipeline(self, handle: dict) -> dict:
        """Повторный запуск пайплайна (v3.5 POST .../pipelines/{number}).

        Сервер создаёт НОВЫЙ пайплайн по тому же коммиту/конфигу;
        возвращаем handle-совместимый dict (job_id/number/repo_id).
        """
        repo_id = self._repo_ref(handle)
        r = self._post(f"/api/repos/{repo_id}/pipelines/{handle['number']}")
        if r.status_code in (401, 403):
            raise PermissionError(
                f"Woodpecker denied rerun for pipeline #{handle.get('number')} "
                f"(HTTP {r.status_code}) — нужен token с push-доступом к repo"
            )
        r.raise_for_status()
        data = r.json()
        return {
            "job_id": data["id"],
            "number": data["number"],
            "repo_id": repo_id,
        }

    def close(self) -> None:
        self._session.close()

    def __enter__(self) -> "WoodpeckerAdapter":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()
