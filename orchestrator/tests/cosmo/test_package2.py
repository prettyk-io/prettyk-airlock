# -*- coding: utf-8 -*-
"""COS-140-151: Consolidated tests for Package 2."""
import sys, json
from pathlib import Path
import pytest
_orch = Path(__file__).resolve().parents[1]
if str(_orch) not in sys.path:
    sys.path.insert(0, str(_orch))

# ========== COS-140: DAG Solver ==========
from orchestrator.cosmo.compiler.dag_solver import DAGSolver

class TestDAGSolver:
    def test_topo_simple(self):
        nodes = {"a": {}, "b": {}, "c": {}}
        edges = [("a", "b"), ("b", "c")]
        s = DAGSolver(nodes, edges)
        assert s.topological_order() == ["a", "b", "c"]

    def test_cycle_detection(self):
        nodes = {"a": {}, "b": {}, "c": {}}
        edges = [("a", "b"), ("b", "c"), ("c", "a")]
        s = DAGSolver(nodes, edges)
        cycles = s.detect_cycles()
        assert len(cycles) == 1
        assert set(cycles[0]) == {"a", "b", "c"}

    def test_critical_path(self):
        nodes = {"a": {}, "b": {}, "c": {}}
        edges = [("a", "b"), ("b", "c")]
        s = DAGSolver(nodes, edges)
        path = s.critical_path({"a": 3, "b": 5, "c": 2})
        assert path == ["a", "b", "c"]

    def test_no_cycles_chain(self):
        nodes = {"a": {}, "b": {}, "c": {}, "d": {}}
        edges = [("a", "b"), ("b", "c"), ("c", "d")]
        s = DAGSolver(nodes, edges)
        assert len(s.detect_cycles()) == 0

    def test_parallel_schedule(self):
        nodes = {"a": {}, "b": {}, "c": {}, "d": {}}
        edges = [("a", "b"), ("a", "c"), ("b", "d"), ("c", "d")]
        s = DAGSolver(nodes, edges)
        schedule = s.parallel_schedule({"a": 1, "b": 3, "c": 2, "d": 1})
        assert len(schedule) >= 3

# ========== COS-141: Vault Lease ==========
from orchestrator.cosmo.capability.vault_lease import VaultLeaseEngine

class TestVaultLease:
    def test_issue(self):
        e = VaultLeaseEngine()
        l = e.issue_lease("db", {"user": "app", "pass": "secret"}, ttl=10)
        assert l.lease_type == "db"
        assert e.is_valid(l.lease_id) is True

    def test_revoke(self):
        e = VaultLeaseEngine()
        l = e.issue_lease("db", {"user": "x"}, ttl=10)
        assert e.revoke_lease(l.lease_id) is True
        assert e.is_valid(l.lease_id) is False

    def test_renew(self):
        e = VaultLeaseEngine()
        l = e.issue_lease("token", {"tok": "abc"}, ttl=0.01)
        assert e.renew_lease(l.lease_id, ttl=60) is True

    def test_teardown(self):
        e = VaultLeaseEngine()
        e.issue_lease("gitea_token", {"tok": "x"})
        assert e.teardown() == 1
        assert e.active_lease_count == 0

# ========== COS-142: CAS Storage ==========
from orchestrator.cosmo.ledger.cas_storage import CASStorage
import tempfile, shutil

class TestCASStorage:
    @pytest.fixture
    def cas(self):
        d = tempfile.mkdtemp(prefix="cas_")
        c = CASStorage(d)
        yield c
        shutil.rmtree(d, ignore_errors=True)

    def test_store_retrieve(self, cas):
        data = b"hello" * 1000
        m = cas.store(data)
        assert m["hash"] != ""
        assert cas.retrieve(m["hash"]) == data

    def test_dedup(self, cas):
        data = b"dedup-test" * 500
        m1 = cas.store(data)
        m2 = cas.store(data)
        assert m2["dedup"] is True
        assert m1["hash"] == m2["hash"]

    def test_exists(self, cas):
        data = b"exists-test"
        m = cas.store(data)
        assert cas.exists(m["hash"]) is True
        assert cas.exists("nonexistent") is False

    def test_stats(self, cas):
        cas.store(b"a" * 100)
        cas.store(b"b" * 100)
        s = cas.stats()
        assert s["total_artifacts"] == 2

