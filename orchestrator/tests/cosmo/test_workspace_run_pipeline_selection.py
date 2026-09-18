# -*- coding: utf-8 -*-
"""COS-127: Workspace Run — выбор pipeline-конфига.

Три слоя:
  1. DTO — pipelineName (alias), гигиена строки, backward-compat.
  2. Адаптер — config-swap repo.config_file (GET/PATCH/POST/restore),
     permission-маппинг, restore-on-error.
  3. Роут — валидация pipelineName против discovery COS-118, unknown → 400
     без молчаливого запуска default.

Запуск:  pytest .../test_workspace_run_pipeline_selection.py -q
"""
from __future__ import annotations

import logging
import sys
import time
from pathlib import Path
from typing import Optional

import pytest
import pytest_asyncio
import requests
from httpx import AsyncClient
from pydantic import ValidationError

_orch = Path(__file__).resolve().parents[1]
if str(_orch) not in sys.path:
    sys.path.insert(0, str(_orch))

pytestmark = pytest.mark.asyncio

from orchestrator.cosmo.adapters.execution_woodpecker import WoodpeckerAdapter
from orchestrator.cosmo.api.deps import get_current_principal
from orchestrator.cosmo.api.main import app
from orchestrator.cosmo.domain.rbac import CBRRole, PrincipalContext
from orchestrator.cosmo.domain.workspace import (
    WorkspaceRunRequest,
    validate_pipeline_name,
)

SHA = "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6a7b8c9d0"


# ══════════════════════════════════════════════════════════════════════
# 1. DTO
# ══════════════════════════════════════════════════════════════════════

class TestPipelineNameDto:
    def test_defaults_to_none(self):
        r = WorkspaceRunRequest(repo="org/app", branch="main", commit_sha=SHA)
        assert r.pipeline_name is None

    def test_accepts_alias(self):
        r = WorkspaceRunRequest(
            repo="org/app", branch="main", commit_sha=SHA, pipelineName="deploy",
        )
        assert r.pipeline_name == "deploy"

    def test_accepts_snake_name(self):
        r = WorkspaceRunRequest(
            repo="org/app", branch="main", commit_sha=SHA, pipeline_name=".woodpecker",
        )
        assert r.pipeline_name == ".woodpecker"

    def test_dump_uses_alias(self):
        r = WorkspaceRunRequest(
            repo="org/app", branch="main", commit_sha=SHA, pipeline_name="lint",
        )
        d = r.model_dump(by_alias=True)
        assert d["pipelineName"] == "lint"

    def test_rejects_empty(self):
        with pytest.raises(ValidationError):
            WorkspaceRunRequest(
                repo="org/app", branch="main", commit_sha=SHA, pipeline_name="",
            )

    def test_rejects_padded_whitespace(self):
        with pytest.raises(ValidationError):
            WorkspaceRunRequest(
                repo="org/app", branch="main", commit_sha=SHA, pipeline_name=" deploy",
            )

    def test_rejects_backslash(self):
        with pytest.raises(ValidationError):
            WorkspaceRunRequest(
                repo="org/app", branch="main", commit_sha=SHA,
                pipeline_name="a\\b",
            )

    def test_rejects_newline(self):
        with pytest.raises(ValidationError):
            WorkspaceRunRequest(
                repo="org/app", branch="main", commit_sha=SHA,
                pipeline_name="a\nb",
            )

    def test_rejects_too_long(self):
        with pytest.raises(ValidationError):
            WorkspaceRunRequest(
                repo="org/app", branch="main", commit_sha=SHA,
                pipeline_name="x" * 201,
            )

    def test_validator_passthrough(self):
        assert validate_pipeline_name("deploy") == "deploy"


# ══════════════════════════════════════════════════════════════════════
# 2. Adapter — config-swap
# ══════════════════════════════════════════════════════════════════════

class _Resp:
    def __init__(self, status_code: int = 200, payload: Optional[dict] = None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}

    def json(self) -> dict:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")


class _Session:
    """Записывает вызовы; поведение задаёт routes(method, url, kwargs)."""

    headers: dict = {}

    def __init__(self, routes):
        self.calls: list[tuple[str, str, dict]] = []
        self._routes = routes

    def _call(self, method: str, url: str, kwargs: dict) -> _Resp:
        self.calls.append((method, url, kwargs))
        return self._routes(method, url, kwargs)

    def get(self, url: str, **kw):
        return self._call("GET", url, kw)

    def post(self, url: str, **kw):
        return self._call("POST", url, kw)

    def patch(self, url: str, **kw):
        return self._call("PATCH", url, kw)


