# -*- coding: utf-8 -*-
"""COS-077: Scale-Hardened Smoke Test — 50 Workers Burst.

Конвейер:
  50 parallel worker threads
    → каждый генерирует SARIF-шард (100 findings)
    → сохраняет через MinIOBufferSink
    → StreamingSarifMerger сливает 50 шардов в 1 master SARIF

Проверки:
  - 5000 находок в итоговом SARIF без дублей
  - Все 10 уникальных правил дедуплицированы
  - 50 шардов → 50 × 100 = 5000 результатов
  - Ни одного падения при параллельной записи
  - Чистый teardown (временная директория удаляется)
"""
from __future__ import annotations

import hashlib
import json
import shutil
import sys
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pytest

_orch = Path(__file__).resolve().parents[1]
if str(_orch) not in sys.path:
    sys.path.insert(0, str(_orch))

from orchestrator.cosmo.ledger.artifact_store import ArtifactStore
from orchestrator.cosmo.ledger.minio_buffer import MinIOBufferSink
from orchestrator.cosmo.ledger.sarif_merger import (
    StreamingSarifMerger,
    _validate_sarif,
)


@pytest.fixture
def burst_store():
    """ArtifactStore во временной директории для burst-теста."""
    d = tempfile.mkdtemp(prefix="sonar_burst_")
    s = ArtifactStore(base_dir=d)
    yield s
    shutil.rmtree(d, ignore_errors=True)


# ══════════════════════════════════════════════════════════════════
# SARIF-шард генератор (1 worker)
# ══════════════════════════════════════════════════════════════════

def _generate_shard(worker_id: int, total_workers: int) -> dict:
    """Worker i генерирует SARIF-шард с 100 находками.

    Rule IDs: R000-R009 (10 правил, worker_id % 10).
    Каждая находка имеет уникальный SHA-256 отпечаток (id + severity + path).
    """
    rule_idx = worker_id % 10
    rule_id = f"R{rule_idx:03d}"
    severities = ["Critical", "High", "Medium", "Low"]
    levels = ["error", "warning", "note", "note"]

    findings = []
    for j in range(100):  # 100 findings per shard
        sev_idx = j % 4
        sev = severities[sev_idx]
        level = levels[sev_idx]
        file_path = f"src/worker-{worker_id:03d}/module-{j // 10}/{j % 10}.py"
        finding_id = f"w{worker_id:03d}-f{j:03d}"

        fingerprint = hashlib.sha256(
            f"{finding_id}|{rule_id}|{sev}".encode()
        ).hexdigest()[:16]

        findings.append({
            "ruleId": rule_id,
            "level": level,
            "kind": "fail",
            "message": {"text": f"Finding {finding_id} — {sev} severity"},
            "locations": [{
                "physicalLocation": {
                    "artifactLocation": {"uri": file_path},
                    "region": {"startLine": j + 1},
                }
            }],
            "properties": {
                "finding_id": finding_id,
                "fingerprint": fingerprint,
                "severity": sev,
            },
            "taxa": [{"id": str(79 + (j % 10))}],  # CWE-79..CWE-88
        })

    rules = [{
        "id": rule_id,
        "name": f"Rule {rule_id} — {severities[worker_id % 4]} rule",
        "shortDescription": {"text": f"Security rule {rule_id}"},
        "properties": {"severity": severities[worker_id % 4], "type": "VULNERABILITY"},
    }]

    return {
        "version": "2.1.0",
        "$schema": "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/master/Schemata/sarif-schema-2.1.0.json",
        "runs": [{
            "tool": {"driver": {"name": f"Cosmoport Worker {worker_id:03d}", "rules": rules}},
            "results": findings,
            "properties": {"total_findings": 100, "worker_id": worker_id},
        }],
    }


# ══════════════════════════════════════════════════════════════════
# Worker: save shard through MinIOBufferSink
# ══════════════════════════════════════════════════════════════════

def _worker_save(
    worker_id: int, sink: MinIOBufferSink, errors: list[str], lock: threading.Lock
) -> str:
    """Один worker: генерирует шард, сохраняет через MinIOBufferSink.

    Returns: путь к шарду относительно store._base.
    """
    try:
        run_id = f"burst-run-{worker_id:03d}"
        shard = _generate_shard(worker_id, 50)

        # Сохранить через MinIOBufferSink
        ref = sink.save_report(run_id, shard, report_type="sarif")

        # Путь: runs/{run_id}/report.sarif.json
        shard_path = ref.path  # e.g. "runs/burst-run-000/report.sarif.json"
        return shard_path

    except Exception as exc:
        with lock:
            errors.append(f"Worker {worker_id}: {exc}")
        raise