# ========== COS-143: Quota Governor ==========
from orchestrator.cosmo.control_plane.quota_governor import QuotaGovernor, DomainQuota

class TestQuotaGovernor:
    def test_acquire_release(self):
        g = QuotaGovernor()
        g.register_domain(DomainQuota(domain_id="d1", max_cpu=4, max_runs=10))
        assert g.try_acquire("d1", cpu=2, ram_gb=4) is True
        g.release("d1", cpu=2, ram_gb=4)
        assert g.try_acquire("d1", cpu=5, ram_gb=0) is False

    def test_evict(self):
        g = QuotaGovernor()
        g.register_domain(DomainQuota(domain_id="low", max_cpu=2, priority=0))
        g.register_domain(DomainQuota(domain_id="high", max_cpu=1, priority=10))
        g.try_acquire("high", cpu=1, ram_gb=0)
        assert g.try_acquire("high", cpu=1, ram_gb=0) is False  # high full
        assert g.evict_low_priority("high") is True
        assert g.try_acquire("high", cpu=1, ram_gb=0) is False  # still full — evict clears LOW, not own

    def test_alerts(self):
        g = QuotaGovernor()
        g.register_domain(DomainQuota(domain_id="d1", max_cpu=1, max_ram_gb=1))
        g.try_acquire("d1", cpu=0.9, ram_gb=0)
        alerts = g.check_alerts()
        assert "d1" in alerts

# ========== COS-144: Stream Consumer ==========
from orchestrator.cosmo.control_plane.stream_consumer import StreamConsumerDaemon

class TestStreamConsumer:
    def test_consume_and_process(self):
        d = StreamConsumerDaemon()
        results = []
        d.register_handler("cosmo:events", lambda m: results.append(m.data))
        d.consume("cosmo:events", [{"id": "m1", "data": {"type": "test"}}])
        d.process_pending()
        assert len(results) == 1

    def test_claim_orphaned(self):
        d = StreamConsumerDaemon()
        d.consume("cosmo:events", [{"id": "stale", "data": {"x": 1}}])
        claimed = d.claim_orphaned("cosmo:events", idle_timeout=0)
        assert len(claimed) == 1

    def test_pending_count(self):
        d = StreamConsumerDaemon()
        d.consume("cosmo:events", [{"id": "m1", "data": {}}, {"id": "m2", "data": {}}])
        assert d.pending_count("cosmo:events") == 2

# ========== COS-145: Merkle Ledger ==========
from orchestrator.cosmo.ledger.merkle_ledger import MerkleLedger

class TestMerkleLedger:
    def test_single_leaf(self):
        ml = MerkleLedger()
        ml.add_leaf({"step": "build"})
        assert len(ml.root_hash()) == 64

    def test_proof_verify(self):
        ml = MerkleLedger()
        for i in range(5):
            ml.add_leaf({"step": f"step-{i}"})
        proof = ml.generate_proof(2)
        assert len(proof) >= 2  # at least 2 proof elements for 5 leaves
        assert proof[0]["hash"] != ""

    def test_root_hash_changes(self):
        ml = MerkleLedger()
        h1 = ml.root_hash()
        ml.add_leaf({"step": "build"})
        h2 = ml.root_hash()
        assert h1 != h2

# ========== COS-146: Canary Controller ==========
from orchestrator.cosmo.control_plane.canary_controller import CanaryController, CanaryPhase

