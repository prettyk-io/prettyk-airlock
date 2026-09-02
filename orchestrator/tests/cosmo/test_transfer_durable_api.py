# -*- coding: utf-8 -*-
"""COS-077: Transfer API на durable PgTransferRegistryRepository — integration.

Acceptance-покрытие (боевой путь БЕЗ override get_transfer_repository):
  1. Restart-survival: fresh repo instance (новый engine, тот же PG) видит
     планы/items/landing states/received revisions после «перезапуска».
  2. TRANSFER_FAILED достижим через API (mark_transfer_failed), идемпотентен,
     честен (после RECEIVED → 409), персистентен.
  3. Lease-семантика через API: dispatch без lease → 423 GATEWAY_LEASE_REQUIRED
     (no lease issued / expired / revoked — reason в details); с lease → 200;
     re-dispatch → 409 CONFLICT; не-gateway профили не lease-gated.
  4. item/plan мутации API-слоя (validate/dispatch) персистятся (save_item/
     save_plan) — fresh repo видит validated/dispatched статусы.

Требует тестовый PG (:5433): docker compose -f services/docker-compose.test-pg.yml up -d
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

_orch = Path(__file__).resolve().parents[1]
if str(_orch) not in sys.path:
    sys.path.insert(0, str(_orch))

pytestmark = pytest.mark.asyncio

import _testpg

from orchestrator.cosmo.db.transfer_registry_repo import PgTransferRegistryRepository
from orchestrator.cosmo.transfer.contract import (
    TransferFailureClass,
    TransferItemStatus,
)

BASE = "/api/v1/transfer"

POSTGRES_ADMIN_URL = _testpg.admin_dsn()


def _pg_reachable() -> bool:
    try:
        import psycopg2

        conn = psycopg2.connect(POSTGRES_ADMIN_URL, connect_timeout=3)
        conn.close()
        return True
    except Exception:
        return False


skip_pg = pytest.mark.skipif(
    not _pg_reachable(),
    reason="test PG (:5433) unreachable - docker compose -f services/docker-compose.test-pg.yml up -d",
)

pytestmark = [pytestmark, skip_pg]


# ── fixtures ─────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _clean_durable_registry():
    """Wipe transfer-таблиц тестового PG до/после каждого теста.

    conftest-wipe (CosmoBase) transfer-таблицы не знает — отдельный
    TransferRegistryBase. Здесь боевой durable-путь не подменяется:
    get_transfer_repository резолвит тот же тестовый PG
    (COSMO_DATABASE_URL форсируется conftest)."""
    from orchestrator.cosmo.db.session import get_sync_url

    repo = PgTransferRegistryRepository(get_sync_url())
    repo.reset()
    from orchestrator.cosmo.api.routes.transfer import get_gateway_leases

    get_gateway_leases().reset()
    yield
    repo.reset()
    get_gateway_leases().reset()


# ── helpers ──────────────────────────────────────────────────────────


def _manifest(release_id: str, revision: int = 1, tag: str = "base") -> dict:
    return {"release_id": release_id, "revision": revision, "tag": tag}


def _plan_payload(
    plan_id: str,
    item_id: str,
    release_id: str = "rel-dur",
    revision: int = 1,
    transport_profile: str = "controlled_gateway_relay",
) -> dict:
    return {
        "plan_id": plan_id,
        "release_id": release_id,
        "correlation_id": f"corr-{plan_id}",
        "source_zone": "zr",
        "target_zone": "zt",
        "items": [
            {
                "item_id": item_id,
                "artifact_plane": "metadata_envelope",
                "package_mode": "metadata_envelope",
                "transport_profile": transport_profile,
                "source_ref": "git::gitea/acme/app@main",
                "target_ref": "gateway://zt/inbox/app",
                "manifest": _manifest(release_id, revision),
                "payload_refs": [],
                "revision": revision,
            }
        ],
    }


async def _ensure_domain(client, domain_id: str) -> None:
    """Создать домен в БД (guard require_domain проверяет существование).

    POST /api/v1/domains — system-admin only; выполняется под временным
    system-admin override с восстановлением прежнего principal."""
    from orchestrator.cosmo.api.deps import get_current_principal
    from orchestrator.cosmo.api.main import app
    from orchestrator.cosmo.domain.rbac import PrincipalContext

    prev = app.dependency_overrides.get(get_current_principal)

    async def _sysadmin() -> PrincipalContext:
        return PrincipalContext(
            user_id="sysadmin-setup", roles=[],
            is_authenticated=True, is_system_admin=True,
        )

    app.dependency_overrides[get_current_principal] = _sysadmin
    try:
        r = await client.post("/api/v1/domains", json={
            "id": domain_id,
            "label": f"Domain {domain_id}",
            "forge_binding": {
                "forge_type": "gitea",
                "url": "https://gitea.example",
                "token_ref": f"vault://cosmo/{domain_id}",
            },
            "quota": {"max_runs": 10, "max_storage_gb": 100, "max_cpu": 4},
        })
        assert r.status_code in (201, 409), r.text
    finally:
        if prev is None:
            app.dependency_overrides.pop(get_current_principal, None)
        else:
            app.dependency_overrides[get_current_principal] = prev


async def _create_plan(client, plan_id: str, item_id: str, **kw) -> None:
    r = await client.post(f"{BASE}/plans", json=_plan_payload(plan_id, item_id, **kw))
    assert r.status_code == 201, r.text


def _fresh_repo() -> PgTransferRegistryRepository:
    """«Перезапуск процесса»: новый instance + новый engine, тот же PG."""
    from orchestrator.cosmo.db.session import get_sync_url

    return PgTransferRegistryRepository(get_sync_url())


# ── 1. Restart-survival ──────────────────────────────────────────────


class TestRestartSurvival:

    async def test_plan_items_landing_survive_fresh_repo(self, pg_client):
        """create + receive через API → fresh repo видит всё состояние."""
        await _create_plan(pg_client, "plan-dur-rs1", "item-dur-rs1")
        r = await pg_client.post(f"{BASE}/items/item-dur-rs1/landing/receive")
        assert r.status_code == 200, r.text

        fresh = _fresh_repo()
        entry = fresh.get_plan("plan-dur-rs1")
        assert entry is not None, "plan lost after restart"
        assert entry.plan.items[0].status is TransferItemStatus.RECEIVED

        sm = fresh.get_landing_state("item-dur-rs1")
        assert sm is not None and sm.state.value == "received"

        entry2, item2 = fresh.get_item("item-dur-rs1")
        assert item2.item_id == "item-dur-rs1"
        assert entry2.domain_id == "test"  # conftest-админ: principal.domain_id

        # received-revision персистентна: тот же revision для ДРУГОГО item
        # через fresh repo → DuplicateRevisionError (кросс-item idempotency)
        revision_key = item2.revision_key
        fresh.register_received_revision(revision_key, "item-dur-rs1")  # idempotent no-op
        # честный кросс-item конфликт: второй план в том же release
        await _create_plan(pg_client, "plan-dur-rs3", "item-dur-rs3")
        with pytest.raises(Exception) as exc_info:
            fresh.register_received_revision(revision_key, "item-dur-rs3")
        assert "already received" in str(exc_info.value)

    async def test_validate_status_persisted(self, pg_client):
        """validate через API → fresh repo видит validated статус (save_item)."""
        await _create_plan(pg_client, "plan-dur-v1", "item-dur-v1")
        r = await pg_client.post(f"{BASE}/items/item-dur-v1/validate")
        assert r.status_code == 200, r.text
        fresh = _fresh_repo()
        _, item = fresh.get_item("item-dur-v1")
        assert item.status is TransferItemStatus.VALIDATED
        assert item.readiness is True


# ── 2. TRANSFER_FAILED через API ─────────────────────────────────────


class TestTransferFailedViaAPI:

    async def test_mark_transfer_failed_reachable_and_idempotent(self, pg_client):
        await _create_plan(pg_client, "plan-dur-tf1", "item-dur-tf1")
        r = await pg_client.post(
            f"{BASE}/items/item-dur-tf1/landing/mark_transfer_failed",
            json={"reason": "diode died on the wire"},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["state"] == "transfer_failed"
        assert body["passed"] is False
        assert body["recoverable"] is False
        assert body["transition"] == "mark_transfer_failed"

        # идемпотентность: повтор → 200, состояние то же
        r2 = await pg_client.post(
            f"{BASE}/items/item-dur-tf1/landing/mark_transfer_failed",
            json={"reason": "second call"},
        )
        assert r2.status_code == 200, r2.text
        assert r2.json()["state"] == "transfer_failed"

        # отчёт: transport_failure, честная причина
        r3 = await pg_client.get(f"{BASE}/items/item-dur-tf1/landing")
        report = r3.json()
        assert report["state"] == "transfer_failed"
        assert report["failure_class"] == TransferFailureClass.TRANSPORT_FAILURE.value

        # recovery: терминал, не recoverable, не требует новой revision
        r4 = await pg_client.get(f"{BASE}/items/item-dur-tf1/recovery")
        rec = r4.json()
        assert rec["state"] == "transfer_failed"
        assert rec["recoverable"] is False
        assert rec["failure_class"] == "transport_failure"
        assert rec["failure_detail"] == "diode died on the wire"

        # restart-survival терминала
        sm = _fresh_repo().get_landing_state("item-dur-tf1")
        assert sm is not None and sm.state.value == "transfer_failed"

    async def test_mark_transfer_failed_after_receive_is_409(self, pg_client):
        """Честность: после RECEIVED транспортный провал лгать не может."""
        await _create_plan(pg_client, "plan-dur-tf2", "item-dur-tf2")
        r = await pg_client.post(f"{BASE}/items/item-dur-tf2/landing/receive")
        assert r.status_code == 200
        r2 = await pg_client.post(
            f"{BASE}/items/item-dur-tf2/landing/mark_transfer_failed",
            json={"reason": "too late"},
        )
        assert r2.status_code == 409, r2.text
        err = r2.json()["error"]
        assert err["code"] == "INVALID_TRANSITION"
        assert err["details"]["from_state"] == "received"
        # состояние не пострадало
        r3 = await pg_client.get(f"{BASE}/items/item-dur-tf2/landing")
        assert r3.json()["state"] == "received"

    async def test_transfer_failed_item_status_failed(self, pg_client):
        """_apply_landing_state: TRANSFER_FAILED → item.status=failed."""
        await _create_plan(pg_client, "plan-dur-tf3", "item-dur-tf3")
        r = await pg_client.post(
            f"{BASE}/items/item-dur-tf3/landing/mark_transfer_failed")
        assert r.status_code == 200
        fresh = _fresh_repo()
        _, item = fresh.get_item("item-dur-tf3")
        assert item.status is TransferItemStatus.FAILED
        assert item.failure_class is TransferFailureClass.TRANSPORT_FAILURE


# ── 3. Lease + dispatch ──────────────────────────────────────────────


class TestLeaseAndDispatch:

    async def test_dispatch_without_lease_423(self, pg_client):
        """Gateway-relay dispatch без lease → 423 GATEWAY_LEASE_REQUIRED,
        отказ ДО мутаций (статус не меняется)."""
        await _create_plan(pg_client, "plan-dur-l1", "item-dur-l1")
        r = await pg_client.post(f"{BASE}/items/item-dur-l1/dispatch")
        assert r.status_code == 423, r.text
        err = r.json()["error"]
        assert err["code"] == "GATEWAY_LEASE_REQUIRED"
        assert err["details"]["revision_key"] == "rel-dur:1"
        assert "no lease issued" in err["details"]["reason"]
        # статус не пострадал
        fresh = _fresh_repo()
        _, item = fresh.get_item("item-dur-l1")
        assert item.status is TransferItemStatus.DRAFT

    async def test_dispatch_with_lease_then_redispatch_409(self, pg_client):
        await _create_plan(pg_client, "plan-dur-l2", "item-dur-l2")
        r = await pg_client.post(
            f"{BASE}/items/item-dur-l2/lease",
            json={"ttl_seconds": 3600, "gateway_id": "gw-alpha"},
        )
        assert r.status_code == 200, r.text
        lease = r.json()
        assert lease["revision_key"] == "rel-dur:1"
        assert lease["state"] == "active"
        assert lease["gateway_id"] == "gw-alpha"

        r2 = await pg_client.post(f"{BASE}/items/item-dur-l2/dispatch")
        assert r2.status_code == 200, r2.text
        disp = r2.json()
        assert disp["state"] == "dispatched"
        assert disp["lease_id"] == lease["lease_id"]

        # item персистится dispatched
        fresh = _fresh_repo()
        _, item = fresh.get_item("item-dur-l2")
        assert item.status is TransferItemStatus.DISPATCHED

        # повторный dispatch → 409 CONFLICT
        r3 = await pg_client.post(f"{BASE}/items/item-dur-l2/dispatch")
        assert r3.status_code == 409, r3.text
        assert r3.json()["error"]["code"] == "CONFLICT"

    async def test_revoke_lease_then_dispatch_423(self, pg_client):
        await _create_plan(pg_client, "plan-dur-l3", "item-dur-l3")
        r = await pg_client.post(
            f"{BASE}/items/item-dur-l3/lease", json={"ttl_seconds": 3600})
        assert r.status_code == 200
        r2 = await pg_client.delete(f"{BASE}/items/item-dur-l3/lease")
        assert r2.status_code == 200
        assert r2.json()["revoked"] is True
        # идемпотентный revoke
        r3 = await pg_client.delete(f"{BASE}/items/item-dur-l3/lease")
        assert r3.status_code == 200
        assert r3.json()["revoked"] is False

        r4 = await pg_client.post(f"{BASE}/items/item-dur-l3/dispatch")
        assert r4.status_code == 423, r4.text
        assert "revoked" in r4.json()["error"]["details"]["reason"]

    async def test_expired_lease_423(self, pg_client):
        """TTL=1s → детерминированное истечение → 423 (lease expired)."""
        await _create_plan(pg_client, "plan-dur-l4", "item-dur-l4")
        r = await pg_client.post(
            f"{BASE}/items/item-dur-l4/lease", json={"ttl_seconds": 1})
        assert r.status_code == 200
        await asyncio.sleep(1.2)
        r2 = await pg_client.post(f"{BASE}/items/item-dur-l4/dispatch")
        assert r2.status_code == 423, r2.text
        assert "expired" in r2.json()["error"]["details"]["reason"]

    async def test_reissue_revokes_previous(self, pg_client):
        """Single-active инвариант: новый issue отзывает предыдущий lease."""
        await _create_plan(pg_client, "plan-dur-l5", "item-dur-l5")
        r1 = await pg_client.post(
            f"{BASE}/items/item-dur-l5/lease", json={"ttl_seconds": 3600})
        first = r1.json()["lease_id"]
        r2 = await pg_client.post(
            f"{BASE}/items/item-dur-l5/lease", json={"ttl_seconds": 3600})
        second = r2.json()["lease_id"]
        assert first != second

        # активен ровно второй lease (single-active)
        from orchestrator.cosmo.api.routes.transfer import get_gateway_leases

        current = get_gateway_leases().get("rel-dur:1")
        assert current is not None
        assert current.lease_id == second
        # dispatch валидирует активный lease → проходит
        r3 = await pg_client.post(f"{BASE}/items/item-dur-l5/dispatch")
        assert r3.status_code == 200, r3.text

    async def test_direct_profile_not_lease_gated(self, pg_client):
        """Enforced только для CONTROLLED_GATEWAY_RELAY (kernel parity)."""
        await _create_plan(
            pg_client, "plan-dur-l6", "item-dur-l6",
            transport_profile="direct_authenticated_api",
        )
        r = await pg_client.post(f"{BASE}/items/item-dur-l6/dispatch")
        assert r.status_code == 200, r.text
        assert r.json()["lease_id"] is None

    async def test_dispatch_transport_failure_simulate(self, pg_client):
        """simulate.transport_failure → retryable, retry_count+1, персист.

        Kernel parity: lease-gate стоит ДО любых мутаций — сначала lease,
        потом честный transport failure при отправке."""
        await _create_plan(pg_client, "plan-dur-l7", "item-dur-l7")
        r0 = await pg_client.post(
            f"{BASE}/items/item-dur-l7/lease", json={"ttl_seconds": 3600})
        assert r0.status_code == 200, r0.text
        r = await pg_client.post(
            f"{BASE}/items/item-dur-l7/dispatch",
            json={"simulate": {"transport_failure": True}},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["state"] == "transport_failed_retryable"
        assert body["retry_count"] == 1
        fresh = _fresh_repo()
        _, item = fresh.get_item("item-dur-l7")
        assert item.retry_count == 1
        assert item.failure_class is TransferFailureClass.TRANSPORT_FAILURE

    async def test_lease_unknown_item_404(self, pg_client):
        """Lease/dispatch на несуществующий item → 404 честного контракта."""
        r = await pg_client.post(
            f"{BASE}/items/item-ghost/lease", json={"ttl_seconds": 60})
        assert r.status_code == 404
        assert r.json()["error"]["code"] == "NOT_FOUND"
        r2 = await pg_client.post(f"{BASE}/items/item-ghost/dispatch")
        assert r2.status_code == 404

    async def test_foreign_domain_lease_404_no_disclosure(self, pg_client):
        """Кросс-доменный доступ к lease/dispatch → 404 (anti-disclosure).

        Домены test+beta создаются в БД; foreign ADMIN_SEC (domain beta) с
        заголовком test проходит guard (домен существует, capability есть),
        но handler ownership по principal.domain_id → 404 error contract."""
        from orchestrator.cosmo.api.deps import get_current_principal
        from orchestrator.cosmo.api.main import app
        from orchestrator.cosmo.domain.rbac import PrincipalContext, Role

        await _ensure_domain(pg_client, "test")
        await _ensure_domain(pg_client, "beta")
        await _create_plan(pg_client, "plan-dur-l8", "item-dur-l8")

        async def _foreign() -> PrincipalContext:
            return PrincipalContext(
                user_id="foreign-user", roles=[Role.ADMIN_SEC],
                domain_id="beta", zone="zr", is_authenticated=True,
            )

        app.dependency_overrides[get_current_principal] = _foreign
        try:
            r = await pg_client.post(
                f"{BASE}/items/item-dur-l8/lease",
                json={"ttl_seconds": 60},
                headers={"X-Cosmo-Domain": "test"},
            )
            assert r.status_code == 404, r.text
            assert r.json()["error"]["code"] == "NOT_FOUND"
            r2 = await pg_client.post(
                f"{BASE}/items/item-dur-l8/dispatch",
                headers={"X-Cosmo-Domain": "test"},
            )
            assert r2.status_code == 404, r2.text
        finally:
            app.dependency_overrides.pop(get_current_principal, None)
