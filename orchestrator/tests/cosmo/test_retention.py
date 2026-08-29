"""
COS-066: Retention Policy & Cleanup tests.

Проверяет:
  - RetentionPolicy модель
  - ArtifactRetentionManager.evaluate_cleanup (sparse → candidate logic)
  - Protection: release runs, GOST-signed runs, keep_min_runs
  - purge_expired: dry_run, real удаление, подсчёт байт
  - Edge cases: empty run_ids, all protected, all expired
  - Интеграция с ArtifactStore
"""
import os
import time
from pathlib import Path

import pytest
from cosmo.ledger.artifact_store import ArtifactStore
from cosmo.ledger.retention import (
    ArtifactRetentionManager,
    RetentionPolicy,
    RetentionRecord,
    CleanupPlan,
)


# ── Fixtures ──────────────────────────────────────────────────────────

@pytest.fixture
def store(tmpdir) -> ArtifactStore:
    return ArtifactStore(base_dir=str(tmpdir))


@pytest.fixture
def manager(store) -> ArtifactRetentionManager:
    return ArtifactRetentionManager(store)


def _make_artifact(store: ArtifactStore, run_id: str, content: bytes = b"x" * 100, **kw) -> None:
    store.store(content, provenance=run_id, **kw)


# ── RetentionPolicy ────────────────────────────────────────────────────

class TestRetentionPolicy:
    def test_defaults(self):
        p = RetentionPolicy()
        assert p.max_age_days == 90
        assert p.keep_min_runs == 5
        assert p.protected_tags == []
        assert p.max_storage_gb == 50.0

    def test_custom(self):
        p = RetentionPolicy(max_age_days=30, keep_min_runs=3, protected_tags=["golden"])
        assert p.max_age_days == 30
        assert p.keep_min_runs == 3
        assert p.protected_tags == ["golden"]

    def test_run_success_protection_default(self):
        assert RetentionPolicy().run_success_protection is True


# ── evaluate_cleanup ───────────────────────────────────────────────────

class TestEvaluateCleanup:
    def test_empty_run_ids(self, manager):
        plan = manager.evaluate_cleanup([])
        assert plan.candidates == []
        assert plan.protected == []

    def test_all_fresh_protected(self, store, manager):
        """Все прогоны в пределах max_age (keep_min_runs=5, max_age_days=90) — 0 кандидатов."""
        for i in range(3):
            _make_artifact(store, f"run-{i}")
        plan = manager.evaluate_cleanup(["run-0", "run-1", "run-2"])
        assert len(plan.candidates) == 0
        assert len(plan.protected) == 3

    def test_keep_min_runs_protects_recent(self, store):
        """keep_min_runs свежайших прогонов защищены."""
        manager = ArtifactRetentionManager(store, RetentionPolicy(max_age_days=0, keep_min_runs=2))
        for i in range(5):
            _make_artifact(store, f"run-{i}")

        plan = manager.evaluate_cleanup([f"run-{i}" for i in range(5)])
        assert len(plan.protected) == 2
        assert len(plan.candidates) >= 2
        for p in plan.protected:
            assert p.protection_reason == "keep_min_runs"

    def test_old_runs_become_candidates(self, store, tmpdir):
        """Старые прогоны за пределами keep_min_runs — кандидаты."""
        manager = ArtifactRetentionManager(store, RetentionPolicy(max_age_days=0, keep_min_runs=1))
        for i in range(3):
            _make_artifact(store, f"run-{i}")

        plan = manager.evaluate_cleanup(["run-0", "run-1", "run-2"])
        # keep_min_runs=1 → 1 свежайший прогон защищён, 2 кандидата
        assert len(plan.candidates) == 2
        assert len(plan.protected) == 1

    def test_release_protection(self, store):
        """Артефакты release-прогонов защищены независимо от возраста."""
        manager = ArtifactRetentionManager(store, RetentionPolicy(max_age_days=0, keep_min_runs=0))
        for i in range(3):
            _make_artifact(store, f"run-{i}")
        manager.protect_release_runs(["run-1"])

        plan = manager.evaluate_cleanup(["run-0", "run-1", "run-2"])
        # run-1 защищён как release
        assert not any(c.run_id == "run-1" for c in plan.candidates)
        assert any(p.run_id == "run-1" and "release" in p.protection_reason for p in plan.protected)

    def test_gost_signed_protection(self, store):
        """Подписанные ГОСТ-Акты защищены от удаления."""
        manager = ArtifactRetentionManager(store, RetentionPolicy(max_age_days=0, keep_min_runs=0))
        _make_artifact(store, "run-gost")
        _make_artifact(store, "run-normal")
        manager.protect_gost_signed_runs(["run-gost"])

        plan = manager.evaluate_cleanup(["run-gost", "run-normal"])
        assert not any(c.run_id == "run-gost" for c in plan.candidates)
        assert any(p.run_id == "run-gost" and "gost_signed" in p.protection_reason for p in plan.protected)

    def test_multiple_protection_reasons(self, store):
        """Прогон может быть защищён и релизом, и ГОСТ-Актом."""
        manager = ArtifactRetentionManager(store, RetentionPolicy(max_age_days=0, keep_min_runs=0))
        _make_artifact(store, "run-dual")
        manager.protect_release_runs(["run-dual"])
        manager.protect_gost_signed_runs(["run-dual"])

        plan = manager.evaluate_cleanup(["run-dual"])
        assert len(plan.candidates) == 0
        protected = [p for p in plan.protected if p.run_id == "run-dual"]
        assert len(protected) == 1
        assert "release" in protected[0].protection_reason

    def test_is_protected(self, manager):
        assert not manager.is_protected("run-x")
        manager.protect_release_runs(["run-x"])
        assert manager.is_protected("run-x")


