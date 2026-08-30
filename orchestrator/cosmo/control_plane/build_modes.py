# -*- coding: utf-8 -*-
"""CBR-BOSS-002: CodeQL Artifact Matrix Correction & Canonical Profiles.

Build Modes:
  - Development Build: runtime sanitizers, coverage (build-type only, not compiler flags)
  - Release Build: immutable ЖЦ, optimized, stripped

Canonical Scan Profiles (CBR-BOSS-002):
  1. PureK ordinary source:
       SonarQube + CodeQL (CodeQLPolicy.PUREK)
  2. Cosmoport ordinary source:
       SonarQube + CodeScoring (CodeQL disabled / None before bridge)
  3. Cosmoport security/regulatory source:
       SonarQube + CodeScoring + CodeQL (CodeQLPolicy.SECURITY_COSMO)
  4. Container (docker_image):
       Hadolint + CycloneDX + Trivy + ClamAV + KCS + KubeLinter
       (CodeQL is strictly ABSENT from container profile)

SLSA is sole provenance, CycloneDX is sole SBOM contract.
PrettyK QG as external result.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

Strict = ConfigDict(extra="ignore")

# ══════════════════════════════════════════════════════════════════
# Build Modes — compiler flags removed, abstractions only
# ══════════════════════════════════════════════════════════════════

class BuildMode(str, Enum):
    DEVELOPMENT = "development"
    RELEASE = "release"


class DebugSymbols(str, Enum):
    FULL = "full"
    LINE_TABLES = "line_tables"
    NONE = "none"


class BuildProfile(BaseModel):
    """Per-app build configuration. No compiler flags — only build-type abstractions."""
    model_config = Strict
    mode: BuildMode = BuildMode.DEVELOPMENT
    optimization_level: int = Field(default=0, ge=0, le=3, description="0=none, 1=basic, 2=full, 3=aggressive (release only)")
    debug_info: DebugSymbols = DebugSymbols.FULL
    runtime_sanitizers: list[str] = Field(default_factory=list, description="['asan','ubsan','tsan'] — dev only")


class BuildModeEngine:
    """Resolve build mode config from release type."""

    @staticmethod
    def resolve(release_type: str, app_kind: str = "service") -> BuildProfile:
        if release_type in ("ordinary", "accelerated", "regulatory", "custom"):
            return BuildProfile(
                mode=BuildMode.RELEASE,
                optimization_level=3,
                debug_info=DebugSymbols.NONE,
            )
        if release_type == "hotfix":
            return BuildProfile(
                mode=BuildMode.RELEASE,
                optimization_level=2,
                debug_info=DebugSymbols.LINE_TABLES,
            )
        # Development / draft
        return BuildProfile(
            mode=BuildMode.DEVELOPMENT,
            optimization_level=0,
            debug_info=DebugSymbols.FULL,
            runtime_sanitizers=["asan", "ubsan"],
        )

    @staticmethod
    def is_dev_only_setting(field_name: str) -> bool:
        return field_name in {"runtime_sanitizers"}

    @staticmethod
    def validate_build(profile: BuildProfile) -> list[str]:
        violations = []
        if profile.mode == BuildMode.RELEASE:
            if profile.optimization_level > 3:
                violations.append("optimization_level > 3 invalid")
            if profile.runtime_sanitizers:
                violations.append(f"runtime_sanitizers {profile.runtime_sanitizers} forbidden in RELEASE mode")
        return violations


# ══════════════════════════════════════════════════════════════════
# Scan Profiles — Canonical CBR-BOSS-002 Matrix
# ══════════════════════════════════════════════════════════════════

class ScanTool(str, Enum):
    SONARQUBE = "sonarqube"
    CODESCORING = "codescoring"
    CODEQL = "codeql"
    TRIVY = "trivy"
    KCS = "kcs"
    HADOLINT = "hadolint"
    CLAMAV = "clamav"
    KUBELINTER = "kubelinter"
    SLSA = "slsa"
    CYCLONEDX = "cyclonedx"


class ProvenanceCapability(str, Enum):
    SLSA = "slsa"


class SBOMFormat(str, Enum):
    CYCLONEDX = "cyclonedx"


class CodeQLPolicy(str, Enum):
    """CBR-BOSS-002: CodeQL policy tiers for source code."""
    PUREK = "purek"
    SECURITY_COSMO = "security_cosmo"
    FULL = "full"


class ScanProfile(BaseModel):
    model_config = Strict
    artifact_type: str = "source"
    tools: list[ScanTool] = Field(default_factory=list)
    provenance: ProvenanceCapability = ProvenanceCapability.SLSA
    sbom_format: SBOMFormat = SBOMFormat.CYCLONEDX
    codeql_policy: Optional[CodeQLPolicy] = None
    prettyk_qg_required: bool = True
    fail_on_critical: bool = True
    fail_on_high: bool = False
    max_critical: int = 0
    max_high: int = 5
    immutable_in_release: bool = True


# ── Canonical Tool Sets (CBR-BOSS-002) ──

CONTAINER_TOOLS = [
    ScanTool.HADOLINT,
    ScanTool.CYCLONEDX,
    ScanTool.TRIVY,
    ScanTool.CLAMAV,
    ScanTool.KCS,
    ScanTool.KUBELINTER,
]


class ScanProfileEngine:
    """CBR-BOSS-002: Canonical scan profile engine.

    Truth Matrix:
      - PureK ordinary source: SonarQube + CodeQL (PUREK)
      - Cosmo ordinary source: SonarQube + CodeScoring (CodeQL not active)
      - Cosmo security/regulatory source: SonarQube + CodeScoring + CodeQL (SECURITY_COSMO)
      - Container: Hadolint + CycloneDX + Trivy + ClamAV + KCS + KubeLinter (CodeQL absent)
    """

    @classmethod
    def resolve(
        cls,
        artifact_type: str,
        release_type: str = "ordinary",
        flavor: str = "cosmo",
        overrides: dict[str, Any] | None = None,
    ) -> ScanProfile:
        is_container = artifact_type in ("docker_image", "container")

        if is_container:
            # Container: Hadolint, CycloneDX, Trivy, ClamAV, KCS, KubeLinter.
            # CodeQL is strictly absent from container scan profiles.
            tools = list(CONTAINER_TOOLS)
            codeql_policy = None
        else:
            # Source profile
            if flavor == "purek":
                tools = [ScanTool.SONARQUBE, ScanTool.CODEQL]
                codeql_policy = CodeQLPolicy.PUREK
            elif release_type == "regulatory" or flavor in ("security", "regulatory", "cosmo_sec"):
                tools = [ScanTool.SONARQUBE, ScanTool.CODESCORING, ScanTool.CODEQL]
                codeql_policy = CodeQLPolicy.SECURITY_COSMO
            else:
                # Cosmo ordinary / accelerated / hotfix / custom: SonarQube + CodeScoring, CodeQL inactive
                tools = [ScanTool.SONARQUBE, ScanTool.CODESCORING]
                codeql_policy = None

        base = ScanProfile(
            artifact_type=artifact_type,
            tools=tools,
            codeql_policy=codeql_policy,
        )

        if not overrides:
            return cls._apply_hotfix_guard(base, release_type, is_container)

        data = base.model_dump()
        for key in ("tools", "codeql_policy", "prettyk_qg_required",
                     "fail_on_critical", "fail_on_high", "max_critical", "max_high"):
            if key in overrides:
                data[key] = overrides[key]

        # Guard: container never gets CodeQL even via overrides
        if is_container:
            data["codeql_policy"] = None
            data["tools"] = [
                t for t in data.get("tools", [])
                if (t.value if isinstance(t, ScanTool) else str(t)) not in ("codeql", ScanTool.CODEQL.value)
            ]

        return cls._apply_hotfix_guard(ScanProfile(**data), release_type, is_container)

    @classmethod
    def _apply_hotfix_guard(cls, profile: ScanProfile, release_type: str, is_container: bool) -> ScanProfile:
        if release_type == "hotfix":
            profile.fail_on_critical = True
            profile.max_critical = 0
            profile.prettyk_qg_required = True
        if is_container:
            profile.codeql_policy = None
        return profile

    # ── CBR-BOSS-002: ReleaseType → Steps → Artifact Kind → Gate Effect ──

    @classmethod
    def step_chain(
        cls,
        release_type: str,
        artifact_type: str,
        flavor: str = "cosmo",
    ) -> list[dict[str, Any]]:
        """Build the chain: ReleaseType → Steps → Artifact Kind → Scan Tools → Gate Effect.

        Returns: [{step_id, tool, gate_required, on_failure_action, is_required}]
        """
        profile = cls.resolve(artifact_type, release_type=release_type, flavor=flavor)
        steps = []
        required_tools = {ScanTool.SONARQUBE, ScanTool.TRIVY, ScanTool.CYCLONEDX}

        for i, tool in enumerate(profile.tools):
            is_required = tool in required_tools
            step = {
                "step_id": tool.value,
                "step_order": i,
                "tool": tool.value,
                "artifact_type": artifact_type,
                "gate_required": is_required,
                "is_required": is_required,
                "on_failure": "block" if is_required else "warn",
            }
            steps.append(step)

        # Hotfix: can skip non-required, but never required
        if release_type == "hotfix":
            for s in steps:
                if not s["is_required"]:
                    s["on_failure"] = "skip"

        return steps

    @classmethod
    def slsa_proof(cls, build_id: str, digest_sha256: str, steps: list[dict]) -> dict[str, Any]:
        return {
            "_type": "https://in-toto.io/Statement/v1",
            "subject": [{"name": build_id, "digest": {"sha256": digest_sha256}}],
            "predicateType": "https://slsa.dev/provenance/v1",
            "predicate": {
                "builder": {"id": "https://cosmoport.io/build-service"},
                "buildType": "https://cosmoport.io/stack-build/v1",
                "invocation": {"configSource": {"uri": "git+https://gitea.local/cosmoport"},
                               "parameters": {"steps": steps}},
                "materials": [{"uri": f"pkg:oci/{build_id}?tag=latest",
                               "digest": {"sha256": digest_sha256}}],
            },
        }

    @classmethod
    def cyclonedx_sbom(cls, app_id: str, version: str, dependencies: list[dict]) -> dict[str, Any]:
        return {
            "bomFormat": "CycloneDX",
            "specVersion": "1.5",
            "serialNumber": f"urn:uuid:{hashlib.sha256(f'{app_id}|{version}'.encode()).hexdigest()[:32]}",
            "version": 1,
            "metadata": {
                "component": {"type": "application", "name": app_id, "version": version},
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
            "components": [
                {"type": "library", "name": dep.get("name", "unknown"),
                 "version": dep.get("version", "0.0.0"), "purl": dep.get("purl", "")}
                for dep in dependencies
            ],
        }
