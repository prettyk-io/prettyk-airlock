# -*- coding: utf-8 -*-
"""COS-196: СЃР±РѕСЂРєР° вЂ” СЂРµР°Р»СЊРЅРѕРµ РёСЃРїРѕР»РЅРµРЅРёРµ Р·Р° С‚СЂРёРіРіРµСЂРѕРј, С‡РµСЃС‚РЅС‹Р№ СЃС‚Р°С‚СѓСЃ/Р°СЂС‚РµС„Р°РєС‚.

РџРѕРєСЂС‹С‚РёРµ:
  - reconcile СЃР±РѕСЂРєРё СЃ РїСЂРѕРіРѕРЅРѕРј: succeededв†’success (+ durable digest-ref,
    evidence_refs), failedв†’failed (РїСЂРёС‡РёРЅР°, Р±РµР· С„Р°РЅС‚РѕРјР°), cancelledв†’aborted,
    running/pending вЂ” Р±РµР· РІС‹РґСѓРјРѕРє;
  - РіР»РѕР±Р°Р»СЊРЅС‹Р№ СЂРµРµСЃС‚СЂ GET /api/v1/builds: Р¶РёРІРѕР№ РѕС‚РІРµС‚, app_name, admin/scope;
  - POST /api/v1/builds: 503 Р±РµР· execution-РєРѕРЅС‚СѓСЂР°, 400 Р±РµР· РїР»Р°РЅР°, СЂРµР°Р»СЊРЅС‹Р№
    РїСЂРѕРіРѕРЅ (run + submit_run) РїСЂРё РіРѕС‚РѕРІРѕРј РєРѕРЅС‚СѓСЂРµ;
  - abort: РѕС‚РјРµРЅР° РїСЂРѕРіРѕРЅР° (cancel_run) + С‡РµСЃС‚РЅС‹Р№ aborted;
  - РґРµС‚Р°Р»Рё: РЅРµРґРѕСЃС‚СѓРїРЅС‹Рµ Р»РѕРіРё вЂ” С‡РµСЃС‚РЅР°СЏ РїСЂРёС‡РёРЅР° (logs_error), РЅРµ РІС‹РґСѓРјРєР°;
  - С€РѕРІ РєР°С‚Р°Р»РѕРіР°: bricks_refs ID-СЃС‚СЂРѕРєРё в†’ docker_build-СЃРїРµРєР° (СЂРµР·РѕР»РІ);
  - executor: РїСЂРѕРІР°Р» submit'Р° в†’ С‚РµСЂРјРёРЅР°Р» РІ PG + degraded + run-С„РёРЅР°Р»РёР·Р°С†РёСЏ
    (В«РІРµС‡РЅС‹Р№ runningВ» РёСЃРєР»СЋС‡С‘РЅ).
"""
from __future__ import annotations

import datetime
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

_och = Path(__file__).resolve().parents[3]  # repo root
if str(_och) not in sys.path:
    sys.path.insert(0, str(_och))

from orchestrator.cosmo.api.routes import builds as builds_route  # noqa: E402
from orchestrator.cosmo.domain.build_model import Build  # noqa: E402
from orchestrator.cosmo.domain.rbac import CBRRole, PrincipalContext  # noqa: E402


def _principal(domain_id: str = "dom-kits", *, admin: bool = False) -> PrincipalContext:
    return PrincipalContext(
        user_id="admin" if admin else "dev_user",
        domain_id=domain_id,
        roles=[CBRRole.DEVELOPER],
        is_authenticated=True,
        is_system_admin=admin,
    )


def _mock_request(exec_service=None):
    request = MagicMock()
    request.app.state.execution_service = exec_service
    return request


# в•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђ
# 1. Reconcile: СЃР±РѕСЂРєР° в†” РїСЂРѕРіРѕРЅ
# в•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђ

def _build_mock(status: str = "running", run_id: str | None = "run-1"):
    bm = MagicMock()
    bm.id = "bld-1"
    bm.app_id = "app-1"
    bm.domain_id = "dom-kits"
    bm.title = "Build app-1@abc"
    bm.commit_sha = "a1b2c3d4e5f6"
    bm.branch = "main"
    bm.status = status
    bm.artifacts = []
    bm.build_logs = ""
    bm.started_at = datetime.datetime(2026, 10, 11, 0, 59, 0)
    bm.finished_at = None
    bm.initiator_user_id = "dev_user"
    bm.meta = {"run_id": run_id} if run_id else {}
    return bm


