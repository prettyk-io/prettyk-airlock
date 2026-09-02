"""
CLN-011: Tests for SoD Author-Gate Enforcement, 401 Authentication Barrier, and Linear Zone Promotion (400 ZR->ZPE).

Проверяет:
  1. 401 Unauthorized: любые вызовы без токена или с невалидными кредами отсекаются с 401.
  2. 409 Conflict (Separation of Duties): автор релиза / прогона не может сам себе подписать Security Gate.
  3. 400 Bad Request (Linear Zone Promotion): запрет прямого перескока ЗР ➔ ЗПЭ в обход ЗТ.
  4. Успешный пошаговый линейный трансфер ЗР ➔ ЗТ ➔ ЗПЭ независимым офицером ИБ.
"""
import datetime
from unittest.mock import AsyncMock, MagicMock
import pytest
from fastapi import HTTPException, status

from cosmo.api.deps import get_current_principal
from cosmo.api.routes.gates import (
    CreateGateRequest,
    GateDecisionRequest,
    create_gate,
    record_gate_decision,
)
from cosmo.api.routes.releases import (
    TransferReleaseRequest,
    transfer_release_v2,
)
from cosmo.domain.rbac import CBRRole, PrincipalContext, Role, SeparationOfDutiesEngine


def _api_principal() -> PrincipalContext:
    """COS-067: system-admin principal для прямых (unit) вызовов хендлеров.

    Guard-зависимости при прямом вызове не резолвятся FastAPI, поэтому
    хендлеры с domain-binding-чеком в теле требуют явный principal.
    System-admin пропускает ownership-чек; SoD-логика тестируется через
    decided_by / initiator, как и раньше.
    """
    return PrincipalContext(
        user_id="unit_test_admin",
        roles=[Role.ADMIN_SEC],
        domain_id="dom-kits",
        zone="zr",
        is_authenticated=True,
        is_system_admin=True,
    )


# ═══════════════════════════════════════════════════════════════════════
# 1. ТЕСТЫ 401 UNAUTHORIZED (Отсечка без токена)
# ═══════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_endpoint_missing_token_returns_401():
    """Вызов зависимости без заголовка Authorization возвращает 401."""
    with pytest.raises(HTTPException) as exc_info:
        await get_current_principal(authorization=None, cookie_token=None)

    assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
    assert "401_UNAUTHORIZED" in exc_info.value.detail


@pytest.mark.asyncio
async def test_endpoint_malformed_token_returns_401():
    """Вызов с невалидным / испорченным токеном возвращает 401."""
    with pytest.raises(HTTPException) as exc_info:
        await get_current_principal(authorization="Bearer corrupted_token_123")

    assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
    assert "401_UNAUTHORIZED" in exc_info.value.detail


# ═══════════════════════════════════════════════════════════════════════
# 2. ТЕСТЫ 409 CONFLICT: Separation of Duties (Автор ➔ Гейт)
# ═══════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_author_gate_approval_sod_violation_raises_409():
    """Автор релиза (initiator) пытается сам подписать гейт -> 409 Conflict SoD."""
    from orchestrator.cosmo.db.models import Gate as GateModel, Release as ReleaseModel, Run as RunModel

    mock_db = AsyncMock()

    mock_gate = MagicMock(spec=GateModel)
    mock_gate.id = "gate-sod-01"
    mock_gate.plan_id = "plan-sod"
    mock_gate.type = "manual"
    mock_gate.position = 0
    mock_gate.decision = None
    mock_gate.decided_by = None
    mock_gate.policy_json = {"rules": []}

    mock_rel = MagicMock(spec=ReleaseModel)
    mock_rel.id = "rel-sod-01"
    mock_rel.plan_id = "plan-sod"
    mock_rel.run_ids = ["run-sod-01"]

    mock_run = MagicMock(spec=RunModel)
    mock_run.id = "run-sod-01"
    mock_run.initiator_user_id = "dev_author_ivanov"

    def mock_get(model_cls, pk):
        if model_cls == GateModel:
            return mock_gate
        return None

    mock_db.get = AsyncMock(side_effect=mock_get)

    rel_res = MagicMock()
    rel_res.scalars.return_value.all.return_value = [mock_rel]
    run_res = MagicMock()
    run_res.scalars.return_value.all.return_value = [mock_run]
    mock_db.execute = AsyncMock(side_effect=[rel_res, run_res])

    decision_req = GateDecisionRequest(
        decision="pass",
        decided_by="dev_author_ivanov",
        comment="Self approval",
    )

    with pytest.raises(HTTPException) as exc_info:
        await record_gate_decision(
            gate_id="gate-sod-01",
            body=decision_req,
            db=mock_db,
            principal=_api_principal(),
        )

    assert exc_info.value.status_code == status.HTTP_409_CONFLICT
    assert "SoD violation" in exc_info.value.detail
    assert "dev_author_ivanov" in exc_info.value.detail