def _routes(original: str = ".woodpecker.yaml", submit_status: int = 200,
            patch_status: int = 200, restore_fail: bool = False,
            get_status: int = 200):
    state = {"config": original, "patches": [], "submits": 0}

    def handler(method: str, url: str, kw: dict) -> _Resp:
        if method == "GET" and url.endswith("/api/repos/7"):
            if get_status >= 400:
                return _Resp(get_status, {})
            return _Resp(200, {"config_file": state["config"]})
        if method == "PATCH" and url.endswith("/api/repos/7"):
            value = (kw.get("json") or {}).get("config_file")
            state["patches"].append(value)
            if restore_fail and len(state["patches"]) >= 2:
                return _Resp(500, {})
            if patch_status >= 400:
                return _Resp(patch_status, {})
            state["config"] = value
            return _Resp(200, {})
        if method == "POST" and url.endswith("/api/repos/7/pipelines"):
            state["submits"] += 1
            if submit_status >= 400:
                return _Resp(submit_status, {})
            return _Resp(200, {"id": 100, "number": 1})
        return _Resp(404, {})

    return handler, state


def _adapter(handler) -> WoodpeckerAdapter:
    a = WoodpeckerAdapter(base_url="http://wp", token="t")
    a._session = _Session(handler)
    # Seed lookup cache — не дёргаем /api/repos/lookup в юнитах.
    a._repo_id_cache[("org", "app")] = (7, time.time())
    return a


class TestWoodpeckerConfigSwap:
    def test_no_config_single_post(self):
        handler, state = _routes()
        a = _adapter(handler)
        out = a.submit_run("org", "app", "main")
        assert out["number"] == 1
        methods = [c[0] for c in a._session.calls]
        assert methods == ["POST"]
        assert state["patches"] == []

    def test_config_swaps_and_restores(self):
        handler, state = _routes(original=".woodpecker.yaml")
        a = _adapter(handler)
        a.submit_run("org", "app", "main", config_file=".woodpecker/deploy.yml")
        assert state["patches"] == [".woodpecker/deploy.yml", ".woodpecker.yaml"]
        methods = [c[0] for c in a._session.calls]
        assert methods == ["GET", "PATCH", "POST", "PATCH"]

    def test_config_equals_original_no_patch(self):
        handler, state = _routes(original=".woodpecker/deploy.yml")
        a = _adapter(handler)
        a.submit_run("org", "app", "main", config_file=".woodpecker/deploy.yml")
        assert state["patches"] == []
        assert [c[0] for c in a._session.calls] == ["GET", "POST"]

    def test_restore_on_submit_error(self):
        handler, state = _routes(submit_status=500)
        a = _adapter(handler)
        with pytest.raises(requests.HTTPError):
            a.submit_run("org", "app", "main", config_file=".woodpecker/deploy.yml")
        assert state["patches"] == [".woodpecker/deploy.yml", ".woodpecker.yaml"]

    def test_restore_on_submit_timeout(self):
        handler, state = _routes()

        def handler_timeout(method, url, kw):
            if method == "POST" and url.endswith("/api/repos/7/pipelines"):
                raise requests.Timeout("submit timed out")
            return handler(method, url, kw)

        a = _adapter(handler_timeout)
        with pytest.raises(requests.Timeout):
            a.submit_run("org", "app", "main", config_file=".woodpecker/deploy.yml")
        assert state["patches"] == [".woodpecker/deploy.yml", ".woodpecker.yaml"]

    def test_restore_failure_logged_not_masking(self, caplog):
        handler, state = _routes(restore_fail=True)
        a = _adapter(handler)
        with caplog.at_level(logging.ERROR):
            out = a.submit_run(
                "org", "app", "main", config_file=".woodpecker/deploy.yml",
            )
        assert out["number"] == 1
        assert state["patches"] == [".woodpecker/deploy.yml", ".woodpecker.yaml"]
        assert "Failed to restore config_file" in caplog.text

    def test_restore_failure_does_not_mask_submit_error(self, caplog):
        handler, state = _routes(submit_status=500, restore_fail=True)
        a = _adapter(handler)
        with caplog.at_level(logging.ERROR):
            with pytest.raises(requests.HTTPError):
                a.submit_run(
                    "org", "app", "main", config_file=".woodpecker/deploy.yml",
                )
        assert "Failed to restore config_file" in caplog.text

    def test_submit_permission_401(self):
        handler, _ = _routes(submit_status=401)
        a = _adapter(handler)
        with pytest.raises(PermissionError):
            a.submit_run("org", "app", "main")

    def test_patch_permission_403(self):
        handler, state = _routes(patch_status=403)
        a = _adapter(handler)
        with pytest.raises(PermissionError):
            a.submit_run("org", "app", "main", config_file=".woodpecker/deploy.yml")
        assert state["submits"] == 0

    def test_patch_body_is_config_file(self):
        handler, _ = _routes()
        a = _adapter(handler)
        a.submit_run("org", "app", "main", config_file=".woodpecker/lint.yml")
        patch = next(c for c in a._session.calls if c[0] == "PATCH")
        assert patch[2]["json"] == {"config_file": ".woodpecker/lint.yml"}

    def test_submit_body_has_branch(self):
        handler, _ = _routes()
        a = _adapter(handler)
        a.submit_run("org", "app", "feature")
        post = next(c for c in a._session.calls if c[0] == "POST")
        assert post[2]["json"] == {"branch": "feature"}

    def test_get_repo_config_value(self):
        handler, _ = _routes(original=".woodpecker.yaml")
        a = _adapter(handler)
        assert a.get_repo_config("org", "app") == ".woodpecker.yaml"

    def test_get_repo_config_empty_when_missing(self):
        handler, _ = _routes(original="")
        a = _adapter(handler)
        assert a.get_repo_config("org", "app") == ""

    def test_get_repo_config_404_lookup_error(self):
        handler, _ = _routes(get_status=404)
        a = _adapter(handler)
        with pytest.raises(LookupError):
            a.get_repo_config("org", "app")


