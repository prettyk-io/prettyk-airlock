"""
SAN-012 + SAN-013: Tests for Builds and Deployments First-Class Entities and API.

РџСЂРѕРІРµСЂСЏРµС‚:
  1. Pydantic v2 РјРѕРґРµР»Рё Build Рё Deployment (РІР°Р»РёРґР°С†РёСЏ РїРѕР»РµР№, СЃС‚Р°С‚СѓСЃС‹, СЃРІРѕР№СЃС‚РІР°).
  2. REST API СЌРЅРґРїРѕРёРЅС‚С‹ СЃР±РѕСЂРѕРє (Builds):
     - GET /api/v1/apps/{app_id}/builds
     - POST /api/v1/apps/{app_id}/builds
     - GET /api/v1/builds/{build_id}
     - POST /api/v1/builds/{build_id}/abort
  3. REST API СЌРЅРґРїРѕРёРЅС‚С‹ СЂР°Р·РІРµСЂС‚С‹РІР°РЅРёР№ (Deployments):
     - GET /api/v1/apps/{app_id}/deploys
     - POST /api/v1/apps/{app_id}/deploys
     - GET /api/v1/deploys/{id}
     - POST /api/v1/deploys/{id}/rollback
  4. РР·РѕР»СЏС†РёСЋ РјСѓР»СЊС‚РёС‚РµРЅР°РЅС‚РЅРѕСЃС‚Рё Рё РїСЂРѕРІРµСЂРєРё 404/400.
"""
import datetime
from unittest.mock import AsyncMock, MagicMock
import pytest
from fastapi import HTTPException

from cosmo.domain.build_model import Build, BuildStatus
from cosmo.domain.deployment_model import Deployment, DeploymentSegment, DeploymentStatus, DeploymentZone
from cosmo.domain.rbac import CBRRole, PrincipalContext, Role


# в•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђ
# 1. Pydantic Models Unit Tests
# в•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђ

def test_build_model_properties_and_status():
    now = datetime.datetime.utcnow()
    finished = now + datetime.timedelta(seconds=45)

    build = Build(
        id="bld-001",
        app_id="app-core",
        domain_id="dom-banking",
        commit_sha="e4d909c290d0fb1ca068ffaddf22cbd0adddef11",
        branch="main",
        status="success",
        artifacts=["oci://registry.corp/core:e4d909c2", "vault:secret/sbom/core"],
        started_at=now,
        finished_at=finished,
        initiator_user_id="dev_ivanov",
    )

    assert build.id == "bld-001"
    assert build.is_finished is True
    assert build.is_success is True
    assert build.duration_seconds == 45.0
    assert len(build.artifacts) == 2


def test_deployment_model_properties():
    now = datetime.datetime.utcnow()

    dep = Deployment(
        id="dep-100",
        build_id="bld-001",
        app_id="app-core",
        domain_id="dom-banking",
        target_zone="zt",
        segment="bare",
        status="success",
        custom_url="https://app-core.zt.bank.corp:8443",
        operator_id="devops_lead",
        started_at=now,
    )

    assert dep.id == "dep-100"
    assert dep.is_active is True
    assert dep.can_rollback is True
    assert dep.target_zone == "zt"
    assert dep.segment == "bare"


# в•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђ
# 2. Builds API Route Handlers Tests
# в•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђ

