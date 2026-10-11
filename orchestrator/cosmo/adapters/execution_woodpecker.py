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
    возвращает workflows[].children[]; ``steps`` — legacy-форма).
    Строки лога приходят в ``data`` (base64), ``line`` — номер строки.
  - submit — POST /api/repos/{repo_id}/pipelines с JSON-телом
    PipelineOptions {branch, variables}; query-параметр branch из
    прототипа сервером игнорируется.

Статус возвращается RAW-строкой без домысливания: маппинг в batch-статусы
и honest unknown/degraded — зона BatchExecutor (COS-097), не адаптера.
"""
from __future__ import annotations

import base64
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

# SAST-STEP-1 (live-гонка): WP пишет log_entries шага асинхронно — строки
# могут появиться ПОСЛЕ смены статуса пайплайна (замер на стенде: маркер
# отчёта лёг в БД в ту же секунду, что и terminal, но уже после нашего
# чтения → ложный alert «отчёт не найден»). Добор пустых логов терминальных
# шагов включается явно (settle_empty_s), чтобы не менять legacy-семантику.
_TERMINAL_STEP_STATES = frozenset({"success", "failure", "error", "killed"})
_EMPTY_LOG_SETTLE_ATTEMPTS = 3

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

        COS-162: шаг типа ``docker_build`` (``definition.type == "docker_build"``)
        разворачивается в канонический ``docker build`` (под qualified-тегом)
        + ``docker push`` по тегу (no-``latest``); manifest-digest снимается
        с ответа push → маркер ``<name>:<version>@sha256:<digest>``.

        COS-194: нерезолвнутая ссылка (не-dict ref либо ``unresolved_refs`` от
        резолвера) не выдумывает шаг и не роняет генерацию — неполнота явно
        фиксируется секцией ``x-audit-incomplete`` (ref + причина).
        """
        bricks = batch.get("bricks", [])
        unresolved: list[dict[str, Any]] = [
            dict(u) for u in (batch.get("unresolved_refs") or [])
            if isinstance(u, dict)
        ]
        pipeline: dict[str, Any] = {"when": {"event": ["manual"]}, "steps": {}}

        for i, brick in enumerate(bricks):
            if not isinstance(brick, dict):
                # COS-194: ссылка не разрешена — честный маркер, без шага-фантома.
                unresolved.append({
                    "ref": str(brick),
                    "reason": "brick definition not resolved (raw ref in audit batch)",
                })
                continue
            step_name = brick.get("name", f"step-{i}")
            definition = brick.get("definition", {})
            step_type = definition.get("type")
            if step_type == "docker_build":
                pipeline["steps"][step_name] = self._docker_build_step(definition)
                continue
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
            # SAST-STEP-1: образы с собственным entrypoint (напр. sonar-scanner-cli)
            # требуют явного сброса, чтобы `commands` исполнялись шеллом шага.
            entrypoint = definition.get("entrypoint")
            if entrypoint is not None:
                step_config["entrypoint"] = entrypoint
            pipeline["steps"][step_name] = step_config

        if unresolved:
            pipeline["x-audit-incomplete"] = unresolved

        return yaml.dump(pipeline, default_flow_style=False, allow_unicode=True)

    def _docker_build_step(self, definition: dict) -> dict[str, Any]:
        """COS-162: woodpecker-шаг docker_build (build + push digest-tag).

        Docker-доступ внутри executor'а — через mounted ``docker.sock``
        (woodpecker-agent монтирует ``/var/run/docker.sock``); kaniko/podman
        НЕ выдумываются. Образ пушится в registry зоны по тегу (no-``latest``);
        manifest-digest снимается с ответа push и печатается каноническим
        маркером COS-142.
        """
        from orchestrator.cosmo.domain.docker_build import (
            DockerBuildSpec,
            render_docker_build_commands,
        )
        from orchestrator.cosmo.adapters.registry_gap import enforce_gap_push

        spec = DockerBuildSpec.from_definition(definition)
        # COS-163: docker_build — push в registry зоны. В GAP-режиме внешний
        # registry (docker.io/ghcr.io/quay.io) → честная ошибка на генерации,
        # а не молчаливый пайплайн, падающий в никуда при исполнении.
        enforce_gap_push(
            "local-oci", spec.registry, operation_type="push"
        )
        digest_file = ".woodpecker-image-digest"
        commands = render_docker_build_commands(spec, digest_file)
        return {
            "image": "docker:24-cli",
            "volumes": ["/var/run/docker.sock:/var/run/docker.sock"],
            "commands": commands,
        }

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
        """Развёрнутый список шагов из workflows-дерева (v3.5).

        Живой WP API отдаёт шаги как ``workflows[].children`` (Go-модель v3
        ``Workflow.Children``); ``steps`` — legacy-форма (моки/старые ответы).
        Дрифт пойман live-смоком COS-188: без fallback деривация чанков и
        collect_all_logs молча видели 0 шагов на реальном пайплайне.
        """
        steps: list[dict] = []
        for wf in detail.get("workflows") or []:
            for st in wf.get("steps") or wf.get("children") or []:
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
                raw = entry.get("data")
                if raw is not None:
                    # v3.5: строка лога — base64 в ``data``; ``line`` — номер.
                    # Контракт-дрифт найден live-смоком COS-188 (было: числа).
                    try:
                        lines.append(
                            base64.b64decode(raw).decode("utf-8", "replace"))
                    except Exception:  # noqa: BLE001 — не base64 → как есть
                        lines.append(str(raw))
                else:
                    lines.append(str(entry.get("line", entry.get("message", ""))))
            else:
                lines.append(str(entry))
        return lines

    def collect_all_logs(self, handle: dict, settle_empty_s: float = 0.0,
                         settle_attempts: int = _EMPTY_LOG_SETTLE_ATTEMPTS,
                         ) -> dict[str, list[str]]:
        """COS-097: логи всех шагов пайплайна {step_name: [lines]}.

        Используется evidence-путём: SHA-256 digest собирается из
        реального прогона, а не выдумывается.

        SAST-STEP-1: ``settle_empty_s > 0`` включает bounded-добор для
        терминальных шагов с пустыми логами — WP флешит log_entries
        асинхронно, и чтение ровно в момент terminal могло застать шаг
        пустым (→ ложный alert «отчёт не найден»). По умолчанию ожидание
        выключено: legacy-вызовы сохраняют прежнюю семантику, живой
        evidence-путь (executor) включает добор явно.

        COS-196: тот же флеш-лаг режет и НЕПУСТЫЕ логи — хвост шага
        (digest-маркер печатается последним) мог ещё не долиться в момент
        terminal-полла. Bounded добор до стабилизации размера; данные —
        только реальные (ожидание, не выдумка).
        """
        detail = self.get_pipeline(handle)
        out: dict[str, list[str]] = {}
        for step in self._flatten_steps(detail):
            name = str(step["name"])
            lines = self._fetch_step_logs(handle, step)
            terminal = str(step.get("state") or "") in _TERMINAL_STEP_STATES
            if terminal and settle_empty_s > 0:
                if not lines:
                    attempts = max(1, int(settle_attempts))
                    for attempt in range(2, attempts + 1):
                        time.sleep(settle_empty_s)
                        lines = self._fetch_step_logs(handle, step)
                        if lines:
                            logger.info(
                                "Woodpecker logs settled for pipeline #%s step %r "
                                "(attempt %d)", handle.get("number"), name, attempt)
                            break
                else:
                    lines = self._settle_growing_logs(
                        handle, step, lines, settle_empty_s, settle_attempts)
            out[name] = lines
        return out

    def _settle_growing_logs(self, handle: dict, step: dict,
                             lines: list[str], pause_s: float,
                             attempts: int) -> list[str]:
        """COS-196: bounded добор растущих логов терминального шага.

        WP флешит лог-чанки асинхронно; пока размер растёт — перечитываем
        (до ``attempts`` раз), две подряд равных выборки считаем стабильными.
        """
        stable = 0
        for _ in range(max(1, int(attempts))):
            time.sleep(pause_s)
            fresh = self._fetch_step_logs(handle, step)
            if len(fresh) > len(lines):
                logger.info(
                    "Woodpecker logs grew for pipeline #%s step %r (%d→%d lines)",
                    handle.get("number"), step.get("name"), len(lines), len(fresh))
                lines = fresh
                stable = 0
            else:
                stable += 1
                if stable >= 2:
                    break
        return lines

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
