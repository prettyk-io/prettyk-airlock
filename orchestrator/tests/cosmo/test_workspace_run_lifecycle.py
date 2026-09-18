# -*- coding: utf-8 -*-
"""COS-133: Workspace run lifecycle — DTO unit + route mock.

Покрытие: GET /workspace/runs/{run_id} (детали + sync статуса),
POST .../cancel (killed / 400 на терминальном), POST .../rerun
(новый WorkspaceRunRow + original_run_id), auth/ghost/error guards.

Запуск:  pytest .../test_workspace_run_lifecycle.py -q
"""
from __future__ import annotations

import os
import sys
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

from orchestrator.cosmo.api.deps import get_current_principal
from orchestrator.cosmo.api.main import app
from orchestrator.cosmo.domain.rbac import CBRRole, PrincipalContext
from orchestrator.cosmo.domain.workspace import (
    WorkspaceRunCancelResponse,
    WorkspaceRunDetailResponse,
    WorkspaceRunRerunResponse,
    WorkspaceRunStepSummary,
)

SHA = "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6a7b8c9d0"
DOMAIN = "ws-life-dom"
REPO = "ws-owner/ws-repo"

RUN_RUNNING = "life00000001"
RUN_DONE = "life00000002"
RUN_NOPIPE = "life00000003"
RUN_GHOST = "life00000004"

_PG_URL = os.getenv(
    "COSMO_DATABASE_URL",
    "postgresql+asyncpg://cosmo:cosmo@127.0.0.1:5433/cosmo_test",
)


async def _fetch_row(run_id: str) -> Optional[dict]:
    """Прочитать строку прогона напрямую из PG (вне route-сессии)."""
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(_PG_URL, echo=False)
    try:
        async with engine.connect() as conn:
            res = await conn.execute(
                text(
                    "SELECT run_id, status, original_run_id, wp_number "
                    "FROM cosmo_workspace_runs WHERE run_id = :rid"
                ),
                {"rid": run_id},
            )
            row = res.mappings().first()
            return dict(row) if row else None
    finally:
        await engine.dispose()


# ── Fake Woodpecker ──────────────────────────────────────────────────────

class FakeWoodpecker:
    """In-memory Woodpecker: detail / cancel / rerun + injectable errors."""

    def __init__(self) -> None:
        self._base = "http://woodpecker:8000"
        self.detail_status = "success"
        self.detail_error: Optional[Exception] = None
        self.cancel_error: Optional[Exception] = None
        self.rerun_error: Optional[Exception] = None
        self.detail_calls: list[dict] = []
        self.cancel_calls: list[dict] = []
        self.rerun_calls: list[dict] = []
        self.rerun_number = 7
        self.rerun_pipeline_id = 200

    def get_pipeline_detail(self, handle: dict) -> dict:
        if self.detail_error:
            raise self.detail_error
        self.detail_calls.append(handle)
        return {
            "number": handle.get("number"),
            "status": self.detail_status,
            "started": 1700000000,
            "finished": 1700000012,
            "workflows": [{
                "name": "default",
                "steps": [
                    {"id": 1, "pid": 1, "name": "build", "state": "success",
                     "exit_code": 0, "started": 1700000000,
                     "finished": 1700000005},
                    {"id": 2, "pid": 1, "name": "test", "state": "failure",
                     "exit_code": 1, "started": 1700000005,
                     "finished": 1700000012},
                ],
            }],
        }

    def cancel_pipeline(self, handle: dict) -> dict:
        if self.cancel_error:
            raise self.cancel_error
        self.cancel_calls.append(handle)
        return {"number": handle.get("number"), "cancelled": True}

    def rerun_pipeline(self, handle: dict) -> dict:
        if self.rerun_error:
            raise self.rerun_error
        self.rerun_calls.append(handle)
        return {
            "job_id": self.rerun_pipeline_id,
            "number": self.rerun_number,
            "repo_id": 1,
        }


# ── DTO unit ─────────────────────────────────────────────────────────────

