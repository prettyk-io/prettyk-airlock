# -*- coding: utf-8 -*-
"""COS-046: tests for BatchExecutor + RunControlPlane integration."""
from __future__ import annotations

import sys
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_orch = Path(__file__).resolve().parents[1]
if str(_orch) not in sys.path:
    sys.path.insert(0, str(_orch))

from orchestrator.cosmo.adapters.execution_woodpecker import WoodpeckerAdapter
from orchestrator.cosmo.control_plane.executor import (
    BatchExecutor,
    BatchPollResult,
)
from orchestrator.cosmo.control_plane.run_control import (
    FailureClass,
    RunControlPlane,
    RunRecord,
    RunState,
)


@pytest.fixture
def adapter():
    return WoodpeckerAdapter(base_url="http://localhost:8000", token="test-token")


@pytest.fixture
def executor(adapter):
    return BatchExecutor(adapter=adapter, dry_run=True)


@pytest.fixture
def run_record():
    return RunRecord(id="run-test-1", plan_id="plan-test-1", domain_id="dom-1", trigger="manual")


def _make_batch_orms(plan_id="plan-test-1"):
    return [
        {"id": "batch-build", "plan_id": plan_id, "type": "build", "status": "pending",
         "bricks": ["brick-build-1"], "artifacts": []},
        {"id": "batch-dast", "plan_id": plan_id, "type": "dynamic_test", "status": "pending",
         "bricks": ["brick-dast-1", "brick-dast-2"], "artifacts": []},
    ]


class TestSubmitBatches:
    def test_submit_no_op_without_db(self, executor, run_record):
        assert executor.submit_batches(run_record) == []

    def test_submit_creates_pipeline_handles(self, executor, run_record):
        executor._query_batches = MagicMock(return_value=_make_batch_orms())
        executor._update_batch_pg = MagicMock()

        submitted = executor.submit_batches(run_record)
        assert len(submitted) == 2
        assert "batch-build" in submitted
        assert "batch-dast" in submitted

        handles = executor.active_batches()
        assert len(handles) == 2
        assert handles["batch-build"].run_id == "run-test-1"
        assert handles["batch-build"].batch_id == "batch-build"

    def test_submit_tracking_replacement(self, executor, run_record):
        executor._query_batches = MagicMock(return_value=_make_batch_orms())
        executor._update_batch_pg = MagicMock()

        s1 = executor.submit_batches(run_record)
        # COS-097 resubmit-guard: повторный submit не плодит дубли pipeline'ов.
        s2 = executor.submit_batches(run_record)
        assert len(s1) == 2
        assert s2 == []
        assert len(executor.active_batches()) == 2

    def test_submit_skips_fail_batch_ids(self, executor, run_record):
        executor._query_batches = MagicMock(return_value=_make_batch_orms())
        executor._update_batch_pg = MagicMock()
        executor._submit_fail_batch_ids.add("batch-build")

        submitted = executor.submit_batches(run_record)
        assert submitted == ["batch-dast"]
        assert "batch-build" not in executor.active_batches()

    def test_submit_async_spawns_thread(self, executor, run_record):
        executor._query_batches = MagicMock(return_value=_make_batch_orms())
        executor._update_batch_pg = MagicMock()

        executor.submit_batches_async(run_record)
        time.sleep(0.15)

        assert len(executor.active_batches()) == 2

    def test_submit_updates_pg_to_running(self, executor, run_record):
        executor._query_batches = MagicMock(return_value=_make_batch_orms())
        pg_calls = []
        executor._update_batch_pg = MagicMock(side_effect=lambda bid, st: pg_calls.append((bid, st)))

        executor.submit_batches(run_record)
        assert ("batch-build", "running") in pg_calls
        assert ("batch-dast", "running") in pg_calls

    def test_submit_handles_yaml_failure(self, executor, run_record):
        executor._query_batches = MagicMock(return_value=_make_batch_orms())
        executor._update_batch_pg = MagicMock()
        executor._adapter.generate_pipeline_yaml = MagicMock(side_effect=Exception("YAML error"))

        submitted = executor.submit_batches(run_record)
        assert len(submitted) == 2


