import sys
from pathlib import Path

_orch = Path(__file__).resolve().parents[1]
if str(_orch) not in sys.path:
    sys.path.insert(0, str(_orch))

import pytest
from orchestrator.cosmo.control_plane.lifecycle_resolver import (
    LifecycleResolver, LCStepConfig, CANONICAL_8_STEPS,
    BuildBatch, StaticScanBatch, DeployBatch,
)


class TestLCStepConfig:
    def test_model_creation(self):
        s = LCStepConfig(step_id="build", step_name="Build", section="build", step_order=0)
        assert s.step_id == "build"
        assert s.step_required is True

    def test_default_values(self):
        s = LCStepConfig(step_id="sonarqube", step_name="SonarQube", step_order=3)
        assert s.section == "static"
        assert s.step_on_failure == "fail"
        assert s.step_enabled is True

    def test_extra_fields_ignored(self):
        s = LCStepConfig(step_id="test", step_name="Test", step_order=0, unknown_field=42)
        assert not hasattr(s, "unknown_field")


class TestCanonical8Steps:
    def test_exactly_8_steps(self):
        assert len(CANONICAL_8_STEPS) == 8

    def test_required_step_ids(self):
        required = [s.step_id for s in CANONICAL_8_STEPS.values() if s.step_required]
        assert "build" in required
        assert "unit_tests" in required
        assert "sonarqube" in required
        assert "trivy" in required
        assert "deploy" in required
        assert len(required) == 5

    def test_optional_step_ids(self):
        optional = [s.step_id for s in CANONICAL_8_STEPS.values() if not s.step_required]
        assert set(optional) == {"docs_gen", "codescoring", "kcs"}

    def test_step_order_unique(self):
        orders = [s.step_order for s in CANONICAL_8_STEPS.values()]
        assert len(orders) == len(set(orders)) == 8
        assert min(orders) == 0
        assert max(orders) == 7


class TestLifecycleResolver:
    def test_resolve_canonical(self):
        r = LifecycleResolver()
        steps = r.resolve_as_list()
        assert len(steps) == 8
        assert steps[0].step_id == "build"
        assert steps[-1].step_id == "deploy"

    def test_resolve_dict_keys(self):
        r = LifecycleResolver()
        resolved = r.resolve()
        for sid in CANONICAL_8_STEPS:
            assert sid in resolved
            assert isinstance(resolved[sid], LCStepConfig)

    def test_domain_default_override(self):
        domain = {"build": {"step_enabled": False, "step_on_failure": "warn"}}
        r = LifecycleResolver(domain_defaults=domain)
        steps = {s.step_id: s for s in r.resolve_as_list()}
        # Required step stays enabled even if domain tries to disable
        assert steps["build"].step_enabled is True
        assert steps["build"].step_on_failure == "warn"

    def test_app_override_disable_optional(self):
        app = {"docs_gen": {"step_enabled": False}}
        r = LifecycleResolver(app_overrides=app)
        steps = {s.step_id: s for s in r.resolve_as_list()}
        assert steps["docs_gen"].step_enabled is False

    def test_cannot_disable_required_step(self):
        app = {"build": {"step_required": False, "step_enabled": False}}
        r = LifecycleResolver(app_overrides=app)
        steps = {s.step_id: s for s in r.resolve_as_list()}
        assert steps["build"].step_required is True

    def test_domain_plus_app_override(self):
        domain = {"sonarqube": {"step_enabled": False}}
        app = {"sonarqube": {"step_on_failure": "warn"}}
        r = LifecycleResolver(domain_defaults=domain, app_overrides=app)
        steps = {s.step_id: s for s in r.resolve_as_list()}
        # Required step stays enabled despite domain override
        assert steps["sonarqube"].step_enabled is True
        assert steps["sonarqube"].step_on_failure == "warn"

    def test_app_override_new_field(self):
        app = {"deploy": {"step_on_failure": "skip"}}
        r = LifecycleResolver(app_overrides=app)
        steps = {s.step_id: s for s in r.resolve_as_list()}
        assert steps["deploy"].step_on_failure == "skip"
        assert steps["deploy"].step_required is True


class TestBatchGeneration:
    def test_three_batches(self):
        r = LifecycleResolver()
        batches = r.generate_batches()
        assert set(batches.keys()) == {"build", "static_scan", "deploy"}

    def test_build_batch_has_3_steps(self):
        r = LifecycleResolver()
        batches = r.generate_batches()
        assert len(batches["build"]["steps"]) == 3

    def test_static_scan_batch_has_4_steps(self):
        r = LifecycleResolver()
        batches = r.generate_batches()
        assert len(batches["static_scan"]["steps"]) == 4

    def test_deploy_batch_has_1_step(self):
        r = LifecycleResolver()
        batches = r.generate_batches()
        assert len(batches["deploy"]["steps"]) == 1

    def test_disabled_step_not_in_batch(self):
        app = {"docs_gen": {"step_enabled": False}}
        r = LifecycleResolver(app_overrides=app)
        batches = r.generate_batches()
        build_step_ids = [s["step_id"] for s in batches["build"]["steps"]]
        assert "docs_gen" not in build_step_ids


class TestRequiredCoverage:
    def test_all_required_enabled(self):
        r = LifecycleResolver()
        cov = r.validate_required_coverage()
        assert cov["ok"] is True
        assert cov["disabled"] == 0

    def test_required_disabled_impossible(self):
        app = {"build": {"step_required": False, "step_enabled": False}}
        r = LifecycleResolver(app_overrides=app)
        cov = r.validate_required_coverage()
        assert cov["ok"] is True

    def test_optional_disabled_ok(self):
        app = {"docs_gen": {"step_enabled": False}}
        r = LifecycleResolver(app_overrides=app)
        cov = r.validate_required_coverage()
        assert cov["ok"] is True
        assert cov["total_required"] == 5