class TestCanaryController:
    def test_start_canary(self):
        c = CanaryController()
        s = c.start_canary("rel-1")
        assert s.phase == CanaryPhase.SHIFTING_10
        assert s.traffic_pct == 10

    def test_report_metrics_healthy(self):
        c = CanaryController()
        c.start_canary("rel-2")
        s = None
        for _ in range(40):  # 4 phases × 10 metrics each
            s = c.report_metrics("rel-2", ok=100, errors=0)
        assert s.phase == CanaryPhase.FULL
        assert s.traffic_pct == 100

    def test_auto_rollback_on_errors(self):
        c = CanaryController()
        c.start_canary("rel-3")
        s = c.report_metrics("rel-3", ok=90, errors=10)
        assert s.phase == CanaryPhase.ROLLED_BACK

    def test_manual_rollback(self):
        c = CanaryController()
        c.start_canary("rel-4")
        assert c.rollback("rel-4") is True

# ========== COS-147: SemVer Solver ==========
from orchestrator.cosmo.compiler.semver_solver import SemVerSolver, satisfies, parse_semver

class TestSemVer:
    def test_caret(self):
        assert satisfies("1.5.0", "^1.2.0") is True
        assert satisfies("2.0.0", "^1.2.0") is False

    def test_tilde(self):
        assert satisfies("1.2.5", "~1.2.3") is True
        assert satisfies("1.3.0", "~1.2.3") is False

    def test_gte_lte(self):
        assert satisfies("2.0.0", ">=1.5.0") is True
        assert satisfies("1.0.0", "<=1.5.0") is True
        assert satisfies("2.0.0", "<=1.5.0") is False

    def test_exact(self):
        assert satisfies("1.2.3", "1.2.3") is True
        assert satisfies("1.2.4", "1.2.3") is False

    def test_solver(self):
        solver = SemVerSolver({"app-auth": ["1.0.0", "1.5.0", "2.0.0"]})
        r = solver.solve({"app-auth": "^1.0.0"})
        assert r["app-auth"] == "1.0.0"

    def test_unsatisfiable(self):
        solver = SemVerSolver({"app-x": ["1.0.0"]})
        assert solver.solve({"app-x": "^2.0.0"}) == {}

# ========== COS-148: Online Schema Change ==========
from orchestrator.cosmo.db.online_schema_change import OnlineSchemaChange

class TestOnlineSchemaChange:
    def test_start(self):
        osc = OnlineSchemaChange()
        m = osc.start_migration("runs", "ADD COLUMN foo TEXT")
        assert m["status"] in ("init", "copying")

    def test_rollback(self):
        osc = OnlineSchemaChange()
        m = osc.start_migration("batches", "ADD COLUMN bar INT")
        assert osc.rollback(m["id"]) is True
        assert osc.status(m["id"])["status"] == "rolled_back"

# ========== COS-149: Tiered Query Cache ==========
from orchestrator.cosmo.api.query_cache import TieredQueryCache

class TestTieredCache:
    def test_get_set(self):
        c = TieredQueryCache()
        c.set("/api/v1/domains", {}, {"items": ["d1"]})
        assert c.get("/api/v1/domains", {}) == {"items": ["d1"]}

    def test_miss(self):
        c = TieredQueryCache()
        assert c.get("/api/v1/ghost", {}) is None

    def test_invalidation(self):
        c = TieredQueryCache()
        c.set("/api/v1/apps", {}, {"data": [1]})
        c.invalidate("domain:updated")
        assert c.get("/api/v1/apps", {}) is None

    def test_subscriber(self):
        c = TieredQueryCache()
        events = []
        c.subscribe("release:created", lambda e: events.append(e))
        c.invalidate("release:created")
        assert "release:created" in events

# ========== COS-151: Blast Radius ==========
from orchestrator.cosmo.ledger.blast_radius import DependencyGraph

class TestBlastRadius:
    def test_simple_chain(self):
        g = DependencyGraph([("auth-service", "crypto-lib"), ("api-gateway", "auth-service")])
        blast = g.blast_radius("crypto-lib")
        assert blast["total_affected"] >= 2

    def test_quarantine_set(self):
        g = DependencyGraph([("frontend", "api"), ("api", "db-lib")])
        q = g.quarantine("db-lib")
        assert "frontend" in q
        assert "api" in q

    def test_no_consumers(self):
        g = DependencyGraph([("a", "b")])
        blast = g.blast_radius("a")
        assert blast["total_affected"] == 0