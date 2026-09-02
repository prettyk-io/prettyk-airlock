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
]