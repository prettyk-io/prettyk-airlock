# -*- coding: utf-8 -*-
"""COS-034: Лежит + Хеартбеат — unit tests for LeaseTracker."""
from __future__ import annotations

import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_orch = Path(__file__).resolve().parents[1]
if str(_orch) not in sys.path:
    sys.path.insert(0, str(_orch))

from orchestrator.cosmo.control_plane.lease import (
    LeaseTracker,
    LeaseRecord,
)


@pytest.fixture
def tracker():
    return LeaseTracker(default_ttl_seconds=1.0)


# ══════════════════════════════════════════════════════════════════
# Registration
# ══════════════════════════════════════════════════════════════════

class TestRegistration:
    def test_register_creates_record(self, tracker):
        rec = tracker.register_worker("w1", frozenset({"dast", "playwright"}))
        assert rec.worker_id == "w1"
        assert rec.capabilities == frozenset({"dast", "playwright"})
        assert rec.busy is False
        assert rec.is_alive is True

    def test_register_is_idempotent(self, tracker):
        r1 = tracker.register_worker("w1")
        r2 = tracker.register_worker("w1")
        assert r1 is r2

    def test_register_updates_capabilities(self, tracker):
        tracker.register_worker("w1", frozenset({"dast"}))
        tracker.register_worker("w1", frozenset({"playwright"}))
        rec = tracker.get_worker("w1")
        assert rec.capabilities == frozenset({"playwright"})

    def test_deregister_removes_and_markes_terminated(self, tracker):
        tracker.register_worker("w1")
        rec = tracker.deregister_worker("w1")
        assert rec is not None
        assert tracker.get_worker("w1") is None
        # health history has "terminated"
        assert any(h[1] == "terminated" for h in rec.health_history)

    def test_deregister_nonexistent_returns_none(self, tracker):
        assert tracker.deregister_worker("nobody") is None


# ══════════════════════════════════════════════════════════════════
# Heartbeat
# ══════════════════════════════════════════════════════════════════

class TestHeartbeat:
    def test_heartbeat_extends_lease(self, tracker):
        tracker.register_worker("w1")
        old_lease = tracker.get_worker("w1").lease_expires_at or 0
        time.sleep(0.01)
        tracker.heartbeat("w1")
        new_lease = tracker.get_worker("w1").lease_expires_at or 0
        assert new_lease > old_lease

    def test_heartbeat_unknown_worker_returns_false(self, tracker):
        assert tracker.heartbeat("nobody") is False

    def test_heartbeat_increments_counter(self, tracker):
        tracker.register_worker("w1")
        tracker.heartbeat("w1")
        tracker.heartbeat("w1")
        assert tracker.get_worker("w1").total_heartbeats == 2

    def test_heartbeat_resets_stale_count(self, tracker):
        tracker.register_worker("w1")
        rec = tracker.get_worker("w1")
        rec.stale_count = 3  # симулируем dead history
        tracker.heartbeat("w1")
        assert rec.stale_count == 0

    def test_heartbeat_writes_health_history(self, tracker):
        tracker.register_worker("w1")
        tracker.heartbeat("w1")
        rec = tracker.get_worker("w1")
        assert any(h[1] == "alive" for h in rec.health_history)


# ══════════════════════════════════════════════════════════════════
# Dead worker detection
# ══════════════════════════════════════════════════════════════════

