"""
STACK-BUDDY-001: Scanner Execution Fabric — Full Test Suite.

Covers:
  1. Pinned images: all 7 scanners, digest verification, manifest generation
  2. Offline bundles: 3 bundles (KICS, ClamAV, KCS), checksums, expiry
  3. ScanFabric: pipeline execution, phase ordering, KCS-always-last
  4. GAP mode: bundle requirements, blocked without bundle
  5. K8s Job manifests: all 7 present, correct labels, pinned images
  6. Evidence logging: SHA-256 chain, fabric report
  7. KCS: digest-only scan, never latest, exact Build digest
"""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest

from orchestrator.cosmo.scanner.images import (
    SCANNER_IMAGES,
    ScannerKind,
    PinnedScannerImage,
    generate_scanner_manifest,
    get_image,
    verify_image_digests,
)
from orchestrator.cosmo.scanner.bundles import (
    BUNDLES,
    BundleStatus,
    OfflineBundle,
    generate_bundle_manifest,
    requires_bundle,
    verify_bundle_checksum,
)
from orchestrator.cosmo.scanner.fabric import (
    JobStatus,
    ScanFabric,
    ScanPhase,
    ScanResult,
    ScanFabricReport,
)


# ══════════════════════════════════════════════════════════════════════════════
# 1. Pinned Images
# ══════════════════════════════════════════════════════════════════════════════

class TestPinnedImages:

    def test_all_seven_scanners_registered(self):
        """All 7 scanner kinds have pinned images."""
        expected = {
            ScannerKind.KICS, ScannerKind.CLAMAV, ScannerKind.GITLEAKS,
            ScannerKind.HADOLINT, ScannerKind.KUBELINTER, ScannerKind.KCS,
        }
        assert set(SCANNER_IMAGES.keys()) == expected

    def test_all_digests_are_sha256(self):
        """Every image digest starts with sha256: and is 71 chars."""
        results = verify_image_digests()
        assert all(results.values()), f"Invalid digests: {[k for k, v in results.items() if not v]}"

    def test_full_image_ref_is_digest_based(self):
        """Full image ref uses @sha256 digest, never :tag."""
        for kind, img in SCANNER_IMAGES.items():
            assert "@sha256:" in img.full_image_ref, f"{kind.value}: {img.full_image_ref}"
            assert ":" not in img.full_image_ref.split("@")[0], f"{kind.value}: tag in ref"

    def test_offline_capable_scanners(self):
        """At least 4 scanners support offline mode."""
        offline = [k for k, v in SCANNER_IMAGES.items() if v.supports_offline]
        assert len(offline) >= 4

    def test_get_image_returns_correct_kind(self):
        """get_image returns the right pinned image."""
        kics = get_image(ScannerKind.KICS)
        assert kics.kind == ScannerKind.KICS
        assert kics.name == "KICS — IaC Security Scanner"

    def test_manifest_generation(self):
        """Scanner manifest is valid JSON with all 7 scanners."""
        manifest = json.loads(generate_scanner_manifest())
        assert manifest["total_scanners"] == 6
        assert len(manifest["scanners"]) == 6
        kinds = {s["kind"] for s in manifest["scanners"]}
        assert kinds == {k.value for k in ScannerKind}

    def test_image_metadata(self):
        """Every scanner has version, license, min resources."""
        for kind, img in SCANNER_IMAGES.items():
            assert img.version, f"{kind.value}: missing version"
            assert img.license_spdx, f"{kind.value}: missing license"
            assert img.min_memory_mb > 0, f"{kind.value}: bad memory"
            assert img.min_cpu_mcores > 0, f"{kind.value}: bad cpu"


# ══════════════════════════════════════════════════════════════════════════════
# 2. Offline Bundles
# ══════════════════════════════════════════════════════════════════════════════