class TestPoll:
    def test_poll_empty_no_ops(self, executor):
        assert executor.poll() == []

    def test_poll_terminal_batch(self, executor, run_record):
        executor._query_batches = MagicMock(return_value=[_make_batch_orms()[0]])
        executor._update_batch_pg = MagicMock()
        executor._update_batch_pg_terminal = MagicMock()
        # stateful: submit-guard видит "pending", poll — "running"
        pg = {"status": "pending"}
        executor._get_batch_pg_status = MagicMock(side_effect=lambda bid: pg["status"])

        executor.submit_batches(run_record)
        pg["status"] = "running"
        executor._status_override["batch-build"] = "success"

        results = executor.poll()
        assert len(results) == 1
        r = results[0]
        assert r.batch_id == "batch-build"
        assert r.terminal is True
        assert r.new_status == "passed"

    def test_poll_non_terminal_stays_active(self, executor, run_record):
        executor._query_batches = MagicMock(return_value=[_make_batch_orms()[0]])
        executor._update_batch_pg = MagicMock()
        pg = {"status": "pending"}
        executor._get_batch_pg_status = MagicMock(side_effect=lambda bid: pg["status"])

        executor.submit_batches(run_record)
        pg["status"] = "running"
        executor._status_override["batch-build"] = "running"

        results = executor.poll()
        assert results == []
        assert "batch-build" in executor.active_batches()

    def test_poll_status_change_without_terminal(self, executor, run_record):
        executor._query_batches = MagicMock(return_value=[_make_batch_orms()[0]])
        executor._update_batch_pg = MagicMock()
        executor._get_batch_pg_status = MagicMock(return_value="pending")

        executor.submit_batches(run_record)
        executor._status_override["batch-build"] = "running"

        results = executor.poll()
        assert len(results) == 1
        assert results[0].terminal is False
        assert results[0].new_status == "running"

    def test_poll_partial_terminal(self, executor, run_record):
        executor._query_batches = MagicMock(return_value=_make_batch_orms())
        executor._update_batch_pg = MagicMock()
        executor._update_batch_pg_terminal = MagicMock()
        pg = {"status": "pending"}
        executor._get_batch_pg_status = MagicMock(side_effect=lambda bid: pg["status"])

        executor.submit_batches(run_record)
        pg["status"] = "running"
        executor._status_override["batch-build"] = "success"
        executor._status_override["batch-dast"] = "running"

        results = executor.poll()
        assert len(results) == 1
        assert results[0].batch_id == "batch-build"
        assert results[0].terminal is True
        assert "batch-dast" in executor.active_batches()
        assert "batch-build" not in executor.active_batches()

    def test_poll_all_passed_triggers_callback(self, executor, run_record):
        callback_calls = []
        lt = BatchExecutor(
            adapter=executor._adapter, dry_run=True,
            on_all_terminal=lambda rid, ok: callback_calls.append((rid, ok)),
        )
        lt._query_batches = MagicMock(return_value=_make_batch_orms())
        lt._update_batch_pg = MagicMock()
        lt._update_batch_pg_terminal = MagicMock()
        # After poll marks both terminal, _check_run_terminal читает статусы:
        pg = {"status": "pending"}
        lt._get_batch_pg_status = MagicMock(side_effect=lambda bid: pg["status"])

        lt.submit_batches(run_record)
        pg["status"] = "passed"
        lt._status_override["batch-build"] = "success"
        lt._status_override["batch-dast"] = "success"

        lt.poll()
        assert len(callback_calls) == 1
        assert callback_calls[0] == ("run-test-1", True)

    def test_poll_failures_triggers_callback_false(self, executor, run_record):
        callback_calls = []
        lt = BatchExecutor(
            adapter=executor._adapter, dry_run=True,
            on_all_terminal=lambda rid, ok: callback_calls.append((rid, ok)),
        )
        lt._query_batches = MagicMock(return_value=_make_batch_orms())
        lt._update_batch_pg = MagicMock()
        lt._update_batch_pg_terminal = MagicMock()
        # After poll: оба terminal, но failed
        pg = {"status": "pending"}
        lt._get_batch_pg_status = MagicMock(side_effect=lambda bid: pg["status"])

        lt.submit_batches(run_record)
        pg["status"] = "failed"
        lt._status_override["batch-build"] = "failure"
        lt._status_override["batch-dast"] = "failure"

        lt.poll()
        assert len(callback_calls) == 1
        assert callback_calls[0] == ("run-test-1", False)

    def test_poll_not_all_terminal_no_callback(self, executor, run_record):
        callback_calls = []
        lt = BatchExecutor(
            adapter=executor._adapter, dry_run=True,
            on_all_terminal=lambda rid, ok: callback_calls.append((rid, ok)),
        )
        lt._query_batches = MagicMock(return_value=_make_batch_orms())
        lt._update_batch_pg = MagicMock()
        lt._update_batch_pg_terminal = MagicMock()
        pg = {"status": "pending"}
        lt._get_batch_pg_status = MagicMock(side_effect=lambda bid: pg["status"])

        lt.submit_batches(run_record)
        pg["status"] = "running"
        lt._status_override["batch-build"] = "success"

        lt.poll()
        assert len(callback_calls) == 0

    def test_poll_adapter_error_graceful(self, executor, run_record):
        from orchestrator.cosmo.adapters.execution_woodpecker import WoodpeckerAdapter
        real_adapter = WoodpeckerAdapter(base_url="http://localhost:8000", token="test")
        real_adapter.get_status = MagicMock(side_effect=Exception("network error"))
        real_adapter.submit_run = MagicMock(return_value={
            "id": 1, "number": 1, "repo_owner": "cosmo", "repo_name": "default"})

        lt = BatchExecutor(adapter=real_adapter, dry_run=False)
        lt._query_batches = MagicMock(return_value=[_make_batch_orms()[0]])
        lt._update_batch_pg = MagicMock()
        lt._get_batch_pg_status = MagicMock(return_value="pending")

        lt.submit_batches(run_record)
        assert "batch-build" in lt.active_batches()

        # COS-097 honesty: ошибка транспорта — видимый unknown-result
        # (счётчик подряд-неизвестных), не тихий no-op.
        results = lt.poll()
        assert len(results) == 1
        assert results[0].terminal is False
        assert results[0].raw_status == "unknown"
        assert "batch-build" in lt.active_batches()


