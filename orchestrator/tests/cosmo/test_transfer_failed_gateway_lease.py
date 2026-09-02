# -*- coding: utf-8 -*-
"""COS-074: transfer_failed terminal path + gateway lease/TTL semantics.

Слои:
  - LandingStateMachine: честный терминал NOT_RECEIVED -> TRANSFER_FAILED.
  - TransferRegistry (in-memory): record_transfer_retryable / record_transfer_failed.
  - GatewayLeaseRegistry: lease/TTL офлайн-семантика (single-active, deterministic
    expiry via injected clock).
  - DiodeAdapter: dispatch по CONTROLLED_GATEWAY_RELAY требует активный lease —
    отказ ДО чанков/checkpoint/attempts.
  - PgTransferRegistryRepository: durable mirror — transfer_failed наблюдаем
    в PG (transfer_landing_states.state), restart-survival, идемпотентность.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

import _testpg

from orchestrator.cosmo.transfer.contract import (
    ArtifactPlane,
    PackageMode,
    PackageRevision,
    TransferFailureClass,
    TransportProfile,
    TransferItem,
    TransferItemStatus,
    TransferPlan,
)
from orchestrator.cosmo.transfer.diode_adapter import DiodeAdapter
from orchestrator.cosmo.transfer.gateway_lease import (
    GatewayLeaseRegistry,
    LeaseRequiredError,
    LeaseState,
)
from orchestrator.cosmo.transfer.landing import (
    LandingState,
    LandingStateMachine,
    LandingStateError,
)
from orchestrator.cosmo.transfer.registry import TransferRegistry

# ══════════════════════════════════════════════════════════════════
# Fixtures
# ══════════════════════════════════════════════════════════════════

# COS-078: scratch-имя уникально per-run (catalog-race mitigation);
# availability-чек — _testpg.pg_available (унификация дублей).
SCRATCH_DB = _testpg.scratch_name("transfer_failed")
_POSTGRES_ADMIN_URL = _testpg.admin_dsn()
_SCRATCH_URL = _testpg.psycopg2_url(SCRATCH_DB)


skip_pg = pytest.mark.skipif(
    not _testpg.pg_available(),
    reason="test PG (:5433) unreachable - docker compose -f services/docker-compose.test-pg.yml up -d",
)


def _make_item(
    item_id: str,
    plan_id: str,
    release_id: str = "rel-1",
    rev: int = 1,
    profile: TransportProfile = TransportProfile.CONTROLLED_GATEWAY_RELAY,
) -> TransferItem:
    return TransferItem(
        item_id=item_id,
        release_id=release_id,
        transfer_plan_id=plan_id,
        correlation_id=f"corr-{plan_id}",
        artifact_plane=ArtifactPlane.NEXUS_PACKAGE,
        package_mode=PackageMode.FULL_PACKAGE,
        transport_profile=profile,
        source_ref="s3://spool/pkg.zip",
        target_ref="nexus://zt/pkg.zip",
        package_revision=PackageRevision(
            release_id=release_id,
            revision=rev,
            manifest_sha256=PackageRevision.compute_manifest_sha256(
                {"release": release_id, "rev": rev}
            ),
        ),
        status=TransferItemStatus.DRAFT,
    )


def _make_plan(plan_id: str, items: list[TransferItem]) -> TransferPlan:
    plan = TransferPlan(
        plan_id=plan_id, release_id="rel-1", source_zone="zr", target_zone="zt"
    )
    for it in items:
        plan.add_item(it)
    return plan


class FakeLink:
    """Минимальный one-way link: пишет чанки, пишет ничего не значит."""

    def __init__(self):
        self.received: dict[int, bytes] = {}
        self.flushes = 0

    def write_chunk(self, chunk: bytes, ref) -> None:
        self.received[ref.index] = chunk

    def flush(self) -> None:
        self.flushes += 1

    def reassemble(self) -> bytes:
        return b"".join(self.received[i] for i in sorted(self.received))


PAYLOAD = b"x" * 100  # 2 chunks при chunk_size=64


# ══════════════════════════════════════════════════════════════════
# LandingStateMachine: TRANSFER_FAILED terminal
# ══════════════════════════════════════════════════════════════════

class TestLandingTransferFailed:
    def test_not_received_to_transfer_failed_is_valid(self):
        sm = LandingStateMachine(_make_item("i-lf-1", "p-lf"))
        assert sm.transition(LandingState.TRANSFER_FAILED, "max attempts") is             LandingState.TRANSFER_FAILED
        assert sm.is_terminal()
        assert not sm.is_recoverable()
        assert not sm.requires_new_revision()

    def test_report_honest_transport_failure(self):
        sm = LandingStateMachine(_make_item("i-lf-2", "p-lf"))
        sm.transition(LandingState.TRANSFER_FAILED)
        report = sm.check_report()
        assert report.passed is False
        assert report.failure_class is TransferFailureClass.TRANSPORT_FAILURE
        assert any(not c["passed"] for c in report.checks)

    def test_terminal_has_no_exits(self):
        sm = LandingStateMachine(_make_item("i-lf-3", "p-lf"))
        sm.transition(LandingState.TRANSFER_FAILED)
        for target in LandingState:
            if target is LandingState.TRANSFER_FAILED:
                continue
            with pytest.raises(LandingStateError):
                sm.transition(target)

    def test_transfer_failed_after_received_is_a_lie(self):
        """Target что-то получил — транспортный терминал лгать не может."""
        sm = LandingStateMachine(_make_item("i-lf-4", "p-lf"))
        sm.transition(LandingState.RECEIVED)
        with pytest.raises(LandingStateError):
            sm.transition(LandingState.TRANSFER_FAILED)

    def test_history_records_transition(self):
        sm = LandingStateMachine(_make_item("i-lf-5", "p-lf"))
        sm.transition(LandingState.TRANSFER_FAILED, reason="diode died")
        assert sm.history[-1]["from"] == "not_received"
        assert sm.history[-1]["to"] == "transfer_failed"
        assert sm.history[-1]["reason"] == "diode died"


# ══════════════════════════════════════════════════════════════════
# TransferRegistry (in-memory): retryable + failed
# ══════════════════════════════════════════════════════════════════

class TestRegistryTransferFailed:
    def _registry_with_item(self, item_id: str = "i-rf-1"):
        reg = TransferRegistry()
        item = _make_item(item_id, "p-rf")
        reg.register_plan(_make_plan("p-rf", [item]), domain_id="d1")
        return reg, item

    def test_retryable_increments_count_without_state_change(self):
        reg, item = self._registry_with_item()
        assert reg.record_transfer_retryable(
            "i-rf-1", TransferFailureClass.TRANSPORT_FAILURE, "link dropped") == 1
        assert reg.record_transfer_retryable(
            "i-rf-1", TransferFailureClass.TRANSPORT_FAILURE, "again") == 2
        assert item.retry_count == 2
        assert item.failure_detail == "again"
        entry = reg.get_plan("p-rf")
        assert entry.landing_for(item).state is LandingState.NOT_RECEIVED

    def test_failed_transitions_and_is_idempotent(self):
        reg, item = self._registry_with_item()
        st = reg.record_transfer_failed(
            "i-rf-1", TransferFailureClass.TRANSPORT_FAILURE, "exhausted")
        assert st is LandingState.TRANSFER_FAILED
        # repeat: idempotent terminal no-op — no error, no extra event
        st2 = reg.record_transfer_failed("i-rf-1", None, "repeat")
        assert st2 is LandingState.TRANSFER_FAILED
        events = reg.transfer_events("i-rf-1")
        assert [e["event"] for e in events] == ["transfer_failed"]
        assert item.failure_detail == "exhausted"  # no-op не мутирует

    def test_failed_after_received_raises(self):
        reg, item = self._registry_with_item("i-rf-2")
        reg.get_plan("p-rf").landing_for(item).transition(LandingState.RECEIVED)
        with pytest.raises(LandingStateError):
            reg.record_transfer_failed("i-rf-2", None, "lie")

    def test_unknown_item_raises_keyerror(self):
        reg, _ = self._registry_with_item()
        with pytest.raises(KeyError):
            reg.record_transfer_failed("ghost", None)
        with pytest.raises(KeyError):
            reg.record_transfer_retryable("ghost", None)

    def test_event_log_shape(self):
        reg, _ = self._registry_with_item("i-rf-3")
        reg.record_transfer_retryable("i-rf-3", TransferFailureClass.CAPACITY_QUOTA_FAILURE, "disk full")
        reg.record_transfer_failed("i-rf-3", TransferFailureClass.TRANSPORT_FAILURE, "max attempts")
        events = reg.transfer_events("i-rf-3")
        assert events[0] == {
            "event": "transfer_retryable",
            "item_id": "i-rf-3",
            "failure_class": "capacity_quota_failure",
            "detail": "disk full",
            "from_state": "not_received",
            "to_state": "not_received",
            "timestamp": events[0]["timestamp"],
        }
        assert events[1]["from_state"] == "not_received"
        assert events[1]["to_state"] == "transfer_failed"


# ══════════════════════════════════════════════════════════════════
# GatewayLeaseRegistry: issue/validate/revoke, TTL, single-active
# ══════════════════════════════════════════════════════════════════

class TestGatewayLeaseRegistry:
    def _clock_registry(self):
        now = {"t": datetime(2026, 9, 2, 12, 0, 0, tzinfo=timezone.utc)}
        reg = GatewayLeaseRegistry(clock=lambda: now["t"])
        return reg, now

    def test_issue_and_validate(self):
        reg, _ = self._clock_registry()
        lease = reg.issue("rk-1", "i-1", "gw-1", ttl_seconds=60)
        assert lease.state is LeaseState.ACTIVE
        assert reg.validate("rk-1") is lease

    def test_single_active_invariant(self):
        reg, _ = self._clock_registry()
        first = reg.issue("rk-1", "i-1", "gw-1", ttl_seconds=60)
        second = reg.issue("rk-1", "i-1", "gw-2", ttl_seconds=60)
        assert first.state is LeaseState.REVOKED
        assert second.state is LeaseState.ACTIVE
        assert reg.validate("rk-1") is second

    def test_expiry_boundary_is_deterministic(self):
        """now >= expires_at -> EXPIRED; за секунду до — ещё жив."""
        reg, now = self._clock_registry()
        reg.issue("rk-1", "i-1", "gw-1", ttl_seconds=60)
        now["t"] = now["t"] + timedelta(seconds=59)
        assert reg.validate("rk-1") is not None
        now["t"] = now["t"] + timedelta(seconds=1)  # ровно expires_at
        with pytest.raises(LeaseRequiredError) as exc:
            reg.validate("rk-1")
        assert "expired" in exc.value.reason
        assert reg.get("rk-1").state is LeaseState.EXPIRED

    def test_revoked_rejected_and_revoke_idempotent(self):
        reg, _ = self._clock_registry()
        reg.issue("rk-1", "i-1", "gw-1", ttl_seconds=60)
        assert reg.revoke("rk-1") is True
        assert reg.revoke("rk-1") is False  # идемпотентен
        with pytest.raises(LeaseRequiredError) as exc:
            reg.validate("rk-1")
        assert "revoked" in exc.value.reason

    def test_missing_lease_rejected(self):
        reg, _ = self._clock_registry()
        with pytest.raises(LeaseRequiredError) as exc:
            reg.validate("never-issued")
        assert "no lease issued" in exc.value.reason


# ══════════════════════════════════════════════════════════════════
# DiodeAdapter: lease gate для CONTROLLED_GATEWAY_RELAY
# ══════════════════════════════════════════════════════════════════

class TestDiodeAdapterLeaseGate:
    def _adapter(self, link: FakeLink, leases=None, **kw) -> DiodeAdapter:
        return DiodeAdapter(link, chunk_size=64, gateway_leases=leases, **kw)

    def test_dispatch_without_lease_writes_nothing(self):
        link = FakeLink()
        adapter = self._adapter(link, GatewayLeaseRegistry())
        item = _make_item("i-gl-1", "p-gl")
        with pytest.raises(LeaseRequiredError):
            adapter.dispatch(item, PAYLOAD)
        # отказ ДО мутаций: нет чанков, нет checkpoint, attempts не растут
        assert link.received == {}
        assert adapter.list_active() == []
        assert adapter._checkpoints == {}

    def test_dispatch_with_expired_lease_rejected(self):
        now = {"t": datetime(2026, 9, 2, 12, 0, 0, tzinfo=timezone.utc)}
        leases = GatewayLeaseRegistry(clock=lambda: now["t"])
        link = FakeLink()
        adapter = self._adapter(link, leases)
        item = _make_item("i-gl-2", "p-gl")
        leases.issue(item.revision_key, item.item_id, "gw", ttl_seconds=30)
        now["t"] = now["t"] + timedelta(seconds=30)
        with pytest.raises(LeaseRequiredError):
            adapter.dispatch(item, PAYLOAD)
        assert link.received == {}

    def test_dispatch_with_revoked_lease_rejected(self):
        leases = GatewayLeaseRegistry()
        link = FakeLink()
        adapter = self._adapter(link, leases)
        item = _make_item("i-gl-3", "p-gl")
        leases.issue(item.revision_key, item.item_id, "gw", ttl_seconds=60)
        leases.revoke(item.revision_key)
        with pytest.raises(LeaseRequiredError):
            adapter.dispatch(item, PAYLOAD)
        assert link.received == {}

    def test_dispatch_with_active_lease_proceeds(self):
        leases = GatewayLeaseRegistry()
        link = FakeLink()
        adapter = self._adapter(link, leases)
        item = _make_item("i-gl-4", "p-gl")
        leases.issue(item.revision_key, item.item_id, "gw", ttl_seconds=60)
        result = adapter.dispatch(item, PAYLOAD)
        assert result.chunks_sent == 2
        assert len(link.received) == 2

    def test_other_profiles_unaffected(self):
        leases = GatewayLeaseRegistry()  # пустой реестр
        link = FakeLink()
        adapter = self._adapter(link, leases)
        item = _make_item("i-gl-5", "p-gl",
                          profile=TransportProfile.ONE_WAY_DIODE_RELAY)
        result = adapter.dispatch(item, PAYLOAD)
        assert result.chunks_sent == 2

    def test_no_registry_backcompat(self):
        """Реестр не передан — lease-политика не enforced (старое поведение)."""
        link = FakeLink()
        adapter = self._adapter(link, None)
        item = _make_item("i-gl-6", "p-gl")
        result = adapter.dispatch(item, PAYLOAD)
        assert result.chunks_sent == 2


# ══════════════════════════════════════════════════════════════════
# Durable mirror: transfer_failed наблюдаем в PG, restart-survival
# ══════════════════════════════════════════════════════════════════

@pytest.fixture(scope="module")
def pg_repo():
    """Scratch DB + create_all transfer-таблиц + репозиторий; дроп в конце."""
    import psycopg2
    from sqlalchemy import create_engine
    from orchestrator.cosmo.db.models_transfer import TransferRegistryBase
    from orchestrator.cosmo.db.transfer_registry_repo import PgTransferRegistryRepository

    def _admin():
        return psycopg2.connect(_POSTGRES_ADMIN_URL)

    def _drop():
        conn = _admin()
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname = %s AND pid <> pg_backend_pid()",
            (SCRATCH_DB,),
        )
        cur.execute(f"DROP DATABASE IF EXISTS {SCRATCH_DB}")
        conn.close()

    _drop()
    conn = _admin()
    conn.autocommit = True
    conn.cursor().execute(f"CREATE DATABASE {SCRATCH_DB}")
    conn.close()

    engine = create_engine(_SCRATCH_URL, future=True)
    TransferRegistryBase.metadata.create_all(engine)
    repo = PgTransferRegistryRepository(engine)
    yield repo
    engine.dispose()
    _drop()


@skip_pg
class TestDurableTransferFailed:
    def _register(self, repo, plan_id: str, item_id: str):
        item = _make_item(item_id, plan_id)
        repo.register_plan(_make_plan(plan_id, [item]), domain_id="d1")
        return item

    def _landing_row(self, item_id: str):
        from sqlalchemy import text

        with _engine_ref().connect() as conn:
            return conn.execute(
                text(
                    "SELECT state, revision_key, history FROM transfer_landing_states "
                    "WHERE item_id = :iid"
                ),
                {"iid": item_id},
            ).mappings().one_or_none()

    def test_retryable_persists_retry_count(self, pg_repo):
        item = self._register(pg_repo, "p-df-1", "i-df-1")
        assert pg_repo.record_transfer_retryable(
            "i-df-1", TransferFailureClass.TRANSPORT_FAILURE, "drop 1") == 1
        assert pg_repo.record_transfer_retryable(
            "i-df-1", TransferFailureClass.TRANSPORT_FAILURE, "drop 2") == 2
        from sqlalchemy import text

        with _engine_ref().connect() as conn:
            row = conn.execute(
                text("SELECT retry_count, payload FROM transfer_items WHERE item_id = :iid"),
                {"iid": "i-df-1"},
            ).mappings().one()
        assert row["retry_count"] == 2
        assert row["payload"]["failure_detail"] == "drop 2"
        # состояние НЕ изменилось — landing row ещё не существует
        assert self._landing_row("i-df-1") is None
        _ = item  # keepalive

    def test_failed_persists_terminal_state(self, pg_repo):
        self._register(pg_repo, "p-df-2", "i-df-2")
        st = pg_repo.record_transfer_failed(
            "i-df-2", TransferFailureClass.TRANSPORT_FAILURE, "max attempts")
        assert st is LandingState.TRANSFER_FAILED
        row = self._landing_row("i-df-2")
        assert row is not None
        assert row["state"] == "transfer_failed"
        assert row["revision_key"] == _make_item("i-df-2", "p-df-2").revision_key
        assert row["history"][-1]["to"] == "transfer_failed"
        assert row["history"][-1]["reason"] == "max attempts"

    def test_failed_idempotent_no_extra_history(self, pg_repo):
        self._register(pg_repo, "p-df-3", "i-df-3")
        pg_repo.record_transfer_failed("i-df-3", None, "first")
        before = self._landing_row("i-df-3")["history"]
        st = pg_repo.record_transfer_failed("i-df-3", None, "second")
        assert st is LandingState.TRANSFER_FAILED
        after = self._landing_row("i-df-3")["history"]
        assert before == after  # no-op: ни события, ни мутации payload
        from sqlalchemy import text

        with _engine_ref().connect() as conn:
            payload = conn.execute(
                text("SELECT payload FROM transfer_items WHERE item_id = :iid"),
                {"iid": "i-df-3"},
            ).scalar_one()
        assert payload["failure_detail"] == "first"

    def test_failed_after_received_raises(self, pg_repo):
        item = self._register(pg_repo, "p-df-4", "i-df-4")
        sm = LandingStateMachine(item)
        sm.transition(LandingState.RECEIVED)
        pg_repo.save_landing_state("i-df-4", sm)
        with pytest.raises(LandingStateError):
            pg_repo.record_transfer_failed("i-df-4", None, "lie")
        assert self._landing_row("i-df-4")["state"] == "received"

    def test_terminal_survives_restart(self, pg_repo):
        self._register(pg_repo, "p-df-5", "i-df-5")
        pg_repo.record_transfer_failed(
            "i-df-5", TransferFailureClass.TRANSPORT_FAILURE, "diode died")
        # "restart": новый инстанс репозитория читает из PG
        from orchestrator.cosmo.db.transfer_registry_repo import PgTransferRegistryRepository

        fresh = PgTransferRegistryRepository(_engine_ref())
        sm = fresh.get_landing_state("i-df-5")
        assert sm is not None
        assert sm.state is LandingState.TRANSFER_FAILED
        assert sm.is_terminal()
        assert sm.history[-1]["reason"] == "diode died"
        report = sm.check_report()
        assert report.failure_class is TransferFailureClass.TRANSPORT_FAILURE

    def test_unknown_item_keyerror(self, pg_repo):
        with pytest.raises(KeyError):
            pg_repo.record_transfer_failed("ghost", None)
        with pytest.raises(KeyError):
            pg_repo.record_transfer_retryable("ghost", None)


# ── engine access for direct SQL ─────────────────────────────────────

def _engine_ref():
    from sqlalchemy import create_engine

    return create_engine(_SCRATCH_URL, future=True)
