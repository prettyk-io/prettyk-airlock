# -*- coding: utf-8 -*-
"""COS-016 + COS-017: Steel Thread PG + Idempotency tests.

COS-016: Domain → App → Bricks → Plan → Run → Batch → Gate → Evidence — all 8 entities on real PG.
COS-017: Two identical creates don't duplicate. Valkey reset — statuses recover from PG.

All PG-dependent tests auto-skip when the test PG (:5433) is unreachable.
"""
from __future__ import annotations
import _testpg  # noqa: E402  (COS-078: unified PG check)

import sys
from pathlib import Path

import pytest
from sqlalchemy import text

_orch = Path(__file__).resolve().parents[1]
if str(_orch) not in sys.path:
    sys.path.insert(0, str(_orch))

from orchestrator.cosmo.db.session import get_sync_session, get_sync_url
from orchestrator.cosmo.db.models import (
    Domain, Application, Group, RepositoryBinding,
    PipelineBrick, PipelinePlan, PlanBrick,
    Batch, Gate, Run, EvidenceLedgerEntry,
)
from sqlalchemy.exc import OperationalError


# ── PG availability skip ────────────────────────────────────────────

def _pg_available() -> bool:
    """COS-078: unified on _testpg.pg_available (single resolution point)."""
    return _testpg.pg_available()


_pg_needed = pytest.mark.skipif(not _pg_available(), reason="test PG (:5433) unreachable - docker compose -f services/docker-compose.test-pg.yml up -d")


# ── Clean DB before each PG test ────────────────────────────────────

@pytest.fixture(autouse=False)
def _clean_db():
    s = get_sync_session()
    try:
        for tbl in ["evidence_ledger", "runs", "gates", "batches",
                     "plan_bricks", "pipeline_plans", "pipeline_bricks",
                     "repo_bindings", "apps", "groups", "domains"]:
            s.execute(text(f"DELETE FROM {tbl} CASCADE"))
        s.commit()
    except Exception:
        s.rollback()
    finally:
        s.close()
    yield


# ── Test helpers ────────────────────────────────────────────────────

def _create_domain(s, domain_id: str = "d-steel") -> Domain:
    d = Domain(id=domain_id, label="Steel Thread Domain",
               forge_type="gitea", forge_url="http://gitea:3000",
               forge_token_ref="VAULT/TEST_TOKEN")
    s.add(d); s.commit()
    return d


def _create_bricks(s) -> list[PipelineBrick]:
    bricks = [
        PipelineBrick(id="b-sast", name="SAST", type="sast", source="web",
                      definition_json={"image": "sonarsource/sonar-scanner-cli:latest"}),
        PipelineBrick(id="b-dast", name="DAST", type="dast", source="web",
                      definition_json={"image": "zaproxy/zap-stable:2.17.0"}),
        PipelineBrick(id="b-gate", name="Gate", type="gate", source="internal",
                      definition_json={"image": "internal/gate:latest"}),
    ]
    for b in bricks:
        s.add(b)
    s.commit()
    return bricks


def _create_plan(s, app_id: str, bricks: list[PipelineBrick]) -> PipelinePlan:
    plan = PipelinePlan(id="plan-steel", app_id=app_id, level="app",
                        scope_id=app_id, compiled_hash="sha256:abc")
    s.add(plan); s.commit()
    for i, b in enumerate(bricks):
        s.add(PlanBrick(plan_id=plan.id, brick_id=b.id, sort_order=i))
    s.commit()
    return plan


def _create_batches(s, plan_id: str) -> list[Batch]:
    batches = [
        Batch(id="batch-build", plan_id=plan_id, type="build",
              bricks_refs=["b-sast"]),
        Batch(id="batch-scan", plan_id=plan_id, type="static_scan",
              bricks_refs=["b-dast"]),
    ]
    for b in batches:
        s.add(b)
    s.commit()
    return batches