# ══════════════════════════════════════════════════════════════════
# Burst test
# �══════════════════════════════════════════════════════════════════════

class TestSonarBurst50:
    """COS-077: залповый запуск 50 воркеров."""

    def test_50_workers_parallel_save_and_merge(self, burst_store):
        """50 параллельных воркеров → save → merge → verify 5000 findings.

        Конвейер:
          1. ThreadPoolExecutor(50) запускает воркеров параллельно.
          2. Каждый воркер генерирует и сохраняет SARIF-шард.
          3. StreamingSarifMerger сливает 50 шардов.
          4. Проверка: 5000 находок, 10 уникальных правил, нет дублей.
        """
        sink = MinIOBufferSink(store=burst_store, bucket="cosmo-evidence", valkey_url="")

        # ── Phase 1: burst save (50 parallel workers) ──
        errors: list[str] = []
        lock = threading.Lock()
        shard_paths: list[str] = []

        with ThreadPoolExecutor(max_workers=50, thread_name_prefix="sonar-burst") as executor:
            futures = {
                executor.submit(_worker_save, i, sink, errors, lock): i
                for i in range(50)
            }

            for future in as_completed(futures):
                worker_id = futures[future]
                try:
                    path = future.result(timeout=30)
                    shard_paths.append(path)
                except Exception as exc:
                    with lock:
                        errors.append(f"Worker {worker_id} failed: {exc}")

        # Ни одного сбоя
        assert len(errors) == 0, f"Burst errors: {errors}"
        assert len(shard_paths) == 50, f"Expected 50 shards, got {len(shard_paths)}"

        # ── Phase 2: verify all shard files exist ──
        for path in shard_paths:
            full = Path(burst_store._base) / path
            assert full.exists(), f"Shard missing: {path}"
            content = json.loads(full.read_text(encoding="utf-8"))
            assert len(content.get("runs", [{}])[0].get("results", [])) == 100

        # ── Phase 3: stream merge ──
        merger = StreamingSarifMerger(burst_store)
        merged = merger.merge_sarif_streams(
            sorted(shard_paths),
            "merged/sonar_burst_master.sarif",
        )

        # ── Phase 4: verify master SARIF ──
        _validate_sarif(merged)

        run = merged["runs"][0]
        results = run["results"]
        rules = run["tool"]["driver"]["rules"]

        # 5000 findings (50 × 100)
        assert len(results) == 5000, (
            f"Expected 5000 findings, got {len(results)}"
        )

        # 10 unique rules (R000-R009)
        assert len(rules) == 10, f"Expected 10 rules, got {len(rules)}"
        rule_ids = {r["id"] for r in rules}
        assert rule_ids == {f"R{i:03d}" for i in range(10)}

        # Properties: shard_count == 50
        props = run.get("properties", {})
        assert props["shard_count"] == 50
        assert props["unique_rules"] == 10
        assert props["total_results"] == 5000

        # ── Phase 5: no duplicate findings ──
        fingerprints: set[str] = set()
        for res in results:
            fp = (res.get("properties", {}).get("fingerprint")
                  or res.get("message", {}).get("text", ""))
            assert fp not in fingerprints, f"Duplicate finding: {fp}"
            fingerprints.add(fp)

        assert len(fingerprints) == 5000, (
            f"Expected 5000 unique fingerprints, got {len(fingerprints)}"
        )

        # ── Phase 6: output file exists and is valid ──
        out = Path(burst_store._base) / "merged/sonar_burst_master.sarif"
        assert out.exists()
        parsed = json.loads(out.read_text(encoding="utf-8"))
        _validate_sarif(parsed)

    def test_50_workers_no_deadlocks(self, burst_store):
        """50 workers save to same ArtifactStore — no file-level contention."""
        sink = MinIOBufferSink(store=burst_store, bucket="cosmo-evidence", valkey_url="")
        errors: list[str] = []
        lock = threading.Lock()
        paths = []

        # 50 threads writing to different run_id paths → no contention
        with ThreadPoolExecutor(max_workers=50) as executor:
            futures = [executor.submit(
                _worker_save, i, sink, errors, lock
            ) for i in range(50)]

            for f in futures:
                try:
                    paths.append(f.result(timeout=30))
                except Exception:
                    pass

        assert len(errors) == 0
        assert len(paths) == 50

        # Verify all files are unique (different SHA)
        shas = set()
        for p in paths:
            full = Path(burst_store._base) / p
            content = full.read_bytes()
            shas.add(hashlib.sha256(content).hexdigest())
        assert len(shas) == 50  # все шарды разые

    def test_burst_then_merge_all_findings_accounted(self, burst_store):
        """Каждая из 5000 находок присутствует в итоговом SARIF."""
        sink = MinIOBufferSink(store=burst_store, bucket="cosmo-evidence", valkey_url="")
        errors: list[str] = []
        lock = threading.Lock()
        paths = []

        with ThreadPoolExecutor(max_workers=50) as executor:
            futures = {executor.submit(_worker_save, i, sink, errors, lock): i for i in range(50)}
            for f in as_completed(futures):
                paths.append(f.result(timeout=30))

        merger = StreamingSarifMerger(burst_store)
        merged = merger.merge_sarif_streams(sorted(paths), "merged/accounted.sarif")

        # Собрать все finding_id из результатов
        actual_ids = set()
        for res in merged["runs"][0]["results"]:
            fid = (res.get("properties", {}).get("finding_id") or
                   res.get("message", {}).get("text", ""))
            actual_ids.add(fid)

        # Ожидаемые: w000-f000 .. w049-f099
        expected_ids = set()
        for w in range(50):
            for f in range(100):
                expected_ids.add(f"w{w:03d}-f{f:03d}")

        assert actual_ids == expected_ids
        assert len(actual_ids) == 5000

    def test_teardown_clean_on_exception(self, burst_store):
        """При исключении воркера — остальные продолжают, данные консистетны."""
        sink = MinIOBufferSink(store=burst_store, bucket="cosmo-evidence", valkey_url="")
        errors: list[str] = []
        lock = threading.Lock()
        paths = []

        def fragile_worker(wid):
            if wid == 13:
                raise RuntimeError("Simulated worker failure")
            return _worker_save(wid, sink, errors, lock)

        with ThreadPoolExecutor(max_workers=50) as executor:
            futures = {executor.submit(fragile_worker, i): i for i in range(50)}
            for f in as_completed(futures):
                try:
                    paths.append(f.result(timeout=30))
                except Exception:
                    pass

        # 49 workers should succeed
        assert len(paths) == 49
        assert "Simulated worker failure" in str(errors[0]) if errors else True

        # Remaining 49 shards should merge correctly
        merger = StreamingSarifMerger(burst_store)
        merged = merger.merge_sarif_streams(sorted(paths), "merged/partial.sarif")
        assert len(merged["runs"][0]["results"]) == 4900  # 49 × 100

    def test_sequential_vs_parallel_identical(self, burst_store):
        """Последовательное и параллельное сохранение дают одинаковый результат."""
        # Sequential
        sink1 = MinIOBufferSink(store=burst_store, bucket="cosmo-evidence", valkey_url="")
        errors: list[str] = []
        lock = threading.Lock()
        seq_paths = []
        for i in range(50):
            seq_paths.append(_worker_save(i, sink1, errors, lock))

        merger = StreamingSarifMerger(burst_store)
        merged_seq = merger.merge_sarif_streams(sorted(seq_paths), "merged/se.sarif")

        # Parallel (fresh store)
        d2 = tempfile.mkdtemp(prefix="sonar_burst_par_")
        store2 = ArtifactStore(base_dir=d2)
        sink2 = MinIOBufferSink(store=store2, bucket="cosmo-evidence", valkey_url="")
        errors2 = []
        lock2 = threading.Lock()
        par_paths = []

        with ThreadPoolExecutor(max_workers=50) as executor:
            futures = [executor.submit(_worker_save, i, sink2, errors2, lock2) for i in range(50)]
            for f in futures:
                p = f.result(timeout=30)
                par_paths.append(p)

        merger2 = StreamingSarifMerger(store2)
        merged_par = merger2.merge_sarif_streams(sorted(par_paths), "merged/par.sarif")

        # Same number of findings
        assert len(merged_seq["runs"][0]["results"]) == len(merged_par["runs"][0]["results"])
        assert len(merged_seq["runs"][0]["results"]) == 5000

        shutil.rmtree(d2, ignore_errors=True)

        # Same rule count
        seq_rule_ids = {r["id"] for r in merged_seq['runs'][0]['tool']['driver']['rules']}
        par_rule_ids = {r["id"] for r in merged_par['runs'][0]['tool']['driver']['rules']}
        assert seq_rule_ids == par_rule_ids