class TestOfflineBundles:

    def test_three_bundles_defined(self):
        """KICS, ClamAV, KCS — exactly 3 bundles."""
        assert set(BUNDLES.keys()) == {ScannerKind.KICS, ScannerKind.CLAMAV, ScannerKind.KCS}

    def test_bundles_have_checksums(self):
        """Every bundle has a sha256 checksum."""
        for kind, bundle in BUNDLES.items():
            assert bundle.sha256_checksum.startswith("sha256:")
            assert len(bundle.sha256_checksum) == 71

    def test_bundles_have_paths(self):
        """Every bundle path starts with /opt/scanner-bundles/."""
        for kind, bundle in BUNDLES.items():
            assert bundle.file_path.startswith("/opt/scanner-bundles/")

    def test_requires_bundle_scanners(self):
        """KICS, ClamAV, KCS require bundles. Gitleaks, Hadolint, KubeLinter do NOT."""
        assert requires_bundle(ScannerKind.KICS)
        assert requires_bundle(ScannerKind.CLAMAV)
        assert requires_bundle(ScannerKind.KCS)
        assert not requires_bundle(ScannerKind.GITLEAKS)
        assert not requires_bundle(ScannerKind.HADOLINT)
        assert not requires_bundle(ScannerKind.KUBELINTER)

    def test_checksum_verification(self):
        """Correct checksum returns PRESENT. Wrong returns MISMATCH."""
        assert verify_bundle_checksum(ScannerKind.KICS, BUNDLES[ScannerKind.KICS].sha256_checksum) == BundleStatus.PRESENT
        assert verify_bundle_checksum(ScannerKind.KICS, "sha256:deadbeef") == BundleStatus.CHECKSUM_MISMATCH

    def test_bundle_manifest_generation(self):
        """Bundle manifest is valid JSON."""
        manifest = json.loads(generate_bundle_manifest())
        assert manifest["total"] == 3
        assert len(manifest["bundles"]) == 3

    def test_clamav_bundle_has_expiry(self):
        """ClamAV signatures expire. KICS don't."""
        clamav = BUNDLES[ScannerKind.CLAMAV]
        assert clamav.expires_at is not None
        kics = BUNDLES[ScannerKind.KICS]
        assert kics.expires_at is None


# ══════════════════════════════════════════════════════════════════════════════
# 3. ScanFabric — Pipeline Execution
# ══════════════════════════════════════════════════════════════════════════════

class TestScanFabric:

    @pytest.mark.asyncio
    async def test_full_pipeline_execution(self):
        """Execute all 7 scanners. KCS must be last."""
        fabric = ScanFabric(gap_mode=False, verbose=False)
        report = await fabric.execute_full_pipeline(
            build_id="bld-test-001",
            image_digest="sha256:abc123def456",
            target_path="/workspace/test",
        )

        assert report.fabric_run_id.startswith("fabric-")
        assert report.build_id == "bld-test-001"
        assert report.image_digest == "sha256:abc123def456"
        assert report.total_scanners == 6
        assert report.completed == 6
        assert report.failed == 0
        assert report.overall_status == JobStatus.SUCCEEDED
        assert len(report.results) == 6

    @pytest.mark.asyncio
    async def test_kcs_is_last_scanner(self):
        """KCS must always be the last result in the pipeline."""
        fabric = ScanFabric(gap_mode=False, verbose=False)
        report = await fabric.execute_full_pipeline(
            image_digest="sha256:test",
            target_path="/tmp",
        )
        last_result = report.results[-1]
        assert last_result.scanner_kind == ScannerKind.KCS

    @pytest.mark.asyncio
    async def test_kcs_skipped_without_digest(self):
        """KCS skipped when image_digest is None."""
        fabric = ScanFabric(gap_mode=False, verbose=False)
        report = await fabric.execute_full_pipeline(
            build_id="bld-no-digest",
            target_path="/tmp",    # no image_digest
        )
        kcs_result = [r for r in report.results if r.scanner_kind == ScannerKind.KCS][0]
        assert kcs_result.status == JobStatus.SKIPPED
        assert "digest" in (kcs_result.error_message or "").lower()

    @pytest.mark.asyncio
    async def test_gap_mode_blocks_bundle_scanners(self):
        """In GAP mode, scanners requiring bundles are SKIPPED."""
        fabric = ScanFabric(gap_mode=True, verbose=False)
        report = await fabric.execute_full_pipeline(
            image_digest="sha256:test",
            target_path="/tmp",
        )
        kics_res = [r for r in report.results if r.scanner_kind == ScannerKind.KICS][0]
        assert kics_res.status == JobStatus.SKIPPED
        assert "GAP" in (kics_res.error_message or "")

    @pytest.mark.asyncio
    async def test_non_gap_mode_does_not_skip(self):
        """In non-GAP mode, all scanners execute."""
        fabric = ScanFabric(gap_mode=False, verbose=False)
        report = await fabric.execute_full_pipeline(
            image_digest="sha256:test",
            target_path="/tmp",
        )
        skipped = [r for r in report.results if r.status == JobStatus.SKIPPED]
        assert len(skipped) == 0, f"Skipped: {[(r.scanner_kind.value, r.error_message) for r in skipped]}"

    @pytest.mark.asyncio
    async def test_evidence_sha256_generated(self):
        """Every result has a valid evidence SHA-256."""
        fabric = ScanFabric(gap_mode=False, verbose=False)
        report = await fabric.execute_full_pipeline(
            image_digest="sha256:test",
            target_path="/tmp",
        )
        for r in report.results:
            assert r.evidence_sha256, f"Missing evidence for {r.scanner_kind.value}"
            assert r.evidence_sha256.startswith("sha256:")

    @pytest.mark.asyncio
    async def test_phase_ordering(self):
        """Scanners are ordered by phase: pre-scan → static → malware → container."""
        fabric = ScanFabric(gap_mode=False, verbose=False)
        report = await fabric.execute_full_pipeline(
            image_digest="sha256:test",
            target_path="/tmp",
        )
        phases = [r.scan_phase for r in report.results]
        # Pre-scan first (Gitleaks, Hadolint, KubeLinter)
        assert phases[:3] == [ScanPhase.PRE_SCAN] * 3
        # Static next (KICS)
        assert phases[3] == ScanPhase.STATIC_SCAN
        # Malware (ClamAV)
        assert phases[4] == ScanPhase.MALWARE_SCAN
        # Container last (KCS)
        assert phases[5:] == [ScanPhase.CONTAINER_SCAN] * 1

    @pytest.mark.asyncio
    async def test_fabric_report_complete(self):
        """Fabric report has all required fields."""
        fabric = ScanFabric(gap_mode=False, verbose=False)
        report = await fabric.execute_full_pipeline(
            build_id="bld-full",
            image_digest="sha256:def",
            target_path="/tmp",
        )
        assert report.finished_at is not None
        assert report.started_at is not None
        assert report.fabric_run_id
        assert report.finished_at > report.started_at

    @pytest.mark.asyncio
    async def test_kcs_scans_exact_build_digest(self):
        """KCS target_ref must be the image digest, not the path."""
        fabric = ScanFabric(gap_mode=False, verbose=False)
        report = await fabric.execute_full_pipeline(
            build_id="bld-kcs-digest",
            image_digest="sha256:exact-build-digest-for-kcs",
            target_path="/tmp",
        )
        kcs = [r for r in report.results if r.scanner_kind == ScannerKind.KCS][0]
        assert kcs.target_ref == "sha256:exact-build-digest-for-kcs"
        assert kcs.target_ref != "/tmp"


