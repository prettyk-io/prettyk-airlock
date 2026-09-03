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
    COS-099: опциональная security-секция (pinned SBOM / vuln report digests) —
    входит в canonical checksum, модификация пинов ловится контролем целостности.
    """

    @staticmethod
    def build_manifest(
        release_id: str,
        revision: int,
        artifact_plane: ArtifactPlane,
        package_mode: PackageMode,
        payload_refs: list[str],
        metadata: dict[str, Any] | None = None,
        security: Any | None = None,
    ) -> dict[str, Any]:
        """Собрать manifest для TransferItem.

        security: dict (или pydantic-модель с model_dump) — pinned digests
        SBOM / vulnerability report (COS-099).
        """
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
        if security is not None:
            manifest["security"] = (
                security if isinstance(security, dict) else security.model_dump()
            )
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
        security: Any | None = None,
    ) -> TransferItem:
        """Собрать готовый TransferItem с manifest + checksum + PackageRevision."""
        from orchestrator.cosmo.transfer.contract import TransportProfile

        refs = payload_refs or []
        manifest = PackageBuilder.build_manifest(
            release_id, 1, artifact_plane, package_mode, refs, metadata,
            security=security,
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
        COS-099: security-секция (pinned digests) сохраняется — payload_refs
        те же, значит SBOM/report валидны и для новой revision.
        """
        manifest = PackageBuilder.build_manifest(
            item.release_id, new_revision, item.artifact_plane,
            item.package_mode, item.payload_refs,
            security=item.manifest.get("security"),
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

        # 7. COS-099: security pins (SBOM / vuln report digests)
        issues.extend(cls._validate_security_pins(item))

        return ValidationResult(passed=len(issues) == 0, issues=issues)

    @staticmethod
    def _validate_security_pins(item: TransferItem) -> list[ValidationIssue]:
        """Sanity security-секции манифеста (без payload-байтов)."""
        security = item.manifest.get("security") if item.manifest else None
        if not isinstance(security, dict):
            return []
        issues: list[ValidationIssue] = []
        sbom = security.get("sbom")
        if isinstance(sbom, dict):
            digest = str(sbom.get("sha256", ""))
            if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
                issues.append(ValidationIssue(
                    code="SECURITY_DIGEST_MALFORMED",
                    message=f"pinned sbom sha256 malformed: '{digest[:16]}...'",
                    failure_class=TransferFailureClass.VALIDATION_FAILURE,
                ))
            ref = str(sbom.get("ref", ""))
            if (item.package_mode == PackageMode.FULL_PACKAGE
                    and ref and ref not in item.payload_refs):
                issues.append(ValidationIssue(
                    code="SECURITY_REF_NOT_IN_PAYLOAD",
                    message=f"pinned sbom ref '{ref}' not in payload_refs",
                    failure_class=TransferFailureClass.VALIDATION_FAILURE,
                ))
        return issues

    @classmethod
    def validate_with_artifacts(
        cls,
        item: TransferItem,
        payload_bytes: dict[str, bytes],
        *,
        envelope_artifacts: list[dict[str, Any]] | None = None,
    ) -> ValidationResult:
        """COS-099: проверка pinned digests против ФАКТИЧЕСКИХ байтов payload.

        Отвергает пакет с модифицированным SBOM: sha256 предоставленных
        байтов обязан совпасть с manifest.security pin. Опциональная сверка
        с envelope artifacts (COS-126 bundle) — тройная tamper-evidence:
        manifest checksum ↔ payload bytes ↔ envelope digest.

        envelope_artifacts: [{name, artifact_type, sha256, size_bytes}] —
        envelope.artifacts_digest в to_dict()-форме (без импорта ledger).
        """
        result = cls.validate(item)
        issues = list(result.issues)
        security = item.manifest.get("security") if item.manifest else None
        if isinstance(security, dict):
            pins: list[tuple[str, str, str]] = []  # (kind, ref, sha256)
            sbom = security.get("sbom")
            if isinstance(sbom, dict) and sbom.get("ref"):
                pins.append(("sbom", str(sbom["ref"]), str(sbom.get("sha256", ""))))
            vr = security.get("vulnerability_report")
            if isinstance(vr, dict) and vr.get("ref") and vr.get("source") == "grype":
                pins.append(("vulnerability_report", str(vr["ref"]),
                             str(vr.get("sha256", ""))))
            for kind, ref, pinned in pins:
                data = payload_bytes.get(ref)
                if data is None:
                    issues.append(ValidationIssue(
                        code="SECURITY_PAYLOAD_MISSING",
                        message=f"pinned {kind} payload '{ref}' not provided",
                        failure_class=TransferFailureClass.VALIDATION_FAILURE,
                    ))
                    continue
                actual = hashlib.sha256(data).hexdigest()
                if actual != pinned:
                    issues.append(ValidationIssue(
                        code="SECURITY_PAYLOAD_DIGEST_MISMATCH",
                        message=(f"modified {kind} payload '{ref}': "
                                 f"pinned {pinned[:12]}..., got {actual[:12]}..."),
                        failure_class=TransferFailureClass.CHECKSUM_MISMATCH,
                    ))
                elif envelope_artifacts is not None:
                    matching = [a for a in envelope_artifacts
                                if a.get("sha256") == pinned]
                    if not matching:
                        issues.append(ValidationIssue(
                            code="SECURITY_ENVELOPE_DIGEST_MISMATCH",
                            message=(f"pinned {kind} digest {pinned[:12]}... "
                                     "not present in envelope artifacts"),
                            failure_class=TransferFailureClass.CHECKSUM_MISMATCH,
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