class TestDeadWorkerDetection:
    def test_detect_dead_worker(self, tracker):
        tracker.register_worker("w1")
        tracker.assign_worker("w1", "run-1")
        rec = tracker.get_worker("w1")
        rec.lease_expires_at = 0.0  # expired

        dead = tracker.detect_dead_workers()
        assert len(dead) == 1
        assert dead[0].worker_id == "w1"
        assert dead[0].stale_count == 1

    def test_reclaim_orphaned_runs(self, tracker):
        tracker.register_worker("w1")
        tracker.assign_worker("w1", "run-orphan")
        rec = tracker.get_worker("w1")
        rec.lease_expires_at = 0.0

        orphaned = tracker.reclaim_orphaned_runs()
        assert orphaned == ["run-orphan"]
        assert rec.busy is False
        assert rec.current_run_id is None

    def test_dead_worker_calls_callback(self, tracker):
        callback_calls = []
        def cb(rec, run_id):
            callback_calls.append((rec.worker_id, run_id))

        lt = LeaseTracker(default_ttl_seconds=0.1, on_worker_dead=cb)
        lt.register_worker("w-cb")
        lt.assign_worker("w-cb", "run-cb")
        lt.get_worker("w-cb").lease_expires_at = 0.0

        lt.reclaim_orphaned_runs()
        assert len(callback_calls) == 1
        assert callback_calls[0] == ("w-cb", "run-cb")

    def test_alive_worker_not_detected(self, tracker):
        tracker.register_worker("w1")
        tracker.assign_worker("w1", "run-1")
        tracker.heartbeat("w1")  # продлили lease на TTL=1s

        dead = tracker.detect_dead_workers()
        assert len(dead) == 0

    def test_max_stale_deregisters(self, tracker):
        lt = LeaseTracker(default_ttl_seconds=0.01, max_stale_count=2)
        lt.register_worker("w-doomed")

        # Цикл 1: assign → die → reclaim (stale_count=1)
        lt.assign_worker("w-doomed", "run-doomed-1")
        lt.get_worker("w-doomed").lease_expires_at = 0.0
        lt.reclaim_orphaned_runs()
        assert lt.get_worker("w-doomed") is not None
        assert lt.get_worker("w-doomed").stale_count == 1

        # Цикл 2: переподключился → assign снова → снова die → reclaim (stale_count=2 → deregister)
        lt.get_worker("w-doomed").lease_expires_at = None  # reset lease
        lt.assign_worker("w-doomed", "run-doomed-2")
        lt.get_worker("w-doomed").lease_expires_at = 0.0
        lt.reclaim_orphaned_runs()
        assert lt.get_worker("w-doomed") is None


# ══════════════════════════════════════════════════════════════════
# Assignment / release
# ══════════════════════════════════════════════════════════════════

class TestAssignment:
    def test_assign_worker_marks_busy(self, tracker):
        tracker.register_worker("w1")
        assert tracker.assign_worker("w1", "run-1") is True
        rec = tracker.get_worker("w1")
        assert rec.busy is True
        assert rec.current_run_id == "run-1"
        assert rec.lease_expires_at is not None

    def test_assign_unknown_worker(self, tracker):
        assert tracker.assign_worker("nobody", "run-1") is False

    def test_release_worker(self, tracker):
        tracker.register_worker("w1")
        tracker.assign_worker("w1", "run-1")
        orphaned = tracker.release_worker("w1")
        assert orphaned == "run-1"
        rec = tracker.get_worker("w1")
        assert rec.busy is False
        assert rec.current_run_id is None

    def test_release_unknown_worker(self, tracker):
        assert tracker.release_worker("nobody") is None


# ══════════════════════════════════════════════════════════════════
# Health snapshot
# ══════════════════════════════════════════════════════════════════

class TestHealthSnapshot:
    def test_empty_snapshot(self, tracker):
        snap = tracker.health_snapshot()
        assert snap["total"] == 0
        assert snap["alive"] == 0
        assert snap["busy"] == 0
        assert snap["workers"] == []

    def test_snapshot_with_workers(self, tracker):
        tracker.register_worker("w1", frozenset({"dast"}))
        tracker.register_worker("w2", frozenset({"playwright"}))
        tracker.assign_worker("w1", "run-1")

        snap = tracker.health_snapshot()
        assert snap["total"] == 2
        assert snap["alive"] == 2
        assert snap["busy"] == 1
        assert len(snap["workers"]) == 2

        w1 = next(w for w in snap["workers"] if w["worker_id"] == "w1")
        assert w1["busy"] is True
        assert w1["current_run_id"] == "run-1"
        assert "dast" in w1["capabilities"]

    def test_dead_worker_in_snapshot(self, tracker):
        tracker.register_worker("w-dead")
        tracker.assign_worker("w-dead", "run-x")
        tracker.get_worker("w-dead").lease_expires_at = 0.0

        snap = tracker.health_snapshot()
        assert snap["dead"] == 1
        w = next(w for w in snap["workers"] if w["worker_id"] == "w-dead")
        assert w["alive"] is False
        assert w["stale_count"] == 0  # ещё не вызывали detect_dead_workers


