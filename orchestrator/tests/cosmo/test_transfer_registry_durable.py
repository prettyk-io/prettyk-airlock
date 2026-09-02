# -*- coding: utf-8 -*-
"""Durable Transfer Registry — behavioral contract tests against real PostgreSQL.

PgTransferRegistryRepository обязан повторять контракт in-memory
TransferRegistry (orchestrator/cosmo/transfer/registry.py): ошибки
регистрации, идемпотентность revision, restart-survival. Skip при
недоступном PG. Миграционная корректность покрыта
test_migration_reconciliation.py — здесь только таблицы (create_all).
"""
from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

import pytest

import _testpg

_repo = Path(__file__).resolve().parents[3]
_orch = Path(__file__).resolve().parents[2]
for p in (str(_repo), str(_orch)):
    if p not in sys.path:
        sys.path.insert(0, p)

from orchestrator.cosmo.transfer.contract import (
    ArtifactPlane,
    PackageMode,
    PackageRevision,
    TransportProfile,
    TransferItem,
    TransferItemStatus,
    TransferPlan,
)
from orchestrator.cosmo.transfer.landing import LandingState, LandingStateMachine
from orchestrator.cosmo.transfer.registry import DuplicateRevisionError, TransferRegistry

# COS-078: scratch-имя уникально per-run (catalog-race mitigation); админ/URL —
# через _testpg (изолированный test PG :5433, контракт COS-073).
SCRATCH_DB = _testpg.scratch_name("transfer_repo")
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
    status: TransferItemStatus = TransferItemStatus.DRAFT,
) -> TransferItem:
    return TransferItem(
        item_id=item_id,
        release_id=release_id,
        transfer_plan_id=plan_id,
        correlation_id=f"corr-{plan_id}",
        artifact_plane=ArtifactPlane.NEXUS_PACKAGE,
        package_mode=PackageMode.FULL_PACKAGE,
        transport_profile=TransportProfile.IMMUTABLE_OFFLINE_IMPORT,
        source_ref="s3://spool/pkg.zip",
        target_ref="nexus://zt/pkg.zip",
        package_revision=PackageRevision(
            release_id=release_id,
            revision=rev,
            manifest_sha256=PackageRevision.compute_manifest_sha256(
                {"release": release_id, "rev": rev}
            ),
        ),
        status=status,
    )


def _make_plan(plan_id: str, release_id: str = "rel-1", n_items: int = 2) -> TransferPlan:
    plan = TransferPlan(plan_id=plan_id, release_id=release_id, source_zone="zr", target_zone="zt")
    for i in range(n_items):
        plan.add_item(_make_item(f"{plan_id}-item-{i}", plan_id, release_id, rev=i + 1))
    return plan


@pytest.fixture(scope="module")
def repo():
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

    engine = create_engine(_SCRATCH_URL)
    TransferRegistryBase.metadata.create_all(engine)
    yield PgTransferRegistryRepository(engine)
    engine.dispose()
    _drop()


@pytest.fixture(autouse=True)
def _clean(repo):
    repo.reset()
    yield
    repo.reset()


# ════════════════════════════════════════════════════════════════════
# Plan / item registration contract
# ════════════════════════════════════════════════════════════════════


class TestPlanRegistration:
    def test_register_and_get_plan_roundtrip(self, repo):
        plan = _make_plan("plan-rt", n_items=2)
        entry = repo.register_plan(plan, domain_id="dom-1")
        assert entry.plan.plan_id == "plan-rt"
        assert entry.domain_id == "dom-1"
        assert len(entry.plan.items) == 2

        fetched = repo.get_plan("plan-rt")
        assert fetched is not None
        assert fetched.plan == plan
        assert fetched.domain_id == "dom-1"

    def test_duplicate_plan_raises_valueerror(self, repo):
        repo.register_plan(_make_plan("plan-dup"), domain_id="dom-1")
        with pytest.raises(ValueError, match="Transfer plan 'plan-dup' already exists"):
            repo.register_plan(_make_plan("plan-dup"), domain_id="dom-1")

    def test_duplicate_item_across_plans_raises_valueerror(self, repo):
        item = _make_item("shared-item", "plan-a", release_id="rel-a")
        plan_a = TransferPlan(plan_id="plan-a", release_id="rel-a")
        plan_a.add_item(item)
        repo.register_plan(plan_a, domain_id="dom-1")

        plan_b = TransferPlan(plan_id="plan-b", release_id="rel-b")
        plan_b.add_item(_make_item("shared-item", "plan-b", release_id="rel-b"))
        with pytest.raises(ValueError, match="Transfer item 'shared-item' already exists"):
            repo.register_plan(plan_b, domain_id="dom-1")

    def test_get_plan_missing_returns_none(self, repo):
        assert repo.get_plan("no-such-plan") is None

    def test_get_item_roundtrip(self, repo):
        repo.register_plan(_make_plan("plan-item"), domain_id="dom-1")
        result = repo.get_item("plan-item-item-0")
        assert result is not None
        entry, item = result
        assert entry.plan.plan_id == "plan-item"
        assert item.item_id == "plan-item-item-0"
        assert item.artifact_plane == ArtifactPlane.NEXUS_PACKAGE
        assert item.is_deployable is True

    def test_get_item_missing_returns_none(self, repo):
        assert repo.get_item("ghost-item") is None

    def test_plans_for_release_filters(self, repo):
        repo.register_plan(_make_plan("plan-r1a", release_id="rel-r1"), domain_id="d")
        repo.register_plan(_make_plan("plan-r1b", release_id="rel-r1"), domain_id="d")
        repo.register_plan(_make_plan("plan-r2", release_id="rel-r2"), domain_id="d")
        ids = {e.plan.plan_id for e in repo.plans_for_release("rel-r1")}
        assert ids == {"plan-r1a", "plan-r1b"}


