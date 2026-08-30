# -*- coding: utf-8 -*-
"""COS-200-208: Combined tests for security/compliance engines."""
import sys
from pathlib import Path
import pytest
_orch = Path(__file__).resolve().parents[1]
if str(_orch) not in sys.path:
    sys.path.insert(0, str(_orch))

from orchestrator.cosmo.compiler.auto_patcher import AutoPatcher
from orchestrator.cosmo.control_plane.policy_evaluator import PolicyEvaluator
from orchestrator.cosmo.db.rls_manager import RLSManager
from orchestrator.cosmo.control_plane.anomaly_detector import AnomalyDetector
from orchestrator.cosmo.capability.mesh_controller import MeshController
from orchestrator.cosmo.control_plane.saga_orchestrator import SagaOrchestrator, SagaStatus
from orchestrator.cosmo.ledger.tsa_signer import TSASigner
from orchestrator.cosmo.control_plane.bin_packer import BinPacker, Job, Worker
from orchestrator.cosmo.ledger.suppression_engine import SuppressionEngine


class TestAutoPatcher:
    def test_sql_patch(self):
        p = AutoPatcher()
        src = 'query = "SELECT * FROM users WHERE id = %s" % (user_input,)'
        r = p.generate_patch({"id": "f1", "file_path": "a.py", "rule_type": "SQL_INJECTION"}, src)
        assert r.diff != ""
        assert r.rule_type == "SQL_INJECTION"

    def test_xss_patch(self):
        p = AutoPatcher()
        src = 'return request.GET["name"]'
        r = p.generate_patch({"id": "f2", "rule_type": "XSS"}, src)
        assert "html.escape" in r.patched

    def test_infer_rule(self):
        p = AutoPatcher()
        assert p._infer_rule({"message": "SQL injection"}) == "SQL_INJECTION"
        assert p._infer_rule({"title": "XSS"}) == "XSS"

    def test_patch_result_fields(self):
        p = AutoPatcher()
        r = p.generate_patch({"id": "f3", "file_path": "x.py", "rule_type": "XSS"}, "a")
        assert r.finding_id == "f3"
        assert r.file_path == "x.py"
        assert r.confidence > 0


class TestPolicyEvaluator:
    def test_privileged_blocked(self):
        pe = PolicyEvaluator.default_hardening_policy()
        r = pe.evaluate({"privileged": True, "run_as_root": False, "critical_cve_count": 0})
        assert r.passed is False
        assert any(v.rule == "no-privileged" for v in r.violations)

    def test_clean_passes(self):
        pe = PolicyEvaluator.default_hardening_policy()
        r = pe.evaluate({"privileged": False, "run_as_root": False, "critical_cve_count": 0,
                         "read_only_root_fs": True, "base_image": "alpine:3.19", "cve_count": 10})
        assert r.passed is True

    def test_cve_limit(self):
        pe = PolicyEvaluator.default_hardening_policy()
        r = pe.evaluate({"critical_cve_count": 3})
        assert r.passed is False

    def test_validate_release(self):
        pe = PolicyEvaluator.default_hardening_policy()
        r = pe.validate_release([
            {"privileged": False, "run_as_root": False, "critical_cve_count": 0},
            {"privileged": True, "run_as_root": False, "critical_cve_count": 0},
        ])
        assert r.passed is False


class TestRLSManager:
    def test_shard_key_consistent(self):
        r = RLSManager()
        assert r.shard_key("dom-a") == r.shard_key("dom-a")
        assert r.shard_key("dom-a") != r.shard_key("dom-b")

    def test_shard_key_range(self):
        r = RLSManager()
        for i in range(100):
            assert 0 <= r.shard_key(f"dom-{i}") < 16

    def test_generate_policy(self):
        r = RLSManager()
        policy = r.generate_policy("runs")
        assert "USING" in policy and "app.current_domain_id" in policy

    def test_generate_enable_rls(self):
        r = RLSManager()
        assert "ENABLE ROW LEVEL SECURITY" in r.generate_enable_rls("runs")

    def test_apply_rls(self):
        r = RLSManager()
        stmts = r.apply_rls(["runs", "gates"])
        assert len(stmts) == 4

    def test_hash_audit(self):
        r = RLSManager()
        h = r.hash_domain_for_audit("digital-ruble")
        assert len(h) == 16
        assert "digital-ruble" not in h