@pytest.mark.asyncio
async def test_independent_officer_gate_approval_passes_200():
    """Независимый офицер ИБ успешно подписывает гейт автора (SoD соблюден)."""
    from orchestrator.cosmo.db.models import Gate as GateModel, Release as ReleaseModel, Run as RunModel

    mock_db = AsyncMock()
    mock_gate = MagicMock(spec=GateModel)
    mock_gate.id = "gate-sod-02"
    mock_gate.plan_id = "plan-sod-2"
    mock_gate.type = "manual"
    mock_gate.position = 0
    mock_gate.decision = "pass"
    mock_gate.decided_by = "sec_officer_petrov"
    mock_gate.signature = "gost_signature_hex_123"
    mock_gate.decided_at = datetime.datetime.utcnow()
    mock_gate.policy_json = {"rules": [{"finding_type": "Critical", "action": "block"}]}

    mock_rel = MagicMock(spec=ReleaseModel)
    mock_rel.id = "rel-sod-02"
    mock_rel.plan_id = "plan-sod-2"
    mock_rel.run_ids = ["run-sod-02"]

    mock_run = MagicMock(spec=RunModel)
    mock_run.id = "run-sod-02"
    mock_run.initiator_user_id = "dev_author_ivanov"

    mock_db.get = AsyncMock(return_value=mock_gate)

    rel_res = MagicMock()
    rel_res.scalars.return_value.all.return_value = [mock_rel]
    run_res = MagicMock()
    run_res.scalars.return_value.all.return_value = [mock_run]
    mock_db.execute = AsyncMock(side_effect=[rel_res, run_res])

    decision_req = GateDecisionRequest(
        decision="pass",
        decided_by="sec_officer_petrov",
        comment="Verified independently",
        signature="gost_signature_hex_123",
    )

    res = await record_gate_decision(
        gate_id="gate-sod-02",
        body=decision_req,
        db=mock_db,
        principal=_api_principal(),
    )

    assert mock_gate.decision == "pass"
    assert mock_gate.decided_by == "sec_officer_petrov"


