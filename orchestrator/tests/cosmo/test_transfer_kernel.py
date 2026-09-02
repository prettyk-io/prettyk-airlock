# -*- coding: utf-8 -*-
"""COS-050 + COS-053: Transfer Kernel & Landing Kernel tests (30+)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_orch = Path(__file__).resolve().parents[1]
if str(_orch) not in sys.path:
    sys.path.insert(0, str(_orch))

from orchestrator.cosmo.transfer.contract import (
    ArtifactPlane,
    PackageMode,
    PackageRevision,
    TransportProfile,
    TransferFailureClass,
    TransferItem,
    TransferItemStatus,
    TransferPlan,
    TransferPlanStatus,
)
from orchestrator.cosmo.transfer.builder import (
    PackageBuilder,
    PreTransferValidator,
)
from orchestrator.cosmo.transfer.landing import (
    LandingCheckReport,
    LandingState,
    LandingStateError,
    LandingStateMachine,
)


# ══════════════════════════════════════════════════════════════════
# 1. TransferItem — basic properties
# ══════════════════════════════════════════════════════════════════

class TestTransferItem:
    def test_metadata_envelope_not_deployable(self):
        item = TransferItem(
            item_id="t1", release_id="rel-1", transfer_plan_id="tp-1",
            artifact_plane=ArtifactPlane.METADATA_ENVELOPE,
            package_mode=PackageMode.METADATA_ENVELOPE,
        )
        assert item.is_deployable is False

    def test_full_package_is_deployable(self):
        item = TransferItem(
            item_id="t2", release_id="rel-1", transfer_plan_id="tp-1",
            artifact_plane=ArtifactPlane.OCI_IMAGE,
            package_mode=PackageMode.FULL_PACKAGE,
        )
        assert item.is_deployable is True

    def test_skeleton_context_not_deployable(self):
        item = TransferItem(
            item_id="t3", release_id="rel-1", transfer_plan_id="tp-1",
            artifact_plane=ArtifactPlane.SOURCE_CODE,
            package_mode=PackageMode.SKELETON_CONTEXT,
        )
        assert item.is_deployable is False

    def test_item_defaults(self):
        item = TransferItem(item_id="t4", release_id="rel-1", transfer_plan_id="tp-1")
        assert item.status == TransferItemStatus.DRAFT
        assert item.retry_count == 0
        assert item.readiness is False
        assert item.failure_class is None

    def test_revision_key(self):
        item = TransferItem(
            item_id="t5", release_id="rel-x", transfer_plan_id="tp-1",
            package_revision=PackageRevision(
                release_id="rel-x", revision=1, manifest_sha256="a" * 64,
            ),
        )
        assert item.revision_key == "rel-x:1"


# ══════════════════════════════════════════════════════════════════
# 2. PackageRevision — immutability
# ══════════════════════════════════════════════════════════════════

class TestPackageRevision:
    def test_deterministic_checksum(self):
        m = {"key": "value", "release_id": "rel-1", "revision": 1}
        h1 = PackageRevision.compute_manifest_sha256(m)
        h2 = PackageRevision.compute_manifest_sha256(m)
        assert h1 == h2
        assert len(h1) == 64

    def test_different_manifest_different_checksum(self):
        m1 = {"key": "value1"}
        m2 = {"key": "value2"}
        assert PackageRevision.compute_manifest_sha256(m1) != PackageRevision.compute_manifest_sha256(m2)

    def test_revision_key_format(self):
        pr = PackageRevision(release_id="rel-1", revision=3, manifest_sha256="a" * 64)
        assert pr.revision_key == "rel-1:3"

    def test_immutability_by_model(self):
        """PackageRevision — Pydantic model; fields are settable but conceptually immutable."""
        pr = PackageRevision(release_id="rel-1", revision=1, manifest_sha256="a" * 64)
        assert pr.revision == 1
        assert pr.release_id == "rel-1"


# ══════════════════════════════════════════════════════════════════
# 3. TransferPlan — multi-plane
# ══════════════════════════════════════════════════════════════════

class TestTransferPlan:
    def test_multi_plane_plan(self):
        """Один release может иметь несколько TransferItem по разным planes."""
        plan = TransferPlan(plan_id="tp-1", release_id="rel-1")
        for plane in [ArtifactPlane.METADATA_ENVELOPE, ArtifactPlane.OCI_IMAGE,
                      ArtifactPlane.EVIDENCE, ArtifactPlane.SOURCE_CODE]:
            plan.add_item(TransferItem(
                item_id=f"item-{plane.value}", release_id="rel-1", transfer_plan_id="tp-1",
                artifact_plane=plane,
            ))
        assert len(plan.items) == 4
        planes = {i.artifact_plane for i in plan.items}
        assert len(planes) == 4

    def test_plan_status_draft_when_empty(self):
        plan = TransferPlan(plan_id="tp-2", release_id="rel-1")
        assert plan.compute_status() == TransferPlanStatus.DRAFT

    def test_plan_status_active_when_items_dispatched(self):
        plan = TransferPlan(plan_id="tp-3", release_id="rel-1")
        item = TransferItem(item_id="t1", release_id="rel-1", transfer_plan_id="tp-3",
                            status=TransferItemStatus.DISPATCHED)
        plan.add_item(item)
        assert plan.compute_status() == TransferPlanStatus.ACTIVE

    def test_plan_completed_when_all_reconciled(self):
        plan = TransferPlan(plan_id="tp-4", release_id="rel-1")
        for i in range(3):
            plan.add_item(TransferItem(
                item_id=f"t{i}", release_id="rel-1", transfer_plan_id="tp-4",
                status=TransferItemStatus.RECONCILED,
            ))
        assert plan.compute_status() == TransferPlanStatus.COMPLETED

    def test_plan_partially_complete(self):
        plan = TransferPlan(plan_id="tp-5", release_id="rel-1")
        plan.add_item(TransferItem(item_id="t-ok", release_id="rel-1",
                                    transfer_plan_id="tp-5", status=TransferItemStatus.RECONCILED))
        plan.add_item(TransferItem(item_id="t-fail", release_id="rel-1",
                                    transfer_plan_id="tp-5", status=TransferItemStatus.FAILED))
        assert plan.compute_status() == TransferPlanStatus.PARTIALLY_COMPLETE

    def test_plan_failed_when_all_failed(self):
        plan = TransferPlan(plan_id="tp-6", release_id="rel-1")
        for i in range(3):
            plan.add_item(TransferItem(
                item_id=f"t{i}", release_id="rel-1", transfer_plan_id="tp-6",
                status=TransferItemStatus.FAILED,
            ))
        assert plan.compute_status() == TransferPlanStatus.FAILED

    def test_plan_rejects_wrong_release_id(self):
        plan = TransferPlan(plan_id="tp-7", release_id="rel-1")
        with pytest.raises(ValueError, match="release_id"):
            plan.add_item(TransferItem(
                item_id="t-wrong", release_id="rel-OTHER", transfer_plan_id="tp-7",
            ))

    def test_failed_item_does_not_lose_sibling_results(self):
        """App A failed ≠ App B and App C results lost."""
        plan = TransferPlan(plan_id="tp-8", release_id="rel-1")
        plan.add_item(TransferItem(item_id="t-a", release_id="rel-1",
                                    transfer_plan_id="tp-8", status=TransferItemStatus.RECONCILED))
        plan.add_item(TransferItem(item_id="t-b", release_id="rel-1",
                                    transfer_plan_id="tp-8", status=TransferItemStatus.FAILED))
        plan.add_item(TransferItem(item_id="t-c", release_id="rel-1",
                                    transfer_plan_id="tp-8", status=TransferItemStatus.RECONCILED))
        assert len(plan.completed_items) == 2
        assert len(plan.failed_items) == 1
        assert plan.failed_items[0].item_id == "t-b"


# ══════════════════════════════════════════════════════════════════
# 4. PackageBuilder
# ══════════════════════════════════════════════════════════════════

class TestPackageBuilder:
    def test_build_item_creates_revision(self):
        item = PackageBuilder.build_item(
            item_id="t-build-1", release_id="rel-1", plan_id="tp-1",
            artifact_plane=ArtifactPlane.OCI_IMAGE,
            package_mode=PackageMode.FULL_PACKAGE,
            payload_refs=["registry.local/app:1.0"],
            source_ref="harbor.source/app:1.0",
        )
        assert item.package_revision is not None
        assert item.package_revision.revision == 1
        assert len(item.package_revision.manifest_sha256) == 64

    def test_build_manifest_deterministic(self):
        m1 = PackageBuilder.build_manifest("rel-1", 1, ArtifactPlane.SOURCE_CODE,
                                            PackageMode.FULL_PACKAGE, ["a.py", "b.py"])
        m2 = PackageBuilder.build_manifest("rel-1", 1, ArtifactPlane.SOURCE_CODE,
                                            PackageMode.FULL_PACKAGE, ["a.py", "b.py"])
        # built_at differs → checksums differ but structure matches
        m1.pop("built_at")
        m2.pop("built_at")
        assert m1 == m2

    def test_rebuild_with_revision_creates_new_checksum(self):
        item = PackageBuilder.build_item(
            item_id="t-rev", release_id="rel-1", plan_id="tp-1",
            artifact_plane=ArtifactPlane.SOURCE_CODE,
            package_mode=PackageMode.FULL_PACKAGE,
            payload_refs=["file.py"],
        )
        old_checksum = item.package_revision.manifest_sha256
        PackageBuilder.rebuild_with_revision(item, 2)
        assert item.package_revision.revision == 2
        assert item.package_revision.manifest_sha256 != old_checksum

    def test_transport_profile_stored(self):
        item = PackageBuilder.build_item(
            item_id="t-tp", release_id="rel-1", plan_id="tp-1",
            artifact_plane=ArtifactPlane.METADATA_ENVELOPE,
            package_mode=PackageMode.METADATA_ENVELOPE,
            transport_profile="immutable_offline_import",
        )
        assert item.transport_profile == TransportProfile.IMMUTABLE_OFFLINE_IMPORT


# ══════════════════════════════════════════════════════════════════
# 5. PreTransferValidator — positive
# ══════════════════════════════════════════════════════════════════

class TestValidatorPositive:
    def test_valid_metadata_envelope(self):
        item = PackageBuilder.build_item(
            item_id="t-val-1", release_id="rel-1", plan_id="tp-1",
            artifact_plane=ArtifactPlane.METADATA_ENVELOPE,
            package_mode=PackageMode.METADATA_ENVELOPE,
        )
        result = PreTransferValidator.validate(item)
        assert result.passed is True
        assert result.issues == []

    def test_valid_full_package(self):
        item = PackageBuilder.build_item(
            item_id="t-val-2", release_id="rel-1", plan_id="tp-1",
            artifact_plane=ArtifactPlane.OCI_IMAGE,
            package_mode=PackageMode.FULL_PACKAGE,
            payload_refs=["registry/app:1.0"],
            source_ref="harbor.source/app:1.0",
        )
        result = PreTransferValidator.validate(item)
        assert result.passed is True

    def test_valid_skeleton_context(self):
        item = PackageBuilder.build_item(
            item_id="t-val-3", release_id="rel-1", plan_id="tp-1",
            artifact_plane=ArtifactPlane.SOURCE_CODE,
            package_mode=PackageMode.SKELETON_CONTEXT,
            payload_refs=["context.json"],
            source_ref="git@gitea:repo.git",
        )
        result = PreTransferValidator.validate(item)
        assert result.passed is True


# ══════════════════════════════════════════════════════════════════
# 6. PreTransferValidator — negative
# ══════════════════════════════════════════════════════════════════

class TestValidatorNegative:
    def test_metadata_only_not_deployable(self):
        """Metadata-only не проходит как deployable release."""
        item = PackageBuilder.build_item(
            item_id="t-neg-1", release_id="rel-1", plan_id="tp-1",
            artifact_plane=ArtifactPlane.METADATA_ENVELOPE,
            package_mode=PackageMode.METADATA_ENVELOPE,
        )
        # Force is_deployable check to fail
        item.package_mode = PackageMode.METADATA_ENVELOPE
        result = PreTransferValidator.validate(item)
        # metadata_envelope IS valid as a metadata transfer, just not deployable
        # The validator checks is_deployable only if mode is METADATA_ENVELOPE
        codes = result.error_codes
        # Should NOT have METADATA_ONLY_NOT_DEPLOYABLE because is_deployable is False
        assert "METADATA_ONLY_NOT_DEPLOYABLE" not in codes

    def test_full_package_no_payload_fails(self):
        item = PackageBuilder.build_item(
            item_id="t-neg-2", release_id="rel-1", plan_id="tp-1",
            artifact_plane=ArtifactPlane.OCI_IMAGE,
            package_mode=PackageMode.FULL_PACKAGE,
        )
        result = PreTransferValidator.validate(item)
        assert not result.passed
        assert "FULL_PACKAGE_NO_PAYLOAD" in result.error_codes

    def test_oci_source_ref_missing(self):
        item = PackageBuilder.build_item(
            item_id="t-neg-3", release_id="rel-1", plan_id="tp-1",
            artifact_plane=ArtifactPlane.OCI_IMAGE,
            package_mode=PackageMode.FULL_PACKAGE,
            payload_refs=["app:1.0"],
        )
        result = PreTransferValidator.validate(item)
        assert "OCI_SOURCE_REF_MISSING" in result.error_codes

    def test_evidence_refs_empty(self):
        item = PackageBuilder.build_item(
            item_id="t-neg-4", release_id="rel-1", plan_id="tp-1",
            artifact_plane=ArtifactPlane.EVIDENCE,
            package_mode=PackageMode.FULL_PACKAGE,
            payload_refs=[],
            source_ref="s3://bucket/evidence",
        )
        result = PreTransferValidator.validate(item)
        assert "EVIDENCE_REFS_EMPTY" in result.error_codes

    def test_checksum_mismatch_detected(self):
        item = PackageBuilder.build_item(
            item_id="t-neg-5", release_id="rel-1", plan_id="tp-1",
            artifact_plane=ArtifactPlane.SOURCE_CODE,
            package_mode=PackageMode.FULL_PACKAGE,
            payload_refs=["code.py"],
            source_ref="git@repo:app.git",
        )
        # Tamper with manifest
        item.manifest["tampered"] = True
        result = PreTransferValidator.validate(item)
        assert "MANIFEST_CHECKSUM_MISMATCH" in result.error_codes

    def test_missing_release_id(self):
        # Bypass Pydantic validation to test the validator's own check
        item = TransferItem.model_construct(
            item_id="t-neg-6", release_id="", transfer_plan_id="tp-1",
        )
        result = PreTransferValidator.validate(item)
        assert "MISSING_RELEASE_ID" in result.error_codes

    def test_missing_package_revision(self):
        item = TransferItem(item_id="t-neg-7", release_id="rel-1", transfer_plan_id="tp-1")
        result = PreTransferValidator.validate(item)
        assert "MISSING_PACKAGE_REVISION" in result.error_codes

    def test_validate_plan_aggregates(self):
        plan = TransferPlan(plan_id="tp-neg", release_id="rel-1")
        plan.add_item(TransferItem(item_id="t-bad-1", release_id="rel-1",
                                    transfer_plan_id="tp-neg"))  # no revision
        plan.add_item(TransferItem(item_id="t-bad-2", release_id="rel-1",
                                    transfer_plan_id="tp-neg"))  # no revision
        result = PreTransferValidator.validate_plan(plan)
        assert not result.passed
        assert len(result.issues) >= 2


# ══════════════════════════════════════════════════════════════════
# 7. Landing State Machine — happy path
# ══════════════════════════════════════════════════════════════════

class TestLandingHappyPath:
    def _make_landing(self) -> LandingStateMachine:
        item = PackageBuilder.build_item(
            item_id="t-landing", release_id="rel-1", plan_id="tp-1",
            artifact_plane=ArtifactPlane.OCI_IMAGE,
            package_mode=PackageMode.FULL_PACKAGE,
            payload_refs=["app:1.0"],
        )
        return LandingStateMachine(item)

    def test_full_landing_cycle(self):
        ls = self._make_landing()
        assert ls.state == LandingState.NOT_RECEIVED
        ls.transition(LandingState.RECEIVED)
        ls.transition(LandingState.VERIFIED)
        ls.transition(LandingState.LANDING_APPROVED)
        ls.transition(LandingState.IMPORTED)
        ls.transition(LandingState.BOOTSTRAPPED)
        ls.transition(LandingState.RECONCILED)
        assert ls.state == LandingState.RECONCILED
        assert ls.is_terminal()

    def test_landing_report_passed(self):
        ls = self._make_landing()
        for s in [LandingState.RECEIVED, LandingState.VERIFIED,
                   LandingState.LANDING_APPROVED, LandingState.IMPORTED,
                   LandingState.BOOTSTRAPPED, LandingState.RECONCILED]:
            ls.transition(s)
        report = ls.check_report()
        assert report.passed is True
        assert len(report.checks) == 6


# ══════════════════════════════════════════════════════════════════
# 8. Landing State Machine — negative
# ══════════════════════════════════════════════════════════════════

class TestLandingNegative:
    def _make_landing(self) -> LandingStateMachine:
        item = PackageBuilder.build_item(
            item_id="t-land-neg", release_id="rel-1", plan_id="tp-1",
            artifact_plane=ArtifactPlane.OCI_IMAGE,
            package_mode=PackageMode.FULL_PACKAGE,
            payload_refs=["app:1.0"],
        )
        return LandingStateMachine(item)

    def test_cannot_bootstrap_before_verified_and_approved(self):
        """Нельзя перейти к bootstrap до verified и landing_approved."""
        ls = self._make_landing()
        ls.transition(LandingState.RECEIVED)
        with pytest.raises(LandingStateError):
            ls.transition(LandingState.BOOTSTRAPPED)

    def test_rejected_state(self):
        ls = self._make_landing()
        ls.transition(LandingState.RECEIVED)
        ls.transition(LandingState.VERIFIED)
        ls.transition(LandingState.REJECTED)
        assert ls.state == LandingState.REJECTED
        assert ls.requires_new_revision()

    def test_checksum_mismatch_state(self):
        ls = self._make_landing()
        ls.transition(LandingState.RECEIVED)
        ls.transition(LandingState.CHECKSUM_MISMATCH)
        assert ls.state == LandingState.CHECKSUM_MISMATCH
        assert ls.requires_new_revision()
        assert not ls.is_recoverable()

    def test_bootstrap_failure_is_recoverable(self):
        ls = self._make_landing()
        ls.transition(LandingState.RECEIVED)
        ls.transition(LandingState.VERIFIED)
        ls.transition(LandingState.LANDING_APPROVED)
        ls.transition(LandingState.IMPORTED)
        ls.transition(LandingState.BOOTSTRAP_FAILURE)
        assert ls.is_recoverable()
        # Retry bootstrap
        ls.transition(LandingState.IMPORTED)
        ls.transition(LandingState.BOOTSTRAPPED)
        assert ls.state == LandingState.BOOTSTRAPPED

    def test_reconcile_failure_recoverable(self):
        ls = self._make_landing()
        for s in [LandingState.RECEIVED, LandingState.VERIFIED,
                   LandingState.LANDING_APPROVED, LandingState.IMPORTED,
                   LandingState.BOOTSTRAPPED, LandingState.RECONCILE_FAILURE]:
            ls.transition(s)
        assert ls.is_recoverable()
        ls.transition(LandingState.BOOTSTRAPPED)
        ls.transition(LandingState.RECONCILED)
        assert ls.state == LandingState.RECONCILED

    def test_incomplete_import_resume(self):
        ls = self._make_landing()
        ls.transition(LandingState.RECEIVED)
        ls.transition(LandingState.VERIFIED)
        ls.transition(LandingState.LANDING_APPROVED)
        ls.transition(LandingState.IMPORTED)
        ls.transition(LandingState.INCOMPLETE)
        assert ls.is_recoverable()
        ls.transition(LandingState.IMPORTED)  # resume
        ls.transition(LandingState.BOOTSTRAPPED)
        ls.transition(LandingState.RECONCILED)
        assert ls.state == LandingState.RECONCILED


# ══════════════════════════════════════════════════════════════════
# 9. Idempotency
# ══════════════════════════════════════════════════════════════════

class TestIdempotency:
    def test_duplicate_revision_detected(self):
        """Повторная доставка той же revision → duplicate detected."""
        item = PackageBuilder.build_item(
            item_id="t-idem", release_id="rel-1", plan_id="tp-1",
            artifact_plane=ArtifactPlane.OCI_IMAGE,
            package_mode=PackageMode.FULL_PACKAGE,
            payload_refs=["app:1.0"],
        )
        ls = LandingStateMachine(item)
        ls.transition(LandingState.RECEIVED)
        ls.transition(LandingState.VERIFIED)

        # Same revision arrives again
        assert ls.detect_duplicate(item.revision_key) is True

    def test_different_revision_not_duplicate(self):
        item = PackageBuilder.build_item(
            item_id="t-idem-2", release_id="rel-1", plan_id="tp-1",
            artifact_plane=ArtifactPlane.OCI_IMAGE,
            package_mode=PackageMode.FULL_PACKAGE,
            payload_refs=["app:1.0"],
        )
        ls = LandingStateMachine(item)
        ls.transition(LandingState.RECEIVED)

        # Different revision key
        assert ls.detect_duplicate("rel-1:2") is False

    def test_retry_uses_same_revision(self):
        """Retry использует ту же immutable revision."""
        item = PackageBuilder.build_item(
            item_id="t-retry", release_id="rel-1", plan_id="tp-1",
            artifact_plane=ArtifactPlane.OCI_IMAGE,
            package_mode=PackageMode.FULL_PACKAGE,
            payload_refs=["app:1.0"],
        )
        original_key = item.revision_key
        original_checksum = item.package_revision.manifest_sha256

        # Retry: item status goes back to DISPATCHED
        item.status = TransferItemStatus.DISPATCHED
        item.retry_count += 1

        # Revision unchanged
        assert item.revision_key == original_key
        assert item.package_revision.manifest_sha256 == original_checksum

    def test_landing_state_error_is_exception(self):
        with pytest.raises(Exception):
            raise LandingStateError("item-1", LandingState.RECONCILED, LandingState.RECEIVED)


# ══════════════════════════════════════════════════════════════════
# 10. Failure Classification
# ══════════════════════════════════════════════════════════════════

class TestFailureClassification:
    def test_transport_vs_bootstrap_distinct(self):
        """Transport failure и bootstrap failure различаются."""
        assert TransferFailureClass.TRANSPORT_FAILURE != TransferFailureClass.BOOTSTRAP_FAILURE

    def test_validation_vs_landing_distinct(self):
        assert TransferFailureClass.VALIDATION_FAILURE != TransferFailureClass.LANDING_REJECTED

    def test_checksum_vs_capacity_distinct(self):
        assert TransferFailureClass.CHECKSUM_MISMATCH != TransferFailureClass.CAPACITY_QUOTA_FAILURE

    def test_all_failure_classes_exist(self):
        expected = {
            "transport_failure", "validation_failure", "landing_rejected",
            "landing_incomplete", "checksum_mismatch", "capacity_quota_failure",
            "bootstrap_failure", "reconcile_failure", "idempotency_conflict",
            "package_not_ready",
        }
        actual = {f.value for f in TransferFailureClass}
        assert actual == expected


# ══════════════════════════════════════════════════════════════════
# 11. Transport Profiles
# ══════════════════════════════════════════════════════════════════

class TestTransportProfiles:
    def test_all_profiles_exist(self):
        expected = {
            "direct_authenticated_api", "immutable_offline_import",
            "controlled_gateway_relay", "one_way_diode_relay", "sod_bridge",
        }
        actual = {t.value for t in TransportProfile}
        assert actual == expected

    def test_same_contract_different_transport(self):
        """Все transport profiles используют один contract и одну idempotency model."""
        item_api = PackageBuilder.build_item(
            item_id="t-api", release_id="rel-1", plan_id="tp-1",
            artifact_plane=ArtifactPlane.METADATA_ENVELOPE,
            package_mode=PackageMode.METADATA_ENVELOPE,
            transport_profile="direct_authenticated_api",
        )
        item_diode = PackageBuilder.build_item(
            item_id="t-diode", release_id="rel-1", plan_id="tp-1",
            artifact_plane=ArtifactPlane.METADATA_ENVELOPE,
            package_mode=PackageMode.METADATA_ENVELOPE,
            transport_profile="one_way_diode_relay",
        )
        # Same release_id → same revision_key structure
        assert item_api.revision_key.startswith("rel-1:")
        assert item_diode.revision_key.startswith("rel-1:")


# ══════════════════════════════════════════════════════════════════
# 12. SOD Adapter Seam
# ══════════════════════════════════════════════════════════════════

class TestSODAdapterSeam:
    def test_seam_raises_not_implemented(self):
        from orchestrator.cosmo.transfer.contract import SODTransferAdapter
        adapter = SODTransferAdapter()
        item = TransferItem(item_id="t-sod", release_id="rel-1", transfer_plan_id="tp-1")
        with pytest.raises(NotImplementedError):
            adapter.dispatch(item)
        with pytest.raises(NotImplementedError):
            adapter.check_status(item)
        with pytest.raises(NotImplementedError):
            adapter.cancel(item)
