"""Cosmoport 2.0 — Pipelines & Bricks REST API endpoints.

CRUD operations for PipelineBrick and PipelinePlan, plus Plan Compilation.
"""
from __future__ import annotations

import datetime
import uuid
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select, delete
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.cosmo.api.deps import get_db
from orchestrator.cosmo.db.models import (
    PipelineBrick as BrickModel,
    PipelinePlan as PlanModel,
    PlanBrick as PlanBrickModel,
    Application as ApplicationModel,
    Batch as BatchModel,
)
from orchestrator.cosmo.domain.pipeline_brick import (
    PipelineBrick,
    BrickDefinition,
    BrickType,
    BrickOverride,
)
from orchestrator.cosmo.domain.run_model import Batch
from orchestrator.cosmo.compiler.plan_compiler import PlanCompiler

router = APIRouter(tags=["pipelines"])


# ── Schemas ────────────────────────────────────────────────────────────

class PipelinePlanSchema(BaseModel):
    id: str
    app_id: str
    level: str = "app"
    scope_id: str
    compiled_at: datetime.datetime
    compiled_hash: str
    brick_ids: list[str] = Field(default_factory=list)


class CreatePlanRequest(BaseModel):
    id: str = Field(..., min_length=1)
    app_id: str = Field(..., min_length=1)
    level: str = Field(default="app")
    scope_id: str = Field(default="")
    brick_ids: list[str] = Field(default_factory=list)
    compiled_hash: Optional[str] = None


class CompilePlanRequest(BaseModel):
    plan_id: str = Field(..., min_length=1)
    app_id: str = Field(..., min_length=1)
    brick_ids: list[str] = Field(..., min_length=1)
    level: str = Field(default="app")


class UpdateBrickRequest(BaseModel):
    name: Optional[str] = None
    type: Optional[BrickType] = None
    source: Optional[str] = None
    definition: Optional[BrickDefinition] = None
    depends_on: Optional[list[str]] = None
    gates: Optional[list[str]] = None


def _to_brick_schema(model: BrickModel) -> PipelineBrick:
    return PipelineBrick(
        id=model.id,
        name=model.name,
        type=model.type,  # type: ignore
        source=model.source,
        definition=BrickDefinition.model_validate(model.definition_json or {}),
        depends_on=model.depends_on or [],
        gates=model.gates or [],
    )


# ── Bricks ─────────────────────────────────────────────────────────────

@router.get("/api/v1/bricks", response_model=list[PipelineBrick])
async def list_bricks(
    brick_type: Optional[BrickType] = Query(None, alias="type", description="Filter by brick type"),
    db: AsyncSession = Depends(get_db),
) -> list[PipelineBrick]:
    """List all pipeline bricks."""
    stmt = select(BrickModel)
    if brick_type:
        stmt = stmt.where(BrickModel.type == brick_type)
    stmt = stmt.order_by(BrickModel.id)

    res = await db.execute(stmt)
    bricks = res.scalars().all()
    return [_to_brick_schema(b) for b in bricks]


@router.post("/api/v1/bricks", response_model=PipelineBrick, status_code=status.HTTP_201_CREATED)
async def create_brick(
    body: PipelineBrick,
    db: AsyncSession = Depends(get_db),
) -> PipelineBrick:
    """Register a new pipeline brick."""
    existing = await db.get(BrickModel, body.id)
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Brick with id '{body.id}' already exists",
        )

    db_brick = BrickModel(
        id=body.id,
        name=body.name,
        type=body.type,
        source=body.source,
        definition_json=body.definition.model_dump(),
        depends_on=body.depends_on,
        gates=body.gates,
    )
    db.add(db_brick)
    await db.commit()
    await db.refresh(db_brick)
    return _to_brick_schema(db_brick)


