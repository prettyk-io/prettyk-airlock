"""COS-066: Artifact Retention API — плановая очистка, статус хранилища."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from orchestrator.cosmo.api.deps import require_principal, require_system_admin
from orchestrator.cosmo.domain.rbac import PrincipalContext
from orchestrator.cosmo.ledger.artifact_store import ArtifactStore
from orchestrator.cosmo.ledger.retention import ArtifactRetentionManager, RetentionPolicy

router = APIRouter(prefix="/api/v1/artifacts", tags=["artifacts"])

# In-memory store (dev) — replace with DB/MinIO backend in production
_store = ArtifactStore()

# Default policy
_manager = ArtifactRetentionManager(_store)


# ── Schemas ────────────────────────────────────────────────────────────

class CleanupRequest(BaseModel):
    run_ids: list[str] = Field(default_factory=list, description="ID прогонов для проверки")
    dry_run: bool = Field(default=False, description="Если True — только отчёт без удаления")
    max_age_days: int = Field(default=90, ge=1, description="Максимальный возраст артефакта (дни)")
    keep_min_runs: int = Field(default=5, ge=1, description="Минимум последних прогонов для защиты")


class RetentionStatus(BaseModel):
    total_runs: int
    total_artifacts: int
    total_size_bytes: int
    total_size_mb: float
    policy: dict
    protected_run_ids: list[str]
    candidates_count: int
    candidates_freed_mb: float


# ── Endpoints ───────────────────────────────────────────────────────────

@router.post("/cleanup")
async def trigger_cleanup(
    body: CleanupRequest,
    principal: PrincipalContext = Depends(require_system_admin()),
):
    """COS-066: запустить плановую очистку артефактов.

    COS-068: system-admin only — деструктивная операция (удаление
    артефактов прогонов) была доступна анонимно.
    """
    run_ids = body.run_ids or _list_all_run_dirs()

    policy = RetentionPolicy(
        max_age_days=body.max_age_days,
        keep_min_runs=body.keep_min_runs,
    )
    _manager.set_policy(policy)

    result = _manager.purge_expired(run_ids, dry_run=body.dry_run)
    return result


@router.get("/retention/status", response_model=RetentionStatus)
async def retention_status(
    principal: PrincipalContext = Depends(require_principal()),
):
    """COS-066: сводка хранилища — место, кандидаты, защищённые прогоны.

    COS-068: authentication required.
    """
    run_ids = _list_all_run_dirs()
    plan = _manager.evaluate_cleanup(run_ids)

    return RetentionStatus(
        total_runs=len(run_ids),
        total_artifacts=len(plan.candidates) + len(plan.protected),
        total_size_bytes=plan.total_candidates_bytes + plan.total_protected_bytes,
        total_size_mb=(plan.total_candidates_bytes + plan.total_protected_bytes) / (1024 * 1024),
        policy={
            "max_age_days": _manager.policy.max_age_days,
            "keep_min_runs": _manager.policy.keep_min_runs,
            "protected_tags": _manager.policy.protected_tags,
        },
        protected_run_ids=sorted(_manager._protected_run_ids),
        candidates_count=len(plan.candidates),
        candidates_freed_mb=plan.total_candidates_mb,
    )


# ── Helpers ────────────────────────────────────────────────────────────

def _list_all_run_dirs() -> list[str]:
    """List all run directories in the artifact store."""
    run_ids: list[str] = []
    if _store._base.is_dir():
        for entry in _store._base.iterdir():
            if entry.is_dir():
                run_ids.append(entry.name)
    return sorted(run_ids)


# ── Test helpers ────────────────────────────────────────────────────────

def _reset_retention_state() -> None:
    """Сбросить состояние менеджера (для тестов)."""
    global _store, _manager
    _store = ArtifactStore()
    _manager = ArtifactRetentionManager(_store)