# ════════════════════════════════════════════════════════════════════
# Received revisions (кросс-item idempotency)
# ════════════════════════════════════════════════════════════════════


class TestReceivedRevisions:
    def test_same_item_is_idempotent_noop(self, repo):
        repo.register_plan(_make_plan("plan-recv"), domain_id="d")
        repo.register_received_revision("rel-1:1", "plan-recv-item-0")
        repo.register_received_revision("rel-1:1", "plan-recv-item-0")  # no-op

    def test_cross_item_duplicate_raises(self, repo):
        repo.register_plan(_make_plan("plan-x", n_items=2), domain_id="d")
        repo.register_received_revision("rel-1:1", "plan-x-item-0")
        with pytest.raises(DuplicateRevisionError) as excinfo:
            repo.register_received_revision("rel-1:1", "plan-x-item-1")
        assert excinfo.value.revision_key == "rel-1:1"
        assert excinfo.value.existing_item_id == "plan-x-item-0"
        assert excinfo.value.incoming_item_id == "plan-x-item-1"

    def test_revision_of_planless_item_still_indexed(self, repo):
        repo.register_received_revision("orphan:1", "some-item")
        with pytest.raises(DuplicateRevisionError):
            repo.register_received_revision("orphan:1", "other-item")


# ════════════════════════════════════════════════════════════════════
# Landing state durability
# ════════════════════════════════════════════════════════════════════


class TestLandingDurability:
    def test_save_and_restore_landing_state(self, repo):
        repo.register_plan(_make_plan("plan-land"), domain_id="d")
        item = _make_item("plan-land-item-0", "plan-land")
        sm = LandingStateMachine(item)
        sm.transition(LandingState.RECEIVED, "delivered")
        sm.transition(LandingState.VERIFIED, "manifest ok")
        repo.save_landing_state("plan-land-item-0", sm)

        restored = repo.get_landing_state("plan-land-item-0")
        assert restored is not None
        assert restored.state == LandingState.VERIFIED
        assert len(restored.history) == 2
        assert restored.history[0]["from"] == "not_received"
        assert restored.history[1]["reason"] == "manifest ok"

    def test_save_landing_state_unknown_item_raises(self, repo):
        sm = LandingStateMachine(_make_item("ghost", "ghost-plan"))
        with pytest.raises(ValueError, match="does not exist"):
            repo.save_landing_state("ghost", sm)

    def test_get_landing_state_missing_returns_none(self, repo):
        assert repo.get_landing_state("never-saved") is None


# ════════════════════════════════════════════════════════════════════
# Restart survival — durable registry vs in-memory
# ════════════════════════════════════════════════════════════════════


class TestRestartSurvival:
    def test_plans_survive_new_repo_instance(self, repo):
        from orchestrator.cosmo.db.transfer_registry_repo import PgTransferRegistryRepository

        plan = _make_plan("plan-restart", release_id="rel-restart")
        repo.register_plan(plan, domain_id="dom-9")
        repo.register_received_revision("rel-restart:1", "plan-restart-item-0")
        sm = LandingStateMachine(plan.items[0])
        sm.transition(LandingState.RECEIVED)
        repo.save_landing_state("plan-restart-item-0", sm)

        fresh = PgTransferRegistryRepository(_SCRATCH_URL)
        fetched = fresh.get_plan("plan-restart")
        assert fetched is not None
        assert fetched.plan == plan
        assert fetched.domain_id == "dom-9"
        assert fresh.get_landing_state("plan-restart-item-0").state == LandingState.RECEIVED

        # Идемпотентность переживает рестарт: тот же item — no-op, другой — конфликт.
        fresh.register_received_revision("rel-restart:1", "plan-restart-item-0")
        with pytest.raises(DuplicateRevisionError):
            fresh.register_received_revision("rel-restart:1", "plan-restart-item-1")

    def test_in_memory_registry_loses_state(self):
        """Контраст: in-memory singleton не переживает пересоздание."""
        registry = TransferRegistry()
        registry.register_plan(_make_plan("plan-mem"), domain_id="d")
        registry.reset()
        assert registry.get_plan("plan-mem") is None


# ════════════════════════════════════════════════════════════════════
# Behavioral parity: in-memory vs durable
# ════════════════════════════════════════════════════════════════════


class TestContractParity:
    def test_same_scenario_same_outcomes(self, repo):
        """Один сценарий на обоих стораха — идентичные исходы."""
        scenario_plan = _make_plan("plan-parity", release_id="rel-parity")

        def run(store):
            outcomes = []
            store.register_plan(scenario_plan, domain_id="dom-p")
            outcomes.append(store.get_plan("plan-parity") is not None)
            try:
                store.register_plan(_make_plan("plan-parity"), domain_id="dom-p")
            except ValueError:
                outcomes.append("dup-plan-ValueError")
            store.register_received_revision("rel-parity:1", "plan-parity-item-0")
            try:
                store.register_received_revision("rel-parity:1", "plan-parity-item-1")
            except DuplicateRevisionError:
                outcomes.append("cross-item-DuplicateRevisionError")
            return outcomes

        in_memory = run(TransferRegistry())
        durable = run(repo)
        assert in_memory == durable == [
            True,
            "dup-plan-ValueError",
            "cross-item-DuplicateRevisionError",
        ]