class TestRunLifecycleDto:
    def test_step_minimal(self):
        s = WorkspaceRunStepSummary(name="build", status="success")
        assert s.exit_code is None
        assert s.duration_ms is None

    def test_step_full(self):
        s = WorkspaceRunStepSummary(
            name="test", status="failure", exit_code=1,
            duration_ms=7000, started_at="2026-01-01T00:00:00Z",
            finished_at="2026-01-01T00:00:07Z",
        )
        assert s.exit_code == 1
        assert s.duration_ms == 7000

    def test_step_extra_forbidden(self):
        with pytest.raises(ValidationError):
            WorkspaceRunStepSummary(name="x", status="success", hack=1)

    def test_detail_defaults(self):
        d = WorkspaceRunDetailResponse(
            run_id="r1", repo=REPO, branch="main", commit_sha=SHA,
            status="running",
        )
        assert d.steps == []
        assert d.pipeline_number is None
        assert d.original_run_id is None

    def test_detail_full(self):
        d = WorkspaceRunDetailResponse(
            run_id="r1", repo=REPO, branch="main", commit_sha=SHA,
            status="success", pipeline_number=11, original_run_id="r0",
            duration_ms=12000, started_at="t0", finished_at="t1",
            steps=[WorkspaceRunStepSummary(name="build", status="success")],
        )
        assert d.original_run_id == "r0"
        assert len(d.steps) == 1

    def test_detail_extra_forbidden(self):
        with pytest.raises(ValidationError):
            WorkspaceRunDetailResponse(
                run_id="r1", repo=REPO, branch="main", commit_sha=SHA,
                status="running", hack=1,
            )

    def test_cancel_defaults(self):
        c = WorkspaceRunCancelResponse(run_id="r1", status="killed")
        assert c.cancelled is True

    def test_cancel_extra_forbidden(self):
        with pytest.raises(ValidationError):
            WorkspaceRunCancelResponse(run_id="r1", status="killed", hack=1)

    def test_rerun_minimal(self):
        r = WorkspaceRunRerunResponse(
            run_id="r2", original_run_id="r1",
            pipeline_number=7, status="running",
        )
        assert r.pipeline_id is None
        assert r.tracking_url is None

    def test_rerun_extra_forbidden(self):
        with pytest.raises(ValidationError):
            WorkspaceRunRerunResponse(
                run_id="r2", original_run_id="r1",
                pipeline_number=7, status="running", hack=1,
            )


# ── Route tests ──────────────────────────────────────────────────────────