class TestCancel:
    def test_cancel_marks_blocked(self, executor, run_record):
        executor._query_batches = MagicMock(return_value=_make_batch_orms())
        executor._update_batch_pg = MagicMock()
        executor._update_batch_pg_terminal = MagicMock()
        executor._adapter.cancel_run = MagicMock(return_value=True)

        executor.submit_batches(run_record)
        cancelled = executor.cancel_batches(run_record)
        assert len(cancelled) == 2
        assert "batch-build" in cancelled
        assert "batch-dast" in cancelled
        assert len(executor.active_batches()) == 0

    def test_cancel_dry_run_skips_adapter(self, executor, run_record):
        executor._query_batches = MagicMock(return_value=_make_batch_orms())
        executor._update_batch_pg = MagicMock()
        executor._update_batch_pg_terminal = MagicMock()

        executor.submit_batches(run_record)
        cancelled = executor.cancel_batches(run_record)
        assert len(cancelled) == 2

    def test_cancel_adapter_error_graceful(self, executor, run_record):
        executor._query_batches = MagicMock(return_value=[_make_batch_orms()[0]])
        executor._update_batch_pg = MagicMock()
        executor._update_batch_pg_terminal = MagicMock()
        executor._adapter.cancel_run = MagicMock(side_effect=Exception("cancel failed"))

        executor.submit_batches(run_record)
        cancelled = executor.cancel_batches(run_record)
        assert len(cancelled) == 1
        assert len(executor.active_batches()) == 0


class TestStatusMapping:
    @pytest.mark.parametrize("wp_status,expected", [
        ("pending", "pending"),
        ("running", "running"),
        ("success", "passed"),
        ("failure", "failed"),
        ("killed", "failed"),
        ("error", "failed"),
    ])
    def test_woodpecker_to_batch_status(self, wp_status, expected):
        from orchestrator.cosmo.control_plane.executor import _STATUS_MAP
        assert _STATUS_MAP[wp_status] == expected

    def test_terminal_wp_statuses(self):
        # COS-097: declined/skipped — честные terminal-статусы v3.5
        # (blocked ждёт approval — НЕ terminal).
        from orchestrator.cosmo.control_plane.executor import _TERMINAL_WP
        assert _TERMINAL_WP == frozenset(
            {"success", "failure", "killed", "error", "declined", "skipped"})

    def test_terminal_batch_statuses(self):
        from orchestrator.cosmo.control_plane.executor import _TERMINAL_BATCH
        assert _TERMINAL_BATCH == frozenset({"passed", "failed", "blocked"})


class TestLifecycle:
    def test_reset_clears_all_state(self, executor, run_record):
        executor._query_batches = MagicMock(return_value=_make_batch_orms())
        executor._update_batch_pg = MagicMock()

        executor.submit_batches(run_record)
        assert len(executor.active_batches()) == 2

        executor.reset()
        assert len(executor.active_batches()) == 0
        assert executor._status_override == {}
        assert executor._submit_fail_batch_ids == set()

    def test_active_batches_returns_snapshot(self, executor, run_record):
        executor._query_batches = MagicMock(return_value=[_make_batch_orms()[0]])
        executor._update_batch_pg = MagicMock()

        executor.submit_batches(run_record)
        snapshot = executor.active_batches()
        assert "batch-build" in snapshot
        snapshot.clear()
        assert "batch-build" in executor.active_batches()


