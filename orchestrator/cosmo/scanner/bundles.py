"""
STACK-BUDDY-001: Offline rules/signature bundles for scanner fabric.

Each scanner requiring offline operation (KICS, ClamAV, KCS) has a bundle
of signatures/rules/queries. Bundles are checksum-protected and versioned.

In GAP mode: bundles MUST be pre-loaded. Runtime pull of signatures is BLOCKED.
"""

from __future__ import annotations

import datetime
import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional

from orchestrator.cosmo.scanner.images import ScannerKind


class BundleStatus(str, Enum):
    PRESENT = "present"
    MISSING = "missing"
    EXPIRED = "expired"
    CHECKSUM_MISMATCH = "checksum_mismatch"


@dataclass(frozen=True)
class OfflineBundle:
    """Immutable offline scanner bundle (rules, signatures, queries)."""
    scanner_kind: ScannerKind
    bundle_id: str                         # e.g. "kics-queries-v2.1.4"
    version: str                           # matching scanner version
    file_path: str                         # path in shared volume
    sha256_checksum: str
    size_bytes: int = 0
    update_url: str = ""                   # where to fetch updates (airgap: internal mirror)
    last_updated: str = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat())
    expires_at: Optional[str] = None       # None = no expiry


# ══════════════════════════════════════════════════════════════════════════════
# Canonical offline bundles (STACK-BUDDY-001)
# ══════════════════════════════════════════════════════════════════════════════

BUNDLES: Dict[ScannerKind, OfflineBundle] = {
    ScannerKind.KICS: OfflineBundle(
        scanner_kind=ScannerKind.KICS,
        bundle_id="kics-queries-v2.1.4",
        version="2.1.4",
        file_path="/opt/scanner-bundles/kics/queries.tar.gz",
        sha256_checksum="sha256:00000000000000000000000000000000000000000000000000000000000000a1",
        size_bytes=15_000_000,
        update_url="https://mirror.cosmoport.local/bundles/kics/queries-v2.1.4.tar.gz",
    ),
    ScannerKind.CLAMAV: OfflineBundle(
        scanner_kind=ScannerKind.CLAMAV,
        bundle_id="clamav-sigs-daily",
        version="daily-1.4.1",
        file_path="/opt/scanner-bundles/clamav/daily.cvd",
        sha256_checksum="sha256:00000000000000000000000000000000000000000000000000000000000000a2",
        size_bytes=200_000_000,
        update_url="https://mirror.cosmoport.local/bundles/clamav/daily.cvd",
        expires_at=(datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=1)).isoformat(),
    ),
    ScannerKind.KCS: OfflineBundle(
        scanner_kind=ScannerKind.KCS,
        bundle_id="kcs-bases-enterprise",
        version="enterprise",
        file_path="/opt/scanner-bundles/kcs/bases.tar.gz",
        sha256_checksum="sha256:00000000000000000000000000000000000000000000000000000000000000a6",
        size_bytes=500_000_000,
        update_url="https://mirror.cosmoport.local/bundles/kcs/bases.tar.gz",
    ),
}

# Scanners WITHOUT bundles (built-in rules only)
NO_BUNDLE_SCANNERS = {
    ScannerKind.GITLEAKS,
    ScannerKind.HADOLINT,
    ScannerKind.KUBELINTER,
}


def get_bundle(kind: ScannerKind) -> OfflineBundle:
    if kind not in BUNDLES:
        raise KeyError(f"No offline bundle defined for {kind.value}")
    return BUNDLES[kind]


def requires_bundle(kind: ScannerKind) -> bool:
    return kind not in NO_BUNDLE_SCANNERS


def verify_bundle_checksum(kind: ScannerKind, actual_checksum: str) -> BundleStatus:
    """Verify a bundle against its expected checksum."""
    if kind not in BUNDLES:
        return BundleStatus.MISSING
    expected = BUNDLES[kind].sha256_checksum
    if actual_checksum != expected:
        return BundleStatus.CHECKSUM_MISMATCH
    # Check expiry
    bundle = BUNDLES[kind]
    if bundle.expires_at:
        expires = datetime.datetime.fromisoformat(bundle.expires_at)
        if datetime.datetime.now(datetime.timezone.utc) > expires:
            return BundleStatus.EXPIRED
    return BundleStatus.PRESENT


def generate_bundle_manifest() -> str:
    """Generate JSON manifest of all offline bundles."""
    entries = []
    for kind, bundle in BUNDLES.items():
        entries.append({
            "scanner": kind.value,
            "bundle_id": bundle.bundle_id,
            "version": bundle.version,
            "path": bundle.file_path,
            "checksum": bundle.sha256_checksum,
            "size_bytes": bundle.size_bytes,
            "expires_at": bundle.expires_at,
        })
    return json.dumps({
        "manifest_version": "1.0",
        "generated_for": "STACK-BUDDY-001",
        "bundles": entries,
        "total": len(entries),
    }, indent=2)