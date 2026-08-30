"""
STACK-BUDDY-001: Pinned scanner images with checksums and provenance.

Each scanner image is pinned by immutable digest (NEVER by mutable tag).
All images support offline operation: signatures/rules must be bundled.
Provenance metadata for SLSA attestation.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional


class ScannerKind(str, Enum):
    KICS = "kics"
    CLAMAV = "clamav"
    GITLEAKS = "gitleaks"
    HADOLINT = "hadolint"
    KUBELINTER = "kubelinter"
    KCS = "kcs"


@dataclass(frozen=True)
class PinnedScannerImage:
    """Immutable scanner image pinned by digest. Never mutable tag."""
    kind: ScannerKind
    name: str
    image_repository: str
    image_tag: str
    image_digest: str                         # sha256:abc...
    full_image_ref: str = field(init=False)   # repo@sha256:digest
    platforms: List[str] = field(default_factory=lambda: ["linux/amd64"])

    # Offline capabilities
    supports_offline: bool = True
    bundle_required: bool = True
    default_bundle_path: str = ""
    default_checksum: str = ""                # sha256 of the bundle

    # Metadata
    version: str = ""
    license_spdx: str = ""
    source_url: str = ""
    min_memory_mb: int = 512
    min_cpu_mcores: int = 250

    def __post_init__(self):
        object.__setattr__(self, "full_image_ref", f"{self.image_repository}@{self.image_digest}")

    def manifest_entry(self) -> dict:
        return {
            "kind": self.kind.value,
            "name": self.name,
            "image": self.full_image_ref,
            "digest": self.image_digest,
            "platforms": self.platforms,
            "version": self.version,
            "offline": self.supports_offline,
            "bundle": self.default_bundle_path,
            "bundle_checksum": self.default_checksum,
        }


# ══════════════════════════════════════════════════════════════════════════════
# Canonical scanner images — pinned by digest (STACK-BUDDY-001)
# ══════════════════════════════════════════════════════════════════════════════

SCANNER_IMAGES: dict[ScannerKind, PinnedScannerImage] = {
    ScannerKind.KICS: PinnedScannerImage(
        kind=ScannerKind.KICS,
        name="KICS — IaC Security Scanner",
        image_repository="checkmarx/kics",
        image_tag="v2.1.4-alpine",
        image_digest="sha256:0000000000000000000000000000000000000000000000000000000000000001",
        version="2.1.4",
        license_spdx="Apache-2.0",
        source_url="https://github.com/Checkmarx/kics",
        default_bundle_path="/opt/scanner-bundles/kics/queries.tar.gz",
        default_checksum="sha256:00000000000000000000000000000000000000000000000000000000000000a1",
        min_memory_mb=512,
        min_cpu_mcores=500,
    ),
    ScannerKind.CLAMAV: PinnedScannerImage(
        kind=ScannerKind.CLAMAV,
        name="ClamAV — Malware & Virus Scanner",
        image_repository="clamav/clamav",
        image_tag="1.4.1",
        image_digest="sha256:0000000000000000000000000000000000000000000000000000000000000002",
        version="1.4.1",
        license_spdx="GPL-2.0",
        source_url="https://github.com/Cisco-Talos/clamav",
        default_bundle_path="/opt/scanner-bundles/clamav/daily.cvd",
        default_checksum="sha256:00000000000000000000000000000000000000000000000000000000000000a2",
        min_memory_mb=1024,
        min_cpu_mcores=500,
    ),
    ScannerKind.GITLEAKS: PinnedScannerImage(
        kind=ScannerKind.GITLEAKS,
        name="Gitleaks — Secrets Detection",
        image_repository="zricethezav/gitleaks",
        image_tag="v8.21.2",
        image_digest="sha256:0000000000000000000000000000000000000000000000000000000000000003",
        version="8.21.2",
        license_spdx="MIT",
        source_url="https://github.com/gitleaks/gitleaks",
        bundle_required=False,   # Gitleaks rules are built-in + custom config
        default_bundle_path="/opt/scanner-bundles/gitleaks/.gitleaks.toml",
        min_memory_mb=256,
        min_cpu_mcores=250,
    ),
    ScannerKind.HADOLINT: PinnedScannerImage(
        kind=ScannerKind.HADOLINT,
        name="Hadolint — Dockerfile/build-context lint",
        image_repository="hadolint/hadolint",
        image_tag="v2.12.0-alpine",
        image_digest="sha256:0000000000000000000000000000000000000000000000000000000000000004",
        version="2.12.0",
        license_spdx="GPL-3.0",
        source_url="https://github.com/hadolint/hadolint",
        bundle_required=False,
        default_bundle_path="/opt/scanner-bundles/hadolint/.hadolint.yaml",
        min_memory_mb=128,
        min_cpu_mcores=100,
    ),
    ScannerKind.KUBELINTER: PinnedScannerImage(
        kind=ScannerKind.KUBELINTER,
        name="KubeLinter — Kubernetes Manifest Linter",
        image_repository="stackrox/kube-linter",
        image_tag="0.7.1",
        image_digest="sha256:0000000000000000000000000000000000000000000000000000000000000005",
        version="0.7.1",
        license_spdx="Apache-2.0",
        source_url="https://github.com/stackrox/kube-linter",
        bundle_required=False,
        default_bundle_path="/opt/scanner-bundles/kubelinter/.kube-linter.yaml",
        min_memory_mb=256,
        min_cpu_mcores=250,
    ),
    ScannerKind.KCS: PinnedScannerImage(
        kind=ScannerKind.KCS,
        name="Kaspersky Container Security — Container Scan (final step)",
        image_repository="kcs-scanner",
        image_tag="latest",
        image_digest="sha256:0000000000000000000000000000000000000000000000000000000000000006",
        version="enterprise",
        license_spdx="Proprietary",
        source_url="",
        supports_offline=True,
        bundle_required=True,
        default_bundle_path="/opt/scanner-bundles/kcs/bases.tar.gz",
        default_checksum="sha256:00000000000000000000000000000000000000000000000000000000000000a6",
        min_memory_mb=2048,
        min_cpu_mcores=1000,
    ),
}


def get_image(kind: ScannerKind) -> PinnedScannerImage:
    return SCANNER_IMAGES[kind]


def verify_image_digests() -> dict[str, bool]:
    """Verify all scanner image digests are valid sha256 format."""
    results = {}
    for kind, img in SCANNER_IMAGES.items():
        digest = img.image_digest
        valid = digest.startswith("sha256:") and len(digest) == 71
        results[kind.value] = valid
    return results


def generate_scanner_manifest() -> str:
    """Generate JSON manifest of all pinned scanner images."""
    manifest = {
        "manifest_version": "1.0",
        "generated_for": "STACK-BUDDY-001",
        "scanners": [img.manifest_entry() for img in SCANNER_IMAGES.values()],
        "total_scanners": len(SCANNER_IMAGES),
        "offline_capable": sum(1 for img in SCANNER_IMAGES.values() if img.supports_offline),
    }
    return json.dumps(manifest, indent=2)


def compute_sha256(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()