class TestIntegration:
    def test_set_executor_wires_callback(self, executor):
        c = RunControlPlane()
        c.set_executor(executor)
        assert executor._on_all_terminal is not None
        assert executor._on_all_terminal == c._on_batches_terminal

    def test_set_executor_shares_db_factory(self, executor):
        fake_factory = MagicMock()
        c = RunControlPlane(db_session_factory=fake_factory)
        c.set_executor(executor)
        assert executor._db_session_factory is fake_factory

    def test_executor_submitted_on_running(self, executor):
        c = RunControlPlane()
        c.register_worker("w1", frozenset({"dast"}))

        executor.submit_batches_async = MagicMock()
        c.set_executor(executor)

        run, _ = c.create_run({"plan_id": "p", "domain_id": "d"}, frozenset({"dast"}))
        c.submit_run(run.id)
        c.enqueue_run(run.id)

        assert run.state == RunState.RUNNING
        executor.submit_batches_async.assert_called_once()

    def test_on_batches_terminal_all_passed(self, executor):
        c = RunControlPlane()
        c.register_worker("w1", frozenset({"dast"}))

        executor.submit_batches_async = MagicMock()
        c.set_executor(executor)

        run, _ = c.create_run({"plan_id": "p", "domain_id": "d"}, frozenset({"dast"}))
        c.submit_run(run.id)
        c.enqueue_run(run.id)
        assert run.state == RunState.RUNNING

        c._on_batches_terminal(run.id, all_passed=True)
        assert run.state == RunState.SUCCEEDED

    def test_on_batches_terminal_all_failed(self, executor):
        c = RunControlPlane()
        c.register_worker("w1", frozenset({"dast"}))

        executor.submit_batches_async = MagicMock()
        c.set_executor(executor)

        run, _ = c.create_run({"plan_id": "p", "domain_id": "d"}, frozenset({"dast"}))
        c.submit_run(run.id)
        c.enqueue_run(run.id)
        assert run.state == RunState.RUNNING

        c._on_batches_terminal(run.id, all_passed=False)
        assert run.state == RunState.BLOCKED
        assert run.failure_class == FailureClass.GATE

    def test_on_batches_terminal_ignores_non_running(self, executor):
        c = RunControlPlane()
        executor.submit_batches_async = MagicMock()
        c.set_executor(executor)

        run, _ = c.create_run({"plan_id": "p", "domain_id": "d"})
        c._on_batches_terminal(run.id, all_passed=True)
        assert run.state == RunState.DRAFT

    def test_on_batches_terminal_nonexistent(self, executor):
        c = RunControlPlane()
        executor.submit_batches_async = MagicMock()
        c.set_executor(executor)
        c._on_batches_terminal("nonexistent", all_passed=True)

    def test_poll_batches_delegates(self, executor):
        c = RunControlPlane()
        executor.poll = MagicMock(return_value=[BatchPollResult("b1", "r1", "running", "passed", True)])
        c.set_executor(executor)

        results = c.poll_batches()
        assert len(results) == 1
        assert results[0].batch_id == "b1"

    def test_poll_batches_none_without_executor(self):
        c = RunControlPlane()
        assert c.poll_batches() == []

    def test_reset_clears_executor(self, executor):
        c = RunControlPlane()
        c.set_executor(executor)

        executor._query_batches = MagicMock(return_value=[_make_batch_orms()[0]])
        executor._update_batch_pg = MagicMock()
        executor.submit_batches(RunRecord(id="r1", plan_id="p", domain_id="d"))

        assert len(executor.active_batches()) == 1
        c.reset()
        assert len(executor.active_batches()) == 0

    def test_no_executor_no_error(self):
        c = RunControlPlane()
        c.register_worker("w1", frozenset({"dast"}))

        run, _ = c.create_run({"plan_id": "p", "domain_id": "d"}, frozenset({"dast"}))
        c.submit_run(run.id)
        c.enqueue_run(run.id)
        assert run.state == RunState.RUNNING

    def test_set_executor_none_disables(self, executor):
        c = RunControlPlane()
        c.set_executor(executor)
        c.set_executor(None)
        assert c._executor is None
        assert c.poll_batches() == []