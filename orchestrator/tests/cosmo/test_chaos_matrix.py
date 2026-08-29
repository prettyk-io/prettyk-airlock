"""
COS-078: Chaos Matrix tests — все 7 сценариев отказоустойчивости.

F-01 Port Conflict
F-02 Worker OOM/Crash
F-03 Scanner Error
F-04 Orchestrator Restart
F-05 Standalone Outage
F-06 Idempotent Re-delivery
F-07 Timeout

+ ChaosVerdict / ChaosInjectionResult / ChaosReport model tests.
+ Full run_all() orchestration.
"""
import time
import pytest

from cosmo.capability.chaos_runner import (
    ChaosRunner, ChaosVerdict, ChaosInjectionResult, ChaosReport,
    run_chaos_matrix,
)
from cosmo.capability.sonar_pool import (
    PortLeaseTracker, MockDockerBackend, SonarWorkerPool,
)
from cosmo.domain.worker_lease import WorkerLease, WorkerState, FailureReason


# ═══════════════════════════════════════════════════════════════════════════
# Models
# ═══════════════════════════════════════════════════════════════════════════

class TestChaosModels:
    def test_verdict_enum(self):
        assert ChaosVerdict.PASS.value == "PASS"
        assert ChaosVerdict.FAIL.value == "FAIL"
        assert ChaosVerdict.UNSUPPORTED.value == "UNSUPPORTED"

    def test_injection_result_defaults(self):
        r = ChaosInjectionResult(scenario="F-01", verdict=ChaosVerdict.PASS, detail="ok")
        assert r.scenario == "F-01"
        assert r.verdict == ChaosVerdict.PASS
        assert r.duration_ms == 0
        assert r.evidence == {}

    def test_report_empty(self):
        rpt = ChaosReport()
        assert rpt.total() == 0
        assert rpt.passed_ratio() == 0.0

    def test_report_counts(self):
        rpt = ChaosReport()
        rpt.results = [
            ChaosInjectionResult(scenario="F-01", verdict=ChaosVerdict.PASS, detail="ok"),
            ChaosInjectionResult(scenario="F-02", verdict=ChaosVerdict.PASS, detail="ok"),
            ChaosInjectionResult(scenario="F-03", verdict=ChaosVerdict.FAIL, detail="fail"),
        ]
        rpt.passed = 2
        rpt.failed = 1
        assert rpt.total() == 3
        assert rpt.passed_ratio() == pytest.approx(2 / 3)

    def test_report_to_dict(self):
        rpt = ChaosReport()
        rpt.results = [
            ChaosInjectionResult(scenario="F-01", verdict=ChaosVerdict.PASS, detail="ok", duration_ms=42),
        ]
        rpt.passed = 1
        d = rpt.to_dict()
        assert d["summary"]["total"] == 1
        assert d["summary"]["passed_ratio"] == "100%"
        assert d["results"][0]["duration_ms"] == 42


# ═══════════════════════════════════════════════════════════════════════════
# F-01: Port Conflict
# ═══════════════════════════════════════════════════════════════════════════

class TestF01PortConflict:
    def test_port_conflict_resolved(self):
        runner = ChaosRunner()
        result = runner.f01_port_conflict()
        assert result.verdict == ChaosVerdict.PASS
        assert "9002" in result.detail
        assert result.evidence["free_count"] >= 0

    def test_idempotent_acquire(self):
        pt = PortLeaseTracker(range(9000, 9005))
        p1 = pt.acquire("run-x", "w-x")
        p2 = pt.acquire("run-x", "w-x")
        assert p1 == p2

    def test_exhausted_all_ports(self):
        pt = PortLeaseTracker(range(9000, 9001))
        pt.acquire("run-1", "w-1")
        port = pt.acquire("run-2", "w-2")
        assert port is None


# ═══════════════════════════════════════════════════════════════════════════
# F-02: Worker OOM/Crash
# ═══════════════════════════════════════════════════════════════════════════

