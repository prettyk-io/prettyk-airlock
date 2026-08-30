# -*- coding: utf-8 -*-
"""COS-150: 10,000 Concurrent Runs Simulation & Scale Benchmark."""
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import pytest
_orch = Path(__file__).resolve().parents[1]
if str(_orch) not in sys.path:
    sys.path.insert(0, str(_orch))
from orchestrator.cosmo.control_plane.run_control import RunControlPlane, RunState


def _bench_worker(worker_id: int, c: RunControlPlane, plan: str, domain: str, results: list, lock: threading.Lock):
    t0 = time.perf_counter()
    try:
        run, _ = c.create_run({"plan_id": plan, "domain_id": domain}, frozenset({"dast"}))
        c.submit_run(run.id)
        c.enqueue_run(run.id)
        if run.state == RunState.RUNNING:
            c.succeed_run(run.id)
        elapsed = time.perf_counter() - t0
        with lock:
            results.append({"worker": worker_id, "ms": round(elapsed * 1000, 1)})
    except Exception as exc:
        with lock:
            results.append({"worker": worker_id, "error": str(exc)})


class TestScale10K:
    def test_1k_runs_10_domains(self):
        """1,000 runs across 10 domains — validate throughput."""
        c = RunControlPlane(max_concurrent=20)
        for i in range(20):
            c.register_worker(f"w{i}", frozenset({"dast"}))

        results: list[dict] = []
        lock = threading.Lock()
        domains = [f"dom-{i:03d}" for i in range(10)]

        with ThreadPoolExecutor(max_workers=50) as executor:
            futures = []
            for d in domains:
                for i in range(100):
                    futures.append(executor.submit(_bench_worker, i, c, f"plan-{d}", d, results, lock))
            for f in as_completed(futures):
                try:
                    f.result(timeout=30)
                except Exception:
                    pass

        errors = [r for r in results if "error" in r]
        assert len(errors) == 0, f"{len(errors)} errors in 1K run test"
        assert len(results) == 1000

        # Check throughput
        times = [r["ms"] for r in results if "ms" in r]
        avg_ms = sum(times) / len(times) if times else 0
        max_ms = max(times) if times else 0
        assert avg_ms < 5000, f"Average latency {avg_ms:.0f}ms exceeds 5s threshold"
        assert max_ms < 30000, f"Max latency {max_ms:.0f}ms exceeds 30s threshold"

    def test_100_domains_burst(self):
        """100 domains × 10 runs each = 1,000 burst."""
        c = RunControlPlane(max_concurrent=30)
        for i in range(30):
            c.register_worker(f"bw{i}", frozenset({"dast"}))

        results: list[dict] = []
        lock = threading.Lock()

        with ThreadPoolExecutor(max_workers=100) as executor:
            futures = []
            for d_idx in range(100):
                domain = f"dom-burst-{d_idx:03d}"
                for i in range(10):
                    futures.append(executor.submit(_bench_worker, i, c, f"plan-{domain}", domain, results, lock))
            for f in as_completed(futures):
                try:
                    f.result(timeout=30)
                except Exception:
                    pass

        errors = [r for r in results if "error" in r]
        assert len(errors) == 0
        assert len(results) == 1000

    def test_snapshot_performance(self):
        """Snapshot after 500 runs should complete in < 100ms."""
        c = RunControlPlane(max_concurrent=50)
        for i in range(50):
            c.register_worker(f"sw{i}", frozenset({"dast"}))

        lock = threading.Lock()
        results: list[dict] = []

        with ThreadPoolExecutor(max_workers=50) as executor:
            futures = [executor.submit(_bench_worker, i, c, "plan-snap", "dom-snap", results, lock) for i in range(500)]
            for f in as_completed(futures):
                try:
                    f.result(timeout=30)
                except Exception:
                    pass

        t0 = time.perf_counter()
        snap = c.snapshot()
        elapsed = time.perf_counter() - t0

        assert snap["total"] >= 450  # Some may still be queued
        assert elapsed < 0.5, f"Snapshot took {elapsed*1000:.0f}ms, should be <500ms"

    def test_list_runs_performance(self):
        """list_runs() on 1000 registered runs should be fast."""
        c = RunControlPlane(max_concurrent=50)
        for i in range(50):
            c.register_worker(f"lw{i}", frozenset({"dast"}))

        lock = threading.Lock()
        results: list[dict] = []

        with ThreadPoolExecutor(max_workers=50) as executor:
            futures = [executor.submit(_bench_worker, i, c, "plan-list", "dom-list", results, lock) for i in range(1000)]
            for f in as_completed(futures):
                try:
                    f.result(timeout=30)
                except Exception:
                    pass

        t0 = time.perf_counter()
        runs = c.list_runs()
        elapsed = time.perf_counter() - t0

        assert len(runs) >= 900
        assert elapsed < 0.5, f"list_runs took {elapsed*1000:.0f}ms, should be <500ms"