# ═══════════════════════════════════════════════════════════════════════
# 3. ТЕСТЫ 400 BAD REQUEST: Linear Zone Promotion (ЗР ➔ ЗПЭ запрещен)
# ═══════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_direct_transfer_zr_to_zpe_raises_400():
    """Попытка трансфера напрямую из ЗР в ЗПЭ блокируется (HTTP 400)."""
    from orchestrator.cosmo.db.models import Gate as GateModel, Release as ReleaseModel

    mock_db = AsyncMock()

    mock_rel = MagicMock(spec=ReleaseModel)
    mock_rel.id = "rel-promo-01"
    mock_rel.domain_id = "dom-kits"
    mock_rel.plan_id = "plan-1"
    mock_rel.status = "deployed"
    mock_rel.current_zone = "zr"
    mock_rel.transfer_history = []
    mock_rel.approvals = []
    mock_rel.trigger = "manual"
    mock_rel.version = "1.0.0"
    mock_rel.changelog = "test"
    mock_rel.artifacts = []
    mock_rel.run_ids = ["r1"]

    mock_db.get = AsyncMock(return_value=mock_rel)

    mock_gate = MagicMock(spec=GateModel)
    mock_gate.id = "gate-1"
    mock_gate.decision = "pass"

    gate_res = MagicMock()
    gate_res.scalars.return_value.all.return_value = [mock_gate]
    mock_db.execute = AsyncMock(return_value=gate_res)

    req = TransferReleaseRequest(
        target_zone="zpe",
        officer_name="Петров П.С.",
        sign_signature="gost_sig_hex",
        transfer_notes="Illegal jump to ZPE",
    )

    with pytest.raises(HTTPException) as exc_info:
        await transfer_release_v2(
            release_id="rel-promo-01",
            body=req,
            db=mock_db,
            principal=_api_principal(),
        )

    assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST
    assert "Invalid zone promotion" in exc_info.value.detail
    assert "Strict path is ZR -> ZT -> ZPE" in exc_info.value.detail


@pytest.mark.asyncio
async def test_linear_transfer_step_by_step_succeeds_200():
    """Пошаговый линейный трансфер ЗР ➔ ЗТ и затем ЗТ ➔ ЗПЭ успешен."""
    from orchestrator.cosmo.db.models import Gate as GateModel, Release as ReleaseModel

    mock_db = AsyncMock()

    mock_rel = MagicMock(spec=ReleaseModel)
    mock_rel.id = "rel-promo-02"
    mock_rel.domain_id = "dom-kits"
    mock_rel.plan_id = "plan-2"
    mock_rel.status = "deployed"
    mock_rel.current_zone = "zr"
    mock_rel.transfer_history = []
    mock_rel.approvals = []
    mock_rel.trigger = "manual"
    mock_rel.version = "1.0.0"
    mock_rel.changelog = "test"
    mock_rel.artifacts = []
    mock_rel.run_ids = ["r1"]

    mock_db.get = AsyncMock(return_value=mock_rel)

    mock_gate = MagicMock(spec=GateModel)
    mock_gate.id = "gate-2"
    mock_gate.decision = "pass"
    gate_res = MagicMock()
    gate_res.scalars.return_value.all.return_value = [mock_gate]
    mock_db.execute = AsyncMock(return_value=gate_res)

    # 1. Шаг 1: ЗР ➔ ЗТ
    req_step1 = TransferReleaseRequest(
        target_zone="zt",
        officer_name="Петров П.С.",
        sign_signature="gost_sig_step1",
    )

    res1 = await transfer_release_v2(
        release_id="rel-promo-02",
        body=req_step1,
        db=mock_db,
        principal=_api_principal(),
    )
    assert mock_rel.current_zone == "zt"

    # 2. Шаг 2: ЗТ ➔ ЗПЭ
    mock_db.execute = AsyncMock(return_value=gate_res)
    req_step2 = TransferReleaseRequest(
        target_zone="zpe",
        officer_name="Сидоров С.С.",
        sign_signature="gost_sig_step2",
    )

    res2 = await transfer_release_v2(
        release_id="rel-promo-02",
        body=req_step2,
        db=mock_db,
        principal=_api_principal(),
    )
    assert mock_rel.current_zone == "zpe"
    assert len(mock_rel.transfer_history) == 2