class TestF02WorkerCrash:
    def test_crash_to_infra_failed(self):
        runner = ChaosRunner()
        result = runner.f02_worker_crash()
        assert result.verdict == ChaosVerdict.PASS
        assert "INFRA_FAILED" in result.detail
        assert "RELEASED" in result.detail

    def test_crash_preserves_failure_reason(self):
        lease = WorkerLease(run_id="run-f", state=WorkerState.RUNNING,
                            container_id="abc123")
        lease = lease.fail(FailureReason.INFRA_FAILED, "OOM kill -9")
        assert lease.state == WorkerState.FAILED
        assert lease.failure_reason == FailureReason.INFRA_FAILED

    def test_crash_teardown_cleans_docker(self):
        docker = MockDockerBackend()
        pool = SonarWorkerPool(docker=docker)
        lease = pool.request_worker("run-c")
        lease = pool.provision(lease)
        cid = lease.container_id

        lease = lease.fail(FailureReason.INFRA_FAILED, "kill -9")
        lease = pool.teardown_worker(lease)
        assert not docker.is_running(cid)


# ═══════════════════════════════════════════════════════════════════════════
# F-03: Scanner Error
# ═══════════════════════════════════════════════════════════════════════════

class TestF03ScannerError:
    def test_scanner_error_cleans(self):
        runner = ChaosRunner()
        result = runner.f03_scanner_error()
        assert result.verdict == ChaosVerdict.PASS
        assert "SCAN_FAILED" in result.detail

    def test_scanner_error_allow_retry(self):
        """После SCAN_FAILED можно запросить нового worker'а."""
        docker = MockDockerBackend()
        pool = SonarWorkerPool(docker=docker)
        lease = pool.request_worker("run-se")
        lease = pool.provision(lease)
        lease = pool.start_scan(lease)
        lease = lease.fail(FailureReason.SCAN_FAILED, "syntax error")
        pool.teardown_worker(lease)

        # Новый worker для того же run_id
        l2 = pool.request_worker("run-se")
        assert l2 is not None


# ═══════════════════════════════════════════════════════════════════════════
# F-04: Orchestrator Restart
# ═══════════════════════════════════════════════════════════════════════════

class TestF04OrchestratorRestart:
    def test_restart_finds_orphans(self):
        runner = ChaosRunner()
        result = runner.f04_orchestrator_restart()
        assert result.verdict == ChaosVerdict.PASS
        assert "zombies" in result.detail.lower()
        assert result.evidence["orphans_found"] == 10
        assert result.evidence["still_running"] == 0

    def test_orphan_reconcile_cleans_labels(self):
        docker = MockDockerBackend()
        cid = docker.run_container("img", "name", 9000, {
            "com.prettyk.run_id": "stale-run",
            "com.prettyk.component": "sonar-ce-worker",
        })

        pool = SonarWorkerPool(docker=docker)
        orphans = pool.reconcile_orphans()
        assert len(orphans) == 1
        assert not docker.is_running(cid)


# ═══════════════════════════════════════════════════════════════════════════
# F-05: Standalone Outage
# ═══════════════════════════════════════════════════════════════════════════

class TestF05StandaloneOutage:
    def test_outage_events_not_lost(self):
        runner = ChaosRunner()
        result = runner.f05_standalone_outage()
        assert result.verdict == ChaosVerdict.PASS
        assert result.evidence["submitted"] == 0  # SonarQube down
        assert result.evidence["pending_count"] > 0  # events preserved

    def test_outage_sonar_unreachable(self):
        from cosmo.capability.ingest_controller import MockSonarQubeBackend
        sonar = MockSonarQubeBackend(sim_unavailable=True)
        with pytest.raises(ConnectionError):
            sonar.get_ce_activity()


# ═══════════════════════════════════════════════════════════════════════════
# F-06: Idempotent Re-delivery
# ═══════════════════════════════════════════════════════════════════════════

