# -*- coding: utf-8 -*-
"""COS-108: Workspace run — DTO unit + route mock + live opt-in.

Запуск:  pytest .../test_workspace_run.py -q
Live:    $env:COSMO_LIVE_RUN = "1"; pytest .../test_workspace_run.py -v
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Optional

import pytest
import pytest_asyncio
from httpx import AsyncClient
from pydantic import ValidationError

_orch = Path(__file__).resolve().parents[1]
if str(_orch) not in sys.path:
    sys.path.insert(0, str(_orch))

pytestmark = pytest.mark.asyncio

from orchestrator.cosmo.api.deps import get_current_principal
from orchestrator.cosmo.api.main import app
from orchestrator.cosmo.domain.rbac import CBRRole, PrincipalContext, Role
from orchestrator.cosmo.domain.workspace import (
    WorkspaceRunRequest,
    WorkspaceRunResponse,
)

_LIVE_GATE = "COSMO_LIVE_RUN"
SHA = "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6a7b8c9d0"


# ── Fake Gitea adapter ──────────────────────────────────────────────────

class FakeAdapter:
    """In-memory Gitea: минимальный forge для run-роута (get_commit + CAS)."""

    def __init__(self, head_sha: str = SHA):
        self._head_sha = head_sha

    def get_repo_info(self, owner: str, name: str):
        import requests as _r
        return type("Info", (), {
            "default_branch": "main",
            "full_name": f"{owner}/{name}",
            "owner": owner, "name": name,
        })()

    def get_commit(self, owner: str, name: str, ref: str = ""):
        import requests as _r
        return type("Commit", (), {
            "sha": self._head_sha, "message": "feat",
            "author": "max", "timestamp": "2026-09-05T00:00:00Z",
        })()


class FakeWoodpecker:
    """In-memory Woodpecker: submit_run → handle, ошибки — через атрибуты."""

    def __init__(self, next_number: int = 1, next_pipeline_id: int = 100,
                 base_url: str = "http://woodpecker:8000"):
        self.next_number = next_number
        self.next_pipeline_id = next_pipeline_id
        self._base = base_url
        self._submit_count = 0
        self.submit_error: Optional[Exception] = None
        self.resolve_repo_error: Optional[Exception] = None
        self.last_config_file: Optional[str] = None

    def submit_run(self, repo_owner: str, repo_name: str,
                   branch: str = "main",
                   config_file: Optional[str] = None) -> dict:
        if self.submit_error:
            raise self.submit_error
        if self.resolve_repo_error:
            raise self.resolve_repo_error
        self.last_config_file = config_file
        number = self.next_number
        pid = self.next_pipeline_id
        self.next_number += 1
        self.next_pipeline_id += 1
        self._submit_count += 1
        return {
            "job_id": pid,
            "number": number,
            "repo_id": 1,
            "repo_owner": repo_owner,
            "repo_name": repo_name,
            "branch": branch,
        }

    def resolve_repo_id(self, repo_owner: str, repo_name: str) -> int:
        if self.resolve_repo_error:
            raise self.resolve_repo_error
        return 1


# ── DTO unit ─────────────────────────────────────────────────────────────

class TestRunDto:
    def test_request_minimal(self):
        r = WorkspaceRunRequest(
            repo="org/app", branch="main", commit_sha=SHA,
        )
        assert r.repo == "org/app"

    def test_request_camel_case(self):
        payload = {"repo": "org/app", "branch": "main", "commitSha": SHA}
        r = WorkspaceRunRequest.model_validate_json(json.dumps(payload))
        assert r.commit_sha == SHA

    def test_request_dump_camel_case(self):
        r = WorkspaceRunRequest(repo="org/app", branch="main", commit_sha=SHA)
        d = r.model_dump(by_alias=True)
        assert "commitSha" in d and d["commitSha"] == SHA

    def test_request_extra_forbidden(self):
        with pytest.raises(ValidationError):
            WorkspaceRunRequest(
                repo="org/app", branch="main", commit_sha=SHA, hack=1,
            )

    def test_short_sha_rejected(self):
        with pytest.raises(ValidationError):
            WorkspaceRunRequest(repo="org/app", branch="main", commit_sha="abc")

    def test_empty_branch_rejected(self):
        with pytest.raises(ValidationError):
            WorkspaceRunRequest(repo="org/app", branch="", commit_sha=SHA)

    def test_bad_repo_traversal_rejected(self):
        with pytest.raises(ValidationError):
            WorkspaceRunRequest(repo="org/../app", branch="main", commit_sha=SHA)

    def test_bad_sha_chars_rejected(self):
        with pytest.raises(ValidationError):
            WorkspaceRunRequest(repo="org/app", branch="main", commit_sha="g" * 40)

    def test_response_minimal(self):
        r = WorkspaceRunResponse(run_id="abc", pipeline_number=1, status="running")
        assert r.run_id == "abc"
        assert r.pipeline_id is None

    def test_response_full(self):
        r = WorkspaceRunResponse(
            run_id="xyz", pipeline_number=5, pipeline_id=42,
            status="running", tracking_url="http://wp/pipeline/5",
        )
        assert r.pipeline_id == 42
        assert r.tracking_url == "http://wp/pipeline/5"

    def test_response_extra_forbidden(self):
        with pytest.raises(ValidationError):
            WorkspaceRunResponse(
                run_id="abc", pipeline_number=1, status="running", hack=1,
            )


# ── Route tests (mock forge + mock woodpecker) ─────────────────────────

class TestRunRoute:
    """Route-тесты: mock forge + mock woodpecker, реальный pg через pg_client."""

    @pytest.fixture(autouse=True)
    def _mocks(self, monkeypatch):
        """Monkeypatch forge + woodpecker adapters; set workspace principal."""
        # Fake Gitea
        self._forge = FakeAdapter(head_sha=SHA)
        import orchestrator.cosmo.api.routes.workspace as _ws
        monkeypatch.setattr(_ws, "build_adapter", lambda: self._forge)

        # Fake Woodpecker
        self._wp = FakeWoodpecker()
        monkeypatch.setattr(_ws, "build_woodpecker", lambda: self._wp)

        # Principal: service admin for ws-run-dom (set directly, не через
        # monkeypatch — чтобы test_anonymous_401 мог pop и _mocks ресетнул)
        async def _principal() -> PrincipalContext:
            return PrincipalContext(
                user_id="ws-run-tester",
                roles=[CBRRole.SERVICE_ADMIN],
                domain_id="ws-run-dom", zone="zr",
                is_authenticated=True, is_system_admin=False,
            )
        app.dependency_overrides[get_current_principal] = _principal
        monkeypatch.setitem(
            app.dependency_overrides, get_current_principal, _principal,
        )

    @pytest_asyncio.fixture(autouse=True)
    async def _seed_db(self, pg_client: AsyncClient):
        """Seed domain + app + repo_binding через прямой PG."""
        from sqlalchemy.ext.asyncio import create_async_engine
        from sqlalchemy import text
        import os

        # Use same test DB as conftest
        pg_url = os.getenv("COSMO_DATABASE_URL",
                           "postgresql+asyncpg://cosmo:cosmo@127.0.0.1:5433/cosmo_test")
        engine = create_async_engine(pg_url, echo=False)
        async with engine.begin() as conn:
            await conn.execute(text(
                "INSERT INTO domains (id, label, forge_type, forge_url, "
                "forge_token_ref, rbac_config, quota_max_runs, "
                "quota_max_storage_gb, quota_max_cpu, created_at) "
                "VALUES ('ws-run-dom', 'ws-run-test', 'gitea', "
                "'http://gitea:3000', 't', '{}'::jsonb, 50, 100, 8, now()) "
                "ON CONFLICT (id) DO NOTHING"
            ))
            await conn.execute(text(
                "INSERT INTO apps (id, domain_id, level) "
                "VALUES ('ws-run-app', 'ws-run-dom', 0) "
                "ON CONFLICT (id) DO NOTHING"
            ))
            await conn.execute(text(
                "INSERT INTO repo_bindings (id, app_id, forge_id, repo_path, "
                "default_branch) "
                "VALUES ('ws-run-bind', 'ws-run-app', 'gitea-1', "
                "'ws-owner/ws-repo', 'main') "
                "ON CONFLICT (id) DO NOTHING"
            ))
        await engine.dispose()

    # ── Happy paths ──

    async def test_run_ok_201(self, pg_client: AsyncClient):
        payload = {"repo": "ws-owner/ws-repo", "branch": "main", "commitSha": SHA}
        res = await pg_client.post("/api/v1/repos/workspace/run", json=payload)
        assert res.status_code == 201, res.text
        body = res.json()
        assert "run_id" in body
        assert body["pipeline_number"] == 1
        assert body["pipeline_id"] == 100
        assert body["status"] == "running"

    async def test_run_creates_row_in_db(self, pg_client: AsyncClient):
        payload = {"repo": "ws-owner/ws-repo", "branch": "main", "commitSha": SHA}
        res = await pg_client.post("/api/v1/repos/workspace/run", json=payload)
        assert res.status_code == 201
        body = res.json()

        from sqlalchemy.ext.asyncio import create_async_engine
        from sqlalchemy import text
        import os
        pg_url = os.getenv("COSMO_DATABASE_URL",
                           "postgresql+asyncpg://cosmo:cosmo@127.0.0.1:5433/cosmo_test")
        engine = create_async_engine(pg_url, echo=False)
        async with engine.connect() as conn:
            rows = await conn.execute(
                text("SELECT count(*) FROM cosmo_workspace_runs WHERE run_id = :rid"),
                {"rid": body["run_id"]},
            )
            assert rows.scalar_one() == 1
        await engine.dispose()

    async def test_run_consecutive_numbers(self, pg_client: AsyncClient):
        payload = {"repo": "ws-owner/ws-repo", "branch": "main", "commitSha": SHA}
        r1 = await pg_client.post("/api/v1/repos/workspace/run", json=payload)
        r2 = await pg_client.post("/api/v1/repos/workspace/run", json=payload)
        assert r1.status_code == 201 and r2.status_code == 201
        assert r1.json()["run_id"] != r2.json()["run_id"]
        assert r1.json()["pipeline_number"] == 1
        assert r2.json()["pipeline_number"] == 2

    # ── Validation ──

    async def test_bad_repo_422(self, pg_client: AsyncClient):
        res = await pg_client.post("/api/v1/repos/workspace/run", json={
            "repo": "../bad", "branch": "main", "commitSha": SHA,
        })
        assert res.status_code == 422

    async def test_short_sha_422(self, pg_client: AsyncClient):
        res = await pg_client.post("/api/v1/repos/workspace/run", json={
            "repo": "ws-owner/ws-repo", "branch": "main", "commitSha": "abc",
        })
        assert res.status_code == 422

    async def test_empty_branch_422(self, pg_client: AsyncClient):
        res = await pg_client.post("/api/v1/repos/workspace/run", json={
            "repo": "ws-owner/ws-repo", "branch": "", "commitSha": SHA,
        })
        assert res.status_code == 422

    async def test_extra_field_422(self, pg_client: AsyncClient):
        res = await pg_client.post("/api/v1/repos/workspace/run", json={
            "repo": "ws-owner/ws-repo", "branch": "main",
            "commitSha": SHA, "hack": 1,
        })
        assert res.status_code == 422

    # ── Ghost / auth ──

    async def test_unknown_repo_404(self, pg_client: AsyncClient):
        res = await pg_client.post("/api/v1/repos/workspace/run", json={
            "repo": "ghost/unknown", "branch": "main", "commitSha": SHA,
        })
        assert res.status_code == 404

    async def test_anonymous_401(self, pg_client: AsyncClient):
        # Pop admin override → real get_current_principal → 401 without Auth header
        app.dependency_overrides.pop(get_current_principal, None)
        try:
            res = await pg_client.post("/api/v1/repos/workspace/run", json={
                "repo": "ws-owner/ws-repo", "branch": "main", "commitSha": SHA,
            })
            assert res.status_code == 401
        finally:
            # _mocks will re-set on next test — no explicit restore needed
            pass

    # ── CAS ──

    async def test_cas_head_mismatch_409(self, pg_client: AsyncClient):
        res = await pg_client.post("/api/v1/repos/workspace/run", json={
            "repo": "ws-owner/ws-repo", "branch": "main", "commitSha": "b" * 40,
        })
        assert res.status_code == 409

    # ── Woodpecker errors ──

    async def test_woodpecker_submit_error_502(self, pg_client: AsyncClient):
        import requests as _r
        self._wp.submit_error = _r.ConnectionError("down")
        res = await pg_client.post("/api/v1/repos/workspace/run", json={
            "repo": "ws-owner/ws-repo", "branch": "main", "commitSha": SHA,
        })
        assert res.status_code == 502

    async def test_woodpecker_permission_denied_502(self, pg_client: AsyncClient):
        self._wp.submit_error = PermissionError("invalid token")
        res = await pg_client.post("/api/v1/repos/workspace/run", json={
            "repo": "ws-owner/ws-repo", "branch": "main", "commitSha": SHA,
        })
        assert res.status_code == 502

    async def test_woodpecker_lookup_error_404(self, pg_client: AsyncClient):
        self._wp.resolve_repo_error = LookupError("repo not in WP")
        res = await pg_client.post("/api/v1/repos/workspace/run", json={
            "repo": "ws-owner/ws-repo", "branch": "main", "commitSha": SHA,
        })
        assert res.status_code == 404


# ── Live opt-in (skipped) ──

@pytest.mark.skipif(
    os.getenv(_LIVE_GATE, "") not in ("1", "true", "yes"),
    reason=f"set {_LIVE_GATE}=1 for live Woodpecker run test",
)
class TestLiveRun:
    async def test_live_submit_tracking(self, pg_client: AsyncClient):
        """Живой submit в Woodpecker — smoke."""
        payload = {
            "repo": os.getenv("COSMO_LIVE_REPO", "test-owner/test-repo"),
            "branch": os.getenv("COSMO_LIVE_BRANCH", "main"),
            "commitSha": os.getenv("COSMO_LIVE_SHA", SHA),
        }
        res = await pg_client.post(
            "/api/v1/repos/workspace/run", json=payload,
        )
        assert res.status_code in (201, 404, 502), (
            f"Unexpected status {res.status_code}: {res.text}"
        )
        if res.status_code == 201:
            body = res.json()
            assert "run_id" in body
            assert body["pipeline_number"] > 0
            print(f"Live run: {body}")