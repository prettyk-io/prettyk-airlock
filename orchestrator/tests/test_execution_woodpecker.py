# -*- coding: utf-8 -*-
"""COS-008/COS-097: Тесты Woodpecker ExecutionAdapter (v3.5 контракт).

Контракт верифицирован по исходникам woodpecker-ci v3.5.0
(server/router/api.go, server/api/pipeline.go):
  - repo-маршруты по ЧИСЛОВОМУ repo_id; owner/name → /repos/lookup/*.
  - submit: POST /repos/{repo_id}/pipelines, JSON-тело {branch}.
  - cancel: POST /repos/{repo_id}/pipelines/{number}/cancel
    (DELETE в v3.5 удаляет запись пайплайна — не cancel!).
  - логи: GET /repos/{repo_id}/logs/{number}/{stepId}; stepId — DB id
    шага из workflow-дерева.
  - статус: RAW-строка без маппинга (решает executor).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

_orch = Path(__file__).resolve().parents[1]
if str(_orch) not in sys.path:
    sys.path.insert(0, str(_orch))

from cosmo.adapters.execution_woodpecker import (  # noqa: E402
    JobStatus,
    WoodpeckerAdapter,
)


# ── Fake HTTP session: фиксирует вызовы, возвращает заготовки ──


class FakeResponse:
    def __init__(self, status_code=200, json_data=None):
        self.status_code = status_code
        self._json = json_data
        self.text = ""

    def json(self):
        if self._json is None:
            raise ValueError("no json")
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests
            raise requests.HTTPError(f"HTTP {self.status_code}")


class FakeSession:
    def __init__(self, responses=None):
        # responses: dict[(method, path_prefix) → FakeResponse | callable]
        self.responses = responses or {}
        self.calls: list[tuple[str, str, dict]] = []
        self.headers: dict[str, str] = {}

    def _find(self, method: str, url: str):
        # "http://wp:8000/api/repos/..." → "/api/repos/..."
        parts = url.split("/", 3)
        path = "/" + parts[3] if len(parts) > 3 else "/"
        for (m, prefix), resp in self.responses.items():
            if m == method and path.startswith(prefix):
                return resp
        return FakeResponse(404)

    def get(self, url, timeout=None, **kw):
        self.calls.append(("GET", url, kw))
        r = self._find("GET", url)
        return r() if callable(r) else r

    def post(self, url, timeout=None, **kw):
        self.calls.append(("POST", url, kw))
        r = self._find("POST", url)
        return r() if callable(r) else r

    def delete(self, url, timeout=None, **kw):
        self.calls.append(("DELETE", url, kw))
        r = self._find("DELETE", url)
        return r() if callable(r) else r

    def close(self):
        pass


def _lookup_response(repo_id=42):
    return FakeResponse(200, {"id": repo_id, "full_name": "cosmo/default"})


def _pipeline_response(status="running", number=7, pipeline_id=9001):
    return FakeResponse(200, {
        "id": pipeline_id,
        "number": number,
        "status": status,
        "workflows": [
            {
                "id": 500, "pid": 1, "name": "wf-main", "status": status,
                "steps": [
                    {"id": 601, "pid": 1, "name": "clone", "state": status},
                    {"id": 602, "pid": 2, "name": "scan", "state": status},
                ],
            },
        ],
    })


def _make_adapter(responses) -> tuple[WoodpeckerAdapter, FakeSession]:
    adapter = WoodpeckerAdapter("http://wp:8000", "tok")
    session = FakeSession(responses)
    adapter._session = session
    return adapter, session


class TestJobStatus:
    def test_all_statuses(self):
        assert JobStatus.PENDING.value == "pending"
        assert JobStatus.RUNNING.value == "running"
        assert JobStatus.SUCCESS.value == "success"
        assert JobStatus.FAILURE.value == "failure"
        assert JobStatus.KILLED.value == "killed"
        assert JobStatus.ERROR.value == "error"
        # COS-097: v3.5 статусы ожидания/отклонения видны честно
        assert JobStatus.BLOCKED.value == "blocked"
        assert JobStatus.DECLINED.value == "declined"
        assert JobStatus.SKIPPED.value == "skipped"

    def test_terminal_contract(self):
        assert JobStatus.is_terminal("success")
        assert JobStatus.is_terminal("failure")
        assert JobStatus.is_terminal("declined")
        assert JobStatus.is_terminal("skipped")
        assert not JobStatus.is_terminal("pending")
        assert not JobStatus.is_terminal("running")
        # blocked ждёт approval — не terminal
        assert not JobStatus.is_terminal("blocked")
        assert JobStatus.is_known("error")
        assert not JobStatus.is_known("banana")


class TestPipelineYaml:
    def test_empty_batch(self):
        adapter = WoodpeckerAdapter("http://woodpecker:8000", "token")
        batch = {"bricks": []}
        yaml_str = adapter.generate_pipeline_yaml(batch)
        assert "steps:" in yaml_str

    def test_single_brick(self):
        adapter = WoodpeckerAdapter("http://woodpecker:8000", "token")
        batch = {
            "bricks": [
                {
                    "name": "SAST Scan",
                    "definition": {
                        "image": "sonarsource/sonar-scanner-cli:latest",
                        "commands": ["sonar-scanner -Dsonar.host.url=http://sonar:9000"],
                    },
                },
            ],
        }
        yaml_str = adapter.generate_pipeline_yaml(batch)
        assert "SAST Scan" in yaml_str
        assert "sonarsource/sonar-scanner-cli:latest" in yaml_str
        assert "commands:" in yaml_str

    def test_multiple_bricks_with_deps(self):
        adapter = WoodpeckerAdapter("http://woodpecker:8000", "token")
        batch = {
            "bricks": [
                {"name": "Build", "definition": {"image": "node:20", "commands": ["npm run build"]}},
                {
                    "name": "Test",
                    "definition": {"image": "node:20", "commands": ["npm test"]},
                    "depends_on": ["Build"],
                },
            ],
        }
        yaml_str = adapter.generate_pipeline_yaml(batch)
        assert "Build" in yaml_str
        assert "Test" in yaml_str

    def test_with_environment(self):
        adapter = WoodpeckerAdapter("http://woodpecker:8000", "token")
        batch = {
            "bricks": [
                {
                    "name": "Deploy",
                    "definition": {
                        "image": "alpine:latest",
                        "commands": ["echo $ENV"],
                        "inputs": {"ENV": "production", "REGION": "eu-west-1"},
                    },
                },
            ],
        }
        yaml_str = adapter.generate_pipeline_yaml(batch)
        assert "environment:" in yaml_str
        assert "ENV" in yaml_str
        assert "production" in yaml_str

    def test_yaml_is_valid(self):
        adapter = WoodpeckerAdapter("http://woodpecker:8000", "token")
        batch = {
            "bricks": [
                {"name": "Step", "definition": {"image": "alpine:latest", "commands": ["echo hi"]}},
            ],
        }
        parsed = yaml.safe_load(adapter.generate_pipeline_yaml(batch))
        assert parsed is not None
        assert "steps" in parsed

    def test_string_ref_marked_incomplete_not_crash(self):
        """COS-194: нерезолвнутая ID-строка не роняет аудит — неполнота помечена."""
        adapter = WoodpeckerAdapter("http://woodpecker:8000", "token")
        parsed = yaml.safe_load(
            adapter.generate_pipeline_yaml({"bricks": ["sast-sonarqube"]})
        )
        assert parsed["steps"] == {}
        incomplete = parsed["x-audit-incomplete"]
        assert incomplete[0]["ref"] == "sast-sonarqube"
        assert "not resolved" in incomplete[0]["reason"]

    def test_unresolved_refs_passthrough_with_reason(self):
        """COS-194: причина неполноты от резолвера доходит до аудита как есть."""
        adapter = WoodpeckerAdapter("http://woodpecker:8000", "token")
        batch = {
            "bricks": [
                {"name": "Sonar SAST",
                 "definition": {"image": "sonarsource/sonar-scanner-cli:latest"}},
            ],
            "unresolved_refs": [
                {"ref": "ghost-brick", "reason": "brick not found in catalog"},
            ],
        }
        parsed = yaml.safe_load(adapter.generate_pipeline_yaml(batch))
        assert "Sonar SAST" in parsed["steps"]
        assert parsed["x-audit-incomplete"] == [
            {"ref": "ghost-brick", "reason": "brick not found in catalog"},
        ]

    def test_resolved_bricks_no_incomplete_section(self):
        """COS-194 happy: все ссылки разрешены — шаги на месте, маркера нет."""
        adapter = WoodpeckerAdapter("http://woodpecker:8000", "token")
        batch = {"bricks": [{
            "name": "Sonar SAST",
            "definition": {"image": "sonarsource/sonar-scanner-cli:latest"},
        }]}
        parsed = yaml.safe_load(adapter.generate_pipeline_yaml(batch))
        assert list(parsed["steps"]) == ["Sonar SAST"]
        assert "x-audit-incomplete" not in parsed


class TestEnvVarFallback:
    def test_default_url(self, monkeypatch):
        """Без PK_WOODPECKER_URL/COSMO_WOODPECKER_URL — http://woodpecker:8000."""
        monkeypatch.delenv("PK_WOODPECKER_URL", raising=False)
        monkeypatch.delenv("COSMO_WOODPECKER_URL", raising=False)
        adapter = WoodpeckerAdapter(token="t")
        assert "woodpecker" in adapter._base

    def test_env_var_override(self, monkeypatch):
        """COSMO_WOODPECKER_URL переопределяет URL."""
        monkeypatch.delenv("PK_WOODPECKER_URL", raising=False)
        monkeypatch.setenv("COSMO_WOODPECKER_URL", "https://ci.cosmo.local")
        adapter = WoodpeckerAdapter(token="t")
        assert adapter._base == "https://ci.cosmo.local"

    def test_pk_env_precedence(self, monkeypatch):
        """PK_WOODPECKER_URL (compose-канон COS-094) сильнее COSMO_*."""
        monkeypatch.setenv("PK_WOODPECKER_URL", "http://cosmo-woodpecker:8000")
        monkeypatch.setenv("COSMO_WOODPECKER_URL", "https://ci.cosmo.local")
        adapter = WoodpeckerAdapter(token="t")
        assert adapter._base == "http://cosmo-woodpecker:8000"

    def test_explicit_arg_wins(self, monkeypatch):
        """Явный base_url имеет приоритет над env."""
        monkeypatch.setenv("COSMO_WOODPECKER_URL", "https://ci.cosmo.local")
        adapter = WoodpeckerAdapter("http://custom:9000", "t")
        assert adapter._base == "http://custom:9000"


