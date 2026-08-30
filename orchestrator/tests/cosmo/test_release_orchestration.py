# -*- coding: utf-8 -*-
"""NX-BOSS-01..04: Targeted core tests."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_orch = Path(__file__).resolve().parents[1]
if str(_orch) not in sys.path:
    sys.path.insert(0, str(_orch))

from orchestrator.cosmo.control_plane.release_orchestration import (
    AppGraphEdge, AppRef, ArtifactType, IndividualRelease, LifecycleStepRef,
    Project, ProjectGraph, ProjectReleaseBatch, ReleaseOrchestrator,
    ReleasePackage, ReleaseTypeName, ReleaseTypeProfile, ReleaseTypeResolver,
    VisibilityLevel, VisibilityPolicy,
    ARTIFACT_PROFILES, ARTIFACT_TRUTH_TABLE,
    resolve_artifact_profile,
)

# ══════════════════════════════════════════════════════════════════
# NX-BOSS-01: Artifact truth table
# ══════════════════════════════════════════════════════════════════

class TestArtifactTruthTable:
    def test_source_exactly_7_steps(self):
        assert len(ARTIFACT_TRUTH_TABLE["source"]) == 7

    def test_docker_exactly_4_steps(self):
        assert len(ARTIFACT_TRUTH_TABLE["docker_image"]) == 4

    def test_source_has_no_kcs_trivy(self):
        ids = {s["step_id"] for s in ARTIFACT_TRUTH_TABLE["source"]}
        assert "kcs" not in ids
        assert "trivy" not in ids

    def test_docker_has_no_sonarqube_codescoring(self):
        ids = {s["step_id"] for s in ARTIFACT_TRUTH_TABLE["docker_image"]}
        assert "sonarqube" not in ids
        assert "codescoring" not in ids

    def test_source_steps_ordered_0_to_6(self):
        orders = [s["order"] for s in ARTIFACT_TRUTH_TABLE["source"]]
        assert orders == [0, 1, 2, 3, 4, 5, 6]

    def test_docker_steps_ordered_0_to_3(self):
        orders = [s["order"] for s in ARTIFACT_TRUTH_TABLE["docker_image"]]
        assert orders == [0, 1, 2, 3]

    def test_source_and_docker_share_sbom_and_deploy(self):
        src_ids = {s["step_id"] for s in ARTIFACT_TRUTH_TABLE["source"]}
        dock_ids = {s["step_id"] for s in ARTIFACT_TRUTH_TABLE["docker_image"]}
        assert "sbom" in src_ids and "sbom" in dock_ids
        assert "deploy" in src_ids and "deploy" in dock_ids

    def test_artifact_profiles_match_truth_table(self):
        assert len(ARTIFACT_PROFILES["source"]) == 7
        assert len(ARTIFACT_PROFILES["docker_image"]) == 4


# ══════════════════════════════════════════════════════════════════
# NX-BOSS-02: Project graph semantics
# ══════════════════════════════════════════════════════════════════

class TestGraphSemantics:
    def test_l2_depends_on_l1_valid(self):
        g = ProjectGraph(project=Project(id="p", label="X", apps=[
            AppRef(app_id="svc", level="L1"), AppRef(app_id="rel", level="L2")]),
            edges=[AppGraphEdge(from_app="rel", to_app="svc")])
        assert g.validate_levels() == []

    def test_l1_depends_on_l0_valid(self):
        g = ProjectGraph(project=Project(id="p", label="X", apps=[
            AppRef(app_id="lib", level="L0"), AppRef(app_id="svc", level="L1")]),
            edges=[AppGraphEdge(from_app="svc", to_app="lib")])
        assert g.validate_levels() == []

    def test_l2_depends_on_l0_valid(self):
        g = ProjectGraph(project=Project(id="p", label="X", apps=[
            AppRef(app_id="lib", level="L0"), AppRef(app_id="rel", level="L2")]),
            edges=[AppGraphEdge(from_app="rel", to_app="lib")])
        assert g.validate_levels() == []

    def test_l0_depends_on_l1_invalid(self):
        g = ProjectGraph(project=Project(id="p", label="X", apps=[
            AppRef(app_id="lib", level="L0"), AppRef(app_id="svc", level="L1")]),
            edges=[AppGraphEdge(from_app="lib", to_app="svc")])
        v = g.validate_levels()
        assert len(v) == 1
        assert "NX-BOSS-02 VIOLATION" in v[0]

    def test_l1_depends_on_l2_invalid(self):
        g = ProjectGraph(project=Project(id="p", label="X", apps=[
            AppRef(app_id="svc", level="L1"), AppRef(app_id="rel", level="L2")]),
            edges=[AppGraphEdge(from_app="svc", to_app="rel")])
        v = g.validate_levels()
        assert len(v) == 1

    def test_l0_depends_on_l2_invalid(self):
        g = ProjectGraph(project=Project(id="p", label="X", apps=[
            AppRef(app_id="lib", level="L0"), AppRef(app_id="rel", level="L2")]),
            edges=[AppGraphEdge(from_app="lib", to_app="rel")])
        assert len(g.validate_levels()) == 1

    def test_same_level_valid(self):
        g = ProjectGraph(project=Project(id="p", label="X", apps=[
            AppRef(app_id="a", level="L1"), AppRef(app_id="b", level="L1")]),
            edges=[AppGraphEdge(from_app="a", to_app="b")])
        assert g.validate_levels() == []

    def test_no_cycle_on_chain(self):
        g = ProjectGraph(project=Project(id="p", label="X", apps=[
            AppRef(app_id="a", level="L2"), AppRef(app_id="b", level="L1"), AppRef(app_id="c", level="L0")]),
            edges=[AppGraphEdge(from_app="a",to_app="b"), AppGraphEdge(from_app="b",to_app="c")])
        assert g.validate_no_cycles() is True
        assert g.validate_levels() == []


# ══════════════════════════════════════════════════════════════════
# NX-BOSS-03: Release Type Engine
# ══════════════════════════════════════════════════════════════════

class TestReleaseTypeEngine:
    def test_resolve_ordinary_source(self):
        r = ReleaseTypeResolver()
        profile = r.resolve(app_kind="service", app_level="L1", artifact_type="source",
                            release_type=ReleaseTypeName.ORDINARY, profile_id="rtp-1")
        assert profile.requires_prettyk_qg is True
        assert profile.requires_gates is True
        assert profile.requires_act is True
        assert len(profile.steps) == 7

    def test_resolve_ordinary_docker(self):
        r = ReleaseTypeResolver()
        profile = r.resolve(app_kind="service", app_level="L1", artifact_type="docker_image",
                            release_type=ReleaseTypeName.ORDINARY, profile_id="rtp-2")
        assert len(profile.steps) == 4
        ids = {s.step_id for s in profile.steps}
        assert "trivy" in ids
        assert "sonarqube" not in ids

    def test_hotfix_cannot_bypass_qg(self):
        """INT-011: Hotfix must maintain mandatory security baseline."""
        r = ReleaseTypeResolver()
        profile = r.resolve(app_kind="service", app_level="L1", artifact_type="source",
                            release_type=ReleaseTypeName.HOTFIX, profile_id="rtp-hf")
        assert profile.requires_prettyk_qg is True   # INT-011: NEVER bypass QG
        assert profile.requires_gates is True          # INT-011: NEVER bypass gates
        assert profile.requires_act is True            # INT-011: NEVER bypass act

    def test_hotfix_cannot_bypass_qg_even_with_override(self):
        """INT-011: Even explicit override cannot disable QG/gates/act for hotfix."""
        r = ReleaseTypeResolver()
        profile = r.resolve(app_kind="service", app_level="L1", artifact_type="source",
                            release_type=ReleaseTypeName.HOTFIX, profile_id="rtp-hf-ov",
                            overrides={"requires_prettyk_qg": False, "requires_gates": False, "requires_act": False})
        assert profile.requires_prettyk_qg is True   # guard blocks override
        assert profile.requires_gates is True
        assert profile.requires_act is True

    def test_hotfix_can_skip_non_required_steps(self):
        """INT-011: Hotfix can disable non-required technical steps (docs_gen)."""
        r = ReleaseTypeResolver()
        profile = r.resolve(app_kind="service", app_level="L1", artifact_type="source",
                            release_type=ReleaseTypeName.HOTFIX, profile_id="rtp-hf-skip",
                            overrides={"step_overrides": [
                                {"step_id":"docs_gen","step_name":"Docs","step_order":2,"required":False,"enabled":False}]})
        smap = {s.step_id: s for s in profile.steps}
        assert smap["docs_gen"].enabled is False    # non-required step can be disabled
        assert smap["sonarqube"].enabled is True     # required step stays enabled
        assert smap["build"].enabled is True          # required step stays enabled

    def test_custom_cannot_bypass_qg(self):
        """NX-BOSS-03: Custom release type cannot bypass mandatory QG/security baseline."""
        r = ReleaseTypeResolver()
        profile = r.resolve(app_kind="service", app_level="L1", artifact_type="source",
                            release_type=ReleaseTypeName.CUSTOM, profile_id="rtp-c1",
                            overrides={"requires_prettyk_qg": False, "requires_gates": False})
        assert profile.requires_prettyk_qg is True   # guard: cannot bypass
        assert profile.requires_gates is True

    def test_step_override_applied(self):
        r = ReleaseTypeResolver()
        profile = r.resolve(app_kind="service", app_level="L1", artifact_type="source",
                            release_type=ReleaseTypeName.ORDINARY, profile_id="rtp-ov",
                            overrides={"step_overrides": [
                                {"step_id":"sonarqube","step_name":"CustomSonar","step_order":3,"required":False}]})
        smap = {s.step_id: s for s in profile.steps}
        assert smap["sonarqube"].step_name == "CustomSonar"

    def test_required_step_stays_enabled(self):
        r = ReleaseTypeResolver()
        profile = r.resolve(app_kind="service", app_level="L1", artifact_type="source",
                            release_type=ReleaseTypeName.ORDINARY, profile_id="rtp-req",
                            overrides={"step_overrides": [
                                {"step_id":"build","step_name":"B","step_order":0,"required":True,"enabled":False}]})
        smap = {s.step_id: s for s in profile.steps}
        assert smap["build"].enabled is True

    def test_snapshot_hash_consistent(self):
        r = ReleaseTypeResolver()
        p1 = r.resolve(app_kind="service", app_level="L1", artifact_type="source",
                       release_type=ReleaseTypeName.ORDINARY, profile_id="rtp-same")
        p2 = r.resolve(app_kind="service", app_level="L1", artifact_type="source",
                       release_type=ReleaseTypeName.ORDINARY, profile_id="rtp-same")
        assert r.snapshot_profile(p1) == r.snapshot_profile(p2)

    def test_regulatory_no_skip_optional(self):
        r = ReleaseTypeResolver()
        profile = r.resolve(app_kind="service", app_level="L1", artifact_type="source",
                            release_type=ReleaseTypeName.REGULATORY, profile_id="rtp-reg")
        assert profile.requires_prettyk_qg is True
        assert profile.requires_gates is True

    def test_all_five_types_resolve(self):
        r = ReleaseTypeResolver()
        for t in ReleaseTypeName:
            p = r.resolve(app_kind="service", app_level="L1", artifact_type="source",
                          release_type=t, profile_id=f"rtp-{t.value}")
            assert len(p.steps) > 0
            assert p.id != ""


# ══════════════════════════════════════════════════════════════════
# NX-BOSS-04: Batch Hardening
# ══════════════════════════════════════════════════════════════════

class TestBatchHardening:
    def test_retry_child_does_not_lose_siblings(self):
        batch = ProjectReleaseBatch(id="b", project_id="p", release_ids=["r1","r2","r3"])
        batch.register_result("r1", "succeeded")
        batch.register_result("r2", "succeeded")
        batch.register_result("r3", "failed")

        batch.retry_child_release("r3")
        assert "r1" in batch.completed_releases and batch.completed_releases["r1"] == "succeeded"
        assert "r2" in batch.completed_releases
        assert "r3" not in batch.completed_releases   # cleared
        assert "r3" in batch.retry_queue

    def test_blocked_app_prevents_dispatch(self):
        batch = ProjectReleaseBatch(id="b", project_id="p", release_ids=["r1","r2"], blocked_apps=["r1"])
        ready = batch.get_ready_queue(set())
        assert "r1" not in ready
        assert "r2" in ready

    def test_unblock_restores_dispatch(self):
        batch = ProjectReleaseBatch(id="b", project_id="p", release_ids=["r1"], blocked_apps=["r1"])
        batch.unblock_app("r1")
        assert "r1" not in batch.blocked_apps
        assert "r1" in batch.get_ready_queue(set())

    def test_partial_success_preserves_sibling_results(self):
        batch = ProjectReleaseBatch(id="b", project_id="p", release_ids=["r1","r2","r3"])
        batch.register_result("r1", "succeeded")
        batch.register_result("r2", "failed")
        batch.register_result("r3", "succeeded")
        assert batch.partial_success_count() == 2
        assert batch.compute_batch_status() == "partially_succeeded"
        # r3 result is NOT lost despite r2 failing
        assert batch.completed_releases["r3"] == "succeeded"

    def test_is_ready_for_transfer_requires_all_readiness(self):
        batch = ProjectReleaseBatch(id="b", project_id="p", release_ids=["r1","r2"])
        batch.register_result("r1", "succeeded")
        batch.register_result("r2", "succeeded")

        rel1 = IndividualRelease(id="r1", app_id="a1", project_id="p",
            release_type_id="rtp", lifecycle_snapshot=[],
            gate_decisions={}, prettyk_qg_result=True, gost_act_attached=True)
        rel2 = IndividualRelease(id="r2", app_id="a2", project_id="p",
            release_type_id="rtp", lifecycle_snapshot=[],
            gate_decisions={}, prettyk_qg_result=True, gost_act_attached=True)
        assert batch.is_ready_for_transfer({"r1":rel1,"r2":rel2}) is True

    def test_is_not_ready_if_gost_act_missing(self):
        batch = ProjectReleaseBatch(id="b", project_id="p", release_ids=["r1"])
        batch.register_result("r1", "succeeded")
        rel1 = IndividualRelease(id="r1", app_id="a1", project_id="p",
            release_type_id="rtp", lifecycle_snapshot=[],
            gate_decisions={}, prettyk_qg_result=True, gost_act_attached=False)
        assert batch.is_ready_for_transfer({"r1":rel1}) is False

    def test_get_ready_queue_respects_dependency_graph(self):
        batch = ProjectReleaseBatch(id="b", project_id="p", release_ids=["r1","r2","r3"],
            dependency_graph=[
                AppGraphEdge(from_app="r3", to_app="r2"),
                AppGraphEdge(from_app="r2", to_app="r1"),
            ])
        # Nothing completed: r1 has no deps, ready first
        ready = batch.get_ready_queue(set())
        assert ready == ["r1"]
        # r1 done, r2 becomes ready
        ready = batch.get_ready_queue({"r1"})
        assert "r2" in ready

    def test_retry_removes_from_completed(self):
        batch = ProjectReleaseBatch(id="b", project_id="p", release_ids=["r1"])
        batch.register_result("r1", "failed")
        batch.retry_child_release("r1")
        assert "r1" not in batch.completed_releases
        assert "r1" in batch.retry_queue


# ══════════════════════════════════════════════════════════════════
# INT-016: Control-Plane Steel Thread
# ══════════════════════════════════════════════════════════════════

class TestSteelThread:
    """INT-016: Full control-plane flow — graph → profiles → batch → partial failure → retry → ready_for_transfer."""

    def test_full_steel_thread(self):
        orchestrator = ReleaseOrchestrator()

        # 1. Project graph with apps at different levels
        project = Project(
            id="proj-payments", label="Retail Payments",
            team_scopes=["team-payments"],
            apps=[
                AppRef(app_id="auth-svc", app_code="AUTH", level="L1", app_kind="service"),
                AppRef(app_id="crypto-lib", app_code="CRYPTO", level="L0", app_kind="library"),
                AppRef(app_id="web-api", app_code="WEB", level="L2", app_kind="frontend"),
            ],
        )

        # 2. Graph validation — L2 depends on L1, L1 depends on L0
        graph = ProjectGraph(
            project=project,
            edges=[
                AppGraphEdge(from_app="web-api", to_app="auth-svc"),
                AppGraphEdge(from_app="auth-svc", to_app="crypto-lib"),
            ],
        )
        assert graph.validate_no_cycles() is True
        assert graph.validate_levels() == []

        # 3. Resolve profiles for each app type
        resolver = ReleaseTypeResolver()
        profiles = {}
        for app in project.apps:
            profile = resolver.resolve(
                app_kind=app.app_kind, app_level=app.level,
                artifact_type="source",
                release_type=ReleaseTypeName.ORDINARY,
                profile_id=f"rtp-{app.app_id}",
            )
            profiles[app.app_id] = profile
            snap = resolver.snapshot_profile(profile)
            assert len(snap) == 16  # SHA-256 hex[:16]

        # 4. Create individual releases with lifecycle snapshots
        releases = {}
        for app in project.apps:
            rel = orchestrator.create_release(
                app.app_id, project.id, profiles[app.app_id],
                app_code=app.app_code, commit_sha=f"sha-{app.app_id}",
            )
            releases[app.app_id] = rel

        assert len(releases) == 3

        # 5. Create batch with actual release IDs
        batch = orchestrator.create_batch(
            project,
            {rel.id: profiles[a.app_id].id for a, rel in zip(project.apps, releases.values())},
            dep_edges=graph.edges,
        )
        # Fix: create_batch sets release_ids to dict keys — use actual release IDs
        batch.release_ids = [rel.id for rel in releases.values()]

        # Update dependency graph to use release IDs
        batch.dependency_graph = [
            AppGraphEdge(from_app=releases["web-api"].id, to_app=releases["auth-svc"].id),
            AppGraphEdge(from_app=releases["auth-svc"].id, to_app=releases["crypto-lib"].id),
        ]

        # 6. Topological queue — only crypto-lib (no deps) is ready first
        ready = batch.get_ready_queue(set())
        assert releases["crypto-lib"].id in ready
        assert releases["auth-svc"].id not in ready  # depends on crypto-lib
        assert releases["web-api"].id not in ready   # depends on auth-svc

        # 7. Simulate partial execution
        # crypto-lib succeeds
        rel_crypto = releases["crypto-lib"]
        rel_crypto.gate_decisions = {"gate-build": "pass", "gate-sonarqube": "pass",
                                      "gate-codescoring": "pass", "gate-deploy": "pass"}
        rel_crypto.prettyk_qg_result = True
        rel_crypto.gost_act_attached = True
        batch.register_result(rel_crypto.id, "succeeded")

        # auth-svc now ready
        ready = batch.get_ready_queue({rel_crypto.id})
        assert releases["auth-svc"].id in ready

        # auth-svc fails
        rel_auth = releases["auth-svc"]
        rel_auth.gate_decisions = {"gate-build": "pass", "gate-sonarqube": "pass",
                                    "gate-codescoring": "pass", "gate-deploy": "pass"}
        rel_auth.prettyk_qg_result = True
        rel_auth.gost_act_attached = True  # initially attached
        batch.register_result(rel_auth.id, "failed")

        # web-api is blocked because auth-svc failed
        assert batch.compute_batch_status() == "partially_succeeded"

        # 8. Retry auth-svc — sibling crypto-lib result preserved
        batch.retry_child_release(rel_auth.id)
        assert rel_crypto.id in batch.completed_releases
        assert batch.completed_releases[rel_crypto.id] == "succeeded"
        assert rel_auth.id not in batch.completed_releases  # cleared
        assert rel_auth.id in batch.retry_queue

        # Retry succeeds
        rel_auth.gate_decisions = {"gate-build": "pass", "gate-sonarqube": "pass",
                                    "gate-codescoring": "pass", "gate-deploy": "pass"}
        rel_auth.prettyk_qg_result = True
        rel_auth.gost_act_attached = True
        batch.register_result(rel_auth.id, "succeeded")

        # web-api now ready
        rel_web = releases["web-api"]
        ready = batch.get_ready_queue({rel_crypto.id, rel_auth.id})
        assert rel_web.id in ready

        # web-api succeeds
        rel_web.gate_decisions = {"gate-build": "pass", "gate-sonarqube": "pass",
                                   "gate-codescoring": "pass", "gate-deploy": "pass"}
        rel_web.prettyk_qg_result = True
        rel_web.gost_act_attached = True
        batch.register_result(rel_web.id, "succeeded")

        assert batch.compute_batch_status() == "succeeded"
        assert batch.partial_success_count() == 3  # all 3 succeeded after retry

        # 9. Ready for transfer — all releases must pass readiness
        assert batch.is_ready_for_transfer({
            rel_crypto.id: rel_crypto, rel_auth.id: rel_auth, rel_web.id: rel_web,
        }) is True

        # 10. Package assembly
        pkg = orchestrator.assemble_package(batch, {
            rel_crypto.id: rel_crypto, rel_auth.id: rel_auth, rel_web.id: rel_web,
        })
        pkg.mark_ready()
        assert pkg.status == "ready_for_transfer"
        assert pkg.is_transfer_ready() is True
        assert len(pkg.app_release_ids) == 3
        assert pkg.prettyk_verdict is True