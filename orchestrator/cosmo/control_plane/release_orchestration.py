# -*- coding: utf-8 -*-
"""NX-BOSS-01..04: Control Plane / Release Orchestration.

NX-BOSS-01: Artifact truth table — source (7 steps) / docker (4 steps), no cross-tool leakage.
NX-BOSS-02: Project graph semantics — L2→L1→L0 edges, unambiguous direction.
NX-BOSS-03: Release Type engine — resolver: kind + level + artifact + type + overrides.
NX-BOSS-04: ReleaseBatch hardening — queue, partial_success, retry child, blocking node.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

Strict = ConfigDict(extra="ignore")

# ══════════════════════════════════════════════════════════════════
# NX-BOSS-02: Project Graph — unambiguous edge direction
# ══════════════════════════════════════════════════════════════════
# SEMANTIC RULE: L2 includes L1, L1 includes L0.
# Edge direction: from (consumer) → to (dependency).
# Valid:   L2 → L1, L2 → L0, L1 → L0   (higher-level depends on lower-level)
# Invalid: L0 → L1, L0 → L2, L1 → L2   (lower-level cannot depend on higher-level)
# Same-level: allowed (peer dependency).

AppLevel = Literal["L0", "L1", "L2"]
_LEVEL_ORDER = {"L0": 0, "L1": 1, "L2": 2}


class AppRef(BaseModel):
    model_config = Strict
    app_id: str
    app_code: str = ""
    app_kind: str = "service"  # NX-BOSS-03: service, library, frontend, infrastructure
    level: AppLevel = "L1"
    team_scope: str = ""
    metadata: dict[str, str] = Field(default_factory=dict)


class Project(BaseModel):
    model_config = Strict
    id: str = Field(..., min_length=1)
    label: str = Field(..., min_length=1)
    description: str = ""
    apps: list[AppRef] = Field(default_factory=list)
    team_scopes: list[str] = Field(default_factory=list)
    admin_kits_tag: Optional[str] = None
    meta: dict[str, str] = Field(default_factory=dict)
    created_at: Optional[datetime] = None

    def app_ids(self) -> set[str]: return {a.app_id for a in self.apps}
    def apps_by_level(self, level: AppLevel) -> list[AppRef]: return [a for a in self.apps if a.level == level]


class AppGraphEdge(BaseModel):
    """NX-BOSS-02: Directed edge — from (consumer) → to (dependency).
    Valid: L2→L1, L2→L0, L1→L0 (higher consuming lower).
    Invalid: L0→L1, L0→L2, L1→L2 (lower consuming higher — forbidden)."""
    model_config = Strict
    from_app: str   # consumer
    to_app: str     # dependency
    relation: str = "depends_on"


class ProjectGraph(BaseModel):
    model_config = Strict
    project: Project
    edges: list[AppGraphEdge] = Field(default_factory=list)

    def validate_no_cycles(self) -> bool:
        adj: dict[str, list[str]] = {a.app_id: [] for a in self.project.apps}
        for e in self.edges:
            adj.setdefault(e.from_app, []).append(e.to_app)
        WHITE, GRAY, BLACK = 0, 1, 2
        color: dict[str, int] = {}
        def dfs(n: str) -> bool:
            color[n] = GRAY
            for nb in adj.get(n, []):
                if nb not in color:
                    if dfs(nb): return True
                elif color.get(nb) == GRAY: return True
            color[n] = BLACK; return False
        for n in adj:
            if n not in color and dfs(n): return False
        return True

    def validate_levels(self) -> list[str]:
        """NX-BOSS-02: from_level < to_level = VIOLATION (lower consuming higher)."""
        violations = []
        app_levels = {a.app_id: a.level for a in self.project.apps}
        for e in self.edges:
            fl, tl = app_levels.get(e.from_app), app_levels.get(e.to_app)
            if fl and tl and _LEVEL_ORDER[fl] < _LEVEL_ORDER[tl]:
                violations.append(
                    f"NX-BOSS-02 VIOLATION: {e.from_app}({fl}) cannot depend on {e.to_app}({tl}). "
                    f"Rule: L2→L1→L0, not {fl}→{tl}.")
        return violations


# ══════════════════════════════════════════════════════════════════
# BR-002: Visibility Policy
# ══════════════════════════════════════════════════════════════════

class VisibilityLevel(str, Enum):
    FULL = "full"
    READONLY_PREVIEW = "readonly_preview"
    NONE = "none"


class VisibilityPolicy(BaseModel):
    model_config = Strict
    principal_teams: list[str] = Field(default_factory=list)
    principal_roles: list[str] = Field(default_factory=list)
    admin_kits_tags: list[str] = Field(default_factory=list)
    is_global_admin: bool = False

    def compute(self, proj: Project, app: AppRef) -> VisibilityLevel:
        if app.team_scope and app.team_scope in self.principal_teams: return VisibilityLevel.FULL
        if any(t in self.principal_teams for t in proj.team_scopes): return VisibilityLevel.FULL
        if self.is_global_admin or any(r in {"admin_sec","security_officer","admin_service"} for r in self.principal_roles):
            return VisibilityLevel.FULL
        if proj.admin_kits_tag and proj.admin_kits_tag in self.admin_kits_tags:
            if app.team_scope in self.principal_teams or app.team_scope == proj.admin_kits_tag:
                return VisibilityLevel.FULL
            return VisibilityLevel.READONLY_PREVIEW
        return VisibilityLevel.NONE


# ══════════════════════════════════════════════════════════════════
# NX-BOSS-01: Artifact Truth Table
# ══════════════════════════════════════════════════════════════════
# SOURCE (7 steps): Build → UnitTests → Docs → SonarQube → CodeScoring → SBOM → Deploy
# DOCKER (4 steps): BuildImage → SBOM → Trivy → Deploy
# RULES:
#   Source: NO Trivy, NO KCS (those are container scanners)
#   Docker: NO SonarQube, NO CodeScoring (those are source SAST)
#   KCS is optional overlay — never in default profiles without explicit decision

SOURCE_AUDIT = [
    {"step_id":"build",       "name":"Build",              "order":0, "req":True,  "gate":False, "evidence":False},
    {"step_id":"unit_tests",  "name":"Unit Tests",         "order":1, "req":True,  "gate":False, "evidence":False},
    {"step_id":"docs_gen",    "name":"Documentation",      "order":2, "req":False, "gate":False, "evidence":False, "on_fail":"continue"},
    {"step_id":"sonarqube",   "name":"SonarQube SAST",     "order":3, "req":True,  "gate":True,  "evidence":False},
    {"step_id":"codescoring", "name":"CodeScoring SAST",   "order":4, "req":True,  "gate":True,  "evidence":False},
    {"step_id":"sbom",        "name":"SBOM Generation",    "order":5, "req":True,  "gate":False, "evidence":True},
    {"step_id":"deploy",      "name":"Deploy",             "order":6, "req":True,  "gate":True,  "evidence":False},
]

DOCKER_AUDIT = [
    {"step_id":"build_image", "name":"Build Image",        "order":0, "req":True,  "gate":False, "evidence":False},
    {"step_id":"sbom",        "name":"SBOM Generation",    "order":1, "req":True,  "gate":False, "evidence":True},
    {"step_id":"trivy",       "name":"Trivy Container Scan","order":2,"req":True,  "gate":True,  "evidence":False},
    {"step_id":"deploy",      "name":"Deploy",             "order":3, "req":True,  "gate":True,  "evidence":False},
]

ARTIFACT_TRUTH_TABLE: dict[str, list[dict[str,Any]]] = {"source": SOURCE_AUDIT, "docker_image": DOCKER_AUDIT}


class LifecycleStepRef(BaseModel):
    model_config = Strict
    step_id: str
    step_name: str
    step_order: int
    required: bool = True
    enabled: bool = True
    on_failure: Literal["continue","terminate"] = "terminate"
    gates_required: bool = False
    evidence_required: bool = False

ARTIFACT_PROFILES: dict[str, list[LifecycleStepRef]] = {
    k: [LifecycleStepRef(step_id=s["step_id"], step_name=s["name"], step_order=s["order"],
          required=s["req"], gates_required=s["gate"], evidence_required=s["evidence"],
          on_failure=s.get("on_fail","terminate"))
        for s in v]
    for k, v in ARTIFACT_TRUTH_TABLE.items()
}


class ArtifactType(str, Enum):
    SOURCE = "source"
    DOCKER_IMAGE = "docker_image"


def resolve_artifact_profile(artifact: str, overrides: list[LifecycleStepRef]|None=None) -> list[LifecycleStepRef]:
    base = ARTIFACT_PROFILES.get(artifact, ARTIFACT_PROFILES["source"])
    if not overrides: return list(base)
    omap = {s.step_id: s for s in overrides}
    return [s.model_copy(update=omap[s.step_id].model_dump(exclude_unset=True)) if s.step_id in omap else s for s in base]


# ══════════════════════════════════════════════════════════════════
# NX-BOSS-03: Release Type Engine
# ══════════════════════════════════════════════════════════════════

class ReleaseTypeName(str, Enum):
    ORDINARY = "ordinary"
    ACCELERATED = "accelerated"
    REGULATORY = "regulatory"
    HOTFIX = "hotfix"
    CUSTOM = "custom"

_RELEASE_TYPE_BASELINE: dict[str, dict[str, Any]] = {
    "ordinary":    {"requires_prettyk_qg": True,  "requires_gates": True,  "requires_act": True,  "allow_skip_optional": True,  "max_concurrent_apps": 3},
    "accelerated": {"requires_prettyk_qg": True,  "requires_gates": True,  "requires_act": True,  "allow_skip_optional": True,  "max_concurrent_apps": 5},
    "regulatory":  {"requires_prettyk_qg": True,  "requires_gates": True,  "requires_act": True,  "allow_skip_optional": False, "max_concurrent_apps": 1},
    # INT-011: Hotfix maintains mandatory security baseline — only non-required technical steps are skippable.
    #          Never bypasses: PrettyK QG, mandatory Gates, Evidence, Act, package readiness.
    "hotfix":      {"requires_prettyk_qg": True,  "requires_gates": True,  "requires_act": True,  "allow_skip_optional": True,  "max_concurrent_apps": 5},
    "custom":      {"requires_prettyk_qg": True,  "requires_gates": True,  "requires_act": True,  "allow_skip_optional": True,  "max_concurrent_apps": 3},
}

class ReleaseTypeProfile(BaseModel):
    model_config = Strict
    id: str = Field(..., min_length=1)
    name: ReleaseTypeName = ReleaseTypeName.ORDINARY
    version: int = 1
    description: str = ""
    app_kind: str = "service"
    app_level: AppLevel = "L1"
    artifact_type: str = "source"
    steps: list[LifecycleStepRef] = Field(default_factory=list)
    requires_prettyk_qg: bool = True
    requires_gates: bool = True
    requires_act: bool = True
    packaging_rules: dict[str, Any] = Field(default_factory=dict)
    route_metadata: dict[str, str] = Field(default_factory=dict)
    created_at: Optional[datetime] = None

    def snapshot(self) -> dict[str, Any]:
        return {
            "release_type_id": self.id,
            "release_type_version": self.version,
            "resolved_lifecycle_snapshot": [s.model_dump() for s in self.steps],
            "requires_prettyk_qg": self.requires_prettyk_qg,
            "requires_gates": self.requires_gates,
            "requires_act": self.requires_act,
            "artifact_type": self.artifact_type,
        }


class ReleaseTypeResolver:
    """NX-BOSS-03: Resolver — kind + level + artifact + type + overrides.

    Guards:
      - Custom type cannot bypass mandatory QG/security baseline.
      - required=True steps cannot be disabled.
    """

    def resolve(self, *, app_kind: str, app_level: AppLevel, artifact_type: str,
                release_type: ReleaseTypeName, overrides: dict[str, Any] | None = None,
                profile_id: str = "") -> ReleaseTypeProfile:
        baseline = _RELEASE_TYPE_BASELINE.get(release_type.value if hasattr(release_type, 'value') else release_type,
                                               _RELEASE_TYPE_BASELINE["ordinary"])
        steps = resolve_artifact_profile(artifact_type)
        ov = overrides or {}

        # INT-011: NO release type (including hotfix) can bypass mandatory QG/security baseline.
        # Only non-required technical steps may be disabled.
        requires_prettyk_qg = baseline["requires_prettyk_qg"]
        requires_gates = baseline["requires_gates"]
        requires_act = baseline["requires_act"]

        # INT-011: Overrides cannot disable mandatory security checks — ever.
        if ov.get("requires_prettyk_qg") is False:
            requires_prettyk_qg = True  # guard: cannot bypass QG
        if ov.get("requires_gates") is False:
            requires_gates = True       # guard: cannot bypass gates
        if ov.get("requires_act") is False:
            requires_act = True         # guard: cannot bypass act

        # Apply step overrides
        step_overrides_raw = ov.get("step_overrides", [])
        step_override_map = {s["step_id"]: LifecycleStepRef(**s) for s in step_overrides_raw if isinstance(s, dict)}
        resolved_steps = resolve_artifact_profile(artifact_type,
            [s for s in step_override_map.values()])

        # Guard: required steps stay enabled
        for s in resolved_steps:
            if s.required and not s.enabled:
                s.enabled = True

        return ReleaseTypeProfile(
            id=profile_id or f"rtp-{release_type.value}-{app_kind}-{artifact_type}",
            name=release_type,
            version=1,
            app_kind=app_kind,
            app_level=app_level,
            artifact_type=artifact_type,
            steps=resolved_steps,
            requires_prettyk_qg=requires_prettyk_qg,
            requires_gates=requires_gates,
            requires_act=requires_act,
            packaging_rules=ov.get("packaging_rules") or baseline.get("packaging_rules", {}),
            route_metadata=ov.get("route_metadata") or baseline.get("route_metadata", {}),
        )

    def snapshot_profile(self, profile: ReleaseTypeProfile) -> str:
        """NX-BOSS-03: Immutable hash of the profile snapshot."""
        data = json.dumps(profile.snapshot(), sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(data.encode()).hexdigest()[:16]


# ══════════════════════════════════════════════════════════════════
# NX-BOSS-04 / BR-005: Individual Release
# ══════════════════════════════════════════════════════════════════

ReleaseStatus = Literal[
    "draft","queued","running","awaiting_prettyk","gates_evaluating",
    "partially_succeeded","succeeded","failed","blocked",
]

class IndividualRelease(BaseModel):
    model_config = Strict
    id: str = Field(..., min_length=1)
    app_id: str
    app_code: str = ""
    project_id: str = ""
    release_type_id: str = ""
    release_type_version: int = 1
    lifecycle_snapshot: list[LifecycleStepRef] = Field(default_factory=list)
    status: ReleaseStatus = "draft"
    build_id: Optional[str] = None
    run_id: Optional[str] = None
    commit_sha: Optional[str] = None
    gate_decisions: dict[str, str] = Field(default_factory=dict)
    prettyk_qg_result: Optional[bool] = None
    findings: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    gost_act_attached: bool = False
    package_ready: bool = False
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    def check_readiness(self) -> tuple[bool, list[str]]:
        blockers = []
        for s in self.lifecycle_snapshot:
            if s.required and s.gates_required:
                d = self.gate_decisions.get(f"gate-{s.step_id}")
                if d != "pass":
                    blockers.append(f"Gate gate-{s.step_id}: {d or 'pending'}")
        if self.prettyk_qg_result is False: blockers.append("PrettyK QG: FAIL")
        elif self.prettyk_qg_result is None: blockers.append("PrettyK QG: pending")
        if not self.gost_act_attached: blockers.append("GOST Act not attached")
        return len(blockers) == 0, blockers


# ══════════════════════════════════════════════════════════════════
# NX-BOSS-04: ReleaseBatch Hardening
# ══════════════════════════════════════════════════════════════════

BatchStatus = Literal["draft","queued","running","partially_succeeded","succeeded","failed","blocked"]


class ProjectReleaseBatch(BaseModel):
    """NX-BOSS-04: Non-atomic batch.

    - Queue by graph: get_ready_queue() respects dependency edges.
    - Partial success: App A fails ≠ App B results lost.
    - Retry child release: retry_queue + retry_child_release().
    - Blocking node: blocked_apps list prevents dispatch.
    - Independent Application Releases: each release tracks own status.
    """
    model_config = Strict
    id: str = Field(..., min_length=1)
    project_id: str
    release_ids: list[str] = Field(default_factory=list)
    status: BatchStatus = "draft"
    app_release_types: dict[str, str] = Field(default_factory=dict)
    dependency_graph: list[AppGraphEdge] = Field(default_factory=list)
    completed_releases: dict[str, str] = Field(default_factory=dict)
    blocked_apps: list[str] = Field(default_factory=list)
    retry_queue: list[str] = Field(default_factory=list)
    created_at: Optional[datetime] = None

    def register_result(self, release_id: str, status: str) -> None:
        self.completed_releases[release_id] = status
        # Auto-remove from retry_queue on success
        if status == "succeeded" and release_id in self.retry_queue:
            self.retry_queue.remove(release_id)

    def partial_success_count(self) -> int:
        return sum(1 for s in self.completed_releases.values() if s == "succeeded")

    def compute_batch_status(self) -> BatchStatus:
        if not self.completed_releases: return self.status
        vals = set(self.completed_releases.values())
        if vals == {"succeeded"}: return "succeeded"
        if "succeeded" in vals and len(vals) > 1: return "partially_succeeded"
        if "failed" in vals: return "failed"
        return self.status

    def get_ready_queue(self, completed: set[str]) -> list[str]:
        """Topological ready-queue: nodes with all deps satisfied."""
        adj: dict[str, list[str]] = {}
        for e in self.dependency_graph:
            adj.setdefault(e.from_app, []).append(e.to_app)
        ready = []
        for rid in self.release_ids:
            if rid in completed or rid in self.blocked_apps: continue
            deps = adj.get(rid, [])
            if all(d in completed for d in deps):
                ready.append(rid)
        return ready

    def retry_child_release(self, release_id: str) -> None:
        """NX-BOSS-04: Retry a specific child release (keeps sibling results)."""
        if release_id not in self.completed_releases: return
        if release_id in self.retry_queue: return  # already queued
        # Clear its result but keep siblings
        del self.completed_releases[release_id]
        self.retry_queue.append(release_id)
        # Recompute status
        self.status = self.compute_batch_status()

    def block_app(self, app_id: str) -> None:
        """NX-BOSS-04: Block an app from dispatch."""
        if app_id not in self.blocked_apps:
            self.blocked_apps.append(app_id)

    def unblock_app(self, app_id: str) -> None:
        if app_id in self.blocked_apps:
            self.blocked_apps.remove(app_id)

    def remaining_releases(self) -> int:
        done = set(self.completed_releases.keys()) | set(self.blocked_apps)
        return len([r for r in self.release_ids if r not in done])

    def is_ready_for_transfer(self, releases: dict[str, IndividualRelease]) -> bool:
        """NX-BOSS-04: ready_for_transfer only after Gates + PrettyK PASS + Act."""
        for rel in releases.values():
            ready, _ = rel.check_readiness()
            if not ready: return False
        return self.compute_batch_status() in ("succeeded", "partially_succeeded")


# ══════════════════════════════════════════════════════════════════
# BR-007: Release Package
# ══════════════════════════════════════════════════════════════════

class ReleasePackage(BaseModel):
    model_config = Strict
    package_id: str = Field(..., min_length=1)
    project_id: str
    batch_id: str
    app_release_ids: dict[str, str] = Field(default_factory=dict)
    release_type_versions: dict[str, int] = Field(default_factory=dict)
    commit_shas: dict[str, str] = Field(default_factory=dict)
    artifact_digests: dict[str, str] = Field(default_factory=dict)
    lifecycle_results: dict[str, list[str]] = Field(default_factory=dict)
    findings_summary: dict[str, int] = Field(default_factory=dict)
    evidence_archive_ref: str = ""
    prettyk_verdict: bool = False
    gost_act_archive_ref: str = ""
    checksums: dict[str, str] = Field(default_factory=dict)
    route_id: str = ""
    schema_version: str = "1.0"
    status: Literal["assembling","ready_for_transfer","transferred"] = "assembling"
    created_at: Optional[datetime] = None

    def mark_ready(self) -> None:
        self.status = "ready_for_transfer"
        self.created_at = datetime.now(timezone.utc)

    def is_transfer_ready(self) -> bool:
        return (self.status == "ready_for_transfer" and bool(self.app_release_ids)
                and self.prettyk_verdict and bool(self.gost_act_archive_ref))


# ══════════════════════════════════════════════════════════════════
# Orchestrator
# ══════════════════════════════════════════════════════════════════

class ReleaseOrchestrator:
    def __init__(self):
        self._releases: dict[str, IndividualRelease] = {}
        self._batches: dict[str, ProjectReleaseBatch] = {}
        self._resolver = ReleaseTypeResolver()

    def create_release(self, app_id: str, project_id: str, profile: ReleaseTypeProfile, **kw) -> IndividualRelease:
        import uuid
        rid = f"rel-{uuid.uuid4().hex[:12]}"
        rel = IndividualRelease(id=rid, app_id=app_id, app_code=kw.get("app_code",""),
                                project_id=project_id, release_type_id=profile.id,
                                release_type_version=profile.version,
                                lifecycle_snapshot=profile.steps, commit_sha=kw.get("commit_sha"))
        self._releases[rid] = rel
        return rel

    def create_batch(self, project: Project, app_release_types: dict[str,str],
                     dep_edges: list[AppGraphEdge]|None=None) -> ProjectReleaseBatch:
        import uuid
        bid = f"batch-{uuid.uuid4().hex[:12]}"
        batch = ProjectReleaseBatch(id=bid, project_id=project.id,
                                    release_ids=list(app_release_types.keys()),
                                    app_release_types=app_release_types,
                                    dependency_graph=dep_edges or [])
        self._batches[bid] = batch
        return batch

    def assemble_package(self, batch: ProjectReleaseBatch,
                         releases: dict[str, IndividualRelease]) -> ReleasePackage:
        import uuid
        pid = f"pkg-{uuid.uuid4().hex[:12]}"
        findings: dict[str,int] = {}
        for rel in releases.values():
            for sev in rel.findings: findings[sev] = findings.get(sev,0)+1
        all_ready = all(r.check_readiness()[0] for r in releases.values())
        return ReleasePackage(
            package_id=pid, project_id=batch.project_id, batch_id=batch.id,
            app_release_ids={rel.app_id:rel.id for rel in releases.values()},
            release_type_versions={rel.id:rel.release_type_version for rel in releases.values()},
            commit_shas={rel.app_id:rel.commit_sha or "" for rel in releases.values()},
            findings_summary=findings, prettyk_verdict=all_ready,
            gost_act_archive_ref="" if not all(r.gost_act_attached for r in releases.values()) else "gost-archive-ref",
            route_id=batch.project_id)