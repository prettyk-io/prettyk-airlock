"""
Cosmoport 2.0 — Deployments REST API Endpoints.

SAN-013: Первоклассная сущность Deployment (Развертывание).
"""
from __future__ import annotations

import datetime
import uuid
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.cosmo.api.deps import get_current_principal, get_db, require_capability  # COS-083 WIP: get_current_principal ещё жив на строках 78/153
from orchestrator.cosmo.api.domain_guard import resolve_caller_domain, verify_ownership
from orchestrator.cosmo.db.models import (
    Application as ApplicationModel,
    Build as BuildModel,
    Deployment as DeploymentModel,
)
from orchestrator.cosmo.domain.deployment_model import (
    Deployment,
    DeploymentSegment,
    DeploymentStatus,
    DeploymentZone,
)
from orchestrator.cosmo.domain.rbac import Action, PrincipalContext

router = APIRouter(tags=["deployments"])


# ── Schemas ──────────────────────────────────────────────────────────────────

class CreateDeploymentRequest(BaseModel):
    build_id: str = Field(..., min_length=1, description="ID сборки для развертывания")
    target_zone: DeploymentZone = Field(default="zr", description="Целевая зона: zr / zt / zpe")
    segment: DeploymentSegment = Field(default="bare", description="Сегмент: bare / integration")
    release_id: Optional[str] = Field(default=None, description="Опциональный ID релиза")
    env_vars: Dict[str, str] = Field(default_factory=dict, description="Переменные окружения")
    custom_url: Optional[str] = Field(default=None, description="Пользовательский URL точки входа")


class RollbackDeploymentRequest(BaseModel):
    reason: str = Field(default="Rollback to previous stable version", description="Причина отката")