# ══════════════════════════════════════════════════════════════════════
# 3. Route — валидация против discovery
# ══════════════════════════════════════════════════════════════════════

class FakeForge:
    """In-memory forge: tree + read_file + commit для discovery."""

    def __init__(self, files: Optional[dict] = None):
        self._files = files if files is not None else _standard_files()
        self.tree_error: Optional[Exception] = None

    def get_tree(self, owner: str, repo: str, ref: str = "", recursive: bool = True):
        if self.tree_error:
            raise self.tree_error
        from orchestrator.cosmo.adapters.forge_gitea import GiteaTreeEntry
        return [
            GiteaTreeEntry(path=p, type="blob", sha=f"sha-{p}", size=len(c))
            for p, c in self._files.items()
        ]

    def get_commit(self, owner: str, repo: str, ref: str = ""):
        return type("Commit", (), {
            "sha": SHA, "message": "feat",
            "author": "max", "timestamp": "2026-09-18T00:00:00Z",
        })()

    def read_file(self, owner: str, repo: str, path: str, ref: str = ""):
        if path in self._files:
            return self._files[path], f"sha-{path}"
        raise LookupError(f"File {path} not found")


class FakeWoodpecker:
    def __init__(self):
        self._base = "http://woodpecker:8000"
        self.calls: list[tuple] = []

    def submit_run(self, repo_owner: str, repo_name: str,
                   branch: str = "main", config_file: Optional[str] = None):
        self.calls.append((repo_owner, repo_name, branch, config_file))
        return {
            "job_id": 100, "number": 1, "repo_id": 1,
            "repo_owner": repo_owner, "repo_name": repo_name, "branch": branch,
        }


def _standard_files() -> dict:
    return {
        ".woodpecker.yml": "pipeline:\n  build:\n    image: python:3\n",
        ".woodpecker/deploy.yml": "pipeline:\n  deploy:\n    image: alpine\n",
        ".woodpecker/lint.yml": "pipeline:\n  lint:\n    image: node\n",
        "README.md": "# x\n",
    }


