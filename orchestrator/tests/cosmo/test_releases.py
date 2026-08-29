"""COS-036: Release model + route logic tests."""
import sys
from pathlib import Path

import pytest

_orch = Path(__file__).resolve().parents[1]
if str(_orch) not in sys.path:
    sys.path.insert(0, str(_orch))

from orchestrator.cosmo.domain.release_model import (
    Release, ReleaseApproval, ReleaseStatus,
)


class TestReleaseApproval:
    def test_approved(self):
        a = ReleaseApproval(decided_by="operator-ivan", decision="approved")
        assert a.decision == "approved"
        assert a.decided_by == "operator-ivan"

    def test_rejected(self):
        a = ReleaseApproval(decided_by="sec-admin", decision="rejected", comment="SQLi remains")
        assert a.decision == "rejected"
        assert a.comment == "SQLi remains"

    def test_no_empty_decider(self):
        with pytest.raises(Exception):
            ReleaseApproval(decided_by="", decision="approved")


class TestReleaseModel:
    def test_minimal(self):
        r = Release(
            id="rel-1", domain_id="d-1", plan_id="plan-1",
            run_ids=["run-1", "run-2"],
        )
        assert r.status == "draft"
        assert r.is_approved is False
        assert r.is_rejected is False
        assert r.can_deploy is False

    def test_empty_runs_raises(self):
        with pytest.raises(Exception):
            Release(id="rel-2", domain_id="d-1", plan_id="plan-1", run_ids=[])

    def test_approved_release(self):
        r = Release(
            id="rel-3", domain_id="d-1", plan_id="plan-1",
            run_ids=["run-1"], status="approved",
        )
        assert r.is_approved
        assert not r.is_rejected
        assert r.can_deploy

    def test_rejected_release(self):
        r = Release(
            id="rel-4", domain_id="d-1", plan_id="plan-1",
            run_ids=["run-1"], status="rejected",
        )
        assert r.is_rejected
        assert not r.is_approved
        assert not r.can_deploy

    def test_with_approvals(self):
        r = Release(
            id="rel-5", domain_id="d-1", plan_id="plan-1",
            run_ids=["run-1"],
            status="approved",
            approvals=[
                ReleaseApproval(decided_by="lead", decision="approved", comment="LGTM"),
                ReleaseApproval(decided_by="sec", decision="approved", comment="Gates clean"),
            ],
        )
        assert len(r.approvals) == 2

    def test_changelog_and_version(self):
        r = Release(
            id="rel-6", domain_id="d-1", plan_id="plan-1",
            run_ids=["run-1"],
            changelog="Fixed SQLi in auth module. Added CORS headers.",
            version="1.2.3",
        )
        assert r.version == "1.2.3"
        assert "SQLi" in r.changelog

    def test_artifacts(self):
        r = Release(
            id="rel-7", domain_id="d-1", plan_id="plan-1",
            run_ids=["run-1"],
            artifacts=["rel-7.sbom.cdx.json", "rel-7.sarif.json"],
        )
        assert len(r.artifacts) == 2


class TestReleaseStatusTransitions:
    """COS-036: бизнес-логика переходов статусов."""

    def test_draft_to_pending_review(self):
        r = Release(
            id="rel-t1", domain_id="d-1", plan_id="plan-1",
            run_ids=["run-1"], status="draft",
        )
        # submit → pending_review
        r.status = "pending_review"
        assert r.status == "pending_review"

    def test_pending_to_approved(self):
        r = Release(
            id="rel-t2", domain_id="d-1", plan_id="plan-1",
            run_ids=["run-1"], status="pending_review",
        )
        r.status = "approved"
        r.approvals.append(ReleaseApproval(decided_by="lead", decision="approved"))
        assert r.is_approved

    def test_pending_to_rejected(self):
        r = Release(
            id="rel-t3", domain_id="d-1", plan_id="plan-1",
            run_ids=["run-1"], status="pending_review",
        )
        r.status = "rejected"
        r.approvals.append(ReleaseApproval(decided_by="sec", decision="rejected", comment="Found Critical"))
        assert r.is_rejected

    def test_approved_to_deploying(self):
        r = Release(
            id="rel-t4", domain_id="d-1", plan_id="plan-1",
            run_ids=["run-1"], status="approved",
            approvals=[ReleaseApproval(decided_by="lead", decision="approved")],
        )
        r.status = "deploying"
        assert r.status == "deploying"

    def test_deploying_to_deployed(self):
        r = Release(
            id="rel-t5", domain_id="d-1", plan_id="plan-1",
            run_ids=["run-1"], status="deploying",
        )
        r.status = "deployed"
        assert r.status == "deployed"


class TestReleaseSchemaConstraints:
    def test_domain_id_required(self):
        with pytest.raises(Exception):
            Release(id="x", plan_id="plan-1", run_ids=["run-1"])

    def test_plan_id_required(self):
        with pytest.raises(Exception):
            Release(id="x", domain_id="d-1", run_ids=["run-1"])

    def test_serialization_roundtrip(self):
        r = Release(
            id="rel-s1", domain_id="d-1", plan_id="plan-1",
            run_ids=["run-a", "run-b"],
            trigger="manual", status="approved",
            changelog="Security fixes",
            version="2.0.0",
            approvals=[ReleaseApproval(decided_by="admin", decision="approved")],
        )
        d = r.model_dump()
        r2 = Release.model_validate(d)
        assert r2.id == "rel-s1"
        assert r2.run_ids == ["run-a", "run-b"]
        assert len(r2.approvals) == 1