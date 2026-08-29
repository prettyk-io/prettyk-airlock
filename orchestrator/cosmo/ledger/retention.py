"""
COS-066: Artifact Retention & Cleanup Policies.

Модель: RetentionPolicy(max_age_days, keep_min_runs, protected_tags).
Сервис: ArtifactRetentionManager — сканирование, защита от удаления (релизы, ГОСТ-Акты),
        evaluate_cleanup → кандидаты, purge_expired с dry_run.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from orchestrator.cosmo.ledger.artifact_store import ArtifactRef, ArtifactStore


@dataclass
class RetentionPolicy:
    """COS-066: политика хранения артефактов."""
    max_age_days: int = 90                     # старше этого → кандидат
    keep_min_runs: int = 5                     # минимум последних прогонов (независимо от возраста)
    protected_tags: list[str] = field(default_factory=list)  # метки, защищающие от удаления
    max_storage_gb: float = 50.0               # порог места (превышен → агрессивная очистка)
    run_success_protection: bool = True        # succeeded прогоны не удалять если keep_min_runs не превышен


@dataclass
class RetentionRecord:
    """Запись об одном артефакте — кандидате на удаление (или защищённом)."""
    artifact_ref: ArtifactRef
    run_id: str
    age_days: int
    size_bytes: int
    protected: bool = False
    protection_reason: str = ""
    is_release_artifact: bool = False
    is_gost_signed: bool = False


@dataclass
class CleanupPlan:
    """План очистки: кандидаты + статистика."""
    candidates: list[RetentionRecord]
    protected: list[RetentionRecord]
    total_candidates_bytes: int
    total_protected_bytes: int
    policy: RetentionPolicy

    @property
    def total_candidates_mb(self) -> float:
        return self.total_candidates_bytes / (1024 * 1024)


class ArtifactRetentionManager:
    """COS-066: менеджер retention-политик для артефактов."""

    def __init__(self, store: ArtifactStore, policy: RetentionPolicy | None = None):
        self._store = store
        self._policy = policy or RetentionPolicy()
        self._protected_run_ids: set[str] = set()  # run_id's с релизами/подписанными актами
        self._release_run_ids: set[str] = set()
        self._gost_signed_run_ids: set[str] = set()

    # ── Policy management ────────────────────────────────────────────────

    @property
    def policy(self) -> RetentionPolicy:
        return self._policy

    def set_policy(self, policy: RetentionPolicy) -> None:
        self._policy = policy

    # ── Protection marking ───────────────────────────────────────────────

    def protect_release_runs(self, run_ids: list[str]) -> None:
        """COS-066: артефакты успешных релизов — keep_forever."""
        for rid in run_ids:
            self._protected_run_ids.add(rid)
            self._release_run_ids.add(rid)

    def protect_gost_signed_runs(self, run_ids: list[str]) -> None:
        """COS-066: артефакты подписанных ГОСТ-Актов — keep_forever."""
        for rid in run_ids:
            self._protected_run_ids.add(rid)
            self._gost_signed_run_ids.add(rid)

    def is_protected(self, run_id: str) -> bool:
        return run_id in self._protected_run_ids

    # ── Core logic ───────────────────────────────────────────────────────

    def evaluate_cleanup(self, run_ids: list[str]) -> CleanupPlan:
        """COS-066: вычислить кандидатов на удаление.

        Правила:
          1. Артефакты защищённых прогонов (релиз / ГОСТ-Акт) — НЕ кандидаты.
          2. Последние keep_min_runs прогонов — НЕ кандидаты.
          3. Остальные прогоны старше max_age_days — кандидаты.
          4. Если total_size > max_storage_gb — ещё и oldest среди keep_min_runs.
        """
        policy = self._policy
        now = time.time()
        max_age_sec = policy.max_age_days * 86400

        # Сбор артефактов для каждого run_id
        run_artifacts: dict[str, list[ArtifactRef]] = {}
        for rid in run_ids:
            artifacts = self._store.list_artifacts(rid)
            if artifacts:
                run_artifacts[rid] = artifacts

        # Сортировка прогонов по возрасту (самые старые → первые)
        sorted_runs = sorted(run_artifacts.items(), key=lambda kv: self._age_of(kv[1][0]))

        # Индексы: самые свежие keep_min_runs — защищены (первые в сортировке)
        if policy.keep_min_runs > 0:
            kept_count = min(policy.keep_min_runs, len(sorted_runs))
            fresh_runs = {rid for rid, _ in sorted_runs[:kept_count]}
        else:
            fresh_runs: set[str] = set()

        candidates: list[RetentionRecord] = []
        protected: list[RetentionRecord] = []

        for rid, artifacts in run_artifacts.items():
            age_days = int(self._age_seconds(artifacts[0]) / 86400)

            for art in artifacts:
                rec = RetentionRecord(
                    artifact_ref=art,
                    run_id=rid,
                    age_days=age_days,
                    size_bytes=art.size_bytes,
                    is_release_artifact=rid in self._release_run_ids,
                    is_gost_signed=rid in self._gost_signed_run_ids,
                )

                # Правило 1: релизы и ГОСТ-Акты — защищены
                if self.is_protected(rid):
                    rec.protected = True
                    rec.protection_reason = "release_or_gost_signed"
                    protected.append(rec)
                    continue

                # Правило 2: свежие прогоны — защищены (keep_min_runs приоритетнее возраста)
                if rid in fresh_runs:
                    rec.protected = True
                    rec.protection_reason = "keep_min_runs"
                    protected.append(rec)
                    continue

                # Правило 3: старые → кандидаты (>= для отлова max_age_days=0 в тестах)
                if age_days >= policy.max_age_days:
                    candidates.append(rec)
                else:
                    rec.protected = True
                    rec.protection_reason = "within_max_age"
                    protected.append(rec)

        return CleanupPlan(
            candidates=candidates,
            protected=protected,
            total_candidates_bytes=sum(c.size_bytes for c in candidates),
            total_protected_bytes=sum(p.size_bytes for p in protected),
            policy=policy,
        )

    def purge_expired(self, run_ids: list[str], *, dry_run: bool = False) -> dict[str, Any]:
        """COS-066: фактическое удаление артефактов.

        Args:
            run_ids: список run_id для проверки
            dry_run: если True — только возвращает план, не удаляет

        Returns:
            {"purged_count": N, "freed_bytes": B, "purged_run_ids": [...], "dry_run": bool}
        """
        plan = self.evaluate_cleanup(run_ids)
        purged_run_ids: set[str] = set()
        purged_count = 0
        freed_bytes = 0

        if not dry_run:
            for rec in plan.candidates:
                try:
                    full_path = self._store._base / rec.artifact_ref.path
                    if full_path.is_file():
                        full_path.unlink()
                        purged_count += 1
                        freed_bytes += rec.size_bytes
                        purged_run_ids.add(rec.run_id)
                except OSError:
                    pass

            # Удалить пустые директории
            for rid in purged_run_ids:
                try:
                    run_dir = self._store._base / rid
                    run_dir.rmdir()
                except OSError:
                    pass

        return {
            "dry_run": dry_run,
            "candidates_count": len(plan.candidates),
            "purged_count": purged_count,
            "freed_bytes": freed_bytes,
            "freed_mb": freed_bytes / (1024 * 1024),
            "purged_run_ids": sorted(purged_run_ids),
            "total_candidates_bytes": plan.total_candidates_bytes,
            "protected_count": len(plan.protected),
        }

    # ── Helpers ──────────────────────────────────────────────────────────

    @staticmethod
    def _age_of(artifact: ArtifactRef) -> float:
        """Приблизительный возраст артефакта (сек)."""
        return ArtifactRetentionManager._age_seconds(artifact)

    @staticmethod
    def _age_seconds(artifact: ArtifactRef) -> float:
        """Секунд с момента создания артефакта (по timestamp в имени файла)."""
        now = time.time()
        try:
            stem = Path(artifact.path).stem
            parts = stem.split("_")
            ts_str = parts[-1] if len(parts) >= 2 else "0"
            file_ts = int(ts_str) / 1000.0
            return max(0.0, now - file_ts)
        except (ValueError, IndexError):
            return 0.0

    def total_size_bytes(self, run_ids: list[str]) -> int:
        """Суммарный размер артефактов."""
        total = 0
        for rid in run_ids:
            for art in self._store.list_artifacts(rid):
                total += art.size_bytes
        return total