class TestRunPipelineSelectionRoute:
    @pytest.fixture(autouse=True)
    def _mocks(self, monkeypatch):
        self._forge = FakeForge()
        import orchestrator.cosmo.api.routes.workspace as _ws
        monkeypatch.setattr(_ws, "build_adapter", lambda: self._forge)

        self._wp = FakeWoodpecker()
        monkeypatch.setattr(_ws, "build_woodpecker", lambda: self._wp)

        async def _principal() -> PrincipalContext:
            return PrincipalContext(
                user_id="ws-127-tester",
                roles=[CBRRole.SERVICE_ADMIN],
                domain_id="ws-127-dom", zone="zr",
                is_authenticated=True, is_system_admin=False,
            )
        app.dependency_overrides[get_current_principal] = _principal
        monkeypatch.setitem(
            app.dependency_overrides, get_current_principal, _principal,
        )

    @pytest_asyncio.fixture(autouse=True)
    async def _seed_db(self, pg_client: AsyncClient):
        from sqlalchemy import text
        from sqlalchemy.ext.asyncio import create_async_engine
        import os

        pg_url = os.getenv(
            "COSMO_DATABASE_URL",
            "postgresql+asyncpg://cosmo:cosmo@127.0.0.1:5433/cosmo_test",
        )
        engine = create_async_engine(pg_url, echo=False)
        async with engine.begin() as conn:
            await conn.execute(text(
                "INSERT INTO domains (id, label, forge_type, forge_url, "
                "forge_token_ref, rbac_config, quota_max_runs, "
                "quota_max_storage_gb, quota_max_cpu, created_at) "
                "VALUES ('ws-127-dom', 'ws-127-test', 'gitea', "
                "'http://gitea:3000', 't', '{}'::jsonb, 50, 100, 8, now()) "
                "ON CONFLICT (id) DO NOTHING"
            ))
            await conn.execute(text(
                "INSERT INTO apps (id, domain_id, level) "
                "VALUES ('ws-127-app', 'ws-127-dom', 0) "
                "ON CONFLICT (id) DO NOTHING"
            ))
            await conn.execute(text(
                "INSERT INTO repo_bindings (id, app_id, forge_id, repo_path, "
                "default_branch) "
                "VALUES ('ws-127-bind', 'ws-127-app', 'gitea-1', "
                "'ws-owner/ws-repo', 'main') "
                "ON CONFLICT (id) DO NOTHING"
            ))
        await engine.dispose()

    def _payload(self, **extra):
        base = {"repo": "ws-owner/ws-repo", "branch": "main", "commitSha": SHA}
        base.update(extra)
        return base

    async def test_no_pipeline_backward_compatible(self, pg_client: AsyncClient):
        res = await pg_client.post(
            "/api/v1/repos/workspace/run", json=self._payload(),
        )
        assert res.status_code == 201, res.text
        assert self._wp.calls == [("ws-owner", "ws-repo", "main", None)]

    async def test_valid_pipeline_passes_path(self, pg_client: AsyncClient):
        res = await pg_client.post(
            "/api/v1/repos/workspace/run",
            json=self._payload(pipelineName="deploy"),
        )
        assert res.status_code == 201, res.text
        assert self._wp.calls == [
            ("ws-owner", "ws-repo", "main", ".woodpecker/deploy.yml"),
        ]

    async def test_root_pipeline_passes_path(self, pg_client: AsyncClient):
        res = await pg_client.post(
            "/api/v1/repos/workspace/run",
            json=self._payload(pipelineName=".woodpecker"),
        )
        assert res.status_code == 201, res.text
        assert self._wp.calls[0][3] == ".woodpecker.yml"

    async def test_unknown_pipeline_400(self, pg_client: AsyncClient):
        res = await pg_client.post(
            "/api/v1/repos/workspace/run",
            json=self._payload(pipelineName="nope"),
        )
        assert res.status_code == 400, res.text
        detail = res.json()["detail"]
        assert "unknown pipeline" in detail
        assert "deploy" in detail and "lint" in detail

    async def test_unknown_pipeline_does_not_submit(self, pg_client: AsyncClient):
        await pg_client.post(
            "/api/v1/repos/workspace/run",
            json=self._payload(pipelineName="nope"),
        )
        assert self._wp.calls == []

    async def test_empty_repo_pipeline_400(self, pg_client: AsyncClient):
        self._forge._files = {"README.md": "# x\n"}
        res = await pg_client.post(
            "/api/v1/repos/workspace/run",
            json=self._payload(pipelineName="deploy"),
        )
        assert res.status_code == 400, res.text
        assert "(none)" in res.json()["detail"]

    async def test_invalid_pipeline_name_422(self, pg_client: AsyncClient):
        res = await pg_client.post(
            "/api/v1/repos/workspace/run",
            json=self._payload(pipelineName="bad\\name"),
        )
        assert res.status_code == 422, res.text
        assert self._wp.calls == []

    async def test_discovery_failure_5xx(self, pg_client: AsyncClient):
        self._forge.tree_error = RuntimeError("forge down")
        res = await pg_client.post(
            "/api/v1/repos/workspace/run",
            json=self._payload(pipelineName="deploy"),
        )
        assert res.status_code >= 500, res.text
        assert self._wp.calls == []
