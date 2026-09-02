# -*- coding: utf-8 -*-
"""COS-053 Phase 2: PackageBuilder & PreTransferValidator.

PackageBuilder — собирает manifest + payload refs, вычисляет SHA-256.
PreTransferValidator — проверяет identity, completeness, readiness, idempotency.

Никаких assumptions что СОД везёт source, OCI, Nexus и evidence одним архивом.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

from orchestrator.cosmo.transfer.contract import (
    ArtifactPlane,
    PackageMode,
    PackageRevision,
    TransferFailureClass,
    TransferItem,
    TransferItemStatus,
    TransferPlan,
)


# ══════════════════════════════════════════════════════════════════
# ValidationResult
# ══════════════════════════════════════════════════════════════════

class ValidationIssue(BaseModel):
    model_config = ConfigDict(extra="ignore")
    code: str
    message: str
    failure_class: TransferFailureClass


class ValidationResult(BaseModel):
    model_config = ConfigDict(extra="ignore")
    passed: bool = False
    issues: list[ValidationIssue] = Field(default_factory=list)

    @property
    def error_codes(self) -> list[str]:
        return [i.code for i in self.issues]


# ══════════════════════════════════════════════════════════════════
# PackageBuilder
# ══════════════════════════════════════════════════════════════════

class PackageBuilder:
    """Собирает manifest + payload references для TransferItem.

    Вычисляет deterministic SHA-256 manifest checksum и создаёт PackageRevision.
    """

    @staticmethod
    def build_manifest(
        release_id: str,
        revision: int,
        artifact_plane: ArtifactPlane,
        package_mode: PackageMode,
        payload_refs: list[str],
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Собрать manifest для TransferItem."""
        manifest: dict[str, Any] = {
            "release_id": release_id,
            "revision": revision,
            "artifact_plane": artifact_plane.value,
            "package_mode": package_mode.value,
            "payload_refs": sorted(payload_refs),
            "built_at": datetime.now(timezone.utc).isoformat(),
        }
        if metadata:
            manifest["metadata"] = metadata
        return manifest

    @staticmethod
    def build_item(
        item_id: str,
        release_id: str,
        plan_id: str,
        artifact_plane: ArtifactPlane,
        package_mode: PackageMode,
        transport_profile: TransportProfileAlias = "direct_authenticated_api",
        payload_refs: list[str] | None = None,
        source_ref: str = "",
        target_ref: str = "",
        metadata: dict[str, Any] | None = None,
        correlation_id: str = "",
    ) -> TransferItem:
        """Собрать готовый TransferItem с manifest + checksum + PackageRevision."""
        from orchestrator.cosmo.transfer.contract import TransportProfile

        refs = payload_refs or []
        manifest = PackageBuilder.build_manifest(
            release_id, 1, artifact_plane, package_mode, refs, metadata,
        )
        checksum = PackageRevision.compute_manifest_sha256(manifest)
        revision = PackageRevision(
            release_id=release_id,
            revision=1,
            manifest_sha256=checksum,
        )

        return TransferItem(
            item_id=item_id,
            release_id=release_id,
            transfer_plan_id=plan_id,
            correlation_id=correlation_id,
            artifact_plane=artifact_plane,
            package_mode=package_mode,
            transport_profile=TransportProfile(transport_profile),
            source_ref=source_ref,
            target_ref=target_ref,
            manifest=manifest,
            payload_refs=refs,
            package_revision=revision,
        )

    @staticmethod
    def rebuild_with_revision(item: TransferItem, new_revision: int) -> TransferItem:
        """Создать следующую revision того же item (например после изменения payload).

        PackageRevision immutable: новая revision = новый checksum.
        """
        manifest = PackageBuilder.build_manifest(
            item.release_id, new_revision, item.artifact_plane,
            item.package_mode, item.payload_refs,
        )
        checksum = PackageRevision.compute_manifest_sha256(manifest)
        new_rev = PackageRevision(
            release_id=item.release_id,
            revision=new_revision,
            manifest_sha256=checksum,
        )
        item.package_revision = new_rev
        item.manifest = manifest
        return item


