"""
LR-006: Release Types & ReleaseBatch REST API.

  GET/POST/PUT   /api/v1/release-types
  GET            /api/v1/release-types/{id}

  GET/POST       /api/v1/projects/{id}/release-batches
  GET            /api/v1/release-batches/{id}
  POST           /api/v1/release-batches/{id}/run
"""
from __future__ import annotations

import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.cosmo.api.deps import get_current_principal, get_db
from orchestrator.cosmo.db.models_lr import (
    ReleaseType as ReleaseTypeModel,
    ReleaseBatch as ReleaseBatchModel,
    Project as ProjectModel,
)
from orchestrator.cosmo.domain.release_type_model import (
    ReleaseType,
    ReleaseTypeStep,
    ReleaseBatch,
)
from orchestrator.cosmo.domain.rbac import PrincipalContext

router = APIRouter(tags=["release-types"])


# ── Schemas ──────────────────────────────────────────────────────────────────

class CreateReleaseTypeRequest(BaseModel):
    id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    description: Optional[str] = None
    version: str = Field(default="1.0.0")
    steps: List[ReleaseTypeStep] = Field(default_factory=list)
    required_approvals: int = Field(default=2, ge=1)
    allowed_zones: List[str] = Field(default_factory=lambda: ["zr", "zt", "zpe"])


class UpdateReleaseTypeRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    version: Optional[str] = None
    steps: Optional[List[ReleaseTypeStep]] = None
    required_approvals: Optional[int] = None
    allowed_zones: Optional[List[str]] = None
    is_active: Optional[bool] = None


class CreateReleaseBatchRequest(BaseModel):
    id: str = Field(..., min_length=1)
    release_type_id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    app_ids: List[str] = Field(default_factory=list)


# ── Release Type Endpoints ──────────────────────────────────────────────────

def _to_rt_schema(rm: ReleaseTypeModel) -> ReleaseType:
    return ReleaseType(
        id=rm.id,
        name=rm.name,
        description=rm.description,
        version=rm.version,
        steps=[ReleaseTypeStep(**s) for s in (rm.steps_json or [])],
        required_approvals=rm.required_approvals,
        allowed_zones=rm.allowed_zones or [],
        is_active=rm.is_active,
        created_at=rm.created_at,
        updated_at=rm.updated_at,
    )


@router.get("/api/v1/release-types", response_model=List[ReleaseType])
async def list_release_types(db: AsyncSession = Depends(get_db)) -> List[ReleaseType]:
    res = await db.execute(select(ReleaseTypeModel).order_by(ReleaseTypeModel.name))
    return [_to_rt_schema(rt) for rt in res.scalars().all()]


@router.post("/api/v1/release-types", response_model=ReleaseType, status_code=status.HTTP_201_CREATED)
async def create_release_type(
    body: CreateReleaseTypeRequest,
    db: AsyncSession = Depends(get_db),
) -> ReleaseType:
    existing = await db.get(ReleaseTypeModel, body.id)
    if existing:
        raise HTTPException(status_code=409, detail=f"Release type '{body.id}' already exists")

    rm = ReleaseTypeModel(
        id=body.id,
        name=body.name,
        description=body.description,
        version=body.version,
        steps_json=[s.model_dump() for s in body.steps],
        required_approvals=body.required_approvals,
        allowed_zones=body.allowed_zones,
    )
    db.add(rm)
    await db.commit()
    await db.refresh(rm)
    return _to_rt_schema(rm)


@router.get("/api/v1/release-types/{release_type_id}", response_model=ReleaseType)
async def get_release_type(release_type_id: str, db: AsyncSession = Depends(get_db)) -> ReleaseType:
    rm = await db.get(ReleaseTypeModel, release_type_id)
    if not rm:
        raise HTTPException(status_code=404, detail=f"Release type '{release_type_id}' not found")
    return _to_rt_schema(rm)