# ══════════════════════════════════════════════════════════════════
# Counts
# ══════════════════════════════════════════════════════════════════

class TestCounts:
    def test_count_active_busy_workers(self, tracker):
        tracker.register_worker("w1")
        tracker.register_worker("w2")
        tracker.assign_worker("w1", "run-1")
        assert tracker.count_active() == 1

    def test_count_alive(self, tracker):
        tracker.register_worker("w1")
        tracker.register_worker("w2")
        assert tracker.count_alive() == 2

    def test_count_dead(self, tracker):
        tracker.register_worker("w-dead")
        tracker.assign_worker("w-dead", "run-x")
        tracker.get_worker("w-dead").lease_expires_at = 0.0
        assert tracker.count_dead() == 1


# ══════════════════════════════════════════════════════════════════
# Recovery
# ══════════════════════════════════════════════════════════════════

class TestRecovery:
    def test_recover_from_valkey_noop(self, tracker, monkeypatch):
        monkeypatch.delenv("COSMO_VALKEY_URL", raising=False)
        count = tracker.recover_from_valkey()
        assert count == 0

    def test_recover_from_pg_noop_without_factory(self, tracker):
        count = tracker.recover_from_pg(None)
        assert count == 0


# ══════════════════════════════════════════════════════════════════
# Integration with RunControlPlane
# ══════════════════════════════════════════════════════════════════

class TestIntegrationWithRunControlPlane:
    def test_run_control_plane_uses_lease_tracker(self):
        from orchestrator.cosmo.control_plane.run_control import RunControlPlane

        c = RunControlPlane(lease_timeout_sec=30)
        assert hasattr(c, '_lease_tracker')
        assert c._lease_tracker is not None

    def test_register_worker_syncs_to_lease_tracker(self):
        from orchestrator.cosmo.control_plane.run_control import RunControlPlane

        c = RunControlPlane()
        c.register_worker("w-sync", frozenset({"dast"}))
        # LeaseTracker должен знать об этом worker'е
        lt = c._lease_tracker
        assert lt.get_worker("w-sync") is not None
        assert lt.get_worker("w-sync").capabilities == frozenset({"dast"})

    def test_heartbeat_syncs_both_layers(self):
        from orchestrator.cosmo.control_plane.run_control import RunControlPlane

        c = RunControlPlane()
        c.register_worker("w-hb")
        c.heartbeat("w-hb")

        # Legacy
        assert c._workers["w-hb"].lease_expires_at is not None
        # LeaseTracker
        assert c._lease_tracker.get_worker("w-hb").total_heartbeats == 1

    def test_detect_stale_requeues_run(self):
        from orchestrator.cosmo.control_plane.run_control import RunControlPlane, RunState

        c = RunControlPlane(lease_timeout_sec=0.01, max_retries=3)
        c.register_worker("w-stale", frozenset({"dast"}))

        run, _ = c.create_run({"plan_id": "p", "domain_id": "d"}, frozenset({"dast"}))
        c.submit_run(run.id)
        c.enqueue_run(run.id)
        assert run.state == RunState.RUNNING

        # Simulate lease expiry
        c._lease_tracker.get_worker("w-stale").lease_expires_at = 0.0
        stale = c.detect_stale()
        assert len(stale) == 1
        assert run.state in (RunState.QUEUED, RunState.FAILED)  # зависит от retries

    def test_reset_clears_both_layers(self):
        from orchestrator.cosmo.control_plane.run_control import RunControlPlane

        c = RunControlPlane()
        c.register_worker("w-rst")
        c.create_run({"plan_id": "p", "domain_id": "d"})
        c.reset()

        assert c._lease_tracker.health_snapshot()["total"] == 0
        assert c.snapshot()["total"] == 0

    def test_snapshot_includes_lease_health(self):
        from orchestrator.cosmo.control_plane.run_control import RunControlPlane

        c = RunControlPlane()
        c.register_worker("w-snap")
        snap = c.snapshot()
        assert "lease" in snap
        assert snap["lease"]["total"] == 1
        assert snap["lease"]["alive"] == 1