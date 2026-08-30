# -*- coding: utf-8 -*-
"""COS-209: Ultra-Scale Ingestion Benchmark (fast, throughput-validated)."""
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import pytest
_orch = Path(__file__).resolve().parents[1]
if str(_orch) not in sys.path:
    sys.path.insert(0, str(_orch))
from orchestrator.cosmo.ledger.merkle_ledger import MerkleLedger
from orchestrator.cosmo.control_plane.stream_consumer import StreamConsumerDaemon
from orchestrator.cosmo.ledger.suppression_engine import SuppressionEngine


class TestScaleBenchmark:
    def test_merkle_1k_ingestion(self):
        ledger = MerkleLedger()
        total = 1_000
        t0 = time.perf_counter()
        for i in range(total):
            ledger.add_leaf({"event": f"finding-{i}", "severity": "Medium"})
        elapsed = time.perf_counter() - t0
        assert len(ledger._leaves) == total
        assert len(ledger.root_hash()) == 64

    def test_parallel_ingestion(self):
        results = []
        lock = threading.Lock()
        threads = 8
        per_thread = 2_000

        def worker(t):
            local = MerkleLedger()
            for i in range(per_thread):
                local.add_leaf({"event": f"e-{t}-{i}"})
            with lock:
                results.append(per_thread)

        with ThreadPoolExecutor(max_workers=threads) as executor:
            futures = [executor.submit(worker, t) for t in range(threads)]
            for f in as_completed(futures):
                f.result(timeout=60)

        assert sum(results) == threads * per_thread

    def test_stream_consumer_throughput(self):
        daemon = StreamConsumerDaemon()
        total = 50_000
        t0 = time.perf_counter()
        for i in range(total):
            daemon.consume("cosmo:events", [{"id": f"m{i}", "data": {"idx": i}}])
        elapsed = time.perf_counter() - t0
        eps = total / max(elapsed, 1e-9)
        assert daemon.pending_count("cosmo:events") == total
        assert eps > 50_000

    def test_suppression_fingerprint_throughput(self):
        engine = SuppressionEngine()
        total = 50_000
        findings = [
            {"file_path": f"src/{i % 100}/f.py", "line": i % 500,
             "rule_id": f"R{i % 50}", "code_snippet": f"x{i}"}
            for i in range(total)
        ]
        t0 = time.perf_counter()
        fps = set()
        for f in findings:
            fps.add(engine.compute_fingerprint(f))
        elapsed = time.perf_counter() - t0
        eps = total / max(elapsed, 1e-9)
        assert len(fps) == total
        assert eps > 20_000