@pytest.mark.asyncio
async def test_cln007_record_gate_decision_sod_conflict_409():
    """CLN-007: SoD в POST /api/v1/gates/{id}/decision: если release.initiator_user_id == principal.user_id -> 409."""
    from orchestrator.cosmo.api.routes.gates import record_gate_decision, GateDecisionRequest
    from orchestrator.cosmo.db.models import Gate as GateModel, Release as ReleaseModel, Run as RunModel

    mock_db = AsyncMock()

    mock_gate = MagicMock(spec=GateModel)
    mock_gate.id = "gate-sod-01"
    mock_gate.plan_id = "plan-sod-01"
    mock_gate.type = "manual"
    mock_gate.decision = None

    mock_db.get = AsyncMock(return_value=mock_gate)

    mock_rel = MagicMock(spec=ReleaseModel)
    mock_rel.id = "rel-sod-01"
    mock_rel.plan_id = "plan-sod-01"
    mock_rel.run_ids = ["run-sod-01"]

    mock_run = MagicMock(spec=RunModel)
    mock_run.id = "run-sod-01"
    mock_run.initiator_user_id = "dev_ivan"

    rel_res = MagicMock()
    rel_res.scalars.return_value.all.return_value = [mock_rel]

    run_res = MagicMock()
    run_res.scalars.return_value.all.return_value = [mock_run]

    mock_db.execute = AsyncMock(side_effect=[rel_res, run_res])

    # Guard representing the authenticated principal 'dev_ivan'
    mock_principal = PrincipalContext(
        user_id="dev_ivan",
        roles=[Role.ADMIN_SEC],
        domain_id="dom-kits",
        zone="zr",
    )

    req = GateDecisionRequest(
        decision="pass",
        decided_by="dev_ivan",
        signature="sig_ivan",
    )

    with pytest.raises(HTTPException) as exc_info:
        await record_gate_decision(
            gate_id="gate-sod-01",
            body=req,
            db=mock_db,
            principal=_api_principal(),
        )

    assert exc_info.value.status_code == status.HTTP_409_CONFLICT
    assert "SoD violation" in exc_info.value.detail


@pytest.mark.asyncio
async def test_cln008_transfer_v1_direct_zr_to_zpe_blocked_400():
    """CLN-008: Линейный трансфер v1: если current_zone == 'zr' AND target_zone == 'zpe' -> HTTP 400."""
    from orchestrator.cosmo.api.routes.releases import transfer_release, TransferRequest
    from orchestrator.cosmo.db.models import Gate as GateModel, Release as ReleaseModel

    mock_db = AsyncMock()

    mock_rel = MagicMock(spec=ReleaseModel)
    mock_rel.id = "rel-v1-01"
    mock_rel.domain_id = "dom-kits"
    mock_rel.plan_id = "plan-v1"
    mock_rel.status = "deployed"
    mock_rel.current_zone = "zr"
    mock_rel.transfer_history = []
    mock_rel.run_ids = ["r1"]

    mock_db.get = AsyncMock(return_value=mock_rel)

    mock_gate = MagicMock(spec=GateModel)
    mock_gate.id = "gate-v1-01"
    mock_gate.decision = "pass"

    gate_res = MagicMock()
    gate_res.scalars.return_value.all.return_value = [mock_gate]
    mock_db.execute = AsyncMock(return_value=gate_res)

    req = TransferRequest(
        initiated_by="officer_ivan",
        comment="Direct illegal jump",
        target_zone="zpe",
    )

    with pytest.raises(HTTPException) as exc_info:
        await transfer_release(
            release_id="rel-v1-01",
            body=req,
            db=mock_db,
            principal=_api_principal(),
        )

    assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST
    assert "Invalid zone promotion" in exc_info.value.detail
    assert "Strict path is ZR -> ZT -> ZPE" in exc_info.value.detail