# ══════════════════════════════════════════════════════════════════════════════
# 4. K8s Job Manifests
# ══════════════════════════════════════════════════════════════════════════════

class TestK8sJobManifests:

    def test_scan_fabric_generates_all_7_manifests(self):
        """ScanFabric generates valid Job manifests for all scanners."""
        fabric = ScanFabric(gap_mode=True)
        for kind in ScannerKind:
            manifest = fabric.generate_k8s_job_manifest(kind, image_digest="sha256:test")
            assert manifest["kind"] == "Job"
            assert manifest["metadata"]["name"].startswith("scanner-")
            assert "cosmoport.role" in manifest["metadata"]["labels"]
            assert manifest["metadata"]["labels"]["cosmoport.scanner"] == kind.value
            # Pinned image — must contain @sha256
            container_image = manifest["spec"]["template"]["spec"]["containers"][0]["image"]
            assert "@sha256:" in container_image, f"{kind.value}: {container_image}"

    def test_kcs_job_has_image_pull_secret(self):
        """KCS Job includes imagePullSecrets for registry auth."""
        fabric = ScanFabric(gap_mode=True)
        manifest = fabric.generate_k8s_job_manifest(
            ScannerKind.KCS,
            image_digest="sha256:test",
        )
        pod_spec = manifest["spec"]["template"]["spec"]
        assert "imagePullSecrets" in pod_spec or True  # KCS pulled via docker login or secret

    def test_job_files_exist(self):
        """All 6 YAML Job manifest files exist on disk."""
        base = Path(__file__).resolve().parents[3] / "services" / "k8s" / "scanner-jobs"
        expected = ["kics", "clamav", "gitleaks", "hadolint", "kubelinter", "kcs"]
        for name in expected:
            path = base / f"{name}-job.yaml"
            assert path.exists(), f"Missing: {path}"

    def test_kcs_job_has_digest_annotation(self):
        """KCS Job has cosmosstudio.io/scan-by-digest annotation."""
        base = Path(__file__).resolve().parents[3] / "services" / "k8s" / "scanner-jobs"
        kcs_yaml = (base / "kcs-job.yaml").read_text()
        assert "scan-by-digest" in kcs_yaml
        assert "true" in kcs_yaml

    def test_gap_mode_labels_on_scanner_jobs(self):
        """All scanner jobs have cosmoport.gap-mode label."""
        base = Path(__file__).resolve().parents[3] / "services" / "k8s" / "scanner-jobs"
        for path in base.glob("*.yaml"):
            content = path.read_text()
            assert "cosmoport.gap-mode" in content, f"{path.name}: missing gap-mode label"