def _run_mock(status: str):
    run = MagicMock()
    run.id = "run-1"
    run.status = status
    run.finished_at = datetime.datetime(2026, 10, 11, 1, 0, 0)
    return run


@pytest.mark.asyncio
async def test_reconcile_success_pins_durable_artifact(monkeypatch):
    bm = _build_mock()
    mock_db = AsyncMock()
    mock_db.get = AsyncMock(return_value=_run_mock("succeeded"))
    monkeypatch.setattr(
        builds_route, "_evidence_entry_ids",
        AsyncMock(return_value=["entry-1", "entry-2"]),
    )
    monkeypatch.setattr(
        builds_route, "_artifact_refs_for_run",
        AsyncMock(return_value=["build-demo:1.0.0@sha256:" + "ab" * 32]),
    )

    await builds_route._reconcile_build(mock_db, bm)

    assert bm.status == "success"
    assert bm.artifacts == ["build-demo:1.0.0@sha256:" + "ab" * 32]
    assert bm.meta["evidence_refs"] == ["entry-1", "entry-2"]
    assert bm.finished_at is not None
    mock_db.commit.assert_awaited()


@pytest.mark.asyncio
async def test_reconcile_success_without_record_is_honest(monkeypatch):
    bm = _build_mock()
    mock_db = AsyncMock()
    mock_db.get = AsyncMock(return_value=_run_mock("succeeded"))
    monkeypatch.setattr(builds_route, "_evidence_entry_ids", AsyncMock(return_value=[]))
    monkeypatch.setattr(builds_route, "_artifact_refs_for_run", AsyncMock(return_value=[]))

    await builds_route._reconcile_build(mock_db, bm)

    assert bm.status == "success"
    assert bm.artifacts == []  # Р±РµР· С„Р°РЅС‚РѕРјР°
    assert "artifact_note" in bm.meta


@pytest.mark.asyncio
async def test_reconcile_failure_names_reason_without_phantom(monkeypatch):
    bm = _build_mock()
    bm.artifacts = ["phantom:latest"]
    mock_db = AsyncMock()
    mock_db.get = AsyncMock(return_value=_run_mock("failed"))
    monkeypatch.setattr(builds_route, "_evidence_entry_ids", AsyncMock(return_value=[]))
    monkeypatch.setattr(
        builds_route, "_failure_reason",
        AsyncMock(return_value="submit failed: Woodpecker denied (HTTP 401)"),
    )

    await builds_route._reconcile_build(mock_db, bm)

    assert bm.status == "failed"
    assert bm.artifacts == []  # С„Р°РЅС‚РѕРј СЃРЅСЏС‚
    assert "HTTP 401" in bm.meta["failure_reason"]


@pytest.mark.asyncio
async def test_reconcile_cancelled_maps_to_aborted(monkeypatch):
    bm = _build_mock()
    mock_db = AsyncMock()
    mock_db.get = AsyncMock(return_value=_run_mock("cancelled"))
    monkeypatch.setattr(builds_route, "_evidence_entry_ids", AsyncMock(return_value=[]))
    monkeypatch.setattr(builds_route, "_failure_reason", AsyncMock(return_value="cancelled"))

    await builds_route._reconcile_build(mock_db, bm)

    assert bm.status == "aborted"


@pytest.mark.asyncio
async def test_reconcile_running_stays_running(monkeypatch):
    bm = _build_mock()
    mock_db = AsyncMock()
    mock_db.get = AsyncMock(return_value=_run_mock("running"))
    monkeypatch.setattr(builds_route, "_evidence_entry_ids", AsyncMock(return_value=[]))

    await builds_route._reconcile_build(mock_db, bm)

    assert bm.status == "running"
    assert bm.finished_at is None


@pytest.mark.asyncio
async def test_reconcile_missing_run_is_honest():
    bm = _build_mock()
    mock_db = AsyncMock()
    mock_db.get = AsyncMock(return_value=None)

    await builds_route._reconcile_build(mock_db, bm)

    assert bm.status == "running"
    assert bm.meta["run_error"] == "linked run not found"


