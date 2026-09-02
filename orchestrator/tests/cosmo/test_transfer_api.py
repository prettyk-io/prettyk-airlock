# -*- coding: utf-8 -*-
"""COS-058: Transfer API Boundary — integration tests (FastAPI test client).

Покрывает acceptance:
  1. create/get plan + items + correlation (multi-plane, skeleton_context).
  2. Validation endpoint — детальный результат, не boolean.
  3. Bootstrap невозможен до verified + landing_approved.
  4. Invalid transition — стабильная ошибка без смены состояния.
  5. CHECKSUM_MISMATCH ≠ DUPLICATE_REVISION — разные ошибки.
  6. Recoverable bootstrap failure → recovery info → retry.
  7. Неавторизованный не видит чужой план (404, не раскрытие существования).
  8. Мутации защищены release:transfer capability.
  9. Нет SOD-specific lifecycle значений в контракте.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_orch = Path(__file__).resolve().parents[1]
if str(_orch) not in sys.path:
    sys.path.insert(0, str(_orch))

pytestmark = pytest.mark.asyncio

from orchestrator.cosmo.api.deps import get_current_principal
from orchestrator.cosmo.api.main import app
from orchestrator.cosmo.api.routes.transfer import get_transfer_repository
from orchestrator.cosmo.domain.rbac import (
    Action,
    DomainRBAC,
    DomainMember,
    PrincipalContext,
    Role,
)
from orchestrator.cosmo.transfer.contract import (
    PackageRevision,
    TransferItemStatus,
    TransferPlanStatus,
)
from orchestrator.cosmo.transfer.landing import LandingState
from orchestrator.cosmo.transfer.registry import get_transfer_registry

BASE = "/api/v1/transfer"


@pytest.fixture(autouse=True)
def _clean_registry():
    """Изоляция in-memory registry между тестами.

    COS-077: боевой путь transfer API — durable PG-репозиторий; hermetic-тесты
    явно подменяют dependency на in-memory registry (PG не затрагивается)."""
    app.dependency_overrides[get_transfer_repository] = get_transfer_registry
    get_transfer_registry().reset()
    yield
    app.dependency_overrides.pop(get_transfer_repository, None)
    get_transfer_registry().reset()


# ── helpers ──────────────────────────────────────────────────────────

def _manifest(release_id: str, revision: int = 1, tag: str = "base") -> dict:
    return {"release_id": release_id, "revision": revision, "tag": tag}


def _plan_payload(
    plan_id: str = "plan-cos58-1",
    release_id: str = "rel-cos58",
    item_id: str = "item-cos58-1",
    revision: int = 1,
    manifest: dict | None = None,
    package_mode: str = "metadata_envelope",
    artifact_plane: str = "metadata_envelope",
    payload_refs: list | None = None,
    source_ref: str = "git::gitea/acme/app@main",
) -> dict:
    if manifest is None:
        manifest = _manifest(release_id, revision)
    return {
        "plan_id": plan_id,
        "release_id": release_id,
        "correlation_id": "corr-cos58-001",
        "source_zone": "zr",
        "target_zone": "zt",
        "items": [
            {
                "item_id": item_id,
                "artifact_plane": artifact_plane,
                "package_mode": package_mode,
                "transport_profile": "direct_authenticated_api",
                "source_ref": source_ref,
                "target_ref": "sod-bridge://inbox/app",
                "manifest": manifest,
                "payload_refs": payload_refs or [],
                "revision": revision,
            }
        ],
    }


async def _create_plan(client, payload: dict) -> dict:
    r = await client.post(f"{BASE}/plans", json=payload)
    assert r.status_code == 201, r.text
    return r.json()


async def _drive_to_imported(client, item_id: str) -> None:
    for transition in ("receive", "verify", "approve_landing", "import"):
        r = await client.post(f"{BASE}/items/{item_id}/landing/{transition}")
        assert r.status_code == 200, f"{transition}: {r.text}"


# ── 1. Plan contract: create/get/items/correlation ───────────────────

class TestTransferPlanContract:

    async def test_create_get_plan_and_correlation(self, pg_client):
        payload = _plan_payload()
        body = await _create_plan(pg_client, payload)

        plan = body["plan"]
        assert plan["plan_id"] == "plan-cos58-1"
        assert plan["release_id"] == "rel-cos58"
        assert plan["correlation_id"] == "corr-cos58-001"
        assert plan["status"] == "draft"
        assert plan["source_zone"] == "zr"
        assert plan["target_zone"] == "zt"

        item = plan["items"][0]
        expected_sha = PackageRevision.compute_manifest_sha256(payload["items"][0]["manifest"])
        assert item["package_revision"]["manifest_sha256"] == expected_sha
        assert item["package_revision"]["revision"] == 1
        assert item["status"] == "draft"
        assert body["landing"]["item-cos58-1"] == "not_received"

        r = await pg_client.get(f"{BASE}/plans/plan-cos58-1")
        assert r.status_code == 200
        assert r.json()["plan"]["plan_id"] == "plan-cos58-1"

        r = await pg_client.get(f"{BASE}/plans/plan-cos58-1/items")
        assert r.status_code == 200
        assert len(r.json()) == 1

        # Correlation: release_id → plans, correlation_id preserved
        r = await pg_client.get(f"{BASE}/releases/rel-cos58/plans")
        assert r.status_code == 200
        plans = r.json()
        assert len(plans) == 1
        assert plans[0]["plan"]["correlation_id"] == "corr-cos58-001"

    async def test_create_multi_plane_plan_with_skeleton(self, pg_client):
        """Один release → несколько planes; metadata-only ≠ deployable."""
        payload = _plan_payload(plan_id="plan-multi", item_id="item-meta")
        payload["items"].append({
            "item_id": "item-skel",
            "artifact_plane": "sbom",
            "package_mode": "skeleton_context",
            "transport_profile": "one_way_diode_relay",
            "source_ref": "git::gitea/acme/app@main",
            "target_ref": "diode://zt/inbox",
            "manifest": _manifest("rel-cos58", 1, "skel"),
            "payload_refs": [],
            "revision": 1,
        })
        body = await _create_plan(pg_client, payload)

        items = body["plan"]["items"]
        assert len(items) == 2
        planes = {i["artifact_plane"] for i in items}
        assert planes == {"metadata_envelope", "sbom"}
        modes = {i["item_id"]: i["package_mode"] for i in items}
        assert modes["item-meta"] == "metadata_envelope"
        assert modes["item-skel"] == "skeleton_context"
        assert set(body["landing"].values()) == {"not_received"}

        r = await pg_client.get(f"{BASE}/plans/plan-multi/items")
        assert r.status_code == 200
        assert len(r.json()) == 2

    async def test_get_item_with_landing_report(self, pg_client):
        await _create_plan(pg_client, _plan_payload())
        r = await pg_client.get(f"{BASE}/items/item-cos58-1")
        assert r.status_code == 200
        body = r.json()
        assert body["item"]["item_id"] == "item-cos58-1"
        assert body["landing"]["state"] == "not_received"
        assert body["landing"]["passed"] is False

    async def test_unknown_plan_error_contract(self, pg_client):
        r = await pg_client.get(f"{BASE}/plans/plan-unknown")
        assert r.status_code == 404
        err = r.json()["error"]
        assert err["code"] == "NOT_FOUND"
        assert "message" in err and "details" in err

    async def test_duplicate_plan_id_conflict(self, pg_client):
        await _create_plan(pg_client, _plan_payload())
        r = await pg_client.post(f"{BASE}/plans", json=_plan_payload())
        assert r.status_code == 409
        assert r.json()["error"]["code"] == "CONFLICT"


# ── 2. Validation: detailed result, не boolean ───────────────────────

class TestValidationEndpoint:

    async def test_validation_pass_updates_status(self, pg_client):
        await _create_plan(pg_client, _plan_payload())
        r = await pg_client.post(f"{BASE}/items/item-cos58-1/validate")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["passed"] is True
        assert body["status"] == "validated"
        assert body["error_codes"] == []

    async def test_validation_failure_detailed_not_boolean(self, pg_client):
        # full_package без payload_refs и без source_ref → две issues
        payload = _plan_payload(
            plan_id="plan-bad", item_id="item-bad",
            package_mode="full_package", source_ref="",
        )
        await _create_plan(pg_client, payload)
        r = await pg_client.post(f"{BASE}/items/item-bad/validate")
        assert r.status_code == 422
        err = r.json()["error"]
        assert err["code"] == "VALIDATION_FAILURE"
        details = err["details"]
        assert "FULL_PACKAGE_NO_PAYLOAD" in details["error_codes"]
        assert "SOURCE_REF_MISSING" in details["error_codes"]
        for issue in details["issues"]:
            assert set(issue) >= {"code", "message", "failure_class"}
        # Статус item не изменён отказом валидации
        r = await pg_client.get(f"{BASE}/items/item-bad")
        assert r.json()["item"]["status"] == "draft"


# ── 3+4. Landing invariants ──────────────────────────────────────────

class TestLandingInvariants:

    async def test_bootstrap_blocked_before_verified_and_approved(self, pg_client):
        await _create_plan(pg_client, _plan_payload())

        r = await pg_client.post(f"{BASE}/items/item-cos58-1/landing/receive")
        assert r.status_code == 200

        # bootstrap из received → запрещён (нужны verified + landing_approved)
        r = await pg_client.post(f"{BASE}/items/item-cos58-1/landing/bootstrap")
        assert r.status_code == 409
        assert r.json()["error"]["code"] == "INVALID_TRANSITION"

        r = await pg_client.post(f"{BASE}/items/item-cos58-1/landing/verify")
        assert r.status_code == 200

        # bootstrap из verified → запрещён (нет landing_approved)
        r = await pg_client.post(f"{BASE}/items/item-cos58-1/landing/bootstrap")
        assert r.status_code == 409

        r = await pg_client.post(f"{BASE}/items/item-cos58-1/landing/approve_landing")
        assert r.status_code == 200

        # bootstrap из landing_approved → запрещён (нужен import)
        r = await pg_client.post(f"{BASE}/items/item-cos58-1/landing/bootstrap")
        assert r.status_code == 409

        # И только import → bootstrap возможен
        r = await pg_client.post(f"{BASE}/items/item-cos58-1/landing/import")
        assert r.status_code == 200
        r = await pg_client.post(f"{BASE}/items/item-cos58-1/landing/bootstrap")
        assert r.status_code == 200
        assert r.json()["state"] == "bootstrapped"

    async def test_invalid_transition_stable_error_no_state_change(self, pg_client):
        await _create_plan(pg_client, _plan_payload())

        r = await pg_client.post(f"{BASE}/items/item-cos58-1/landing/bootstrap")
        assert r.status_code == 409
        err = r.json()["error"]
        assert err["code"] == "INVALID_TRANSITION"
        assert err["details"]["from_state"] == "not_received"
        assert err["details"]["to_state"] == "bootstrapped"

        # Состояние не изменилось
        r = await pg_client.get(f"{BASE}/items/item-cos58-1/landing")
        assert r.json()["state"] == "not_received"
        r = await pg_client.get(f"{BASE}/plans/plan-cos58-1")
        assert r.json()["plan"]["status"] == "draft"
        r = await pg_client.get(f"{BASE}/items/item-cos58-1")
        assert r.json()["item"]["status"] == "draft"

    async def test_full_landing_lifecycle_to_reconciled(self, pg_client):
        await _create_plan(pg_client, _plan_payload())
        r = await pg_client.post(f"{BASE}/items/item-cos58-1/validate")
        assert r.status_code == 200

        await _drive_to_imported(pg_client, "item-cos58-1")
        r = await pg_client.post(f"{BASE}/items/item-cos58-1/landing/bootstrap")
        assert r.status_code == 200
        r = await pg_client.post(f"{BASE}/items/item-cos58-1/landing/reconcile")
        assert r.status_code == 200
        body = r.json()
        assert body["state"] == "reconciled"
        assert body["passed"] is True

        # Plan completed; item reconciled; correlation intact
        r = await pg_client.get(f"{BASE}/plans/plan-cos58-1")
        assert r.json()["plan"]["status"] == "completed"
        r = await pg_client.get(f"{BASE}/items/item-cos58-1")
        assert r.json()["item"]["status"] == "reconciled"
        r = await pg_client.get(f"{BASE}/releases/rel-cos58/plans")
        assert r.json()[0]["plan"]["correlation_id"] == "corr-cos58-001"


# ── 5. CHECKSUM_MISMATCH ≠ DUPLICATE_REVISION ────────────────────────

class TestChecksumVsDuplicate:

    async def test_checksum_mismatch_distinct_from_duplicate_revision(self, pg_client):
        await _create_plan(pg_client, _plan_payload())
        r = await pg_client.post(f"{BASE}/items/item-cos58-1/landing/receive")
        assert r.status_code == 200

        # Tampered delivery → checksum mismatch (состояние фиксируется kernel'ом)
        tampered = _manifest("rel-cos58", 1, tag="tampered")
        r = await pg_client.post(
            f"{BASE}/items/item-cos58-1/landing/verify",
            json={"incoming_manifest": tampered},
        )
        assert r.status_code == 409
        err = r.json()["error"]
        assert err["code"] == "CHECKSUM_MISMATCH"
        assert err["details"]["requires_new_revision"] is True

        r = await pg_client.get(f"{BASE}/items/item-cos58-1/landing")
        assert r.json()["state"] == "checksum_mismatch"
        r = await pg_client.get(f"{BASE}/items/item-cos58-1/recovery")
        assert r.json()["requires_new_revision"] is True
        assert r.json()["recoverable"] is False

        # Повторный receive того же item → invalid transition (state machine)
        r = await pg_client.post(f"{BASE}/items/item-cos58-1/landing/receive")
        assert r.status_code == 409
        assert r.json()["error"]["code"] == "INVALID_TRANSITION"

        # Другой item с той же revision → DUPLICATE_REVISION (другая ошибка)
        other = _plan_payload(
            plan_id="plan-cos58-2", item_id="item-cos58-2", revision=1,
        )
        await _create_plan(pg_client, other)
        r = await pg_client.post(f"{BASE}/items/item-cos58-2/landing/receive")
        assert r.status_code == 409
        err2 = r.json()["error"]
        assert err2["code"] == "DUPLICATE_REVISION"
        assert err2["details"]["revision_key"] == "rel-cos58:1"
        assert err2["details"]["existing_item_id"] == "item-cos58-1"

        # Две разные ошибки — разные коды
        assert err["code"] != err2["code"]


# ── 6. Recoverable failure → recovery info → retry ───────────────────

class TestRecoverableFailure:

    async def test_recoverable_bootstrap_failure_and_retry(self, pg_client):
        await _create_plan(pg_client, _plan_payload())
        await _drive_to_imported(pg_client, "item-cos58-1")

        # Bootstrap упал (V1 simulate hook) → first-class failure state, не 409
        r = await pg_client.post(
            f"{BASE}/items/item-cos58-1/landing/bootstrap",
            json={"simulate": {"bootstrap_failure": True}, "reason": "target side failed"},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["state"] == "bootstrap_failure"
        assert body["recoverable"] is True
        assert body["requires_new_revision"] is False
        assert body["report"]["failure_class"] == "bootstrap_failure"

        # Recovery info
        r = await pg_client.get(f"{BASE}/items/item-cos58-1/recovery")
        rec = r.json()
        assert rec["state"] == "bootstrap_failure"
        assert rec["recoverable"] is True
        assert rec["retry_target"] == "imported"
        assert rec["revision_key"] == "rel-cos58:1"
        assert len(rec["history"]) >= 5

        # Retry → import → bootstrap → reconcile
        r = await pg_client.post(f"{BASE}/items/item-cos58-1/landing/retry")
        assert r.status_code == 200
        assert r.json()["state"] == "imported"

        r = await pg_client.post(f"{BASE}/items/item-cos58-1/landing/bootstrap")
        assert r.status_code == 200
        assert r.json()["state"] == "bootstrapped"

        r = await pg_client.post(f"{BASE}/items/item-cos58-1/landing/reconcile")
        assert r.status_code == 200
        assert r.json()["state"] == "reconciled"

        r = await pg_client.get(f"{BASE}/plans/plan-cos58-1")
        assert r.json()["plan"]["status"] == "completed"

    async def test_retry_from_non_failure_state_rejected(self, pg_client):
        await _create_plan(pg_client, _plan_payload())
        r = await pg_client.post(f"{BASE}/items/item-cos58-1/landing/retry")
        assert r.status_code == 409
        assert r.json()["error"]["code"] == "INVALID_TRANSITION"

    async def test_unknown_transition_404(self, pg_client):
        await _create_plan(pg_client, _plan_payload())
        r = await pg_client.post(f"{BASE}/items/item-cos58-1/landing/teleport")
        assert r.status_code == 404
        assert r.json()["error"]["code"] == "NOT_FOUND"


# ── 7+8. Auth / isolation ────────────────────────────────────────────

class TestAuthAndIsolation:

    async def test_unauthorized_cannot_see_foreign_plan(self, pg_client):
        # Админ создаёт план в домене alpha
        r = await pg_client.post(
            f"{BASE}/plans", json=_plan_payload(),
            headers={"X-Cosmo-Domain": "alpha"},
        )
        assert r.status_code == 201

        # Пользователь другого домена (не admin) — 404 без раскрытия существования
        async def _foreign_user() -> PrincipalContext:
            return PrincipalContext(
                user_id="outsider", roles=[Role.USER],
                domain_id="beta", zone="zr", is_system_admin=False,
            )
        app.dependency_overrides[get_current_principal] = _foreign_user

        r = await pg_client.get(f"{BASE}/plans/plan-cos58-1")
        assert r.status_code == 404
        assert r.json()["error"]["code"] == "NOT_FOUND"

        r = await pg_client.get(f"{BASE}/items/item-cos58-1")
        assert r.status_code == 404

        # Корреляция не утекает чужие планы
        r = await pg_client.get(f"{BASE}/releases/rel-cos58/plans")
        assert r.status_code == 200
        assert r.json() == []

    async def test_mutation_requires_release_transfer_capability(self, pg_client):
        """Guard объявлен и работает: RBAC deny для USER + честный 403 через HTTP."""
        # (a) Каноническая RBAC-проверка: Role.USER не имеет release:transfer
        rbac = DomainRBAC(
            domain_id="dom-1",
            members=[DomainMember(user_id="bob", role=Role.USER)],
        )
        principal = PrincipalContext(user_id="bob", roles=[Role.USER], domain_id="dom-1", zone="zr")
        ok, reason = rbac.evaluate(principal, Action.RELEASE_TRANSFER, target_zone="zr")
        assert not ok, "USER must not hold release:transfer"
        assert "403" in reason or "forbidden" in reason.lower()

        # ADMIN_SEC имеет release:transfer
        rbac_admin = DomainRBAC(
            domain_id="dom-1",
            members=[DomainMember(user_id="alice", role=Role.ADMIN_SEC)],
        )
        principal_admin = PrincipalContext(user_id="alice", roles=[Role.ADMIN_SEC], domain_id="dom-1", zone="zr")
        ok, _ = rbac_admin.evaluate(principal_admin, Action.RELEASE_TRANSFER, target_zone="zr")
        assert ok

        # (b) Честный 403 через HTTP: домен существует, роль USER,
        #     capability guard отклоняет мутацию до обработчика.
        r = await pg_client.post("/api/v1/domains", json={
            "id": "test",
            "label": "Test Domain",
            "forge_binding": {
                "forge_type": "gitea",
                "url": "https://gitea.example",
                "token_ref": "vault://cosmo/test",
            },
            "quota": {"max_runs": 10, "max_storage_gb": 100, "max_cpu": 4},
        })
        assert r.status_code == 201, r.text

        async def _plain_user() -> PrincipalContext:
            return PrincipalContext(
                user_id="plain", roles=[Role.USER],
                domain_id="test", zone="zr", is_system_admin=False,
            )
        app.dependency_overrides[get_current_principal] = _plain_user

        r = await pg_client.post(
            f"{BASE}/plans", json=_plan_payload(),
            headers={"X-Cosmo-Domain": "test"},
        )
        assert r.status_code == 403, r.text
        assert "release:transfer" in r.json()["detail"] or "forbidden" in r.json()["detail"].lower()

        # (c) Мутация не-админа без X-Cosmo-Domain → 400 от require_domain
        r = await pg_client.post(f"{BASE}/plans", json=_plan_payload())
        assert r.status_code == 400, "expected require_domain inside capability guard"


# ── 9. No SOD-specific lifecycle values ──────────────────────────────

class TestContractPurity:

    async def test_no_sod_specific_lifecycle_values_in_openapi(self, pg_client):
        r = await pg_client.get("/openapi.json")
        assert r.status_code == 200
        spec = r.json()

        # Все transfer endpoints присутствуют
        expected_paths = {
            "/api/v1/transfer/plans",
            "/api/v1/transfer/plans/{plan_id}",
            "/api/v1/transfer/plans/{plan_id}/items",
            "/api/v1/transfer/items/{item_id}",
            "/api/v1/transfer/items/{item_id}/validate",
            "/api/v1/transfer/items/{item_id}/landing",
            "/api/v1/transfer/items/{item_id}/landing/{transition}",
            "/api/v1/transfer/items/{item_id}/recovery",
            "/api/v1/transfer/releases/{release_id}/plans",
        }
        for path in expected_paths:
            assert path in spec["paths"], f"missing {path}"

        # Lifecycle enums — ровно kernel-значения, без SOD-утечек
        schemas = spec["components"]["schemas"]
        kernel_landing = {s.value for s in LandingState}
        kernel_item = {s.value for s in TransferItemStatus}
        kernel_plan = {s.value for s in TransferPlanStatus}

        landing_enum = set(schemas["LandingState"]["enum"])
        item_enum = set(schemas["TransferItemStatus"]["enum"])
        plan_enum = set(schemas["TransferPlanStatus"]["enum"])

        assert landing_enum == kernel_landing
        assert item_enum == kernel_item
        assert plan_enum == kernel_plan
        for value in landing_enum | item_enum | plan_enum:
            assert "sod" not in value.lower(), f"SOD-specific value leaked: {value}"

        # OpenAPI отражает реальные схемы kernel
        for schema_name in ("TransferPlan", "TransferItem", "PackageRevision", "LandingCheckReport"):
            assert schema_name in schemas, f"missing schema {schema_name}"

        # COS-058: обязательные примеры в OpenAPI
        plan_in = schemas["TransferPlanIn"]
        example_summaries = [
            ex.get("summary", "") for ex in plan_in.get("examples", [])
        ]
        assert any("Multi-plane" in s for s in example_summaries), example_summaries
        assert any("skeleton" in s.lower() for s in example_summaries), example_summaries

        transition_path = spec["paths"]["/api/v1/transfer/items/{item_id}/landing/{transition}"]["post"]
        responses = transition_path["responses"]
        ex_200 = responses["200"]["content"]["application/json"]["examples"]
        assert "successful-landing" in ex_200
        assert "recoverable-bootstrap-failure" in ex_200
        ex_409 = responses["409"]["content"]["application/json"]["examples"]
        assert ex_409["checksum-mismatch"]["value"]["error"]["code"] == "CHECKSUM_MISMATCH"
        assert ex_409["duplicate-revision"]["value"]["error"]["code"] == "DUPLICATE_REVISION"
        assert ex_409["invalid-transition"]["value"]["error"]["code"] == "INVALID_TRANSITION"

        validate_path = spec["paths"]["/api/v1/transfer/items/{item_id}/validate"]["post"]
        ex_422 = validate_path["responses"]["422"]["content"]["application/json"]["examples"]
        assert ex_422["validation-failure"]["value"]["error"]["code"] == "VALIDATION_FAILURE"
