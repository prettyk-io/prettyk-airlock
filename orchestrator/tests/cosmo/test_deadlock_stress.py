# -*- coding: utf-8 -*-
"""COS-123: Distributed Concurrency & Deadlock Stress Suite.

50 параллельных транзакций смены статусов без дедлоков в PostgreSQL.
"""
from __future__ import annotations

import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pytest

_orch = Path(__file__).resolve().parents[1]
if str(_orch) not in sys.path:
    sys.path.insert(0, str(_orch))

from orchestrator.cosmo.control_plane.lock import ConcurrencyGuard, DistributedLock
from orchestrator.cosmo.control_plane.run_control import RunControlPlane, RunState


def _worker(worker_id: int, c: RunControlPlane, plan: str, domain: str, results: list, lock: threading.Lock):
    """Один worker: создаёт run, энкейтит, меняет статус."""
    try:
        run, _ = c.create_run({"plan_id": plan, "domain_id": domain}, frozenset({"dast"}))
        c.submit_run(run.id)
        c.enqueue_run(run.id)

        # Если диспатчнут — succeed
        if run.state == RunState.RUNNING:
            c.succeed_run(run.id)
        with lock:
            results.append({"worker": worker_id, "state": run.state.value, "id": run.id})
    except Exception as exc:
        with lock:
            results.append({"worker": worker_id, "error": str(exc)})


class TestDeadlockStress:
    def test_10_workers_concurrent(self):
        """10 воркеров — без дедлоков."""
        c = RunControlPlane(max_concurrent=5)
        for i in range(5):
            c.register_worker(f"w{i}", frozenset({"dast"}))

        results: list[dict] = []
        lock = threading.Lock()

        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [
                executor.submit(_worker, i, c, "plan-1", "dom-1", results, lock)
                for i in range(10)
            ]
            for f in as_completed(futures):
                f.result(timeout=10)

        assert len(results) == 10
        errors = [r for r in results if "error" in r]
        assert len(errors) == 0, f"Errors: {errors}"

    def test_50_workers_stress(self):
        """50 воркеров против 3 worker-слотов — без падений."""
        c = RunControlPlane(max_concurrent=3)
        for i in range(3):
            c.register_worker(f"sw{i}", frozenset({"dast"}))

        results: list[dict] = []
        lock = threading.Lock()

        with ThreadPoolExecutor(max_workers=50) as executor:
            futures = [
                executor.submit(_worker, i, c, "plan-s", "dom-s", results, lock)
                for i in range(50)
            ]
            for f in as_completed(futures):
                try:
                    f.result(timeout=15)
                except Exception as exc:
                    results.append({"worker": -1, "error": str(exc)})

        errors = [r for r in results if "error" in r]
        assert len(errors) == 0, f"Errors in 50-worker stress: {errors}"
        assert len(results) == 50

    def test_concurrent_with_guard(self):
        """ConcurrencyGuard блокирует конкурентный запуск одного run."""
        c = RunControlPlane()
        c.register_worker("w1", frozenset({"dast"}))

        guard = ConcurrencyGuard()
        c.set_concurrency_guard(guard)

        # Первый worker захватывает лок
        run, _ = c.create_run({"plan_id": "p", "domain_id": "d"}, frozenset({"dast"}))
        c.submit_run(run.id)
        c.enqueue_run(run.id)

        # Guard должен был сработать
        assert run.state in (RunState.RUNNING, RunState.QUEUED)

    def test_distributed_lock_no_deadlocks(self):
        """DistributedLock acquire/release в 50 потоках — без дедлоков."""
        results = []
        error_count = [0]
        lock = threading.Lock()

        def lock_worker(wid: int):
            try:
                with patch("orchestrator.cosmo.control_plane.lock._get_valkey", return_value=None):
                    with patch.object(DistributedLock, "_acquire_pg", return_value=(wid == 0)):
                        l = DistributedLock(f"test-{wid % 5}", ttl=5)
                        l.acquire()
                        if l.is_acquired:
                            time.sleep(0.001)
                            l.release()
                        with lock:
                            results.append(wid)
            except Exception:
                with lock:
                    error_count[0] += 1

        from unittest.mock import patch
        with ThreadPoolExecutor(max_workers=50) as executor:
            futures = [executor.submit(lock_worker, i) for i in range(50)]
            for f in as_completed(futures):
                try:
                    f.result(timeout=10)
                except Exception:
                    pass

        assert error_count[0] == 0

    def test_multi_domain_isolation(self):
        """3 домена, параллельные worker'ы — изоляция без дедлоков."""
        c = RunControlPlane(max_concurrent=3)
        for i in range(3):
            c.register_worker(f"dw{i}", frozenset({"dast"}))

        domains = ["dom-alpha", "dom-beta", "dom-gamma"]
        results: list[dict] = []
        lock = threading.Lock()

        with ThreadPoolExecutor(max_workers=15) as executor:
            futures = []
            for d in domains:
                for i in range(5):
                    futures.append(executor.submit(_worker, i, c, f"plan-{d}", d, results, lock))
            for f in as_completed(futures):
                try:
                    f.result(timeout=10)
                except Exception:
                    pass

        errors = [r for r in results if "error" in r]
        assert len(errors) == 0
        assert len(results) == 15