# ── purge_expired ──────────────────────────────────────────────────────

class TestPurgeExpired:
    def test_dry_run_does_not_delete(self, store, manager):
        _make_artifact(store, "run-dry")
        manager.set_policy(RetentionPolicy(max_age_days=0, keep_min_runs=0))

        result = manager.purge_expired(["run-dry"], dry_run=True)
        assert result["dry_run"] is True
        assert result["purged_count"] == 0
        # artefact still exists
        assert len(store.list_artifacts("run-dry")) > 0

    def test_real_purge_deletes_files(self, store, manager):
        _make_artifact(store, "run-purge", b"data" * 50)
        manager.set_policy(RetentionPolicy(max_age_days=0, keep_min_runs=0))

        result = manager.purge_expired(["run-purge"], dry_run=False)
        assert result["dry_run"] is False
        assert result["purged_count"] > 0
        # artefact deleted
        refs = store.list_artifacts("run-purge")
        assert len(refs) == 0

    def test_purge_returns_stats(self, store, manager):
        for i in range(4):
            _make_artifact(store, f"run-{i}", b"x" * 200)

        manager.set_policy(RetentionPolicy(max_age_days=0, keep_min_runs=1))
        result = manager.purge_expired([f"run-{i}" for i in range(4)], dry_run=False)

        assert "purged_count" in result
        assert "freed_bytes" in result
        assert "freed_mb" in result
        assert "purged_run_ids" in result

    def test_protected_not_purged(self, store, manager):
        _make_artifact(store, "run-protected", b"important")
        _make_artifact(store, "run-expendable", b"junk")
        manager.protect_release_runs(["run-protected"])
        manager.set_policy(RetentionPolicy(max_age_days=0, keep_min_runs=0))

        result = manager.purge_expired(["run-protected", "run-expendable"], dry_run=False)

        # run-protected still has its artifacts
        assert len(store.list_artifacts("run-protected")) > 0

    def test_candidates_count_in_result(self, store, manager):
        _make_artifact(store, "run-cand")
        manager.set_policy(RetentionPolicy(max_age_days=0, keep_min_runs=0))
        result = manager.purge_expired(["run-cand"], dry_run=True)
        assert result["candidates_count"] > 0


# ── Edge cases ─────────────────────────────────────────────────────────

class TestRetentionEdgeCases:
    def test_no_artifacts_for_run_ids(self, store, manager):
        """Run_ids без артефактов — пустой план."""
        plan = manager.evaluate_cleanup(["ghost-run"])
        assert plan.candidates == []
        assert plan.protected == []

    def test_all_protected_no_candidates(self, store, manager):
        _make_artifact(store, "run-a")
        _make_artifact(store, "run-b")
        manager.protect_release_runs(["run-a", "run-b"])

        plan = manager.evaluate_cleanup(["run-a", "run-b"])
        assert len(plan.candidates) == 0

    def test_single_run_with_policy(self, store):
        manager = ArtifactRetentionManager(store, RetentionPolicy(max_age_days=365, keep_min_runs=5))
        _make_artifact(store, "run-solo")
        plan = manager.evaluate_cleanup(["run-solo"])
        # one run, keep_min_runs=5 — защищён
        assert len(plan.protected) > 0

    def test_total_size_bytes(self, store, manager):
        _make_artifact(store, "run-size", b"a" * 1000)
        total = manager.total_size_bytes(["run-size"])
        assert total == 1000

    def test_cleanup_plan_stats(self, store, manager):
        _make_artifact(store, "run-stats", b"b" * 500)
        manager.set_policy(RetentionPolicy(max_age_days=0, keep_min_runs=0))
        plan = manager.evaluate_cleanup(["run-stats"])
        assert plan.total_candidates_bytes == 500
        assert plan.total_protected_bytes == 0

    def test_cleanup_plan_total_mb(self, store, manager):
        _make_artifact(store, "run-mb", b"c" * 1048576)  # ~1MB
        manager.set_policy(RetentionPolicy(max_age_days=0, keep_min_runs=0))
        plan = manager.evaluate_cleanup(["run-mb"])
        assert plan.total_candidates_mb > 0.9

    def test_retention_record_properties(self, store, manager):
        _make_artifact(store, "run-rec")
        manager.protect_release_runs(["run-rec"])
        plan = manager.evaluate_cleanup(["run-rec"])
        for p in plan.protected:
            assert p.is_release_artifact is True
            assert p.is_gost_signed is False

    def test_protection_reason_field(self, store, manager):
        _make_artifact(store, "run-reason")
        manager.protect_release_runs(["run-reason"])
        plan = manager.evaluate_cleanup(["run-reason"])
        assert plan.protected[0].protection_reason == "release_or_gost_signed"

    def test_policy_set_get(self, manager):
        old = manager.policy
        new = RetentionPolicy(max_age_days=7, keep_min_runs=1)
        manager.set_policy(new)
        assert manager.policy.max_age_days == 7
        assert manager.policy != old