@pytest.mark.asyncio
async def test_trigger_and_list_app_builds():
    from cosmo.api.routes.builds import (
        TriggerBuildRequest,
        get_build_details,
        list_app_builds,
        trigger_app_build,
    )
    from orchestrator.cosmo.db.models import (
        Application as ApplicationModel,
        Batch as BatchModel,
        Build as BuildModel,
        PipelinePlan as PlanModel,
    )

    mock_db = AsyncMock()
    mock_app = MagicMock(spec=ApplicationModel)
    mock_app.id = "app-auth"
    mock_app.name = "auth-service"
    mock_app.domain_id = "dom-kits"
    mock_app.pipeline_plan_id = "plan-auth"

    mock_plan = MagicMock(spec=PlanModel)
    mock_plan.id = "plan-auth"

    async def _get(model_cls, pk):
        if model_cls == ApplicationModel:
            return mock_app
        if model_cls == PlanModel:
            return mock_plan
        return None

    mock_db.get = AsyncMock(side_effect=_get)

    # execute: (1) batches РїР»Р°РЅР° в†’ РѕРґРёРЅ build-Р±Р°С‚С‡; (2) repo binding в†’ None.
    batch_res = MagicMock()
    batch_res.all.return_value = [("batch-auth-build", "pending")]
    binding_res = MagicMock()
    binding_res.scalars.return_value.first.return_value = None
    mock_db.execute = AsyncMock(side_effect=[batch_res, binding_res])

    # COS-196: Р¶РёРІРѕР№ execution-РєРѕРЅС‚СѓСЂ РґРѕСЃС‚СѓРїРµРЅ (РёРЅР°С‡Рµ С‡РµСЃС‚РЅС‹Р№ 503).
    exec_service = AsyncMock()
    mock_request = MagicMock()
    mock_request.app.state.execution_service = exec_service

    principal = PrincipalContext(
        user_id="dev_user",
        domain_id="dom-kits",
        roles=[CBRRole.DEVELOPER],
        is_authenticated=True,
    )

    # 1. Trigger Build вЂ” Р·Р° С‚СЂРёРіРіРµСЂРѕРј СЂРµР°Р»СЊРЅС‹Р№ РїСЂРѕРіРѕРЅ (runs-РєРѕРЅС‚СѓСЂ, COS-196)
    req = TriggerBuildRequest(
        commit_sha="a1b2c3d4e5f6",
        branch="feature/payments",
        meta={"dockerfile": "Dockerfile.hardened"},
    )

    created = await trigger_app_build(
        app_id="app-auth",
        body=req,
        request=mock_request,
        principal=principal,
        db=mock_db,
    )

    assert created.app_id == "app-auth"
    assert created.domain_id == "dom-kits"
    assert created.commit_sha == "a1b2c3d4e5f6"
    assert created.branch == "feature/payments"
    assert created.status == "running"
    assert created.run_id and created.run_id.startswith("run-bld-")
    assert created.meta["dockerfile"] == "Dockerfile.hardened"
    exec_service.submit_run.assert_awaited_once_with(created.run_id)

    # 2. List Builds Mock (meta Р±РµР· run_id в†’ СЂРµРєРѕРЅСЃРёР»СЊ РЅРµ С‚СЂРѕРіР°РµС‚)
    mock_bm = MagicMock(spec=BuildModel)
    mock_bm.id = created.id
    mock_bm.app_id = "app-auth"
    mock_bm.domain_id = "dom-kits"
    mock_bm.title = created.title
    mock_bm.commit_sha = "a1b2c3d4e5f6"
    mock_bm.branch = "feature/payments"
    mock_bm.status = "running"
    mock_bm.artifacts = created.artifacts
    mock_bm.started_at = created.started_at
    mock_bm.finished_at = None
    mock_bm.initiator_user_id = "dev_user"
    mock_bm.build_logs = "Logs"
    mock_bm.meta = {}

    mock_res = MagicMock()
    mock_res.scalars.return_value.all.return_value = [mock_bm]
    mock_db.execute = AsyncMock(return_value=mock_res)

    builds_list = await list_app_builds(
        app_id="app-auth",
        principal=principal,
        db=mock_db,
    )
    assert len(builds_list) == 1
    assert builds_list[0].id == created.id
    assert builds_list[0].title == created.title


@pytest.mark.asyncio
async def test_abort_build_endpoint():
    from cosmo.api.routes.builds import abort_build
    from orchestrator.cosmo.db.models import Build as BuildModel

    mock_db = AsyncMock()
    mock_bm = MagicMock(spec=BuildModel)
    mock_bm.id = "bld-to-abort"
    mock_bm.app_id = "app-auth"
    mock_bm.domain_id = "dom-kits"
    mock_bm.title = "Build app-auth@1234567"
    mock_bm.status = "running"
    mock_bm.build_logs = "Initial logs"
    mock_bm.commit_sha = "1234567"
    mock_bm.branch = "main"
    mock_bm.artifacts = []
    mock_bm.started_at = datetime.datetime.utcnow()
    mock_bm.finished_at = None
    mock_bm.initiator_user_id = "dev_user"
    mock_bm.meta = {}

    mock_db.get = AsyncMock(return_value=mock_bm)

    mock_request = MagicMock()
    mock_request.app.state.execution_service = None

    principal = PrincipalContext(
        user_id="dev_user",
        domain_id="dom-kits",
        roles=[CBRRole.DEVELOPER],
        is_authenticated=True,
    )

    aborted = await abort_build(
        build_id="bld-to-abort",
        request=mock_request,
        principal=principal,
        db=mock_db,
    )
    assert aborted.status == "aborted"
    assert mock_bm.status == "aborted"