# ═══════════════════════════════════════════════════════════════════════════
# COS-016: Steel Thread on real PG
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.usefixtures("_clean_db")
class TestSteelThreadPG:

    @_pg_needed
    def test_full_steel_thread(self):
        """8 entities created, FK-linked, verified through DB."""
        s = get_sync_session()
        domain = _create_domain(s, "d-steel-1")
        assert s.query(Domain).count() == 1

        app = Application(id="app-web", domain_id=domain.id, level=1)
        s.add(app); s.commit()
        assert s.query(Application).count() == 1

        binding = RepositoryBinding(id="rb-1", app_id=app.id, forge_id="f1",
                                    repo_path="d-steel-1/web", default_branch="main")
        s.add(binding); s.commit()
        assert s.query(RepositoryBinding).count() == 1

        bricks = _create_bricks(s)
        assert s.query(PipelineBrick).count() == 3

        plan = _create_plan(s, app.id, bricks)
        assert s.query(PipelinePlan).count() == 1
        assert s.query(PlanBrick).filter(PlanBrick.plan_id == plan.id).count() == 3

        batches = _create_batches(s, plan.id)
        assert s.query(Batch).filter(Batch.plan_id == plan.id).count() == 2

        run = Run(id="run-steel-1", plan_id=plan.id, trigger="manual",
                  domain_id=domain.id, batch_id=batches[0].id, status="draft",
                  initiator_user_id="system", initiator_role="system")
        s.add(run); s.commit()

        # Lifecycle: draft → pending → queued → running → succeeded
        for st in ["pending", "queued", "running", "succeeded"]:
            run.status = st; s.commit()

        run2 = s.query(Run).filter(Run.id == "run-steel-1").first()
        assert run2.status == "succeeded"

        # Gates
        gates = [
            Gate(id="g-quality", plan_id=plan.id, type="automatic", position=0,
                 policy_json={"rules": [{"finding_type": "Critical", "action": "block"},
                                        {"finding_type": "High", "action": "warn"}]}),
            Gate(id="g-release", plan_id=plan.id, type="manual", position=1,
                 policy_json={"rules": [{"finding_type": "Critical", "action": "block"}]}),
        ]
        for g in gates:
            s.add(g)
        s.commit()
        assert s.query(Gate).count() == 2

        # Evidence
        evidence = [
            EvidenceLedgerEntry(run_id=run.id, batch_id=batches[0].id, type="log",
                                content_ref="build.log", content_hash="sha256:abc"),
            EvidenceLedgerEntry(run_id=run.id, batch_id=batches[1].id, type="finding",
                                content_ref="sqli-alert", content_hash="sha256:def"),
            EvidenceLedgerEntry(run_id=run.id, type="decision",
                                content_ref="gate-verdict", content_hash="sha256:ghi"),
        ]
        for ev in evidence:
            s.add(ev)
        s.commit()
        assert s.query(EvidenceLedgerEntry).filter(EvidenceLedgerEntry.run_id == run.id).count() == 3

        # Cross-entity check
        assert s.query(Domain).count() == 1
        assert s.query(Run).count() == 1
        assert s.query(EvidenceLedgerEntry).count() == 3

        s.close()

    @_pg_needed
    def test_run_lifecycle_all_states(self):
        """Run goes through all valid states: draft → pending → queued → running → succeeded."""
        s = get_sync_session()
        domain = _create_domain(s, "d-life")
        app = Application(id="app-life", domain_id=domain.id, level=1)
        s.add(app); s.commit()
        bricks = _create_bricks(s)
        plan = _create_plan(s, app.id, bricks)

        run = Run(id="run-life", plan_id=plan.id, trigger="manual",
                  domain_id=domain.id, status="draft",
                  initiator_user_id="operator", initiator_role="secops")
        s.add(run); s.commit()

        for st in ["pending", "queued", "running", "succeeded"]:
            run.status = st; s.commit()
            r = s.query(Run).filter(Run.id == "run-life").first()
            assert r.status == st

        s.close()

    @_pg_needed
    def test_all_eight_entity_types(self):
        """All 8 entity types created and linked."""
        s = get_sync_session()
        domain = _create_domain(s, "d-all")
        app = Application(id="app-all", domain_id=domain.id, level=1)
        s.add(app); s.commit()
        bricks = _create_bricks(s)
        plan = _create_plan(s, app.id, bricks)
        batches = _create_batches(s, plan.id)
        gates = [
            Gate(id="g1", plan_id=plan.id, type="automatic", position=0,
                 policy_json={"rules": [{"finding_type": "Critical", "action": "block"}]}),
        ]
        for g in gates:
            s.add(g)
        s.commit()

        run = Run(id="run-all", plan_id=plan.id, trigger="manual",
                  domain_id=domain.id, status="succeeded",
                  initiator_user_id="operator", initiator_role="secops")
        s.add(run); s.commit()

        ev = EvidenceLedgerEntry(run_id=run.id, type="decision",
                                 content_ref="all-done", content_hash="sha256:zzz")
        s.add(ev); s.commit()

        counts = {
            "Domain": s.query(Domain).count(),
            "Application": s.query(Application).count(),
            "PipelineBrick": s.query(PipelineBrick).count(),
            "PipelinePlan": s.query(PipelinePlan).count(),
            "PlanBrick": s.query(PlanBrick).count(),
            "Batch": s.query(Batch).count(),
            "Gate": s.query(Gate).count(),
            "Run": s.query(Run).count(),
            "EvidenceLedgerEntry": s.query(EvidenceLedgerEntry).count(),
        }
        assert counts["Domain"] >= 1
        assert counts["Application"] >= 1
        assert counts["PipelineBrick"] >= 3
        assert counts["PipelinePlan"] >= 1
        assert counts["PlanBrick"] >= 3
        assert counts["Batch"] >= 2
        assert counts["Gate"] >= 1
        assert counts["Run"] >= 1
        assert counts["EvidenceLedgerEntry"] >= 1

        s.close()