@router.get("/api/v1/bricks/{brick_id}", response_model=PipelineBrick)
async def get_brick(
    brick_id: str,
    db: AsyncSession = Depends(get_db),
) -> PipelineBrick:
    """Get brick details by ID."""
    b = await db.get(BrickModel, brick_id)
    if b is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Brick '{brick_id}' not found",
        )
    return _to_brick_schema(b)


@router.put("/api/v1/bricks/{brick_id}", response_model=PipelineBrick)
async def update_brick(
    brick_id: str,
    body: UpdateBrickRequest,
    db: AsyncSession = Depends(get_db),
) -> PipelineBrick:
    """Update pipeline brick."""
    b = await db.get(BrickModel, brick_id)
    if b is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Brick '{brick_id}' not found",
        )

    if body.name is not None:
        b.name = body.name
    if body.type is not None:
        b.type = body.type
    if body.source is not None:
        b.source = body.source
    if body.definition is not None:
        b.definition_json = body.definition.model_dump()
    if body.depends_on is not None:
        b.depends_on = body.depends_on
    if body.gates is not None:
        b.gates = body.gates

    await db.commit()
    await db.refresh(b)
    return _to_brick_schema(b)


@router.delete("/api/v1/bricks/{brick_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_brick(
    brick_id: str,
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete pipeline brick."""
    b = await db.get(BrickModel, brick_id)
    if b is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Brick '{brick_id}' not found",
        )
    await db.delete(b)
    await db.commit()


# ── Plans ──────────────────────────────────────────────────────────────

@router.get("/api/v1/plans", response_model=list[PipelinePlanSchema])
async def list_plans(
    app_id: Optional[str] = Query(None, description="Filter by app ID"),
    db: AsyncSession = Depends(get_db),
) -> list[PipelinePlanSchema]:
    """List compiled pipeline plans."""
    stmt = select(PlanModel).options(selectinload(PlanModel.bricks))
    if app_id:
        stmt = stmt.where(PlanModel.app_id == app_id)
    stmt = stmt.order_by(PlanModel.compiled_at.desc())

    res = await db.execute(stmt)
    plans = res.scalars().all()
    return [
        PipelinePlanSchema(
            id=p.id,
            app_id=p.app_id,
            level=p.level,
            scope_id=p.scope_id,
            compiled_at=p.compiled_at,
            compiled_hash=p.compiled_hash,
            brick_ids=[pb.brick_id for pb in p.bricks],
        )
        for p in plans
    ]


@router.post("/api/v1/plans", response_model=PipelinePlanSchema, status_code=status.HTTP_201_CREATED)
async def create_plan(
    body: CreatePlanRequest,
    db: AsyncSession = Depends(get_db),
) -> PipelinePlanSchema:
    """Create a pipeline plan with explicit brick associations."""
    app = await db.get(ApplicationModel, body.app_id)
    if app is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Application '{body.app_id}' not found",
        )

    existing = await db.get(PlanModel, body.id)
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Plan '{body.id}' already exists",
        )

    scope_id = body.scope_id or body.app_id
    compiled_hash = body.compiled_hash or uuid.uuid4().hex

    plan = PlanModel(
        id=body.id,
        app_id=body.app_id,
        level=body.level,
        scope_id=scope_id,
        compiled_at=datetime.datetime.utcnow(),
        compiled_hash=compiled_hash,
    )
    db.add(plan)
    await db.flush()

    for idx, brick_id in enumerate(body.brick_ids):
        pb = PlanBrickModel(
            id=f"pb-{uuid.uuid4().hex[:12]}",
            plan_id=body.id,
            brick_id=brick_id,
            sort_order=idx,
        )
        db.add(pb)

    await db.commit()

    return PipelinePlanSchema(
        id=plan.id,
        app_id=plan.app_id,
        level=plan.level,
        scope_id=plan.scope_id,
        compiled_at=plan.compiled_at,
        compiled_hash=plan.compiled_hash,
        brick_ids=body.brick_ids,
    )


@router.post("/api/v1/plans/compile", response_model=PipelinePlanSchema, status_code=status.HTTP_201_CREATED)
async def compile_plan(
    body: CompilePlanRequest,
    db: AsyncSession = Depends(get_db),
) -> PipelinePlanSchema:
    """Compile application pipeline plan using PlanCompiler and persist batches."""
    app = await db.get(ApplicationModel, body.app_id)
    if app is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Application '{body.app_id}' not found",
        )

    existing = await db.get(PlanModel, body.plan_id)
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Plan '{body.plan_id}' already exists",
        )

    # Fetch bricks
    stmt = select(BrickModel).where(BrickModel.id.in_(body.brick_ids))
    res = await db.execute(stmt)
    db_bricks = res.scalars().all()
    if len(db_bricks) != len(body.brick_ids):
        found_ids = {b.id for b in db_bricks}
        missing = set(body.brick_ids) - found_ids
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Bricks not found: {sorted(missing)}",
        )

    brick_schemas = [_to_brick_schema(b) for b in db_bricks]

    compiler = PlanCompiler()
    cycles = compiler.detect_cycles(brick_schemas)
    if cycles:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cycle detected in brick dependencies: {cycles}",
        )

    batches = compiler.compile(brick_schemas, plan_id=body.plan_id)
    compiled_hash = compiler.compile_hash(batches, brick_schemas)

    plan = PlanModel(
        id=body.plan_id,
        app_id=body.app_id,
        level=body.level,
        scope_id=body.app_id,
        compiled_at=datetime.datetime.utcnow(),
        compiled_hash=compiled_hash,
    )
    db.add(plan)
    await db.flush()

    # Add plan bricks
    for idx, bid in enumerate(body.brick_ids):
        pb = PlanBrickModel(
            id=f"pb-{uuid.uuid4().hex[:12]}",
            plan_id=body.plan_id,
            brick_id=bid,
            sort_order=idx,
        )
        db.add(pb)

    # Add generated batches to DB
    for b in batches:
        db_batch = BatchModel(
            id=b.id,
            plan_id=body.plan_id,
            type=b.type,
            status=b.status,
            bricks_refs=b.bricks,
            artifacts=b.artifacts,
            evidence_refs=b.evidence,
        )
        db.add(db_batch)

    # Update app pipeline_plan_id
    app.pipeline_plan_id = body.plan_id

    await db.commit()

    return PipelinePlanSchema(
        id=plan.id,
        app_id=plan.app_id,
        level=plan.level,
        scope_id=plan.scope_id,
        compiled_at=plan.compiled_at,
        compiled_hash=plan.compiled_hash,
        brick_ids=body.brick_ids,
    )


@router.get("/api/v1/plans/{plan_id}", response_model=PipelinePlanSchema)
async def get_plan(
    plan_id: str,
    db: AsyncSession = Depends(get_db),
) -> PipelinePlanSchema:
    """Get pipeline plan details."""
    stmt = (
        select(PlanModel)
        .where(PlanModel.id == plan_id)
        .options(selectinload(PlanModel.bricks))
    )
    res = await db.execute(stmt)
    plan = res.scalar_one_or_none()
    if plan is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Plan '{plan_id}' not found",
        )

    # Sort bricks by sort_order
    sorted_bricks = sorted(plan.bricks, key=lambda pb: pb.sort_order)
    return PipelinePlanSchema(
        id=plan.id,
        app_id=plan.app_id,
        level=plan.level,
        scope_id=plan.scope_id,
        compiled_at=plan.compiled_at,
        compiled_hash=plan.compiled_hash,
        brick_ids=[pb.brick_id for pb in sorted_bricks],
    )


@router.delete("/api/v1/plans/{plan_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_plan(
    plan_id: str,
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete a pipeline plan."""
    plan = await db.get(PlanModel, plan_id)
    if plan is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Plan '{plan_id}' not found",
        )
    # Delete associated plan_bricks
    await db.execute(delete(PlanBrickModel).where(PlanBrickModel.plan_id == plan_id))
    await db.delete(plan)
    await db.commit()