# в•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђ
# 3. Deployments API Route Handlers Tests
# в•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђ

@pytest.mark.asyncio
async def test_create_and_rollback_deployment():
    from cosmo.api.routes.deployments import (
        CreateDeploymentRequest,
        RollbackDeploymentRequest,
        create_deployment,
        rollback_deployment,
    )
    from orchestrator.cosmo.db.models import Application as ApplicationModel, Build as BuildModel, Deployment as DeploymentModel

    mock_db = AsyncMock()
    mock_app = MagicMock(spec=ApplicationModel)
    mock_app.id = "app-billing"
    mock_app.name = "billing-service"
    mock_app.domain_id = "dom-banking"

    mock_build = MagicMock(spec=BuildModel)
    mock_build.id = "bld-billing-01"
    mock_build.app_id = "app-billing"
    mock_build.domain_id = "dom-banking"

    def mock_get_entity(model_cls, pk):
        if model_cls == ApplicationModel:
            return mock_app
        elif model_cls == BuildModel:
            return mock_build
        return None

    mock_db.get = AsyncMock(side_effect=mock_get_entity)

    principal = PrincipalContext(
        user_id="ops_lead",
        domain_id="dom-banking",
        roles=[CBRRole.RELEASE_MANAGER],
        is_authenticated=True,
    )

    # 1. Create Deployment in Р—Рў (Testing Zone)
    dep_req = CreateDeploymentRequest(
        build_id="bld-billing-01",
        target_zone="zt",
        segment="integration",
        env_vars={"ENV": "test", "PORT": "8080"},
    )

    created_dep = await create_deployment(
        app_id="app-billing",
        body=dep_req,
        principal=principal,
        db=mock_db,
    )

    assert created_dep.app_id == "app-billing"
    assert created_dep.target_zone == "zt"
    assert created_dep.segment == "integration"
    assert created_dep.status == "declarative"
    assert created_dep.finished_at is None  # РЅРµ РІС‹РґР°С‘Рј РјРіРЅРѕРІРµРЅРЅС‹Р№ success/РІС‹РґСѓРјР°РЅРЅС‹Р№ С„РёРЅРёС€
    assert created_dep.custom_url is None   # endpoint РЅРµ РІС‹РґСѓРјС‹РІР°РµС‚СЃСЏ
    assert created_dep.operator_id == "ops_lead"

    # 2. Rollback Deployment Mock
    mock_dep = MagicMock(spec=DeploymentModel)
    mock_dep.id = created_dep.id
    mock_dep.app_id = "app-billing"
    mock_dep.domain_id = "dom-banking"
    mock_dep.build_id = "bld-billing-01"
    mock_dep.target_zone = "zt"
    mock_dep.segment = "integration"
    mock_dep.status = "success"
    mock_dep.custom_url = created_dep.custom_url
    mock_dep.operator_id = "ops_lead"
    mock_dep.env_vars = {}
    mock_dep.release_id = None
    mock_dep.rollback_from_id = None
    mock_dep.started_at = datetime.datetime.utcnow()
    mock_dep.finished_at = datetime.datetime.utcnow()

    mock_db.get = AsyncMock(return_value=mock_dep)
    mock_prev_res = MagicMock()
    mock_prev_res.scalar_one_or_none.return_value = None
    mock_db.execute = AsyncMock(return_value=mock_prev_res)

    rb_req = RollbackDeploymentRequest(reason="Performance regression detected")
    rb_dep = await rollback_deployment(
        id=created_dep.id,
        body=rb_req,
        principal=principal,
        db=mock_db,
    )

    assert rb_dep.rollback_from_id == created_dep.id
    assert mock_dep.status == "rollback"