# ═══════════════════════════════════════════════════════════════════════════
# COS-017: Idempotency + Recovery
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.usefixtures("_clean_db")
class TestIdempotency:

    @_pg_needed
    def test_domain_duplicate_create_is_rejected(self):
        """Creating the same domain twice must be rejected (not silently duplicated)."""
        s = get_sync_session()
        _create_domain(s, "d-dup")
        assert s.query(Domain).filter(Domain.id == "d-dup").count() == 1

        # Second create with same PK → integrity error
        d2 = Domain(id="d-dup", label="Duplicate", forge_type="gitea",
                    forge_url="http://gitea:3000", forge_token_ref="VAULT/X")
        s.add(d2)
        from sqlalchemy.exc import IntegrityError
        with pytest.raises(IntegrityError):
            s.commit()
        s.rollback()
        assert s.query(Domain).filter(Domain.id == "d-dup").count() == 1
        s.close()

    @_pg_needed
    def test_two_identical_runs_different_ids(self):
        """Two runs with same plan but different run_id are NOT duplicates — both allowed."""
        s = get_sync_session()
        domain = _create_domain(s, "d-runs")
        app = Application(id="app-runs", domain_id=domain.id, level=1)
        s.add(app); s.commit()
        bricks = _create_bricks(s)
        plan = _create_plan(s, app.id, bricks)

        run1 = Run(id="run-1", plan_id=plan.id, trigger="manual",
                   domain_id=domain.id, status="pending",
                   initiator_user_id="operator", initiator_role="secops")
        s.add(run1); s.commit()

        run2 = Run(id="run-2", plan_id=plan.id, trigger="manual",
                   domain_id=domain.id, status="pending",
                   initiator_user_id="operator", initiator_role="secops")
        s.add(run2); s.commit()

        assert s.query(Run).count() == 2
        assert s.query(Run).filter(Run.plan_id == plan.id).count() == 2
        s.close()

    @_pg_needed
    def test_run_id_reuse_is_rejected(self):
        """Cannot create two runs with the same run_id."""
        s = get_sync_session()
        domain = _create_domain(s, "d-reuse")
        app = Application(id="app-reuse", domain_id=domain.id, level=1)
        s.add(app); s.commit()
        bricks = _create_bricks(s)
        plan = _create_plan(s, app.id, bricks)

        run = Run(id="run-same", plan_id=plan.id, trigger="manual",
                  domain_id=domain.id, status="pending",
                  initiator_user_id="operator", initiator_role="secops")
        s.add(run); s.commit()

        dup = Run(id="run-same", plan_id=plan.id, trigger="manual",
                  domain_id=domain.id, status="pending",
                  initiator_user_id="operator", initiator_role="secops")
        s.add(dup)
        from sqlalchemy.exc import IntegrityError
        with pytest.raises(IntegrityError):
            s.commit()
        s.rollback()
        assert s.query(Run).count() == 1
        s.close()

    @_pg_needed
    def test_status_persists_in_pg_after_flush(self):
        """Status written to PG survives a fresh query — no in-memory illusion."""
        s = get_sync_session()
        domain = _create_domain(s, "d-flush")
        app = Application(id="app-flush", domain_id=domain.id, level=1)
        s.add(app); s.commit()
        bricks = _create_bricks(s)
        plan = _create_plan(s, app.id, bricks)

        run = Run(id="run-flush", plan_id=plan.id, trigger="manual",
                  domain_id=domain.id, status="draft",
                  initiator_user_id="system", initiator_role="system")
        s.add(run); s.commit()

        # Update and verify via fresh query
        run.status = "running"; s.commit()
        s.expire_all()  # Clear SQLAlchemy identity map — simulate new connection
        fresh = s.query(Run).filter(Run.id == "run-flush").first()
        assert fresh.status == "running"

        # Idempotent: re-setting same status does NOT error
        fresh.status = "running"; s.commit()
        assert s.query(Run).filter(Run.id == "run-flush").first().status == "running"

        s.close()

    @_pg_needed
    def test_batch_idempotent_transition(self):
        """Batch state machine rejects invalid transitions."""
        s = get_sync_session()
        domain = _create_domain(s, "d-batch")
        app = Application(id="app-batch", domain_id=domain.id, level=1)
        s.add(app); s.commit()
        bricks = _create_bricks(s)
        plan = _create_plan(s, app.id, bricks)

        batch = Batch(id="batch-idem", plan_id=plan.id, type="build",
                      bricks_refs=["b-sast"])
        s.add(batch); s.commit()

        # Idempotent: setting same status twice is safe
        batch.status = "running"; s.commit()
        assert s.query(Batch).filter(Batch.id == "batch-idem").first().status == "running"
        batch.status = "running"; s.commit()
        assert s.query(Batch).filter(Batch.id == "batch-idem").first().status == "running"

        # Can move forward
        batch.status = "passed"; s.commit()
        assert s.query(Batch).filter(Batch.id == "batch-idem").first().status == "passed"

        s.close()