class TestAnomalyDetector:
    def test_stable_no_anomaly(self):
        d = AnomalyDetector()
        for i in range(50):
            d.record_metric("p1", "duration", 100 + (i % 3))
        assert len(d.get_anomalies()) == 0

    def test_spike_detected(self):
        d = AnomalyDetector(z_threshold=2.0)
        for i in range(30):
            d.record_metric("p2", "duration", 100)
        event = d.record_metric("p2", "duration", 5000)
        assert event is not None

    def test_critical_freeze(self):
        d = AnomalyDetector(z_threshold=2.0)
        for i in range(30):
            d.record_metric("p3", "cve_count", 5)
        d.record_metric("p3", "cve_count", 1000)
        assert d.is_frozen("p3") is True

    def test_unfreeze(self):
        d = AnomalyDetector()
        d.record_metric("p4", "m", 1000)  # first value, no baseline
        d.unfreeze("p4")
        assert d.is_frozen("p4") is False

    def test_ingest_metric_alias(self):
        d = AnomalyDetector()
        for i in range(30):
            d.ingest_metric("dur", 50, run_id="r1")
        assert len(d.get_anomalies()) == 0


class TestMeshController:
    def test_register_service(self):
        m = MeshController()
        ident = m.register_service("auth", "zr")
        assert ident.zone == "zr"
        assert "auth.zr" in ident.cert_cn

    def test_generate_mtls_cert(self):
        m = MeshController()
        m.register_service("auth", "zt")
        cert = m.generate_mtls_cert("auth")
        assert cert["cn"] == "auth.zt.cosmoport.svc"
        assert "spiffe" in cert["san"][0]

    def test_generate_xds(self):
        m = MeshController()
        m.register_service("api", "zr")
        config = m.generate_xds_config("api", [("db", 5432)])
        assert len(config["clusters"]) == 1
        assert config["mtls"]["mode"] == "STRICT"

    def test_validate_identity(self):
        m = MeshController()
        assert m.validate_service_identity("auth.zt.cosmoport.svc", "auth", "zt") is True
        assert m.validate_service_identity("auth.zt.cosmoport.svc", "auth", "zr") is False


class TestSagaOrchestrator:
    def test_successful_saga(self):
        s = SagaOrchestrator()
        steps = SagaOrchestrator.release_transfer_steps()
        s.create_saga("saga-1", steps)
        status = s.execute("saga-1", {"to_zone": "zt", "signer": "alice"})
        assert status == SagaStatus.COMPLETED

    def test_failed_saga_compensates(self):
        s = SagaOrchestrator()
        steps = SagaOrchestrator.release_transfer_steps()
        s.create_saga("saga-2", steps)
        status = s.execute("saga-2", {"to_zone": "zt", "simulate_failure": True})
        assert status == SagaStatus.COMPENSATED

    def test_saga_status(self):
        s = SagaOrchestrator()
        steps = SagaOrchestrator.release_transfer_steps()
        s.create_saga("saga-3", steps)
        s.execute("saga-3", {})
        assert s.status("saga-3") == SagaStatus.COMPLETED


