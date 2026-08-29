# -*- coding: utf-8 -*-
"""COS-003: тесты Cosmo RunControlPlane (8-state machine, PG persistence)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_orch = Path(__file__).resolve().parents[1]
if str(_orch) not in sys.path:
    sys.path.insert(0, str(_orch))

from orchestrator.cosmo.control_plane.run_control import (
    FailureClass,
    RunControlPlane,
    RunRecord,
    RunState,
    json_dumps_sorted,
)


# ══════════════════════════════════════════════════════════════════
# LIFECYCLE: 8-state machine + атомарные переходы
# ══════════════════════════════════════════════════════════════════

class TestLifecycle:
    def test_happy_path_draft_to_succeeded(self):
        c = RunControlPlane()
        c.register_worker("w1", frozenset({"dast"}))

        run, is_new = c.create_run(
            {"plan_id": "plan-1", "domain_id": "dom-1", "trigger": "scheduled"},
            frozenset({"dast"}),
        )
        assert is_new is True
        assert run.state == RunState.DRAFT

        c.submit_run(run.id)
        assert run.state == RunState.PENDING

        c.enqueue_run(run.id)
        assert run.state == RunState.RUNNING  # сразу диспатчнут на w1
        assert run.worker_id == "w1"

        c.succeed_run(run.id)
        assert run.state == RunState.SUCCEEDED
        assert len(run.history) >= 4

    def test_invalid_transition_raises(self):
        c = RunControlPlane()
        c.register_worker("w1", frozenset({"dast"}))
        run, _ = c.create_run({"plan_id": "p", "domain_id": "d"}, frozenset({"dast"}))
        c.submit_run(run.id)
        c.enqueue_run(run.id)
        c.succeed_run(run.id)

        # Повторный succeed на terminal — no-op
        c.succeed_run(run.id)
        assert run.state == RunState.SUCCEEDED

        # Прямой недопустимый переход — ValueError
        with pytest.raises(ValueError, match="Invalid transition"):
            c._transition(run, RunState.RUNNING)

    def test_cancel_in_queue(self):
        c = RunControlPlane(max_concurrent=1)
        c.register_worker("w1", frozenset({"dast"}))

        r1, _ = c.create_run({"plan_id": "p1", "domain_id": "d"}, frozenset({"dast"}))
        c.submit_run(r1.id)
        c.enqueue_run(r1.id)  # → RUNNING на w1

        r2, _ = c.create_run({"plan_id": "p2", "domain_id": "d"}, frozenset({"dast"}))
        c.submit_run(r2.id)
        c.enqueue_run(r2.id)  # → QUEUED (max_concurrent=1)

        assert r2.state == RunState.QUEUED
        c.cancel_run(r2.id)
        assert r2.state == RunState.CANCELLED
        assert c.queue_position(r2.id) is None

    def test_cancel_while_running(self):
        c = RunControlPlane()
        c.register_worker("w1", frozenset({"dast"}))
        run, _ = c.create_run({"plan_id": "p", "domain_id": "d"}, frozenset({"dast"}))
        c.submit_run(run.id)
        c.enqueue_run(run.id)
        assert run.state == RunState.RUNNING
        c.cancel_run(run.id)
        assert run.state == RunState.CANCELLED

    def test_blocked_state_and_unblock(self):
        c = RunControlPlane()
        c.register_worker("w1", frozenset({"dast"}))
        run, _ = c.create_run({"plan_id": "p", "domain_id": "d"}, frozenset({"dast"}))
        c.submit_run(run.id)
        c.enqueue_run(run.id)
        assert run.state == RunState.RUNNING

        # Gate failure → BLOCKED
        c.fail_run(run.id, FailureClass.GATE, "critical finding exceeds threshold")
        assert run.state == RunState.BLOCKED
        assert run.failure_class == FailureClass.GATE

        # Разблокировать → QUEUED
        c._transition(run, RunState.QUEUED)
        c._queue.append(run.id)
        assert run.state == RunState.QUEUED

    def test_draft_cancel(self):
        c = RunControlPlane()
        run, _ = c.create_run({"plan_id": "p", "domain_id": "d"})
        assert run.state == RunState.DRAFT
        c.cancel_run(run.id)
        assert run.state == RunState.CANCELLED

    def test_pending_to_queue(self):
        c = RunControlPlane()
        c.register_worker("w1", frozenset({"dast"}))
        run, _ = c.create_run({"plan_id": "p", "domain_id": "d"})
        c.submit_run(run.id)
        assert run.state == RunState.PENDING
        c.enqueue_run(run.id)
        assert run.state == RunState.RUNNING  # dispatch to free worker


# ══════════════════════════════════════════════════════════════════
# DEDUP: защита от дублирования
# ══════════════════════════════════════════════════════════════════

class TestDedup:
    def test_duplicate_params_returns_existing(self):
        c = RunControlPlane()
        c.register_worker("w1")
        r1, is_new1 = c.create_run({"plan_id": "x", "domain_id": "d"})
        r2, is_new2 = c.create_run({"plan_id": "x", "domain_id": "d"})
        assert is_new1 is True
        assert is_new2 is False
        assert r1.id == r2.id

    def test_key_order_independent(self):
        a = RunControlPlane._dedup_key({"a": 1, "b": 2})
        b = RunControlPlane._dedup_key({"b": 2, "a": 1})
        assert a == b

    def test_different_params_new_run(self):
        c = RunControlPlane()
        c.register_worker("w1")
        r1, _ = c.create_run({"plan_id": "x", "domain_id": "d"})
        c.submit_run(r1.id)
        c.enqueue_run(r1.id)
        c.succeed_run(r1.id)
        r2, is_new = c.create_run({"plan_id": "x", "domain_id": "d"})
        assert is_new is True
        assert r1.id != r2.id


# ══════════════════════════════════════════════════════════════════
# FIFO: очередь + позиция
# ══════════════════════════════════════════════════════════════════

class TestQueue:
    def test_fifo_order_and_position(self):
        c = RunControlPlane(max_concurrent=1)
        c.register_worker("w1", frozenset({"dast"}))

        def make_and_enqueue(pid):
            r, _ = c.create_run({"plan_id": pid, "domain_id": "d"}, frozenset({"dast"}))
            c.submit_run(r.id)
            c.enqueue_run(r.id)
            return r

        r1 = make_and_enqueue("p1")
        r2 = make_and_enqueue("p2")
        r3 = make_and_enqueue("p3")

        assert r1.state == RunState.RUNNING
        assert r2.state == RunState.QUEUED
        assert r3.state == RunState.QUEUED
        assert c.queue_position(r2.id) == 0
        assert c.queue_position(r3.id) == 1
        assert c.queue_length() == 2

    def test_queue_advances_when_worker_freed(self):
        c = RunControlPlane(max_concurrent=1)
        c.register_worker("w1", frozenset({"dast"}))

        def make(pid):
            r, _ = c.create_run({"plan_id": pid, "domain_id": "d"}, frozenset({"dast"}))
            c.submit_run(r.id)
            c.enqueue_run(r.id)
            return r

        r1 = make("p1")
        r2 = make("p2")
        assert r2.state == RunState.QUEUED
        c.succeed_run(r1.id)
        assert r2.state == RunState.RUNNING
        assert r2.worker_id == "w1"


# ══════════════════════════════════════════════════════════════════
# CAPABILITIES: worker matching
# ══════════════════════════════════════════════════════════════════

class TestCapabilities:
    def test_run_waits_for_matching_worker(self):
        c = RunControlPlane()
        c.register_worker("scanner-only", frozenset({"scanner"}))
        run, _ = c.create_run({"plan_id": "p", "domain_id": "d"}, frozenset({"chrome"}))
        c.submit_run(run.id)
        c.enqueue_run(run.id)

        # Нет worker'а с chrome → остаётся в очереди
        assert run.state == RunState.QUEUED

        c.register_worker("browser", frozenset({"chrome", "scanner"}))
        c._dispatch()
        assert run.state == RunState.RUNNING
        assert run.worker_id == "browser"

    def test_no_caps_run_goes_anywhere(self):
        c = RunControlPlane()
        c.register_worker("w1", frozenset({"scanner"}))
        run, _ = c.create_run({"plan_id": "p", "domain_id": "d"})
        c.submit_run(run.id)
        c.enqueue_run(run.id)
        assert run.state == RunState.RUNNING


# ══════════════════════════════════════════════════════════════════
# LEASE: heartbeat + stale detection
# ══════════════════════════════════════════════════════════════════

class TestLease:
    def test_stale_worker_detected_and_requeued(self):
        c = RunControlPlane(lease_timeout_sec=60, max_retries=3)
        c.register_worker("w1", frozenset({"dast"}))

        run, _ = c.create_run({"plan_id": "p", "domain_id": "d"}, frozenset({"dast"}))
        c.submit_run(run.id)
        c.enqueue_run(run.id)
        assert run.state == RunState.RUNNING

        c._workers["w1"].lease_expires_at = 0.0
        stale = c.detect_stale()
        assert stale == [run.id]
        assert run.state == RunState.QUEUED
        assert run.attempt == 2

    def test_heartbeat_keeps_lease_alive(self):
        c = RunControlPlane(lease_timeout_sec=60)
        c.register_worker("w1", frozenset({"dast"}))
        run, _ = c.create_run({"plan_id": "p", "domain_id": "d"}, frozenset({"dast"}))
        c.submit_run(run.id)
        c.enqueue_run(run.id)

        w1 = c._workers["w1"]
        original_lease = w1.lease_expires_at
        c.heartbeat("w1")
        assert w1.lease_expires_at > original_lease
        assert c.detect_stale() == []

    def test_stale_exhausts_retries_then_failed(self):
        c = RunControlPlane(lease_timeout_sec=60, max_retries=2)
        c.register_worker("w1", frozenset({"dast"}))
        run, _ = c.create_run({"plan_id": "p", "domain_id": "d"}, frozenset({"dast"}))
        c.submit_run(run.id)
        c.enqueue_run(run.id)

        c._workers["w1"].lease_expires_at = 0.0
        c.detect_stale()
        assert run.state == RunState.QUEUED
        assert run.attempt == 2

        c._dispatch()
        assert run.state == RunState.RUNNING
        c._workers["w1"].lease_expires_at = 0.0
        c.detect_stale()
        assert run.state == RunState.FAILED
        assert run.failure_class == FailureClass.INFRA


# ══════════════════════════════════════════════════════════════════
# RETRY CLASSIFICATION
# ══════════════════════════════════════════════════════════════════

class TestRetryClassification:
    def test_infra_failure_retries(self):
        c = RunControlPlane(max_retries=3)
        c.register_worker("w1", frozenset({"dast"}))
        run, _ = c.create_run({"plan_id": "p", "domain_id": "d"}, frozenset({"dast"}))
        c.submit_run(run.id)
        c.enqueue_run(run.id)

        c.fail_run(run.id, FailureClass.INFRA, "network lost")
        assert run.attempt == 2
        assert run.state == RunState.RUNNING
        states = [h[2] for h in run.history]
        assert "queued" in states

    def test_validation_failure_no_retry(self):
        c = RunControlPlane(max_retries=3)
        c.register_worker("w1", frozenset({"dast"}))
        run, _ = c.create_run({"plan_id": "p", "domain_id": "d"}, frozenset({"dast"}))
        c.submit_run(run.id)
        c.enqueue_run(run.id)

        c.fail_run(run.id, FailureClass.VALIDATION, "bad plan")
        assert run.state == RunState.FAILED
        assert run.attempt == 1

    def test_target_failure_no_retry(self):
        c = RunControlPlane(max_retries=3)
        c.register_worker("w1")
        run, _ = c.create_run({"plan_id": "p", "domain_id": "d"})
        c.submit_run(run.id)
        c.enqueue_run(run.id)

        c.fail_run(run.id, FailureClass.TARGET, "target unreachable")
        assert run.state == RunState.FAILED

    def test_gate_failure_blocks(self):
        c = RunControlPlane(max_retries=3)
        c.register_worker("w1")
        run, _ = c.create_run({"plan_id": "p", "domain_id": "d"})
        c.submit_run(run.id)
        c.enqueue_run(run.id)

        c.fail_run(run.id, FailureClass.GATE, "policy violation")
        assert run.state == RunState.BLOCKED
        assert run.error == "policy violation"

    def test_infra_exhausts_max_retries(self):
        c = RunControlPlane(max_retries=2)
        c.register_worker("w1")
        run, _ = c.create_run({"plan_id": "p", "domain_id": "d"})
        c.submit_run(run.id)
        c.enqueue_run(run.id)

        c.fail_run(run.id, FailureClass.INFRA)
        assert run.attempt == 2
        c.fail_run(run.id, FailureClass.INFRA)
        assert run.state == RunState.FAILED


# ══════════════════════════════════════════════════════════════════
# CANONICALIZATION
# ══════════════════════════════════════════════════════════════════

class TestCanonicalization:
    def test_nested_dict_keys_sorted_lists_keep_order(self):
        assert json_dumps_sorted({"b": [3, 1], "a": {"z": 1, "y": 2}}) == (
            '{"a": {"y": 2, "z": 1}, "b": [3, 1]}'
        )

    def test_dedup_key_stable_regardless_of_key_order(self):
        k1 = RunControlPlane._dedup_key({"plan_id": "x", "domain_id": "y"})
        k2 = RunControlPlane._dedup_key({"domain_id": "y", "plan_id": "x"})
        assert k1 == k2

    def test_list_order_is_significant_for_dedup(self):
        k1 = RunControlPlane._dedup_key({"steps": [1, 2]})
        k2 = RunControlPlane._dedup_key({"steps": [2, 1]})
        assert k1 != k2


# ══════════════════════════════════════════════════════════════════
# SNAPSHOT + RECOVERY
# ══════════════════════════════════════════════════════════════════

class TestSnapshot:
    def test_snapshot_counts_by_state(self):
        c = RunControlPlane()
        c.register_worker("w1")

        r1, _ = c.create_run({"plan_id": "p1", "domain_id": "d"})
        r2, _ = c.create_run({"plan_id": "p2", "domain_id": "d"})
        c.submit_run(r1.id)
        c.enqueue_run(r1.id)
        c.succeed_run(r1.id)

        snap = c.snapshot()
        assert snap["total"] == 2
        assert snap["terminal"] == 1
        assert snap["active"] == 1
        assert snap["by_state"]["succeeded"] == 1
        assert snap["by_state"]["draft"] == 1

    def test_recover_from_pg_noop_when_no_session(self):
        c = RunControlPlane()
        count = c.recover_from_pg()
        assert count == 0  # no db session factory configured

    def test_reset_clears_all(self):
        c = RunControlPlane()
        c.register_worker("w1")
        c.create_run({"plan_id": "p", "domain_id": "d"})
        c.reset()
        assert c.snapshot()["total"] == 0