class TestRunLifecycleRoute:
    """Route-тесты: mock woodpecker, реальный PG через pg_client."""

    @pytest.fixture(autouse=True)
    def _mocks(self, monkeypatch):
        self._wp = FakeWoodpecker()
        import orchestrator.cosmo.api.routes.workspace as _ws
        monkeypatch.setattr(_ws, "build_woodpecker", lambda: self._wp)

        async def _principal() -> PrincipalContext:
            return PrincipalContext(
                user_id="ws-life-tester",
                roles=[CBRRole.SERVICE_ADMIN],
                domain_id=DOMAIN, zone="zr",
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

        engine = create_async_engine(_PG_URL, echo=False)
        async with engine.begin() as conn:
            await conn.execute(text(
                "INSERT INTO domains (id, label, forge_type, forge_url, "
                "forge_token_ref, rbac_config, quota_max_runs, "
                "quota_max_storage_gb, quota_max_cpu, created_at) "
                "VALUES (:d, 'ws-life-test', 'gitea', 'http://gitea:3000', "
                "'t', '{}'::jsonb, 50, 100, 8, now()) "
                "ON CONFLICT (id) DO NOTHING"
            ), {"d": DOMAIN})
            await conn.execute(text(
                "INSERT INTO apps (id, domain_id, level) "
                "VALUES ('ws-life-app', :d, 0) ON CONFLICT (id) DO NOTHING"
            ), {"d": DOMAIN})
            await conn.execute(text(
                "INSERT INTO repo_bindings (id, app_id, forge_id, repo_path, "
                "default_branch) VALUES ('ws-life-bind', 'ws-life-app', "
                "'gitea-1', :repo, 'main') ON CONFLICT (id) DO NOTHING"
            ), {"repo": REPO})

        seeded = [
            # (run_id, status, wp_number, owner, name)
            (RUN_RUNNING, "running", 11, "ws-owner", "ws-repo"),
            (RUN_DONE, "succeeded", 12, "ws-owner", "ws-repo"),
            (RUN_NOPIPE, "running", None, "ws-owner", "ws-repo"),
            (RUN_GHOST, "running", 14, "ghost-owner", "ghost-repo"),
        ]
        for run_id, status, wp, owner, name in seeded:
            async with engine.begin() as conn:
                await conn.execute(text(
                    "INSERT INTO cosmo_workspace_runs "
                    "(run_id, repo_owner, repo_name, branch, commit_sha, "
                    " wp_number, repo_id, status, created_at, updated_at) "
                    "VALUES (:rid, :owner, :name, 'main', :sha, :wp, "
                    " :rid_col, :status, now(), now()) "
                    "ON CONFLICT (run_id) DO NOTHING"
                ), {
                    "rid": run_id, "owner": owner, "name": name,
                    "sha": SHA, "wp": wp, "status": status,
                    "rid_col": 1 if wp is not None else None,
                })
        await engine.dispose()

    # ── Detail: happy paths ──

    async def test_detail_ok_200(self, pg_client: AsyncClient):
        res = await pg_client.get(f"/api/v1/repos/workspace/runs/{RUN_RUNNING}")
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["run_id"] == RUN_RUNNING
        assert body["repo"] == REPO
        assert body["pipeline_number"] == 11
        assert body["duration_ms"] == 12000

    async def test_detail_returns_steps(self, pg_client: AsyncClient):
        res = await pg_client.get(f"/api/v1/repos/workspace/runs/{RUN_RUNNING}")
        assert res.status_code == 200
        steps = res.json()["steps"]
        assert [s["name"] for s in steps] == ["build", "test"]
        assert steps[0]["exit_code"] == 0
        assert steps[1]["status"] == "failure"
        assert steps[1]["duration_ms"] == 7000

    async def test_detail_syncs_running_status(self, pg_client: AsyncClient):
        self._wp.detail_status = "success"
        res = await pg_client.get(f"/api/v1/repos/workspace/runs/{RUN_RUNNING}")
        assert res.status_code == 200
        assert res.json()["status"] == "success"
        row = await _fetch_row(RUN_RUNNING)
        assert row["status"] == "success"

    async def test_detail_terminal_not_overwritten(self, pg_client: AsyncClient):
        self._wp.detail_status = "running"
        res = await pg_client.get(f"/api/v1/repos/workspace/runs/{RUN_DONE}")
        assert res.status_code == 200
        assert res.json()["status"] == "succeeded"
        row = await _fetch_row(RUN_DONE)
        assert row["status"] == "succeeded"

    async def test_detail_reports_original_run_id(self, pg_client: AsyncClient):
        # rerun сначала создаёт связь
        await pg_client.post(f"/api/v1/repos/workspace/runs/{RUN_RUNNING}/rerun")
        res = await pg_client.get(f"/api/v1/repos/workspace/runs/{RUN_RUNNING}")
        assert res.status_code == 200
        # исходный прогон связи не имеет — None
        assert res.json()["original_run_id"] is None

    # ── Detail: guards ──

    async def test_detail_unknown_404(self, pg_client: AsyncClient):
        res = await pg_client.get("/api/v1/repos/workspace/runs/nope-nope")
        assert res.status_code == 404

    async def test_detail_ghost_domain_404(self, pg_client: AsyncClient):
        res = await pg_client.get(f"/api/v1/repos/workspace/runs/{RUN_GHOST}")
        assert res.status_code == 404

    async def test_detail_no_pipeline_404(self, pg_client: AsyncClient):
        res = await pg_client.get(f"/api/v1/repos/workspace/runs/{RUN_NOPIPE}")
        assert res.status_code == 404

    async def test_detail_anonymous_401(self, pg_client: AsyncClient):
        app.dependency_overrides.pop(get_current_principal, None)
        res = await pg_client.get(f"/api/v1/repos/workspace/runs/{RUN_RUNNING}")
        assert res.status_code == 401

    async def test_detail_woodpecker_down_502(self, pg_client: AsyncClient):
        self._wp.detail_error = requests.ConnectionError("down")
        res = await pg_client.get(f"/api/v1/repos/workspace/runs/{RUN_RUNNING}")
        assert res.status_code == 502

    # ── Cancel ──

    async def test_cancel_ok_sets_killed(self, pg_client: AsyncClient):
        res = await pg_client.post(
            f"/api/v1/repos/workspace/runs/{RUN_RUNNING}/cancel")
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["run_id"] == RUN_RUNNING
        assert body["status"] == "killed"
        assert body["cancelled"] is True
        row = await _fetch_row(RUN_RUNNING)
        assert row["status"] == "killed"

    async def test_cancel_calls_adapter(self, pg_client: AsyncClient):
        await pg_client.post(f"/api/v1/repos/workspace/runs/{RUN_RUNNING}/cancel")
        assert len(self._wp.cancel_calls) == 1
        assert self._wp.cancel_calls[0]["number"] == 11

    async def test_cancel_finished_400(self, pg_client: AsyncClient):
        res = await pg_client.post(
            f"/api/v1/repos/workspace/runs/{RUN_DONE}/cancel")
        assert res.status_code == 400

    async def test_cancel_unknown_404(self, pg_client: AsyncClient):
        res = await pg_client.post(
            "/api/v1/repos/workspace/runs/nope-nope/cancel")
        assert res.status_code == 404

    async def test_cancel_ghost_404(self, pg_client: AsyncClient):
        res = await pg_client.post(
            f"/api/v1/repos/workspace/runs/{RUN_GHOST}/cancel")
        assert res.status_code == 404

    async def test_cancel_anonymous_401(self, pg_client: AsyncClient):
        app.dependency_overrides.pop(get_current_principal, None)
        res = await pg_client.post(
            f"/api/v1/repos/workspace/runs/{RUN_RUNNING}/cancel")
        assert res.status_code == 401

    async def test_cancel_permission_502(self, pg_client: AsyncClient):
        self._wp.cancel_error = PermissionError("no push access")
        res = await pg_client.post(
            f"/api/v1/repos/workspace/runs/{RUN_RUNNING}/cancel")
        assert res.status_code == 502

    # ── Rerun ──

    async def test_rerun_ok_201(self, pg_client: AsyncClient):
        res = await pg_client.post(
            f"/api/v1/repos/workspace/runs/{RUN_RUNNING}/rerun")
        assert res.status_code == 201, res.text
        body = res.json()
        assert body["original_run_id"] == RUN_RUNNING
        assert body["pipeline_number"] == 7
        assert body["pipeline_id"] == 200
        assert body["status"] == "running"
        assert body["run_id"] != RUN_RUNNING

    async def test_rerun_persists_new_row(self, pg_client: AsyncClient):
        res = await pg_client.post(
            f"/api/v1/repos/workspace/runs/{RUN_RUNNING}/rerun")
        new_id = res.json()["run_id"]
        row = await _fetch_row(new_id)
        assert row is not None
        assert row["original_run_id"] == RUN_RUNNING
        assert row["wp_number"] == 7
        assert row["status"] == "running"

    async def test_rerun_calls_adapter(self, pg_client: AsyncClient):
        await pg_client.post(f"/api/v1/repos/workspace/runs/{RUN_RUNNING}/rerun")
        assert len(self._wp.rerun_calls) == 1
        assert self._wp.rerun_calls[0]["number"] == 11

    async def test_rerun_unknown_404(self, pg_client: AsyncClient):
        res = await pg_client.post(
            "/api/v1/repos/workspace/runs/nope-nope/rerun")
        assert res.status_code == 404

    async def test_rerun_ghost_404(self, pg_client: AsyncClient):
        res = await pg_client.post(
            f"/api/v1/repos/workspace/runs/{RUN_GHOST}/rerun")
        assert res.status_code == 404

    async def test_rerun_no_pipeline_404(self, pg_client: AsyncClient):
        res = await pg_client.post(
            f"/api/v1/repos/workspace/runs/{RUN_NOPIPE}/rerun")
        assert res.status_code == 404

    async def test_rerun_anonymous_401(self, pg_client: AsyncClient):
        app.dependency_overrides.pop(get_current_principal, None)
        res = await pg_client.post(
            f"/api/v1/repos/workspace/runs/{RUN_RUNNING}/rerun")
        assert res.status_code == 401

    async def test_rerun_woodpecker_down_502(self, pg_client: AsyncClient):
        self._wp.rerun_error = requests.ConnectionError("down")
        res = await pg_client.post(
            f"/api/v1/repos/workspace/runs/{RUN_RUNNING}/rerun")
        assert res.status_code == 502