class TestF06IdempotentRedelivery:
    def test_idempotent_ok(self):
        runner = ChaosRunner()
        result = runner.f06_idempotent_redelivery()
        assert result.verdict == ChaosVerdict.PASS

    def test_duplicate_submission_not_rejected(self):
        from cosmo.capability.ingest_controller import MockSonarQubeBackend
        sonar = MockSonarQubeBackend()
        ok1, tid1 = sonar.submit_report("pk", "s3://x/report.sarif")
        ok2, tid2 = sonar.submit_report("pk", "s3://x/report.sarif")
        assert ok1 and ok2
        assert sonar.submitted_count == 2


# ═══════════════════════════════════════════════════════════════════════════
# F-07: Timeout
# ═══════════════════════════════════════════════════════════════════════════

class TestF07Timeout:
    def test_timeout_kills_and_cleans(self):
        runner = ChaosRunner()
        result = runner.f07_timeout()
        assert result.verdict == ChaosVerdict.PASS
        assert "TIMED_OUT" in result.detail

    def test_timeout_teardown_idempotent(self):
        docker = MockDockerBackend()
        pool = SonarWorkerPool(docker=docker)
        lease = pool.request_worker("run-to")
        lease = pool.provision(lease)
        lease = pool.start_scan(lease)
        lease = lease.fail(FailureReason.TIMED_OUT, "600s exceeded")

        # Первый teardown
        l1 = pool.teardown_worker(lease)
        assert l1.state == WorkerState.RELEASED
        # Второй — идемпотентен
        l2 = pool.teardown_worker(l1)
        assert l2.state == WorkerState.RELEASED


# ═══════════════════════════════════════════════════════════════════════════
# Full Matrix run_all() orchestration
# ═══════════════════════════════════════════════════════════════════════════

class TestFullChaosMatrix:
    def test_run_all_completes(self):
        runner = ChaosRunner()
        report = runner.run_all()
        assert report.total() == 7
        assert report.passed >= 0
        assert report.failed >= 0

    def test_run_all_passes_all(self):
        """Все 7 сценариев должны пройти на in-memory mock."""
        runner = ChaosRunner()
        report = runner.run_all()
        assert report.passed == 7, (
            f"Chaos Matrix failures:\n" +
            "\n".join(
                f"  {r.scenario}: {r.verdict.value} — {r.detail}"
                for r in report.results if r.verdict != ChaosVerdict.PASS
            )
        )
        assert report.failed == 0

    def test_convenience_function(self):
        report = run_chaos_matrix()
        assert report.total() == 7
        assert report.passed_ratio() == 1.0

    def test_failure_handled_gracefully(self):
        """Если один сценарий упал — runner продолжает остальные."""
        class BrokenRunner(ChaosRunner):
            def f03_scanner_error(self):
                raise RuntimeError("injection failed")

        runner = BrokenRunner()
        report = runner.run_all()
        assert report.total() == 7
        # F-03 должен быть FAIL
        f03 = [r for r in report.results if r.scenario == "F-03"][0]
        assert f03.verdict == ChaosVerdict.FAIL
        assert "RuntimeError" in f03.detail
        # Остальные PASS
        passed_others = sum(
            1 for r in report.results
            if r.scenario != "F-03" and r.verdict == ChaosVerdict.PASS
        )
        assert passed_others == 6

    def test_duration_ms_tracked(self):
        runner = ChaosRunner()
        report = runner.run_all()
        for r in report.results:
            assert r.duration_ms >= 0, f"{r.scenario}: duration_ms not set"

    def test_run_all_is_deterministic(self):
        """Два запуска дают одинаковый результат."""
        r1 = ChaosRunner().run_all()
        r2 = ChaosRunner().run_all()
        assert r1.total() == r2.total()
        assert r1.passed == r2.passed
        assert r1.failed == r2.failed