# в•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђ
# 2. Р“Р»РѕР±Р°Р»СЊРЅС‹Р№ СЂРµРµСЃС‚СЂ GET /api/v1/builds
# в•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђ

def _list_mock_db(builds):
    builds_res = MagicMock()
    builds_res.scalars.return_value.all.return_value = builds
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=builds_res)
    return mock_db


@pytest.mark.asyncio
async def test_list_builds_returns_live_data():
    bm = _build_mock(status="success")
    mock_db = _list_mock_db([bm])

    result = await builds_route.list_builds(
        app_id=None, project_id=None, status_f=None, branch=None,
        principal=_principal(), db=mock_db,
    )

    assert len(result) == 1
    assert result[0].id == "bld-1"
    assert result[0].title == "Build app-1@abc"
    assert result[0].initiator == "dev_user"
    assert result[0].app_name is None  # РёРјРµРЅРё РїСЂРёР»РѕР¶РµРЅРёСЏ РІ СЃС…РµРјРµ РЅРµС‚ вЂ” app_id


@pytest.mark.asyncio
async def test_list_builds_admin_is_global_nonadmin_scoped():
    bm = _build_mock(status="success")

    admin_db = _list_mock_db([bm])
    await builds_route.list_builds(
        app_id=None, project_id=None, status_f=None, branch=None,
        principal=_principal(admin=True), db=admin_db,
    )
    admin_stmt = str(admin_db.execute.call_args_list[0][0][0])

    user_db = _list_mock_db([bm])
    await builds_route.list_builds(
        app_id=None, project_id=None, status_f=None, branch=None,
        principal=_principal(), db=user_db,
    )
    user_stmt = str(user_db.execute.call_args_list[0][0][0])

    # РђРґРјРёРЅ вЂ” Р±РµР· РґРѕРјРµРЅРЅРѕРіРѕ С„РёР»СЊС‚СЂР° (СЃРІРѕРґРЅР°СЏ РєР°СЂС‚РёРЅР°); РЅРµ-Р°РґРјРёРЅ вЂ” scoped.
    assert "WHERE" not in admin_stmt
    assert "WHERE" in user_stmt
    assert "domain_id" in user_stmt.split("WHERE", 1)[1]


# в•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђ
# 3. POST /api/v1/builds вЂ” СЂРµР°Р»СЊРЅС‹Р№ Р·Р°РїСѓСЃРє
# в•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђ

def _create_db(app, plan):
    mock_db = AsyncMock()
    mock_db.get = AsyncMock(side_effect=lambda model, pk: {
        type(app): app, type(plan): plan,
    }.get(model))
    return mock_db


@pytest.mark.asyncio
async def test_create_build_without_executor_is_honest_failure():
    """Executor РІС‹РєР»СЋС‡РµРЅ в†’ С‡РµСЃС‚РЅС‹Р№ РїСЂРѕРІР°Р» РЅР° СЃС‚Р°СЂС‚Рµ (Р·Р°РїРёСЃСЊ СЃ РїСЂРёС‡РёРЅРѕР№, Р±РµР· run'Р°)."""
    from orchestrator.cosmo.api.routes.builds import CreateBuildRequest
    from orchestrator.cosmo.db.models import (
        Application as ApplicationModel,
        PipelinePlan as PlanModel,
    )

    app = MagicMock(spec=ApplicationModel)
    app.id = "app-1"
    app.domain_id = "dom-kits"
    app.pipeline_plan_id = "plan-1"
    plan = MagicMock(spec=PlanModel)
    plan.id = "plan-1"

    mock_db = AsyncMock()
    mock_db.add = MagicMock()
    mock_db.get = AsyncMock(side_effect=lambda model, pk: (
        app if model is ApplicationModel else plan if model is PlanModel else None
    ))

    batch_res = MagicMock()
    batch_res.all.return_value = [("batch-1", "pending")]
    binding_res = MagicMock()
    binding_res.scalars.return_value.first.return_value = None
    mock_db.execute = AsyncMock(side_effect=[batch_res, binding_res])

    created = await builds_route.create_build(
        body=CreateBuildRequest(app_id="app-1", commit_sha="a1b2c3d4e5f6"),
        request=_mock_request(exec_service=None),
        principal=_principal(admin=True),
        db=mock_db,
    )

    assert created.status == "failed"
    assert "execution disabled" in created.meta["failure_reason"]
    assert created.run_id is None
    assert created.artifacts == []
    added = [call.args[0] for call in mock_db.add.call_args_list]
    assert {type(obj).__name__ for obj in added} == {"Build"}