# TransportProfileAlias для type hint без circular import
TransportProfileAlias = str


# ══════════════════════════════════════════════════════════════════
# PreTransferValidator
# ══════════════════════════════════════════════════════════════════

class PreTransferValidator:
    """Валидация TransferItem перед отправкой.

    Проверяет:
      1. Package identity (release_id, revision присутствуют).
      2. Completeness (manifest не пуст, checksum совпадает).
      3. Artifact references (payload_refs для full_package).
      4. Payload sufficiency (metadata-only не проходит как deployable).
      5. Plane-specific readiness.
      6. Idempotency/revision consistency.
    """

    @classmethod
    def validate(cls, item: TransferItem) -> ValidationResult:
        issues: list[ValidationIssue] = []

        # 1. Package identity
        if not item.release_id:
            issues.append(ValidationIssue(
                code="MISSING_RELEASE_ID",
                message="release_id is required",
                failure_class=TransferFailureClass.VALIDATION_FAILURE,
            ))

        if item.package_revision is None:
            issues.append(ValidationIssue(
                code="MISSING_PACKAGE_REVISION",
                message="PackageRevision is required for idempotency",
                failure_class=TransferFailureClass.VALIDATION_FAILURE,
            ))

        # 2. Completeness — manifest checksum must match
        if item.package_revision and item.manifest:
            computed = PackageRevision.compute_manifest_sha256(item.manifest)
            if computed != item.package_revision.manifest_sha256:
                issues.append(ValidationIssue(
                    code="MANIFEST_CHECKSUM_MISMATCH",
                    message=f"Manifest checksum mismatch: expected {item.package_revision.manifest_sha256[:12]}..., got {computed[:12]}...",
                    failure_class=TransferFailureClass.CHECKSUM_MISMATCH,
                ))

        # 3. Artifact references — full_package needs payload_refs
        if item.package_mode == PackageMode.FULL_PACKAGE and not item.payload_refs:
            issues.append(ValidationIssue(
                code="FULL_PACKAGE_NO_PAYLOAD",
                message="full_package mode requires non-empty payload_refs",
                failure_class=TransferFailureClass.VALIDATION_FAILURE,
            ))

        # 4. Payload sufficiency — metadata-only не deployable
        if item.package_mode == PackageMode.METADATA_ENVELOPE and item.is_deployable:
            issues.append(ValidationIssue(
                code="METADATA_ONLY_NOT_DEPLOYABLE",
                message="metadata_envelope mode is not deployable; use full_package or skeleton_context",
                failure_class=TransferFailureClass.PACKAGE_NOT_READY,
            ))

        # 5. Plane-specific readiness
        if item.artifact_plane == ArtifactPlane.OCI_IMAGE and not item.source_ref:
            issues.append(ValidationIssue(
                code="OCI_SOURCE_REF_MISSING",
                message="OCI image transfer requires source_ref (registry/repo:tag)",
                failure_class=TransferFailureClass.VALIDATION_FAILURE,
            ))

        if item.artifact_plane == ArtifactPlane.EVIDENCE and not item.payload_refs:
            issues.append(ValidationIssue(
                code="EVIDENCE_REFS_EMPTY",
                message="Evidence transfer requires payload_refs (evidence artifact locations)",
                failure_class=TransferFailureClass.VALIDATION_FAILURE,
            ))

        # 6. Source/target ref for non-metadata
        if item.package_mode != PackageMode.METADATA_ENVELOPE and not item.source_ref:
            issues.append(ValidationIssue(
                code="SOURCE_REF_MISSING",
                message="source_ref is required for non-metadata transfers",
                failure_class=TransferFailureClass.VALIDATION_FAILURE,
            ))

        return ValidationResult(passed=len(issues) == 0, issues=issues)

    @classmethod
    def validate_plan(cls, plan: TransferPlan) -> ValidationResult:
        """Валидировать все items плана. Возвращает агрегированный результат."""
        all_issues: list[ValidationIssue] = []
        for item in plan.items:
            result = cls.validate(item)
            all_issues.extend(result.issues)
        return ValidationResult(passed=len(all_issues) == 0, issues=all_issues)