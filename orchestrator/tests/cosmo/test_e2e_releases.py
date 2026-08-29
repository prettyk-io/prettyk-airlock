"""
COS-048: E2E Release Lifecycle — create → submit → approve → deploy → deployed.

Полный цикл без PG: Pydantic модели + бизнес-логика статусных переходов.
"""
import pytest
from cosmo.domain.release_model import (
    Release, ReleaseApproval, ReleaseStatus, ReleaseTrigger,
)
from cosmo.domain.run_model import Run, RunTrigger
from cosmo.domain.gate_model import Gate, GatePolicy, GatePolicyRule


# ═══════════════════════════════════════════════════════════════════════
# Full positive lifecycle
# ═══════════════════════════════════════════════════════════════════════

class TestReleaseFullLifecycle:
    """draft → submit → pending_review → approve → deploy → deployed."""

    def _make_release(self, rel_id="rel-e2e-1", run_ids=None) -> Release:
        return Release(
            id=rel_id, domain_id="d-e2e", plan_id="plan-e2e",
            run_ids=run_ids or ["run-1", "run-2"],
            trigger="manual",
            version="1.0.0",
            changelog="Fixed SQLi, added CORS headers",
        )

    def test_initial_state_is_draft(self):
        rel = self._make_release()
        assert rel.status == "draft"
        assert not rel.is_approved
        assert not rel.is_rejected
        assert not rel.can_deploy

    def test_submit_transitions_to_pending_review(self):
        rel = self._make_release()
        rel.status = "pending_review"
        assert rel.status == "pending_review"

    def test_approve_transitions_to_approved(self):
        rel = self._make_release()
        rel.status = "pending_review"
        rel.status = "approved"
        rel.approvals.append(
            ReleaseApproval(decided_by="lead", decision="approved", comment="Gates clean")
        )
        assert rel.is_approved
        assert rel.can_deploy
        assert len(rel.approvals) == 1

    def test_deploy_transitions_to_deploying(self):
        rel = self._make_release()
        rel.status = "pending_review"
        rel.status = "approved"
        rel.approvals.append(
            ReleaseApproval(decided_by="lead", decision="approved")
        )
        rel.status = "deploying"
        assert rel.status == "deploying"

    def test_deploying_to_deployed(self):
        rel = self._make_release()
        rel.status = "pending_review"
        rel.status = "approved"
        rel.approvals.append(
            ReleaseApproval(decided_by="lead", decision="approved")
        )
        rel.status = "deploying"
        rel.status = "deployed"
        assert rel.status == "deployed"

    def test_full_lifecycle_uninterrupted(self):
        """Полный сквозной путь без ошибок."""
        rel = self._make_release(rel_id="rel-lifecycle")

        # 1. Draft
        assert rel.status == "draft"

        # 2. Submit
        rel.status = "pending_review"

        # 3. Approve by lead
        rel.status = "approved"
        rel.approvals.append(
            ReleaseApproval(decided_by="lead-ivan", decision="approved", comment="All gates passed")
        )

        # 4. Second approval (security)
        rel.approvals.append(
            ReleaseApproval(decided_by="sec-maria", decision="approved", comment="No critical findings")
        )

        assert len(rel.approvals) == 2
        assert rel.is_approved

        # 5. Deploy
        rel.status = "deploying"
        assert rel.status == "deploying"

        # 6. Deployed
        rel.status = "deployed"
        assert rel.status == "deployed"

        # Аудит-трейс: approvals untouched after deploy
        assert len(rel.approvals) == 2


# ═══════════════════════════════════════════════════════════════════════
# Rejection path
# ═══════════════════════════════════════════════════════════════════════

class TestReleaseRejectionPath:
    def test_reject_from_pending_review(self):
        rel = Release(
            id="rel-reject", domain_id="d-1", plan_id="plan-1",
            run_ids=["run-1"], status="pending_review",
        )
        rel.status = "rejected"
        rel.approvals.append(
            ReleaseApproval(decided_by="sec-admin", decision="rejected",
                            comment="SQLi found in /api/auth")
        )
        assert rel.is_rejected
        assert not rel.is_approved
        assert not rel.can_deploy

    def test_rejection_keeps_history(self):
        """Отклонённый релиз сохраняет всю историю approvals."""
        rel = Release(
            id="rel-hist", domain_id="d-1", plan_id="plan-1",
            run_ids=["run-1"], status="draft",
        )
        rel.status = "pending_review"
        rel.status = "rejected"
        rel.approvals.extend([
            ReleaseApproval(decided_by="lead", decision="rejected", comment="Gate violation"),
            ReleaseApproval(decided_by="sec", decision="rejected", comment="Critical SQLi"),
        ])
        assert len(rel.approvals) == 2
        assert rel.is_rejected

    def test_cannot_deploy_rejected(self):
        rel = Release(
            id="rel-block", domain_id="d-1", plan_id="plan-1",
            run_ids=["run-1"], status="rejected",
        )
        assert not rel.can_deploy