@pytest.mark.asyncio
async def test_create_build_honest_400_without_plan():
    from fastapi import HTTPException
    from orchestrator.cosmo.api.routes.builds import CreateBuildRequest

    mock_db = AsyncMock()
    app = SimpleNamespace(id="app-1", domain_id="dom-kits", pipeline_plan_id=None)
    mock_db.get = AsyncMock(return_value=app)
    empty_res = MagicMock()
    empty_res.scalars.return_value.first.return_value = None
    mock_db.execute = AsyncMock(return_value=empty_res)

    with pytest.raises(HTTPException) as exc:
        await builds_route.create_build(
            body=CreateBuildRequest(app_id="app-1", commit_sha="a1b2c3d4e5f6"),
            request=_mock_request(exec_service=AsyncMock()),
            principal=_principal(admin=True),
            db=mock_db,
        )
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_create_build_consumed_plan_is_honest_409():
    """План уже исполнялся → 409 (новый билд = новый план; не вечный running)."""
    from fastapi import HTTPException
    from orchestrator.cosmo.api.routes.builds import CreateBuildRequest
    from orchestrator.cosmo.db.models import (
        Application as ApplicationModel,
        PipelinePlan as PlanModel,
    )

    app = MagicMock(spec=ApplicationModel)
    app.id = "app-1"
    app.domain_id = "dom-kits"
    app.pipeline_plan_id = "plan-1"
    plan = MagicMock(spec=PlanModel)
    plan.id = "plan-1"

    mock_db = AsyncMock()
    mock_db.get = AsyncMock(side_effect=lambda model, pk: (
        app if model is ApplicationModel else plan if model is PlanModel else None
    ))
    batch_res = MagicMock()
    batch_res.all.return_value = [("batch-1", "passed")]
    mock_db.execute = AsyncMock(return_value=batch_res)

    with pytest.raises(HTTPException) as exc:
        await builds_route.create_build(
            body=CreateBuildRequest(app_id="app-1", commit_sha="a1b2c3d4e5f6"),
            request=_mock_request(exec_service=AsyncMock()),
            principal=_principal(admin=True),
            db=mock_db,
        )
    assert exc.value.status_code == 409
    assert "уже исполнялся" in exc.value.detail


@pytest.mark.asyncio
async def test_create_build_triggers_real_run():
    from orchestrator.cosmo.api.routes.builds import CreateBuildRequest
    from orchestrator.cosmo.db.models import (
        Application as ApplicationModel,
        Batch as BatchModel,
        PipelinePlan as PlanModel,
        RepositoryBinding as RepoBindingModel,
    )

    app = MagicMock(spec=ApplicationModel)
    app.id = "app-1"
    app.domain_id = "dom-kits"
    app.pipeline_plan_id = "plan-1"

    plan = MagicMock(spec=PlanModel)
    plan.id = "plan-1"

    async def _get(model, pk):
        if model is PlanModel:
            return plan
        if model is ApplicationModel:
            return app
        return None

    mock_db = AsyncMock()
    mock_db.add = MagicMock()
    mock_db.get = AsyncMock(side_effect=_get)

    batch_res = MagicMock()
    batch_res.all.return_value = [("batch-1", "pending")]
    binding = MagicMock(spec=RepoBindingModel)
    binding.repo_path = "cosmo/build-demo"
    binding.default_branch = "main"
    binding_res = MagicMock()
    binding_res.scalars.return_value.first.return_value = binding
    mock_db.execute = AsyncMock(side_effect=[batch_res, binding_res])

    exec_service = AsyncMock()

    created = await builds_route.create_build(
        body=CreateBuildRequest(
            app_id="app-1", commit_sha="a1b2c3d4e5f6",
            branch="main", title="Demo build",
        ),
        request=_mock_request(exec_service=exec_service),
        principal=_principal(admin=True),
        db=mock_db,
    )

    assert created.status == "running"
    assert created.title == "Demo build"
    assert created.run_id and created.run_id.startswith("run-bld-")
    assert created.meta["repo"] == "cosmo/build-demo"
    assert created.meta["batch_ids"] == ["batch-1"]
    assert created.artifacts == []  # РЅРёС‡РµРіРѕ РЅРµ РІС‹РґСѓРјР°РЅРѕ
    exec_service.submit_run.assert_awaited_once_with(created.run_id)

    added = [call.args[0] for call in mock_db.add.call_args_list]
    kinds = {type(obj).__name__ for obj in added}
    assert kinds == {"Run", "Build"}