class TestV35Contract:
    """COS-097: контракт v3.5 — repo_id, cancel, step-логи, submit body."""

    def test_submit_uses_lookup_and_json_body(self):
        adapter, session = _make_adapter({
            ("GET", "/api/repos/lookup/cosmo/default"): _lookup_response(42),
            ("POST", "/api/repos/42/pipelines"): FakeResponse(200, {"id": 9001, "number": 7, "status": "pending"}),
        })
        handle = adapter.submit_run("cosmo", "default", branch="main")

        methods = [(m, url) for m, url, _ in session.calls]
        # 1) lookup owner/name → repo_id (v3.5 middleware парсит только int)
        assert ("GET", "http://wp:8000/api/repos/lookup/cosmo/default") in methods
        # 2) submit по числовому repo_id с JSON-телом
        assert ("POST", "http://wp:8000/api/repos/42/pipelines") in methods
        assert not any(m == "DELETE" for m, _ in methods)
        assert handle == {
            "job_id": 9001, "number": 7, "repo_id": 42,
            "repo_owner": "cosmo", "repo_name": "default", "branch": "main",
        }
        # branch в JSON-теле (PipelineOptions), не query
        post_calls = [kw for m, _, kw in session.calls if m == "POST"]
        assert post_calls[0].get("json") == {"branch": "main"}

    def test_lookup_cached(self):
        adapter, session = _make_adapter({
            ("GET", "/api/repos/lookup/cosmo/default"): _lookup_response(42),
        })
        rid1 = adapter.resolve_repo_id("cosmo", "default")
        rid2 = adapter.resolve_repo_id("cosmo", "default")
        assert rid1 == rid2 == 42
        assert len(session.calls) == 1  # второй из кэша

    def test_lookup_404_is_explicit(self):
        adapter, _ = _make_adapter({
            ("GET", "/api/repos/lookup/ghost/none"): FakeResponse(404),
        })
        with pytest.raises(LookupError, match="not found"):
            adapter.resolve_repo_id("ghost", "none")

    def test_cancel_is_post_not_delete(self):
        """v3.5: DELETE pipelines/{number} удаляет запись пайплайна.
        Cancel — только POST .../cancel."""
        adapter, session = _make_adapter({})
        ok = adapter.cancel_run({
            "repo_id": 42, "number": 7,
            "repo_owner": "cosmo", "repo_name": "default",
        })
        assert ok is False  # 404 от fake — но метод фиксирован:
        assert session.calls == [("POST", "http://wp:8000/api/repos/42/pipelines/7/cancel", {})]
        assert not any(m == "DELETE" for m, _, _ in session.calls)

    def test_get_status_returns_raw(self):
        """RAW-статус проходит без маппинга — решает executor (honesty)."""
        adapter, _ = _make_adapter({
            ("GET", "/api/repos/42/pipelines/7"): _pipeline_response(status="declined"),
        })
        handle = {"repo_id": 42, "number": 7}
        assert adapter.get_status(handle) == "declined"

    def test_logs_by_step_id(self):
        """Логи: GET logs/{number}/{stepId}; stepId — DB id из дерева."""
        adapter, session = _make_adapter({
            ("GET", "/api/repos/42/pipelines/7"): _pipeline_response(status="success"),
            ("GET", "/api/repos/42/logs/7/601"): FakeResponse(200, [
                {"line": "cloning repo", "time": 1},
                {"line": "done", "time": 2},
            ]),
            ("GET", "/api/repos/42/logs/7/602"): FakeResponse(200, [
                {"line": "scanning", "time": 3},
            ]),
        })
        handle = {"repo_id": 42, "number": 7}
        # индекс 1 → второй шаг дерева (scan, id=602)
        logs = adapter.get_logs(handle, step=1)
        assert logs == ["scanning"]

        all_logs = adapter.collect_all_logs(handle)
        assert sorted(all_logs) == ["clone", "scan"]
        assert all_logs["clone"] == ["cloning repo", "done"]
        log_urls = [url for m, url, _ in session.calls if "/logs/7/" in url]
        assert any(url.endswith("/logs/7/601") for url in log_urls)
        assert any(url.endswith("/logs/7/602") for url in log_urls)

    def test_logs_resolve_children_contract(self):
        """COS-188: живой v3.5 отдаёт шаги в workflows[].children (не steps).

        Контракт-дрифт: без fallback деривация шагов/логов молча давала 0.
        """
        adapter, _ = _make_adapter({
            ("GET", "/api/repos/42/pipelines/7"): FakeResponse(200, {
                "id": 9001, "number": 7, "status": "success",
                "workflows": [
                    {"id": 500, "pid": 1, "name": "wf-main", "state": "success",
                     "children": [
                         {"id": 701, "pid": 2, "name": "clone", "state": "success"},
                         {"id": 702, "pid": 3, "name": "prepare", "state": "success"},
                     ]},
                ],
            }),
            ("GET", "/api/repos/42/logs/7/702"): FakeResponse(200, [
                {"line": "cosmo-fixture prepare", "time": 1},
            ]),
        })
        handle = {"repo_id": 42, "number": 7}
        flat = adapter._flatten_steps(adapter.get_pipeline(handle))
        assert [s["name"] for s in flat] == ["clone", "prepare"]
        assert adapter.get_logs(handle, step=1) == ["cosmo-fixture prepare"]

    def test_logs_decode_base64_data_contract(self):
        """COS-188: живой v3.5 отдаёт строки логов в data (base64); line — номер."""
        import base64 as _b64
        adapter, _ = _make_adapter({
            ("GET", "/api/repos/42/pipelines/7"): _pipeline_response(status="success"),
            ("GET", "/api/repos/42/logs/7/601"): FakeResponse(200, [
                {"id": 1, "step_id": 601, "line": 0,
                 "data": _b64.b64encode(b'+ echo "fixture line"').decode(), "type": 0},
                {"id": 2, "step_id": 601, "line": 1,
                 "data": _b64.b64encode(b"fixture line").decode(), "type": 0},
            ]),
        })
        logs = adapter.get_logs({"repo_id": 42, "number": 7}, step=0)
        assert logs == ['+ echo "fixture line"', "fixture line"]

    def test_logs_404_is_empty_not_error(self):
        """Логи шага ещё не записаны/удалены retention — честно пусто."""
        adapter, _ = _make_adapter({
            ("GET", "/api/repos/42/pipelines/7"): _pipeline_response(status="success"),
            ("GET", "/api/repos/42/logs/7/601"): FakeResponse(404),
            ("GET", "/api/repos/42/logs/7/602"): FakeResponse(404),
        })
        logs = adapter.collect_all_logs({"repo_id": 42, "number": 7})
        assert logs == {"clone": [], "scan": []}

    def test_collect_all_logs_settles_async_log_flush(self):
        """SAST-STEP-1: добор пустых терминальных логов (live-гонка флеша).

        Живой кейс: log_entries отчёт-шага записались в ту же секунду, что
        и terminal-статус, но уже ПОСЛЕ чтения → маркер терялся (ложный
        alert). settle_empty_s включает bounded refetch.
        """
        import base64 as _b64
        calls = {"scan": 0}

        def scan_logs():
            calls["scan"] += 1
            if calls["scan"] == 1:
                return FakeResponse(404)  # строки ещё не записаны
            return FakeResponse(200, [
                {"data": _b64.b64encode(
                    b"[prettyk-sast-report] sha256=deadbeef").decode()},
            ])

        adapter, _ = _make_adapter({
            ("GET", "/api/repos/42/pipelines/7"): _pipeline_response(status="success"),
            ("GET", "/api/repos/42/logs/7/601"): FakeResponse(200, [{"line": "cloned"}]),
            ("GET", "/api/repos/42/logs/7/602"): scan_logs,
        })
        logs = adapter.collect_all_logs({"repo_id": 42, "number": 7},
                                        settle_empty_s=0.01)
        assert logs["clone"] == ["cloned"]
        assert logs["scan"] == ["[prettyk-sast-report] sha256=deadbeef"]
        assert calls["scan"] == 2  # первый fetch пуст → добор

    def test_collect_all_logs_settle_skips_running_step(self):
        """Running-шаг: пустые логи — норма, добора нет (settle не блокирует)."""
        calls = {"scan": 0}

        def scan_logs():
            calls["scan"] += 1
            return FakeResponse(404)

        adapter, _ = _make_adapter({
            ("GET", "/api/repos/42/pipelines/7"): _pipeline_response(status="running"),
            ("GET", "/api/repos/42/logs/7/601"): FakeResponse(404),
            ("GET", "/api/repos/42/logs/7/602"): scan_logs,
        })
        logs = adapter.collect_all_logs({"repo_id": 42, "number": 7},
                                        settle_empty_s=0.05)
        assert logs == {"clone": [], "scan": []}
        assert calls["scan"] == 1

    def test_collect_all_logs_settle_off_by_default(self):
        """Default (settle_empty_s=0) — прежняя семантика: один fetch."""
        calls = {"scan": 0}

        def scan_logs():
            calls["scan"] += 1
            return FakeResponse(404)

        adapter, _ = _make_adapter({
            ("GET", "/api/repos/42/pipelines/7"): _pipeline_response(status="success"),
            ("GET", "/api/repos/42/logs/7/601"): FakeResponse(404),
            ("GET", "/api/repos/42/logs/7/602"): scan_logs,
        })
        logs = adapter.collect_all_logs({"repo_id": 42, "number": 7})
        assert logs == {"clone": [], "scan": []}
        assert calls["scan"] == 1

    def test_collect_all_logs_settles_partial_growth(self):
        """COS-196: хвост логов терминального шага доливается асинхронно.

        Live-кейс: логи шага пришли НЕПУСТЫМИ, но без последних строк
        (digest-маркер печатается в самом конце) — старый добор ждал только
        пустые логи и терял маркер. Growing-settle доводит до стабильного
        размера, оставаясь bounded.
        """
        marker = "build-demo:1.0.0@sha256:" + "ab" * 32
        calls = {"scan": 0}

        def scan_logs():
            calls["scan"] += 1
            if calls["scan"] == 1:
                return FakeResponse(200, [{"line": "building"}, {"line": "pushing"}])
            return FakeResponse(200, [
                {"line": "building"}, {"line": "pushing"}, {"line": marker},
            ])

        adapter, _ = _make_adapter({
            ("GET", "/api/repos/42/pipelines/7"): _pipeline_response(status="success"),
            ("GET", "/api/repos/42/logs/7/601"): FakeResponse(200, [{"line": "cloned"}]),
            ("GET", "/api/repos/42/logs/7/602"): scan_logs,
        })
        logs = adapter.collect_all_logs({"repo_id": 42, "number": 7},
                                        settle_empty_s=0.01)
        assert logs["clone"] == ["cloned"]
        assert logs["scan"][-1] == marker
        assert calls["scan"] >= 2  # хвост добран, не потерян

    def test_submit_permission_error_is_explicit(self):
        """403/401 на submit → явный PermissionError (честный honest error)."""
        adapter, _ = _make_adapter({
            ("GET", "/api/repos/lookup/cosmo/default"): _lookup_response(42),
            ("POST", "/api/repos/42/pipelines"): FakeResponse(403),
        })
        with pytest.raises(PermissionError, match="push-доступом"):
            adapter.submit_run("cosmo", "default")