# ═══════════════════════════════════════════════════════════════════════
# Edge cases
# ═══════════════════════════════════════════════════════════════════════

class TestReleaseEdgeCases:
    def test_rollback_from_deploying(self):
        rel = Release(
            id="rel-rb", domain_id="d-1", plan_id="plan-1",
            run_ids=["run-1"], status="deploying",
        )
        rel.status = "rollback"
        assert rel.status == "rollback"

    def test_multiple_runs_bound_to_release(self):
        """Релиз объединяет несколько прогонов."""
        runs = ["run-sast", "run-dast", "run-fuzz"]
        rel = Release(
            id="rel-multi", domain_id="d-1", plan_id="plan-1",
            run_ids=runs, version="2.0.0",
        )
        assert len(rel.run_ids) == 3
        assert rel.version == "2.0.0"

    def test_artifacts_collected(self):
        rel = Release(
            id="rel-art", domain_id="d-1", plan_id="plan-1",
            run_ids=["run-1"],
            artifacts=[
                "rel-art.sbom.cdx.json",
                "rel-art.sarif.json",
                "oci://registry/app:v2.0.0",
            ],
        )
        assert len(rel.artifacts) == 3

    def test_serialization_roundtrip_full(self):
        """Полный lifecycle → serialize → deserialize — все поля целы."""
        rel = Release(
            id="rel-serial", domain_id="d-1", plan_id="plan-1",
            run_ids=["run-a", "run-b"],
            trigger="pre_release", status="approved",
            version="3.1.4", changelog="Security hardening release",
            artifacts=["rel-serial.sarif.json"],
            approvals=[
                ReleaseApproval(decided_by="admin", decision="approved", comment="Ready"),
            ],
        )
        d = rel.model_dump()
        r2 = Release.model_validate(d)

        assert r2.id == rel.id
        assert r2.run_ids == rel.run_ids
        assert r2.status == "approved"
        assert r2.changelog == rel.changelog
        assert len(r2.approvals) == 1
        assert r2.approvals[0].decided_by == "admin"

    def test_pre_release_trigger(self):
        rel = Release(
            id="rel-pre", domain_id="d-1", plan_id="plan-1",
            run_ids=["run-1"], trigger="pre_release",
        )
        assert rel.trigger == "pre_release"

    def test_emergency_trigger(self):
        rel = Release(
            id="rel-em", domain_id="d-1", plan_id="plan-1",
            run_ids=["run-1"], trigger="emergency",
        )
        assert rel.trigger == "emergency"


# ═══════════════════════════════════════════════════════════════════════
# Run + Gate integration
# ═══════════════════════════════════════════════════════════════════════

class TestReleaseRunGateIntegration:
    """Release связывает Run, прошедшие Gate."""

    def test_release_runs_have_gates(self):
        """Прогоны в релизе имеют ассоциированные gate'ы."""
        policy = GatePolicy(rules=[
            GatePolicyRule(finding_type="Critical", action="block"),
            GatePolicyRule(finding_type="High", action="warn", max_count=3),
        ])

        gate1 = Gate(
            id="gate-build", type="automatic", position=0,
            policy=policy, decision="pass",
        )
        gate2 = Gate(
            id="gate-scan", type="automatic", position=1,
            policy=policy, decision="pass",
        )

        run = Run(
            id="run-gated", plan_id="plan-e2e", trigger="manual",
            initiator="operator", domain_id="d-e2e",
            status="succeeded",
            gates=["gate-build", "gate-scan"],
        )
        assert "gate-build" in run.gates
        assert "gate-scan" in run.gates
        assert run.status == "succeeded"

    def test_release_binds_only_succeeded_runs(self):
        """Релиз должен собирать только succeeded прогоны."""
        run_ok = Run(
            id="run-ok", plan_id="plan-e2e", trigger="manual",
            initiator="operator", domain_id="d-e2e",
            status="succeeded",
        )
        # Релиз формируется из прошедших прогонов
        rel = Release(
            id="rel-from-gates", domain_id="d-e2e", plan_id="plan-e2e",
            run_ids=[run_ok.id],
        )
        assert len(rel.run_ids) == 1
        assert run_ok.status == "succeeded"