# в•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђ
# 4. Abort вЂ” РѕС‚РјРµРЅР° РїСЂРѕРіРѕРЅР°
# в•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђ

@pytest.mark.asyncio
async def test_abort_cancels_linked_run():
    from orchestrator.cosmo.db.models import Build as BuildModel, Run as RunModel

    bm = _build_mock(status="running", run_id="run-1")
    run = _run_mock("running")

    mock_db = AsyncMock()
    mock_db.get = AsyncMock(side_effect=lambda model, pk: (
        bm if model is BuildModel else run if model is RunModel else None
    ))

    exec_service = AsyncMock()

    aborted = await builds_route.abort_build(
        build_id="bld-1",
        request=_mock_request(exec_service=exec_service),
        principal=_principal(admin=True),
        db=mock_db,
    )

    assert aborted.status == "aborted"
    assert run.status == "cancelled"
    assert run.finished_at is not None
    exec_service.cancel_run.assert_awaited_once_with("run-1")


# в•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђ
# 5. Р”РµС‚Р°Р»Рё: Р»РѕРіРё РЅРµРґРѕСЃС‚СѓРїРЅС‹ вЂ” С‡РµСЃС‚РЅРѕ
# в•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђ

@pytest.mark.asyncio
async def test_details_logs_unavailable_is_honest(monkeypatch):
    from orchestrator.cosmo.db.models import (
        Application as ApplicationModel,
        Build as BuildModel,
        Run as RunModel,
    )

    bm = _build_mock(status="running", run_id="run-1")
    handle = SimpleNamespace(
        wp_number=7,
        repo_id=3,
        as_handle_dict=lambda: {
            "number": 7, "repo_id": 3,
            "repo_owner": "cosmo", "repo_name": "build-demo", "branch": "main",
        },
    )

    mock_db = AsyncMock()
    mock_db.get = AsyncMock(side_effect=lambda model, pk: (
        bm if model is BuildModel else
        None if model is RunModel else None
    ))

    handles_res = MagicMock()
    handles_res.scalars.return_value.all.return_value = [handle]
    mock_db.execute = AsyncMock(return_value=handles_res)

    def _wp_down(handle_dict):
        raise RuntimeError("Woodpecker unreachable")

    monkeypatch.setattr(builds_route, "_wp_logs_for_handle", _wp_down)

    result = await builds_route.get_build_details(
        build_id="bld-1",
        principal=_principal(admin=True),
        db=mock_db,
    )

    assert result.build_logs == ""
    assert "Woodpecker unreachable" in result.meta["logs_error"]


# в•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђ
# 6. РЁРѕРІ РєР°С‚Р°Р»РѕРіР°: ID-СЃС‚СЂРѕРєРё bricks_refs в†’ docker_build-СЃРїРµРєР°
# в•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђ

@pytest.mark.asyncio
async def test_details_admin_cross_domain_but_ghost_for_user():
    """COS-032: admin открывает сборку чужого домена; не-админ — ghost-404."""
    from fastapi import HTTPException
    from orchestrator.cosmo.db.models import Build as BuildModel

    bm = _build_mock(status="success", run_id=None)
    mock_db = AsyncMock()
    mock_db.get = AsyncMock(side_effect=lambda model, pk: (
        bm if model is BuildModel else None
    ))

    # admin (identity-домен dom-ops) читает сборку dom-kits — bypass.
    result = await builds_route.get_build_details(
        build_id="bld-1",
        principal=_principal("dom-ops", admin=True),
        db=mock_db,
    )
    assert result.id == "bld-1"

    # не-админ чужого домена — ghost-404 (существование не раскрываем).
    with pytest.raises(HTTPException) as exc:
        await builds_route.get_build_details(
            build_id="bld-1",
            principal=_principal("dom-ops", admin=False),
            db=mock_db,
        )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_resolve_brick_refs_to_docker_build_specs():
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from orchestrator.cosmo.control_plane.artifact_capture import docker_build_specs
    from orchestrator.cosmo.control_plane.execution_service import ExecutionService

    import _testpg

    engine = create_async_engine(_testpg.TEST_PG_URL, echo=False)
    sm = async_sessionmaker(engine, expire_on_commit=False)

    definition = {
        "type": "docker_build", "image_name": "build-demo", "version": "1.0.0",
        "registry": "localhost:5100", "repository": "cosmoport", "namespace": "zr",
    }
    async with engine.begin() as conn:
        await conn.execute(text(
            "INSERT INTO pipeline_bricks (id, name, type, source, definition_json, "
            "depends_on, gates) VALUES ('cos196-brick', 'Docker Build (demo)', "
            "'build', 'internal', :def, '[]'::jsonb, '[]'::jsonb) "
            "ON CONFLICT (id) DO UPDATE SET definition_json = excluded.definition_json"
        ), {"def": json.dumps(definition)})

    async with sm() as s:
        resolved = await ExecutionService._resolve_brick_refs(
            s, ["cos196-brick", {"name": "legacy", "definition": {"image": "x"}}],
        )
    await engine.dispose()

    specs = docker_build_specs(resolved)
    assert len(specs) == 1
    assert specs[0].image_name == "build-demo"
    assert specs[0].version == "1.0.0"


# в•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђ
# 7. Executor: РїСЂРѕРІР°Р» submit'Р° РЅРµ РѕСЃС‚Р°РІР»СЏРµС‚ В«РІРµС‡РЅС‹Р№ runningВ»
# в•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђ

def test_submit_failure_finalizes_run_honestly():
    from orchestrator.cosmo.adapters.execution_woodpecker import WoodpeckerAdapter
    from orchestrator.cosmo.control_plane.executor import BatchExecutor
    from orchestrator.cosmo.control_plane.run_control import RunRecord

    adapter = WoodpeckerAdapter(base_url="http://localhost:8000", token="t")
    adapter.submit_run = MagicMock(side_effect=Exception("Woodpecker denied (HTTP 401)"))

    executor = BatchExecutor(adapter=adapter, dry_run=False)
    executor._query_batches = MagicMock(return_value=[{
        "id": "batch-build", "plan_id": "plan-1", "type": "build",
        "status": "pending", "bricks": [], "artifacts": [],
    }])
    executor._update_batch_pg_terminal = MagicMock()
    executor._check_run_terminal = MagicMock()

    run = RunRecord(id="run-1", plan_id="plan-1", domain_id="dom-1", trigger="manual")
    submitted = executor.submit_batches(run)

    assert submitted == []
    executor._update_batch_pg_terminal.assert_called_once_with("batch-build", "failed")
    executor._check_run_terminal.assert_called_once_with("run-1")
    reason = executor.degraded_reason("run-1")
    assert reason and "HTTP 401" in reason


# в•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђ
# 8. Domain-РјРѕРґРµР»СЊ: РЅРѕРІС‹Рµ РїРѕР»СЏ (РѕР±СЂР°С‚РЅР°СЏ СЃРѕРІРјРµСЃС‚РёРјРѕСЃС‚СЊ)
# в•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђ

def test_build_model_cos196_fields_defaults():
    build = Build(
        id="bld-1", app_id="app-1",
        commit_sha="a1b2c3d4e5f6",
    )
    assert build.title == ""
    assert build.app_name is None
    assert build.initiator is None
    assert build.run_id is None
    assert build.evidence_refs == []

    full = Build(
        id="bld-2", app_id="app-1", commit_sha="a1b2c3d4e5f6",
        title="Demo", app_name="Build Demo", initiator="dev_user",
        run_id="run-1", evidence_refs=["e1", "e2"],
    )
    assert full.title == "Demo"
    assert full.run_id == "run-1"
    assert full.evidence_refs == ["e1", "e2"]
