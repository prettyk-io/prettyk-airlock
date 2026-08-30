# -*- coding: utf-8 -*-
"""CBR-BOSS-002: CodeQL Artifact Matrix Correction & Negative Matrix Tests."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_orch = Path(__file__).resolve().parents[1]
if str(_orch) not in sys.path:
    sys.path.insert(0, str(_orch))

from orchestrator.cosmo.control_plane.build_modes import (
    BuildMode,
    BuildModeEngine,
    BuildProfile,
    CodeQLPolicy,
    CONTAINER_TOOLS,
    DebugSymbols,
    ProvenanceCapability,
    SBOMFormat,
    ScanProfile,
    ScanProfileEngine,
    ScanTool,
)


# ══════════════════════════════════════════════════════════════════
# 1. Build Modes & Compiler Abstractions
# ══════════════════════════════════════════════════════════════════

class TestBuildModes:
    def test_dev_mode_uses_sanitizers_list(self):
        p = BuildModeEngine.resolve("draft")
        assert p.mode == BuildMode.DEVELOPMENT
        assert p.optimization_level == 0
        assert p.debug_info == DebugSymbols.FULL
        assert "asan" in p.runtime_sanitizers
        assert "ubsan" in p.runtime_sanitizers
        assert not hasattr(p, "asan_enabled")

    def test_release_mode_no_sanitizers(self):
        p = BuildModeEngine.resolve("ordinary")
        assert p.mode == BuildMode.RELEASE
        assert p.optimization_level == 3
        assert p.debug_info == DebugSymbols.NONE
        assert p.runtime_sanitizers == []

    def test_hotfix_minimal_debug_info(self):
        p = BuildModeEngine.resolve("hotfix")
        assert p.mode == BuildMode.RELEASE
        assert p.optimization_level == 2
        assert p.debug_info == DebugSymbols.LINE_TABLES

    def test_validate_release_catches_sanitizers(self):
        p = BuildProfile(mode=BuildMode.RELEASE, runtime_sanitizers=["asan"])
        v = BuildModeEngine.validate_build(p)
        assert len(v) == 1
        assert "asan" in v[0]

    def test_validate_dev_allows_sanitizers(self):
        p = BuildProfile(mode=BuildMode.DEVELOPMENT, runtime_sanitizers=["asan", "ubsan", "tsan"])
        v = BuildModeEngine.validate_build(p)
        assert v == []

    def test_all_5_release_types_resolve(self):
        for rt in ["ordinary", "accelerated", "regulatory", "hotfix", "custom"]:
            p = BuildModeEngine.resolve(rt)
            assert p.mode == BuildMode.RELEASE


# ══════════════════════════════════════════════════════════════════
# 2. CBR-BOSS-002: CodeQL Canonical Matrix & Artifact Alignment
# ══════════════════════════════════════════════════════════════════

class TestCodeQLCanonicalMatrix:
    def test_purek_ordinary_source_has_sonarqube_and_codeql(self):
        """PureK ordinary source: SonarQube + CodeQL (CodeQLPolicy.PUREK)."""
        sp = ScanProfileEngine.resolve("source", release_type="ordinary", flavor="purek")
        tools = set(sp.tools)
        assert ScanTool.SONARQUBE in tools
        assert ScanTool.CODEQL in tools
        assert sp.codeql_policy == CodeQLPolicy.PUREK

    def test_cosmo_ordinary_source_no_codeql_before_bridge(self):
        """Cosmoport ordinary source: SonarQube + CodeScoring, CodeQL inactive (None)."""
        sp = ScanProfileEngine.resolve("source", release_type="ordinary", flavor="cosmo")
        tools = set(sp.tools)
        assert ScanTool.SONARQUBE in tools
        assert ScanTool.CODESCORING in tools
        assert ScanTool.CODEQL not in tools
        assert sp.codeql_policy is None

    def test_cosmo_regulatory_source_has_both_sonar_and_codeql(self):
        """Cosmoport security/regulatory source: SonarQube + CodeScoring + CodeQL (SECURITY_COSMO)."""
        sp = ScanProfileEngine.resolve("source", release_type="regulatory", flavor="cosmo")
        tools = set(sp.tools)
        assert ScanTool.SONARQUBE in tools
        assert ScanTool.CODESCORING in tools
        assert ScanTool.CODEQL in tools
        assert sp.codeql_policy == CodeQLPolicy.SECURITY_COSMO

    def test_cosmo_security_flavor_activates_codeql(self):
        """Flavor 'security' activates CodeQL with SECURITY_COSMO policy."""
        sp = ScanProfileEngine.resolve("source", release_type="ordinary", flavor="security")
        assert ScanTool.CODEQL in sp.tools
        assert sp.codeql_policy == CodeQLPolicy.SECURITY_COSMO

    def test_container_profile_canonical_tools(self):
        """Container profile: Hadolint + CycloneDX + Trivy + ClamAV + KCS + KubeLinter."""
        sp = ScanProfileEngine.resolve("docker_image")
        tools = set(sp.tools)
        assert ScanTool.HADOLINT in tools
        assert ScanTool.CYCLONEDX in tools
        assert ScanTool.TRIVY in tools
        assert ScanTool.CLAMAV in tools
        assert ScanTool.KCS in tools
        assert ScanTool.KUBELINTER in tools


# ══════════════════════════════════════════════════════════════════
# 3. CBR-BOSS-002: Negative Matrix Regression Tests (10+ tests)
# ══════════════════════════════════════════════════════════════════

class TestNegativeMatrixRegression:
    def test_neg_01_codeql_strictly_absent_from_container(self):
        """[NEG-01] CodeQL must NEVER be present in container / docker_image profile."""
        sp = ScanProfileEngine.resolve("docker_image")
        assert ScanTool.CODEQL not in sp.tools
        assert "codeql" not in [t.value for t in sp.tools]

    def test_neg_02_container_codeql_policy_is_none(self):
        """[NEG-02] Container profile codeql_policy must be strictly None."""
        sp = ScanProfileEngine.resolve("docker_image")
        assert sp.codeql_policy is None

    def test_neg_03_container_override_cannot_inject_codeql(self):
        """[NEG-03] Overrides cannot inject CodeQL into a container profile."""
        sp = ScanProfileEngine.resolve(
            "docker_image",
            overrides={"tools": [ScanTool.TRIVY, ScanTool.CODEQL], "codeql_policy": CodeQLPolicy.PUREK},
        )
        assert ScanTool.CODEQL not in sp.tools
        assert sp.codeql_policy is None

    def test_neg_04_sonarqube_absent_from_container(self):
        """[NEG-04] SonarQube is source-analysis only, absent from container profile."""
        sp = ScanProfileEngine.resolve("docker_image")
        assert ScanTool.SONARQUBE not in sp.tools

    def test_neg_05_codescoring_absent_from_container(self):
        """[NEG-05] CodeScoring is source SAST only, absent from container profile."""
        sp = ScanProfileEngine.resolve("docker_image")
        assert ScanTool.CODESCORING not in sp.tools

    def test_neg_06_trivy_absent_from_source(self):
        """[NEG-06] Trivy container scan is absent from source profile."""
        sp = ScanProfileEngine.resolve("source")
        assert ScanTool.TRIVY not in sp.tools

    def test_neg_07_hadolint_absent_from_source(self):
        """[NEG-07] Hadolint dockerfile linter is absent from source profile."""
        sp = ScanProfileEngine.resolve("source")
        assert ScanTool.HADOLINT not in sp.tools

    def test_neg_08_clamav_absent_from_source(self):
        """[NEG-08] ClamAV container antivirus is absent from source profile."""
        sp = ScanProfileEngine.resolve("source")
        assert ScanTool.CLAMAV not in sp.tools

    def test_neg_09_kubelinter_absent_from_source(self):
        """[NEG-09] KubeLinter is manifest/container linting, absent from source profile."""
        sp = ScanProfileEngine.resolve("source")
        assert ScanTool.KUBELINTER not in sp.tools

    def test_neg_10_kcs_absent_from_source(self):
        """[NEG-10] KCS is container security, absent from source profile."""
        sp = ScanProfileEngine.resolve("source")
        assert ScanTool.KCS not in sp.tools

    def test_neg_11_container_step_chain_never_contains_codeql(self):
        """[NEG-11] step_chain for docker_image never includes codeql step."""
        for rt in ["ordinary", "accelerated", "regulatory", "hotfix", "custom"]:
            steps = ScanProfileEngine.step_chain(rt, "docker_image")
            step_tools = {s["tool"] for s in steps}
            assert "codeql" not in step_tools
            assert "sonarqube" not in step_tools

    def test_neg_12_cosmo_ordinary_step_chain_has_no_codeql(self):
        """[NEG-12] step_chain for ordinary Cosmo source has SonarQube, but no CodeQL."""
        steps = ScanProfileEngine.step_chain("ordinary", "source", flavor="cosmo")
        step_tools = {s["tool"] for s in steps}
        assert "sonarqube" in step_tools
        assert "codeql" not in step_tools


# ══════════════════════════════════════════════════════════════════
# 4. Step Chain & Gate Effects
# ══════════════════════════════════════════════════════════════════

class TestStepChain:
    def test_source_chain_regulatory_has_codeql(self):
        steps = ScanProfileEngine.step_chain("regulatory", "source")
        tools = {s["tool"] for s in steps}
        assert "sonarqube" in tools
        assert "codescoring" in tools
        assert "codeql" in tools

    def test_container_chain_has_required_tools(self):
        steps = ScanProfileEngine.step_chain("ordinary", "docker_image")
        tools = {s["tool"] for s in steps}
        assert "trivy" in tools
        assert "hadolint" in tools
        assert "clamav" in tools
        assert "kcs" in tools
        assert "kubelinter" in tools

    def test_required_steps_block_on_failure(self):
        steps = ScanProfileEngine.step_chain("ordinary", "source")
        required = [s for s in steps if s["is_required"]]
        for s in required:
            assert s["gate_required"] is True
            assert s["on_failure"] == "block"

    def test_hotfix_non_required_steps_skip(self):
        steps = ScanProfileEngine.step_chain("hotfix", "docker_image")
        non_required = [s for s in steps if not s["is_required"]]
        for s in non_required:
            assert s["on_failure"] == "skip"

    def test_hotfix_required_steps_still_block(self):
        steps = ScanProfileEngine.step_chain("hotfix", "docker_image")
        required = [s for s in steps if s["is_required"]]
        for s in required:
            assert s["on_failure"] == "block"


# ══════════════════════════════════════════════════════════════════
# 5. Hotfix Baseline & Provenance
# ══════════════════════════════════════════════════════════════════

class TestHotfixBaseline:
    def test_hotfix_scan_fail_on_critical(self):
        sp = ScanProfileEngine.resolve("source", release_type="hotfix")
        assert sp.fail_on_critical is True
        assert sp.max_critical == 0
        assert sp.prettyk_qg_required is True

    def test_hotfix_container_scan_secure(self):
        sp = ScanProfileEngine.resolve("docker_image", release_type="hotfix")
        assert sp.fail_on_critical is True
        assert sp.max_critical == 0
        assert sp.prettyk_qg_required is True

    def test_hotfix_override_cannot_bypass_guards(self):
        sp = ScanProfileEngine.resolve(
            "source",
            release_type="hotfix",
            overrides={"fail_on_critical": False, "max_critical": 999, "prettyk_qg_required": False},
        )
        assert sp.fail_on_critical is True
        assert sp.max_critical == 0
        assert sp.prettyk_qg_required is True


# ══════════════════════════════════════════════════════════════════
# 6. SLSA & CycloneDX Contracts
# ══════════════════════════════════════════════════════════════════

class TestProvenanceAndSBOM:
    def test_slsa_sole_provenance(self):
        assert ProvenanceCapability.SLSA.value == "slsa"
        sp = ScanProfileEngine.resolve("source")
        assert sp.provenance == ProvenanceCapability.SLSA

    def test_cyclonedx_sole_sbom(self):
        assert SBOMFormat.CYCLONEDX.value == "cyclonedx"
        sp = ScanProfileEngine.resolve("source")
        assert sp.sbom_format == SBOMFormat.CYCLONEDX

    def test_slsa_proof_structure(self):
        proof = ScanProfileEngine.slsa_proof("build-42", "sha256:aa", [{"name": "build"}])
        assert proof["_type"] == "https://in-toto.io/Statement/v1"
        assert proof["predicateType"] == "https://slsa.dev/provenance/v1"

    def test_cyclonedx_sbom_structure(self):
        sbom = ScanProfileEngine.cyclonedx_sbom("auth", "1.0", [{"name": "flask"}])
        assert sbom["bomFormat"] == "CycloneDX"
        assert sbom["specVersion"] == "1.5"
        assert sbom["components"][0]["name"] == "flask"