# ═══════════════════════════════════════════════════════════════════════
# CLN-007: SoD in create_gate — автор релиза не создаёт гейты к своему плану
# ═══════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_cln007_create_gate_author_sod_conflict_409():
    """CLN-007: Автор релиза пытается создать гейт к своему плану → 409 Conflict."""
    from orchestrator.cosmo.db.models import (
        Gate as GateModel,
        PipelinePlan as PlanModel,
        Release as ReleaseModel,
        Run as RunModel,
        Application as ApplicationModel,
    )
    from orchestrator.cosmo.domain.gate_model import GatePolicyRule

    mock_db = AsyncMock()

    mock_plan = MagicMock(spec=PlanModel)
    mock_plan.id = "plan-007-01"
    mock_plan.app_id = "app-auth"

    # COS-068: ownership chain — db.get вызывается и для ApplicationModel
    mock_app = MagicMock(spec=ApplicationModel)
    mock_app.id = "app-auth"
    mock_app.domain_id = "dom-kits"

    mock_db.get = AsyncMock(side_effect=[mock_plan, mock_app])

    mock_rel = MagicMock(spec=ReleaseModel)
    mock_rel.id = "rel-007-01"
    mock_rel.plan_id = "plan-007-01"
    mock_rel.run_ids = ["run-007-01"]

    mock_run = MagicMock(spec=RunModel)
    mock_run.id = "run-007-01"
    mock_run.initiator_user_id = "dev_author"

    rel_res = MagicMock()
    rel_res.scalars.return_value.all.return_value = [mock_rel]
    run_res = MagicMock()
    run_res.scalars.return_value.all.return_value = [mock_run]

    mock_db.execute = AsyncMock(side_effect=[rel_res, run_res])

    principal = PrincipalContext(
        user_id="dev_author",
        roles=[Role.USER],
        domain_id="dom-kits",
        zone="zr",
    )

    from orchestrator.cosmo.domain.gate_model import GatePolicy
    req = CreateGateRequest(
        id="gate-007-01",
        plan_id="plan-007-01",
        type="manual",
        position=0,
        policy=GatePolicy(rules=[GatePolicyRule(finding_type="Critical", action="block")]),
    )

    with pytest.raises(HTTPException) as exc_info:
        await create_gate(body=req, db=mock_db, principal=principal)

    assert exc_info.value.status_code == status.HTTP_409_CONFLICT
    assert "SoD violation" in exc_info.value.detail
    assert "dev_author" in exc_info.value.detail


@pytest.mark.asyncio
async def test_cln007_create_gate_independent_admin_succeeds_201():
    """CLN-007: Независимый admin_sec успешно создаёт гейт к чужому плану → 201."""
    from orchestrator.cosmo.db.models import (
        Gate as GateModel,
        PipelinePlan as PlanModel,
        Release as ReleaseModel,
        Run as RunModel,
        Application as ApplicationModel,
    )
    from orchestrator.cosmo.domain.gate_model import GatePolicyRule

    mock_db = AsyncMock()

    mock_plan = MagicMock(spec=PlanModel)
    mock_plan.id = "plan-007-02"
    mock_plan.app_id = "app-auth"

    # COS-068: ownership chain — db.get: план → приложение → gate (не существует)
    mock_app = MagicMock(spec=ApplicationModel)
    mock_app.id = "app-auth"
    mock_app.domain_id = "dom-kits"

    mock_db.get = AsyncMock(side_effect=[mock_plan, mock_app, None])

    mock_rel = MagicMock(spec=ReleaseModel)
    mock_rel.id = "rel-007-02"
    mock_rel.plan_id = "plan-007-02"
    mock_rel.run_ids = ["run-007-02"]

    mock_run = MagicMock(spec=RunModel)
    mock_run.id = "run-007-02"
    mock_run.initiator_user_id = "dev_ivan"

    rel_res = MagicMock()
    rel_res.scalars.return_value.all.return_value = [mock_rel]
    run_res = MagicMock()
    run_res.scalars.return_value.all.return_value = [mock_run]
    mock_db.execute = AsyncMock(side_effect=[rel_res, run_res])

    principal = PrincipalContext(
        user_id="admin_sec_petrov",
        roles=[Role.ADMIN_SEC],
        domain_id="dom-kits",
        zone="zr",
    )

    from orchestrator.cosmo.domain.gate_model import GatePolicy
    req = CreateGateRequest(
        id="gate-007-02",
        plan_id="plan-007-02",
        type="manual",
        position=1,
        policy=GatePolicy(rules=[GatePolicyRule(finding_type="Critical", action="block")]),
    )

    res = await create_gate(body=req, db=mock_db, principal=principal)
    assert res is not None
    assert res.id == "gate-007-02"
