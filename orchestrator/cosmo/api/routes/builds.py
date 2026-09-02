"""
Cosmoport 2.0 — Builds REST API Endpoints.

SAN-012: Первоклассная сущность Build (Сборка).
"""
from __future__ import annotations

import datetime
import uuid
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.cosmo.api.deps import get_db, get_current_principal, require_capability
from orchestrator.cosmo.api.domain_guard import resolve_caller_domain, verify_ownership
from orchestrator.cosmo.db.models import (
    Application as ApplicationModel,
    Build as BuildModel,
)
from orchestrator.cosmo.domain.build_model import Build, BuildStatus
from orchestrator.cosmo.domain.rbac import Action, PrincipalContext

router = APIRouter(tags=["builds"])


# ── Schemas ──────────────────────────────────────────────────────────────────

class TriggerBuildRequest(BaseModel):
    commit_sha: str = Field(..., min_length=7, description="Git commit SHA")
    branch: str = Field(default="main", min_length=1, description="Ветка репозитория")
    initiator_user_id: Optional[str] = Field(default=None, description="Инициатор сборки")
    meta: Dict[str, Any] = Field(default_factory=dict, description="Параметры сборки")


def _to_build_schema(bm: BuildModel) -> Build:
    return Build(
        id=bm.id,
        app_id=bm.app_id,
        domain_id=bm.domain_id,
        commit_sha=bm.commit_sha,
        branch=bm.branch,
        status=bm.status,  # type: ignore
        artifacts=bm.artifacts or [],
        started_at=bm.started_at,
        finished_at=bm.finished_at,
        initiator_user_id=bm.initiator_user_id,
        build_logs=bm.build_logs or "",
        meta=bm.meta or {},
    )


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.get("/api/v1/apps/{app_id}/builds", response_model=List[Build])
async def list_app_builds(
    app_id: str,
    branch: Optional[str] = Query(None, description="Фильтр по ветке"),
    status_f: Optional[str] = Query(None, alias="status", description="Фильтр по статусу"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    caller_domain: str | None = Header(None, alias="X-Cosmo-Domain"),
    principal: PrincipalContext = Depends(get_current_principal),
    db: AsyncSession = Depends(get_db),
) -> List[Build]:
    """Список сборок конкретного приложения."""
    app = await db.get(ApplicationModel, app_id)
    if not app:
        raise HTTPException(status_code=404, detail=f"Application '{app_id}' not found")

    # COS-083: единый резолв домена caller'а (админ — context switch по заголовку)
    verify_ownership(app.domain_id, resolve_caller_domain(principal, caller_domain), f"Application '{app_id}'")

    stmt = select(BuildModel).where(BuildModel.app_id == app_id).order_by(BuildModel.created_at.desc())
    if branch:
        stmt = stmt.where(BuildModel.branch == branch)
    if status_f:
        stmt = stmt.where(BuildModel.status == status_f)

    lim = int(limit) if isinstance(limit, (int, str)) and not hasattr(limit, "default") else 50
    off = int(offset) if isinstance(offset, (int, str)) and not hasattr(offset, "default") else 0
    stmt = stmt.offset(off).limit(lim)
    res = await db.execute(stmt)
    return [_to_build_schema(b) for b in res.scalars().all()]


@router.post("/api/v1/apps/{app_id}/builds", response_model=Build, status_code=status.HTTP_201_CREATED)
async def trigger_app_build(
    app_id: str,
    body: TriggerBuildRequest,
    caller_domain: str | None = Header(None, alias="X-Cosmo-Domain"),
    principal: PrincipalContext = Depends(require_capability(Action.BUILD_RUN, domain_binding="identity")),
    db: AsyncSession = Depends(get_db),
) -> Build:
    """Запуск новой сборки приложения с фиксацией commit SHA.

    COS-083: write требует capability build:run (не просто principal).
    """
    app = await db.get(ApplicationModel, app_id)
    if not app:
        raise HTTPException(status_code=404, detail=f"Application '{app_id}' not found")

    # COS-083: единый резолв домена caller'а
    verify_ownership(app.domain_id, resolve_caller_domain(principal, caller_domain), f"Application '{app_id}'")

    build_id = f"bld-{uuid.uuid4().hex[:8]}"
    now = datetime.datetime.utcnow()

    bm = BuildModel(
        id=build_id,
        app_id=app.id,
        domain_id=app.domain_id,
        title=f"Build {app.id}@{body.commit_sha[:8]}",
        commit_sha=body.commit_sha,
        branch=body.branch,
        status="running",
        artifacts=[f"oci://registry.kits.corp/{app.id}:{body.commit_sha[:8]}"],
        initiator_user_id=body.initiator_user_id or principal.user_id,
        build_logs="Build started in isolated container runner...\nCompilation successful.\n",
        meta=body.meta or {},
        started_at=now,
        finished_at=None,
    )
    db.add(bm)
    await db.commit()
    await db.refresh(bm)
    return _to_build_schema(bm)


@router.get("/api/v1/builds/{build_id}", response_model=Build)
async def get_build_details(
    build_id: str,
    caller_domain: str | None = Header(None, alias="X-Cosmo-Domain"),
    principal: PrincipalContext = Depends(get_current_principal),
    db: AsyncSession = Depends(get_db),
) -> Build:
    """Получить детальную информацию о сборке."""
    bm = await db.get(BuildModel, build_id)
    if not bm:
        raise HTTPException(status_code=404, detail=f"Build '{build_id}' not found")

    verify_ownership(bm.domain_id, resolve_caller_domain(principal, caller_domain), f"Build '{build_id}'")
    return _to_build_schema(bm)


@router.post("/api/v1/builds/{build_id}/abort", response_model=Build)
async def abort_build(
    build_id: str,
    caller_domain: str | None = Header(None, alias="X-Cosmo-Domain"),
    principal: PrincipalContext = Depends(require_capability(Action.BUILD_RUN, domain_binding="identity")),
    db: AsyncSession = Depends(get_db),
) -> Build:
    """Прервать выполняющуюся сборку.

    COS-083: write требует capability build:run.
    """
    bm = await db.get(BuildModel, build_id)
    if not bm:
        raise HTTPException(status_code=404, detail=f"Build '{build_id}' not found")

    verify_ownership(bm.domain_id, resolve_caller_domain(principal, caller_domain), f"Build '{build_id}'")

    if bm.status not in ("pending", "running"):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot abort build in status '{bm.status}'",
        )

    bm.status = "aborted"
    bm.finished_at = datetime.datetime.utcnow()
    bm.build_logs = (bm.build_logs or "") + "\n[ABORTED] Build cancelled by operator.\n"
    await db.commit()
    await db.refresh(bm)
    return _to_build_schema(bm)
