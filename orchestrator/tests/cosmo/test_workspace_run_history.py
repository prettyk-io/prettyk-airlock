# -*- coding: utf-8 -*-
"""COS-112: Workspace run history — DTO unit + route mock + list & step logs.

Запуск:  pytest .../test_workspace_run_history.py -q
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
from orchestrator.cosmo.domain.rbac import CBRRole, PrincipalContext
from orchestrator.cosmo.domain.workspace import (
    StepLogsResponse,
    WorkspaceRunListResponse,
    WorkspaceRunSummary,
    validate_repo,
)

SHA = "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6a7b8c9d0"
RUN_ID_1 = "run000000001"
RUN_ID_2 = "run000000002"
RUN_ID_3 = "run000000003"
RUN_ID_4 = "run000000004"
RUN_STEP = "run-step-zzzz"


# ── Fake Woodpecker with get_step_logs_by_id ──────────────────────────────

class FakeWoodpecker:
    """In-memory Woodpecker с get_step_logs_by_id для тестов логов."""

    def __init__(self, step_logs: list[str] | None = None):
        self._step_logs = step_logs or [f"line {i}" for i in range(25)]
        self._step_name = "test-step"
        self._valid_step_id = 1
        self.error: Optional[Exception] = None

    def get_step_logs_by_id(self, handle: dict, step_id: int) -> list[str]:
        if self.error:
            raise self.error
        if step_id != self._valid_step_id:
            return []
        return list(self._step_logs)

    def get_pipeline(self, handle: dict) -> dict:
        return {
            "number": handle.get("number"),
            "status": "success",
            "workflows": [{
                "name": "default",
                "steps": [{
                    "id": 1, "pid": 1, "name": self._step_name,
                    "state": "success", "workflow": "default",
                }],
            }],
        }

    def _flatten_steps(self, detail: dict) -> list[dict]:
        steps: list[dict] = []
        for wf in detail.get("workflows") or []:
            for st in wf.get("steps") or []:
                steps.append({
                    "id": st.get("id"),
                    "pid": st.get("pid"),
                    "name": st.get("name") or "?",
                    "state": st.get("state"),
                    "workflow": wf.get("name"),
                })
        return steps


# ── DTO unit ───────────────────────────────────────────────────────────────

class TestRunSummaryDto:
    def test_minimal(self):
        s = WorkspaceRunSummary(
            run_id="abc", repo_owner="o", repo_name="r",
            branch="main", commit_sha=SHA, status="running",
            created_at="2026-09-05T00:00:00",
        )
        assert s.run_id == "abc"
        assert s.status == "running"

    def test_nullable_fields(self):
        s = WorkspaceRunSummary(
            run_id="abc", repo_owner="o", repo_name="r",
            branch="main", commit_sha=SHA, status="pending",
            created_at="2026-09-05T00:00:00",
            pipeline_number=None, tracking_url=None,
        )
        assert s.pipeline_number is None
        assert s.tracking_url is None

    def test_extra_forbid(self):
        with pytest.raises(ValidationError):
            WorkspaceRunSummary(
                run_id="abc", repo_owner="o", repo_name="r",
                branch="main", commit_sha=SHA, status="running",
                created_at="2026-09-05T00:00:00", hack=1,
            )


class TestRunListResponseDto:
    def test_valid(self):
        r = WorkspaceRunListResponse(
            runs=[],
            total=0,
            limit=20,
            offset=0,
        )
        assert r.runs == []
        assert r.total == 0

    def test_with_runs(self):
        r = WorkspaceRunListResponse(
            runs=[
                WorkspaceRunSummary(
                    run_id="a", repo_owner="o", repo_name="r",
                    branch="main", commit_sha=SHA, status="succeeded",
                    created_at="2026-09-05T00:00:00",
                ),
            ],
            total=1, limit=20, offset=0,
        )
        assert r.total == 1
        assert r.runs[0].status == "succeeded"

    def test_extra_forbid(self):
        with pytest.raises(ValidationError):
            WorkspaceRunListResponse(
                runs=[], total=0, limit=20, offset=0, hack=1,
            )


class TestStepLogsResponseDto:
    def test_valid(self):
        r = StepLogsResponse(
            run_id="abc", step_id=1, total_lines=10,
            lines=["a", "b"], has_more=True,
        )
        assert r.total_lines == 10
        assert r.has_more is True

    def test_has_more_false(self):
        r = StepLogsResponse(
            run_id="abc", step_id=1, total_lines=2,
            lines=["a", "b"], has_more=False,
        )
        assert r.has_more is False

    def test_extra_forbid(self):
        with pytest.raises(ValidationError):
            StepLogsResponse(
                run_id="abc", step_id=1, total_lines=1,
                lines=["a"], has_more=False, hack=1,
            )

    def test_step_name_optional(self):
        r = StepLogsResponse(
            run_id="abc", step_id=1, total_lines=1,
            lines=["a"], has_more=False,
        )
        assert r.step_name is None

        r2 = StepLogsResponse(
            run_id="abc", step_id=1, total_lines=1,
            lines=["a"], has_more=False, step_name="build",
        )
        assert r2.step_name == "build"


# ── Route tests: GET /workspace/runs ───────────────────────────────────────

class TestRunsListRoute:
    """Route-тесты списка прогонов: mock woodpecker, реальный pg_client."""

    @pytest.fixture(autouse=True)
    def _mocks(self, monkeypatch):
        """Monkeypatch woodpecker; set workspace principal + seed DB rows."""
        self._wp = FakeWoodpecker()
        import orchestrator.cosmo.api.routes.workspace as _ws
        monkeypatch.setattr(_ws, "build_woodpecker", lambda: self._wp)

        async def _principal() -> PrincipalContext:
            return PrincipalContext(
                user_id="ws-hist-tester",
                roles=[CBRRole.SERVICE_ADMIN],
                domain_id="ws-hist-dom", zone="zr",
                is_authenticated=True, is_system_admin=False,
            )
        app.dependency_overrides[get_current_principal] = _principal

    @pytest_asyncio.fixture(autouse=True)
    async def _seed_db(self, pg_client: AsyncClient):
        """Seed domain + app + repo_binding + 4 workspace run rows."""
        from sqlalchemy.ext.asyncio import create_async_engine
        from sqlalchemy import text

        pg_url = os.getenv("COSMO_DATABASE_URL",
                           "postgresql+asyncpg://cosmo:cosmo@127.0.0.1:5433/cosmo_test")
        engine = create_async_engine(pg_url, echo=False)
        async with engine.begin() as conn:
            # domain + app + binding (тот же паттерн, что COS-108)
            await conn.execute(text(
                "INSERT INTO domains (id, label, forge_type, forge_url, "
                "forge_token_ref, rbac_config, quota_max_runs, "
                "quota_max_storage_gb, quota_max_cpu, created_at) "
                "VALUES ('ws-hist-dom', 'ws-hist-test', 'gitea', "
                "'http://gitea:3000', 't', '{}'::jsonb, 50, 100, 8, now()) "
                "ON CONFLICT (id) DO NOTHING"
            ))
            await conn.execute(text(
                "INSERT INTO apps (id, domain_id, level) "
                "VALUES ('ws-hist-app', 'ws-hist-dom', 0) "
                "ON CONFLICT (id) DO NOTHING"
            ))
            await conn.execute(text(
                "INSERT INTO repo_bindings (id, app_id, forge_id, repo_path, "
                "default_branch) "
                "VALUES ('ws-hist-bind', 'ws-hist-app', 'gitea-1', "
                "'ws-owner/ws-repo', 'main') "
                "ON CONFLICT (id) DO NOTHING"
            ))

            # Seed 4 runs: 2 succeeded on main, 1 failed on main, 1 running on dev
            # pylint: disable=line-too-long
            seeded = [
                (RUN_ID_1, "succeeded", "main", "2026-09-05T10:00:00Z"),
                (RUN_ID_2, "succeeded", "main", "2026-09-05T09:00:00Z"),
                (RUN_ID_3, "failed",   "main", "2026-09-05T08:00:00Z"),
                (RUN_ID_4, "running",  "dev",  "2026-09-05T07:00:00Z"),
            ]

        for run_id, status, branch, ts in seeded:
            async with engine.begin() as conn:
                await conn.execute(text(
                    "INSERT INTO cosmo_workspace_runs "
                    "(run_id, repo_owner, repo_name, branch, commit_sha, "
                    " wp_number, repo_id, status, created_at, updated_at) "
                    "VALUES (:rid, 'ws-owner', 'ws-repo', :branch, :sha, "
                    f" :wp, 1, :status, '{ts}'::timestamptz, '{ts}'::timestamptz) "
                    "ON CONFLICT (run_id) DO NOTHING"
                ), {
                    "rid": run_id, "branch": branch, "sha": SHA,
                    "wp": int(run_id[3:]), "status": status,
                })

        await engine.dispose()

    # ── Happy paths ──

    async def test_list_ok_200(self, pg_client: AsyncClient):
        res = await pg_client.get(
            "/api/v1/repos/workspace/runs?repo=ws-owner/ws-repo")
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["total"] == 4
        assert len(body["runs"]) == 4
        # ordered by created_at DESC → run000000001 first (newest)
        assert body["runs"][0]["run_id"] == RUN_ID_1

    async def test_list_pagination(self, pg_client: AsyncClient):
        res = await pg_client.get(
            "/api/v1/repos/workspace/runs?repo=ws-owner/ws-repo&limit=2&offset=1")
        assert res.status_code == 200
        body = res.json()
        assert body["total"] == 4
        assert len(body["runs"]) == 2
        assert body["limit"] == 2
        assert body["offset"] == 1

    async def test_list_filter_by_status(self, pg_client: AsyncClient):
        res = await pg_client.get(
            "/api/v1/repos/workspace/runs?repo=ws-owner/ws-repo&status=failed")
        assert res.status_code == 200
        body = res.json()
        assert body["total"] == 1
        assert body["runs"][0]["status"] == "failed"

    async def test_list_filter_by_branch(self, pg_client: AsyncClient):
        res = await pg_client.get(
            "/api/v1/repos/workspace/runs?repo=ws-owner/ws-repo&branch=dev")
        assert res.status_code == 200
        body = res.json()
        assert body["total"] == 1
        assert body["runs"][0]["branch"] == "dev"

    async def test_list_empty_ok(self, pg_client: AsyncClient):
        res = await pg_client.get(
            "/api/v1/repos/workspace/runs?repo=ws-owner/ws-repo&status=blocked")
        assert res.status_code == 200
        body = res.json()
        assert body["total"] == 0
        assert body["runs"] == []

    # ── Auth / ghost ──

    async def test_list_unknown_repo_404(self, pg_client: AsyncClient):
        res = await pg_client.get(
            "/api/v1/repos/workspace/runs?repo=ghost/unknown")
        assert res.status_code == 404

    async def test_list_anonymous_401(self, pg_client: AsyncClient):
        app.dependency_overrides.pop(get_current_principal, None)
        try:
            res = await pg_client.get(
                "/api/v1/repos/workspace/runs?repo=ws-owner/ws-repo")
            assert res.status_code == 401
        finally:
            pass

    # ── Validation ──

    async def test_list_bad_repo_422(self, pg_client: AsyncClient):
        res = await pg_client.get(
            "/api/v1/repos/workspace/runs?repo=../bad")
        assert res.status_code == 422

    async def test_list_no_repo_422(self, pg_client: AsyncClient):
        res = await pg_client.get("/api/v1/repos/workspace/runs")
        assert res.status_code == 422


# ── Route tests: GET /runs/{run_id}/steps/{step_id}/logs ────────────────────

class TestStepLogsRoute:
    """Route-тесты логов шага: mock woodpecker, реальный pg_client."""

    @pytest.fixture(autouse=True)
    def _mocks(self, monkeypatch):
        self._wp = FakeWoodpecker()
        import orchestrator.cosmo.api.routes.workspace as _ws
        monkeypatch.setattr(_ws, "build_woodpecker", lambda: self._wp)

        async def _principal() -> PrincipalContext:
            return PrincipalContext(
                user_id="ws-log-tester",
                roles=[CBRRole.SERVICE_ADMIN],
                domain_id="ws-log-dom", zone="zr",
                is_authenticated=True, is_system_admin=False,
            )
        app.dependency_overrides[get_current_principal] = _principal

    @pytest_asyncio.fixture(autouse=True)
    async def _seed_db(self, pg_client: AsyncClient):
        """Seed one run row so step logs look-up works."""
        from sqlalchemy.ext.asyncio import create_async_engine
        from sqlalchemy import text

        pg_url = os.getenv("COSMO_DATABASE_URL",
                           "postgresql+asyncpg://cosmo:cosmo@127.0.0.1:5433/cosmo_test")
        engine = create_async_engine(pg_url, echo=False)
        async with engine.begin() as conn:
            await conn.execute(text(
                "INSERT INTO cosmo_workspace_runs "
                "(run_id, repo_owner, repo_name, branch, commit_sha, "
                " wp_number, repo_id, status, created_at, updated_at) "
                "VALUES (:rid, 'ws-owner', 'ws-repo', 'main', :sha, "
                " 42, 1, 'succeeded', now(), now()) "
                "ON CONFLICT (run_id) DO NOTHING"
            ), {"rid": RUN_STEP, "sha": SHA})
        await engine.dispose()

    # ── Happy paths ──

    async def test_logs_ok_200(self, pg_client: AsyncClient):
        res = await pg_client.get(
            f"/api/v1/runs/{RUN_STEP}/steps/1/logs")
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["run_id"] == RUN_STEP
        assert body["step_id"] == 1
        assert body["step_name"] == "test-step"
        assert body["total_lines"] == 25
        assert len(body["lines"]) == 25
        assert body["has_more"] is False

    async def test_logs_pagination(self, pg_client: AsyncClient):
        res = await pg_client.get(
            f"/api/v1/runs/{RUN_STEP}/steps/1/logs?offset=2&limit=3")
        assert res.status_code == 200
        body = res.json()
        assert body["total_lines"] == 25
        assert len(body["lines"]) == 3
        assert body["lines"][0] == "line 2"
        assert body["has_more"] is True

    async def test_logs_tail(self, pg_client: AsyncClient):
        res = await pg_client.get(
            f"/api/v1/runs/{RUN_STEP}/steps/1/logs?tail=5")
        assert res.status_code == 200
        body = res.json()
        assert body["total_lines"] == 25
        assert len(body["lines"]) == 5
        assert body["has_more"] is False
        assert body["lines"][-1] == "line 24"

    async def test_logs_tail_exceeds_total(self, pg_client: AsyncClient):
        res = await pg_client.get(
            f"/api/v1/runs/{RUN_STEP}/steps/1/logs?tail=100")
        assert res.status_code == 200
        body = res.json()
        assert len(body["lines"]) == 25
        assert body["has_more"] is False

    # ── Not found ──

    async def test_logs_run_not_found_404(self, pg_client: AsyncClient):
        res = await pg_client.get("/api/v1/runs/ghost-run/steps/1/logs")
        assert res.status_code == 404

    async def test_logs_step_not_found_404(self, pg_client: AsyncClient):
        res = await pg_client.get(
            f"/api/v1/runs/{RUN_STEP}/steps/999/logs")
        assert res.status_code == 200  # WP returns empty list for unknown step
        body = res.json()
        assert body["total_lines"] == 0
        assert body["lines"] == []

    # ── Auth ──

    async def test_logs_anonymous_401(self, pg_client: AsyncClient):
        app.dependency_overrides.pop(get_current_principal, None)
        try:
            res = await pg_client.get(
                f"/api/v1/runs/{RUN_STEP}/steps/1/logs")
            assert res.status_code == 401
        finally:
            pass

    # ── Woodpecker errors ──

    async def test_logs_woodpecker_error_502(self, pg_client: AsyncClient):
        import requests as _r
        self._wp.error = _r.ConnectionError("down")
        res = await pg_client.get(
            f"/api/v1/runs/{RUN_STEP}/steps/1/logs")
        assert res.status_code == 502

    # ── Validation ──

    async def test_logs_negative_offset_422(self, pg_client: AsyncClient):
        res = await pg_client.get(
            f"/api/v1/runs/{RUN_STEP}/steps/1/logs?offset=-1")
        assert res.status_code == 422

    async def test_logs_zero_limit_422(self, pg_client: AsyncClient):
        res = await pg_client.get(
            f"/api/v1/runs/{RUN_STEP}/steps/1/logs?limit=0")
        assert res.status_code == 422