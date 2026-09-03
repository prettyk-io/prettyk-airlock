# -*- coding: utf-8 -*-
"""COS-050/COS-053: PureK-owned Transfer Kernel.

Provider-neutral transfer contract, package builder, pre-transfer validator,
target landing state machine. Независим от СОД, Sfera и конкретного gateway.
"""
from orchestrator.cosmo.transfer.contract import (
    ArtifactPlane,
    PackageMode,
    PackageRevision,
    SODTransferAdapter,
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
    ValidationResult,
    ValidationIssue,
)
from orchestrator.cosmo.transfer.landing import (
    LandingCheckReport,
    LandingState,
    LandingStateError,
    LandingStateMachine,
    LandingTransition,
)
from orchestrator.cosmo.transfer.sbom import (
    SecuritySection,
    SBOMPin,
    SBOMResult,
    VulnReportPin,
    VulnReportResult,
    build_secured_package,
    envelope_artifacts_from_security,
    extract_security,
    generate_sbom,
    generate_vuln_report,
    sha256_hex,
)

__all__ = [
    # Contract
    "ArtifactPlane",
    "PackageMode",
    "PackageRevision",
    "SODTransferAdapter",
    "TransportProfile",
    "TransferFailureClass",
    "TransferItem",
    "TransferItemStatus",
    "TransferPlan",
    "TransferPlanStatus",
    # Builder
    "PackageBuilder",
    "PreTransferValidator",
    "ValidationResult",
    "ValidationIssue",
    # Landing
    "LandingCheckReport",
    "LandingState",
    "LandingStateError",
    "LandingStateMachine",
    "LandingTransition",
    # SBOM (COS-099)
    "SecuritySection",
    "SBOMPin",
    "SBOMResult",
    "VulnReportPin",
    "VulnReportResult",
    "build_secured_package",
    "envelope_artifacts_from_security",
    "extract_security",
    "generate_sbom",
    "generate_vuln_report",
    "sha256_hex",
]