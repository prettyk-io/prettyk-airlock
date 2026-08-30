"""
Unit tests for COS-200 through COS-208 modules.
"""
import pytest

try:
    from cosmo.compiler.auto_patcher import AutoPatcher
    from cosmo.control_plane.policy_evaluator import PolicyEvaluator
    from cosmo.db.rls_manager import RLSManager
    from cosmo.control_plane.anomaly_detector import AnomalyDetector
    from cosmo.capability.mesh_controller import MeshController
    from cosmo.control_plane.saga_orchestrator import SagaOrchestrator, SagaStep, SagaStatus
    from cosmo.ledger.tsa_signer import TSASigner
    from cosmo.control_plane.bin_packer import BinPacker, Job, Worker
    from cosmo.ledger.suppression_engine import SuppressionEngine, SuppressionRule
except ImportError:
    from orchestrator.cosmo.compiler.auto_patcher import AutoPatcher  # type: ignore
    from orchestrator.cosmo.control_plane.policy_evaluator import PolicyEvaluator  # type: ignore
    from orchestrator.cosmo.db.rls_manager import RLSManager  # type: ignore
    from orchestrator.cosmo.control_plane.anomaly_detector import AnomalyDetector  # type: ignore
    from orchestrator.cosmo.capability.mesh_controller import MeshController  # type: ignore
    from orchestrator.cosmo.control_plane.saga_orchestrator import SagaOrchestrator, SagaStep, SagaStatus  # type: ignore
    from orchestrator.cosmo.ledger.tsa_signer import TSASigner  # type: ignore
    from orchestrator.cosmo.control_plane.bin_packer import BinPacker, Job, Worker  # type: ignore
    from orchestrator.cosmo.ledger.suppression_engine import SuppressionEngine, SuppressionRule  # type: ignore


# ── COS-200: Auto Patcher Tests ──────────────────────────────────────────────

def test_auto_patcher_sql_injection():
    patcher = AutoPatcher()
    finding = {"file_path": "app/db.py", "rule_type": "SQL_INJECTION"}
    code = 'query = f"SELECT * FROM users WHERE id = {user_id}"'
    res = patcher.generate_patch(finding, code)
    assert res is not None
    assert res.rule_type == "SQL_INJECTION"
    assert res.confidence >= 0.8
    assert len(res.diff) > 0


# ── COS-201: Policy Evaluator Tests ──────────────────────────────────────────

def test_policy_as_code_evaluation():
    pe = PolicyEvaluator.default_hardening_policy()
    bad_resource = {
        "base_image": "ubuntu:latest",
        "privileged": True,
        "run_as_root": True,
        "critical_cve_count": 3,
    }
    res = pe.evaluate(bad_resource)
    assert res.passed is False
    assert len(res.violations) >= 2


# ── COS-202: RLS Manager Tests ───────────────────────────────────────────────

def test_rls_sql_generation():
    mgr = RLSManager()
    sql_enable = mgr.generate_enable_rls("releases")
    assert "ALTER TABLE releases ENABLE ROW LEVEL SECURITY;" in sql_enable

    sql_policy = mgr.generate_policy("releases")
    assert "CREATE POLICY releases_tenant_isolation ON releases" in sql_policy

    set_ctx = mgr.generate_set_local("dom-tenant-100")
    assert "SET LOCAL app.current_domain_id = 'dom-tenant-100';" in set_ctx

    shard = mgr.shard_key("dom-tenant-100")
    assert 0 <= shard < RLSManager.SHARD_COUNT


# ── COS-203: Anomaly Detector Tests ──────────────────────────────────────────

def test_anomaly_detector_z_score():
    detector = AnomalyDetector(z_threshold=3.0)
    for _ in range(20):
        detector.record_metric("run-1", "duration_ms", 100.0)

    anom = detector.record_metric("run-1", "duration_ms", 10000.0)
    assert anom is not None
    assert anom.z_score > 3.0
    assert detector.is_frozen("run-1") is True


# ── COS-204: Mesh Controller Tests ───────────────────────────────────────────

def test_mesh_controller_sidecar():
    controller = MeshController()
    ident = controller.register_service("PaymentService", zone="zt", namespace="banking")
    assert "banking" in ident.namespace

    xds = controller.generate_xds_config("PaymentService", upstreams=[("auth-svc", 8080)])
    assert xds["service"] == "PaymentService"
    assert xds["mtls"]["mode"] == "STRICT"


# ── COS-205: Saga Orchestrator Tests ─────────────────────────────────────────

def test_saga_orchestrator_success_and_compensation():
    orchestrator = SagaOrchestrator()
    logs = []

    # 1. Success Saga
    step1 = SagaStep(
        name="DeployZT",
        action=lambda ctx: {"status": "ok"},
        compensation=lambda ctx: logs.append("rollback_zt") or {},
    )
    step2 = SagaStep(
        name="SmokeTest",
        action=lambda ctx: {"tested": True},
        compensation=lambda ctx: {},
    )
    orchestrator.create_saga("saga-1", [step1, step2])
    status = orchestrator.execute("saga-1", {})
    assert status == SagaStatus.COMPLETED

    # 2. Failed Saga with compensation
    logs.clear()
    step_fail = SagaStep(
        name="FailStep",
        action=lambda ctx: (_ for _ in ()).throw(ValueError("Boom")),
        compensation=lambda ctx: {},
    )
    orchestrator.create_saga("saga-2", [step1, step_fail])
    status_fail = orchestrator.execute("saga-2", {})
    assert status_fail == SagaStatus.COMPENSATED
    assert "rollback_zt" in logs


# ── COS-206: TSA Signer Tests ────────────────────────────────────────────────

def test_tsa_timestamp_token():
    tsa = TSASigner()
    evidence = {"finding_id": "F-001", "details": "SQLi vulnerability"}

    signed = tsa.sign_evidence(evidence)
    assert "_evidence_hash" in signed
    assert "_timestamp_token" in signed
    assert tsa.verify_evidence(signed) is True

    # Tamper with evidence
    tampered = dict(signed)
    tampered["details"] = "Tampered data"
    assert tsa.verify_evidence(tampered) is False


# ── COS-207: Bin Packer Tests ────────────────────────────────────────────────

def test_bin_packer_allocation():
    packer = BinPacker()
    packer.add_worker(Worker("w1", cpu_capacity=4.0, ram_capacity=8.0))
    packer.add_worker(Worker("w2", cpu_capacity=8.0, ram_capacity=16.0))

    j1 = Job("j1", cpu=2.0, ram_gb=4.0, priority=10)
    plan = packer.pack([j1])
    assert plan["total_placed"] == 1
    assert plan["total_jobs"] == 1
    assert len(plan["unplaced"]) == 0


# ── COS-208: Suppression Engine Tests ────────────────────────────────────────

def test_suppression_engine_filter():
    engine = SuppressionEngine()
    finding = {
        "file_path": "tests/test_mock.py",
        "line": 42,
        "rule_id": "XSS-001",
        "code_snippet": "return html.escape(x)",
    }
    fp = engine.compute_fingerprint(finding)
    engine.add_rule("rule-1", fp, reason="test mock only", approved_by="sec_officer")

    assert engine.is_suppressed(finding) is True
    assert engine.is_suppressed({"file_path": "other.py"}) is False