@router.put("/api/v1/release-types/{release_type_id}", response_model=ReleaseType)
async def update_release_type(
    release_type_id: str,
    body: UpdateReleaseTypeRequest,
    db: AsyncSession = Depends(get_db),
) -> ReleaseType:
    rm = await db.get(ReleaseTypeModel, release_type_id)
    if not rm:
        raise HTTPException(status_code=404, detail=f"Release type '{release_type_id}' not found")

    if body.name is not None:
        rm.name = body.name
    if body.description is not None:
        rm.description = body.description
    if body.version is not None:
        rm.version = body.version
    if body.steps is not None:
        rm.steps_json = [s.model_dump() for s in body.steps]
    if body.required_approvals is not None:
        rm.required_approvals = body.required_approvals
    if body.allowed_zones is not None:
        rm.allowed_zones = body.allowed_zones
    if body.is_active is not None:
        rm.is_active = body.is_active

    await db.commit()
    await db.refresh(rm)
    return _to_rt_schema(rm)


# ── ReleaseBatch Endpoints ──────────────────────────────────────────────────

def _to_rb_schema(rb_model: ReleaseBatchModel) -> ReleaseBatch:
    return ReleaseBatch(
        id=rb_model.id,
        project_id=rb_model.project_id,
        release_type_id=rb_model.release_type_id,
        name=rb_model.name,
        status=rb_model.status,  # type: ignore
        app_ids=rb_model.app_ids or [],
        run_id=rb_model.run_id,
        started_at=rb_model.started_at,
        finished_at=rb_model.finished_at,
        created_at=rb_model.created_at,
    )


@router.get("/api/v1/projects/{project_id}/release-batches", response_model=List[ReleaseBatch])
async def list_project_release_batches(
    project_id: str,
    db: AsyncSession = Depends(get_db),
) -> List[ReleaseBatch]:
    pm = await db.get(ProjectModel, project_id)
    if not pm:
        raise HTTPException(status_code=404, detail=f"Project '{project_id}' not found")

    stmt = select(ReleaseBatchModel).where(
        ReleaseBatchModel.project_id == project_id
    ).order_by(ReleaseBatchModel.created_at.desc())
    res = await db.execute(stmt)
    return [_to_rb_schema(b) for b in res.scalars().all()]


@router.post("/api/v1/projects/{project_id}/release-batches", response_model=ReleaseBatch, status_code=status.HTTP_201_CREATED)
async def create_release_batch(
    project_id: str,
    body: CreateReleaseBatchRequest,
    db: AsyncSession = Depends(get_db),
) -> ReleaseBatch:
    pm = await db.get(ProjectModel, project_id)
    if not pm:
        raise HTTPException(status_code=404, detail=f"Project '{project_id}' not found")

    rt = await db.get(ReleaseTypeModel, body.release_type_id)
    if not rt:
        raise HTTPException(status_code=404, detail=f"Release type '{body.release_type_id}' not found")

    rb = ReleaseBatchModel(
        id=body.id,
        project_id=project_id,
        release_type_id=body.release_type_id,
        name=body.name,
        status="draft",
        app_ids=body.app_ids,
    )
    db.add(rb)
    await db.commit()
    await db.refresh(rb)
    return _to_rb_schema(rb)


@router.get("/api/v1/release-batches/{batch_id}", response_model=ReleaseBatch)
async def get_release_batch(batch_id: str, db: AsyncSession = Depends(get_db)) -> ReleaseBatch:
    rb = await db.get(ReleaseBatchModel, batch_id)
    if not rb:
        raise HTTPException(status_code=404, detail=f"Release batch '{batch_id}' not found")
    return _to_rb_schema(rb)


@router.post("/api/v1/release-batches/{batch_id}/run", response_model=ReleaseBatch)
async def run_release_batch(
    batch_id: str,
    db: AsyncSession = Depends(get_db),
) -> ReleaseBatch:
    rb = await db.get(ReleaseBatchModel, batch_id)
    if not rb:
        raise HTTPException(status_code=404, detail=f"Release batch '{batch_id}' not found")

    if rb.status not in ("draft",):
        raise HTTPException(status_code=400, detail=f"Cannot run batch in status '{rb.status}'")

    rb.status = "running"
    rb.started_at = datetime.datetime.utcnow()
    await db.commit()
    await db.refresh(rb)
    return _to_rb_schema(rb)