def _to_deployment_schema(dm: DeploymentModel) -> Deployment:
    return Deployment(
        id=dm.id,
        build_id=dm.build_id,
        app_id=dm.app_id,
        domain_id=dm.domain_id,
        release_id=dm.release_id,
        segment=dm.segment,        # type: ignore
        target_zone=dm.target_zone,# type: ignore
        status=dm.status,          # type: ignore
        custom_url=dm.custom_url,
        operator_id=dm.operator_id,
        started_at=dm.started_at,
        finished_at=dm.finished_at,
        env_vars=dm.env_vars or {},
        rollback_from_id=dm.rollback_from_id,
    )


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.get("/api/v1/apps/{app_id}/deploys", response_model=List[Deployment])
async def list_app_deployments(
    app_id: str,
    target_zone: Optional[str] = Query(None, description="Фильтр по зоне"),
    status_f: Optional[str] = Query(None, alias="status", description="Фильтр по статусу"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    caller_domain: str | None = Header(None, alias="X-Cosmo-Domain"),
    principal: PrincipalContext = Depends(get_current_principal),
    db: AsyncSession = Depends(get_db),
) -> List[Deployment]:
    """Список развертываний приложения."""
    app = await db.get(ApplicationModel, app_id)
    if not app:
        raise HTTPException(status_code=404, detail=f"Application '{app_id}' not found")

    # COS-083: единый резолв домена caller'а
    verify_ownership(app.domain_id, resolve_caller_domain(principal, caller_domain), f"Application '{app_id}'")

    stmt = select(DeploymentModel).where(DeploymentModel.app_id == app_id).order_by(DeploymentModel.created_at.desc())
    if target_zone:
        stmt = stmt.where(DeploymentModel.target_zone == target_zone)
    if status_f:
        stmt = stmt.where(DeploymentModel.status == status_f)

    lim = int(limit) if isinstance(limit, (int, str)) and not hasattr(limit, "default") else 50
    off = int(offset) if isinstance(offset, (int, str)) and not hasattr(offset, "default") else 0
    stmt = stmt.offset(off).limit(lim)
    res = await db.execute(stmt)
    return [_to_deployment_schema(d) for d in res.scalars().all()]


@router.post("/api/v1/apps/{app_id}/deploys", response_model=Deployment, status_code=status.HTTP_201_CREATED)
async def create_deployment(
    app_id: str,
    body: CreateDeploymentRequest,
    caller_domain: str | None = Header(None, alias="X-Cosmo-Domain"),
    principal: PrincipalContext = Depends(require_capability(Action.DEPLOY_MANAGE, domain_binding="identity")),
    db: AsyncSession = Depends(get_db),
) -> Deployment:
    """Создать новое развертывание сборки в указанную зону.

    COS-083: write требует capability deploy:manage.
    """
    app = await db.get(ApplicationModel, app_id)
    if not app:
        raise HTTPException(status_code=404, detail=f"Application '{app_id}' not found")

    verify_ownership(app.domain_id, resolve_caller_domain(principal, caller_domain), f"Application '{app_id}'")

    build = await db.get(BuildModel, body.build_id)
    if not build or build.app_id != app_id:
        raise HTTPException(status_code=404, detail=f"Build '{body.build_id}' not found for app '{app_id}'")

    dep_id = f"dep-{uuid.uuid4().hex[:8]}"
    now = datetime.datetime.utcnow()
    endpoint_url = body.custom_url or f"https://{app.id}.{body.target_zone}.kits.bank.corp:8443"

    dm = DeploymentModel(
        id=dep_id,
        build_id=build.id,
        app_id=app.id,
        domain_id=app.domain_id,
        release_id=body.release_id,
        segment=body.segment,
        target_zone=body.target_zone,
        status="success",
        custom_url=endpoint_url,
        operator_id=principal.user_id,
        env_vars=body.env_vars,
        started_at=now,
        finished_at=now + datetime.timedelta(seconds=5),
    )
    db.add(dm)
    await db.commit()
    await db.refresh(dm)
    return _to_deployment_schema(dm)


@router.get("/api/v1/deploys/{id}", response_model=Deployment)
async def get_deployment_details(
    id: str,
    caller_domain: str | None = Header(None, alias="X-Cosmo-Domain"),
    principal: PrincipalContext = Depends(get_current_principal),
    db: AsyncSession = Depends(get_db),
) -> Deployment:
    """Получить информацию о развертывании."""
    dm = await db.get(DeploymentModel, id)
    if not dm:
        raise HTTPException(status_code=404, detail=f"Deployment '{id}' not found")

    verify_ownership(dm.domain_id, resolve_caller_domain(principal, caller_domain), f"Deployment '{id}'")
    return _to_deployment_schema(dm)


@router.post("/api/v1/deploys/{id}/rollback", response_model=Deployment)
async def rollback_deployment(
    id: str,
    body: RollbackDeploymentRequest,
    caller_domain: str | None = Header(None, alias="X-Cosmo-Domain"),
    principal: PrincipalContext = Depends(require_capability(Action.DEPLOY_MANAGE, domain_binding="identity")),
    db: AsyncSession = Depends(get_db),
) -> Deployment:
    """Инициировать откат развертывания (Rollback).

    COS-083: write требует capability deploy:manage.
    """
    dm = await db.get(DeploymentModel, id)
    if not dm:
        raise HTTPException(status_code=404, detail=f"Deployment '{id}' not found")

    verify_ownership(dm.domain_id, resolve_caller_domain(principal, caller_domain), f"Deployment '{id}'")

    # Ищем предыдущий успешный деплой в эту же зону
    prev_stmt = (
        select(DeploymentModel)
        .where(
            DeploymentModel.app_id == dm.app_id,
            DeploymentModel.target_zone == dm.target_zone,
            DeploymentModel.id != dm.id,
            DeploymentModel.status == "success",
        )
        .order_by(DeploymentModel.created_at.desc())
        .limit(1)
    )
    prev_res = await db.execute(prev_stmt)
    prev_dep = prev_res.scalar_one_or_none()

    rollback_build_id = prev_dep.build_id if prev_dep else dm.build_id

    # Создаем новый deployment с пометкой rollback
    new_dep_id = f"dep-rb-{uuid.uuid4().hex[:8]}"
    now = datetime.datetime.utcnow()

    new_dm = DeploymentModel(
        id=new_dep_id,
        build_id=rollback_build_id,
        app_id=dm.app_id,
        domain_id=dm.domain_id,
        release_id=dm.release_id,
        segment=dm.segment,
        target_zone=dm.target_zone,
        status="success",
        custom_url=dm.custom_url,
        operator_id=principal.user_id,
        env_vars=dm.env_vars,
        rollback_from_id=dm.id,
        started_at=now,
        finished_at=now,
    )
    # Помечаем старый как rollback
    dm.status = "rollback"

    db.add(new_dm)
    await db.commit()
    await db.refresh(new_dm)
    return _to_deployment_schema(new_dm)