class TestTSASigner:
    def test_sign_evidence(self):
        t = TSASigner()
        evidence = {"type": "finding", "severity": "Critical"}
        signed = t.sign_evidence(evidence)
        assert "_evidence_hash" in signed
        assert "_signature" in signed
        assert "_timestamp_token" in signed

    def test_verify_unchanged(self):
        t = TSASigner()
        signed = t.sign_evidence({"type": "test"})
        assert t.verify_evidence(signed) is True

    def test_verify_tampered(self):
        t = TSASigner()
        signed = t.sign_evidence({"type": "test"})
        signed["type"] = "tampered"
        assert t.verify_evidence(signed) is False

    def test_timestamp_token(self):
        t = TSASigner()
        token = t.timestamp_document("abc123")
        assert token.hash == "abc123"
        assert t.verify_timestamp(token, "abc123") is True


class TestBinPacker:
    def test_pack_fits(self):
        w = Worker("w1", cpu_capacity=4, ram_capacity=8)
        p = BinPacker([w])
        jobs = [Job("j1", 2, 4), Job("j2", 2, 4)]
        plan = p.pack(jobs)
        assert plan["total_placed"] == 2
        assert plan["unplaced"] == []

    def test_pack_overflow(self):
        w = Worker("w1", cpu_capacity=2, ram_capacity=4)
        p = BinPacker([w])
        jobs = [Job("j1", 2, 4), Job("j2", 2, 4)]
        plan = p.pack(jobs)
        assert plan["total_placed"] == 1
        assert len(plan["unplaced"]) == 1

    def test_preemption(self):
        w = Worker("w1", cpu_capacity=2, ram_capacity=4)
        p = BinPacker([w])
        low = Job("low", 2, 4, priority=0)
        high = Job("high", 2, 4, priority=10)
        plan = p.pack([low, high])
        placements = plan["placements"]["w1"]
        assert "high" in placements

    def test_utilization(self):
        w1 = Worker("w1", cpu_capacity=4, ram_capacity=8)
        w2 = Worker("w2", cpu_capacity=4, ram_capacity=8)
        p = BinPacker([w1, w2])
        p.pack([Job("j1", 2, 4), Job("j2", 2, 4)])
        util = p.pack([Job("j3", 2, 4)])["utilization"]
        assert 0 <= util["cpu_utilization"] <= 100


class TestSuppressionEngine:
    def test_compute_fingerprint(self):
        e = SuppressionEngine()
        f1 = {"file_path": "a.py", "line": 10, "rule_id": "R1", "code_snippet": "x"}
        f2 = {"file_path": "a.py", "line": 10, "rule_id": "R1", "code_snippet": "x"}
        f3 = {"file_path": "a.py", "line": 11, "rule_id": "R1", "code_snippet": "x"}
        assert e.compute_fingerprint(f1) == e.compute_fingerprint(f2)
        assert e.compute_fingerprint(f1) != e.compute_fingerprint(f3)

    def test_suppress(self):
        e = SuppressionEngine()
        finding = {"file_path": "a.py", "line": 10, "rule_id": "R1", "code_snippet": "x"}
        fp = e.compute_fingerprint(finding)
        e.add_rule("rule-1", fp, "false positive", "sec-expert")
        assert e.is_suppressed(finding) is True

    def test_filter_findings(self):
        e = SuppressionEngine()
        f1 = {"file_path": "a.py", "line": 1, "rule_id": "R1"}
        f2 = {"file_path": "b.py", "line": 2, "rule_id": "R2"}
        e.add_rule("rule-1", e.compute_fingerprint(f1), "fp", "expert")
        kept, suppressed = e.filter_findings([f1, f2])
        assert len(kept) == 1
        assert len(suppressed) == 1

    def test_remove_rule(self):
        e = SuppressionEngine()
        fp = e.compute_fingerprint({"file_path": "a.py"})
        e.add_rule("r1", fp, "fp", "expert")
        assert e.remove_rule("r1") is True
        assert e.remove_rule("r1") is False

    def test_audit_log(self):
        e = SuppressionEngine()
        fp = e.compute_fingerprint({"file_path": "x.py"})
        e.add_rule("r1", fp, "fp", "expert")
        log = e.audit_log()
        assert len(log) >= 1
        assert log[-1]["action"] == "add_rule"