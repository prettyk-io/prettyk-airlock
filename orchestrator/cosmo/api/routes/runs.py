"""Cosmoport 2.0 — Runs & Batches REST API endpoints.

Lifecycle management for pipeline Runs and execution Batches.
"""
from __future__ import annotations

import datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select, delete
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.cosmo.api.deps import get_db, require_capability
from orchestrator.cosmo.api.domain_guard import require_domain, verify_ownership
from orchestrator.cosmo.domain.rbac import Action
from orchestrator.cosmo.db.models import (
    Run as RunModel,
    Batch as BatchModel,
    PipelinePlan as PlanModel,
    Domain as DomainModel,
    Gate as GateModel,
)
from orchestrator.cosmo.domain.run_model import Run, Batch, RunTrigger, BatchStatus, RunStatus

router = APIRouter(tags=["runs"])


# ── Schemas ────────────────────────────────────────────────────────────

class CreateRunRequest(BaseModel):
    id: str = Field(..., min_length=1)
    plan_id: str = Field(..., min_length=1)
    trigger: RunTrigger = Field(default="manual")
    initiator_user_id: str = Field(default="system")
    initiator_role: str = Field(default="developer")
    domain_id: str = Field(..., min_length=1)


class UpdateRunStatusRequest(BaseModel):
    status: RunStatus = Field(..., description="draft|pending|queued|running|succeeded|failed|blocked|cancelled")


class UpdateBatchStatusRequest(BaseModel):
    status: BatchStatus


class CreateBatchRequest(BaseModel):
    id: str = Field(..., min_length=1)
    plan_id: str = Field(..., min_length=1)
    type: str = Field(..., min_length=1)
    status: BatchStatus = Field(default="pending")
    bricks: list[str] = Field(default_factory=list)
    artifacts: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)


def _to_batch_schema(b: BatchModel) -> Batch:
    return Batch(
        id=b.id,
        plan_id=b.plan_id,
        type=b.type,
        status=b.status,  # type: ignore
        bricks=b.bricks_refs or [],
        artifacts=b.artifacts or [],
        evidence=b.evidence_refs or [],
    )


def _to_run_schema(
    r: RunModel,
    batches: list[BatchModel] | None = None,
    gates: list[GateModel] | None = None,
) -> Run:
    batch_schemas = [_to_batch_schema(b) for b in (batches or [])]
    gate_ids = [g.id for g in (gates or [])]
    return Run(
        id=r.id,
        plan_id=r.plan_id,
        trigger=r.trigger,  # type: ignore
        initiator=r.initiator_user_id or "system",
        domain_id=r.domain_id,
        status=r.status,  # type: ignore
        started_at=r.started_at,
        finished_at=r.finished_at,
        created_at=r.created_at,
        batches=batch_schemas,
        gates=gate_ids,
        findings=r.findings_refs or [],
        evidence_ledger_ref=None,
    )


# ── Runs ───────────────────────────────────────────────────────────────

@router.get("/api/v1/runs", response_model=list[Run])
async def list_runs(
    domain_id: Optional[str] = Query(None, description="Filter by domain ID"),
    plan_id: Optional[str] = Query(None, description="Filter by plan ID"),
    run_status: Optional[str] = Query(None, alias="status", description="Filter by status"),
    caller_domain: str = Depends(require_domain),
    db: AsyncSession = Depends(get_db),
) -> list[Run]:
    """List pipeline runs (scoped to caller's domain)."""
    stmt = select(RunModel)
    # COS-061: filter by caller's domain (override explicit param for isolation)
    stmt = stmt.where(RunModel.domain_id == caller_domain)
    if plan_id:
        stmt = stmt.where(RunModel.plan_id == plan_id)
    if run_status:
        stmt = stmt.where(RunModel.status == run_status)
    stmt = stmt.order_by(RunModel.created_at.desc())

    res = await db.execute(stmt)
    runs = res.scalars().all()
    return [_to_run_schema(r) for r in runs]


@router.post("/api/v1/runs", response_model=Run, status_code=status.HTTP_201_CREATED)
async def create_run(
    body: CreateRunRequest,
    db: AsyncSession = Depends(get_db),
    _guard: None = Depends(require_capability(Action.SCAN_START)),
) -> Run:
    """Create and trigger a new pipeline run."""
    # Check domain exists
    domain = await db.get(DomainModel, body.domain_id)
    if domain is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Domain '{body.domain_id}' not found",
        )

    # Check plan exists
    plan = await db.get(PlanModel, body.plan_id)
    if plan is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Plan '{body.plan_id}' not found",
        )

    existing = await db.get(RunModel, body.id)
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Run '{body.id}' already exists",
        )

    run = RunModel(
        id=body.id,
        plan_id=body.plan_id,
        trigger=body.trigger,
        initiator_user_id=body.initiator_user_id,
        initiator_role=body.initiator_role,
        domain_id=body.domain_id,
        status="pending",
        findings_refs=[],
        created_at=datetime.datetime.utcnow(),
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)

    # Fetch associated batches and gates for the plan
    batch_stmt = select(BatchModel).where(BatchModel.plan_id == body.plan_id)
    batch_res = await db.execute(batch_stmt)
    batches = batch_res.scalars().all()

    gate_stmt = select(GateModel).where(GateModel.plan_id == body.plan_id)
    gate_res = await db.execute(gate_stmt)
    gates = gate_res.scalars().all()

    return _to_run_schema(run, list(batches), list(gates))


@router.get("/api/v1/runs/{run_id}", response_model=Run)
async def get_run(
    run_id: str,
    caller_domain: str = Depends(require_domain),
    db: AsyncSession = Depends(get_db),
) -> Run:
    """Get run details by ID with batches and gates."""
    run = await db.get(RunModel, run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Run '{run_id}' not found")
    # COS-061: verify domain ownership
    verify_ownership(run.domain_id, caller_domain, f"Run '{run_id}'")

    batch_stmt = select(BatchModel).where(BatchModel.plan_id == run.plan_id)
    batch_res = await db.execute(batch_stmt)
    batches = batch_res.scalars().all()

    gate_stmt = select(GateModel).where(GateModel.plan_id == run.plan_id)
    gate_res = await db.execute(gate_stmt)
    gates = gate_res.scalars().all()

    return _to_run_schema(run, list(batches), list(gates))


@router.patch("/api/v1/runs/{run_id}/status", response_model=Run)
async def update_run_status(
    run_id: str,
    body: UpdateRunStatusRequest,
    caller_domain: str = Depends(require_domain),
    db: AsyncSession = Depends(get_db),
) -> Run:
    """Update status of a run."""
    run = await db.get(RunModel, run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Run '{run_id}' not found")
    verify_ownership(run.domain_id, caller_domain, f"Run '{run_id}'")

    run.status = body.status
    if body.status == "running" and run.started_at is None:
        run.started_at = datetime.datetime.utcnow()
    elif body.status in ("succeeded", "failed", "cancelled", "blocked"):
        run.finished_at = datetime.datetime.utcnow()

    await db.commit()
    await db.refresh(run)

    return _to_run_schema(run)


@router.post("/api/v1/runs/{run_id}/cancel", response_model=Run)
async def cancel_run(
    run_id: str,
    db: AsyncSession = Depends(get_db),
    _guard: None = Depends(require_capability(Action.SCAN_STOP)),
) -> Run:
    """Cancel an active run."""
    run = await db.get(RunModel, run_id)
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Run '{run_id}' not found",
        )

    run.status = "cancelled"
    run.finished_at = datetime.datetime.utcnow()
    await db.commit()
    await db.refresh(run)
    return _to_run_schema(run)


# ── Batches ────────────────────────────────────────────────────────────

@router.get("/api/v1/batches", response_model=list[Batch])
async def list_batches(
    plan_id: Optional[str] = Query(None, description="Filter by plan ID"),
    db: AsyncSession = Depends(get_db),
) -> list[Batch]:
    """List execution batches."""
    stmt = select(BatchModel)
    if plan_id:
        stmt = stmt.where(BatchModel.plan_id == plan_id)
    stmt = stmt.order_by(BatchModel.id)

    res = await db.execute(stmt)
    batches = res.scalars().all()
    return [_to_batch_schema(b) for b in batches]


@router.post("/api/v1/batches", response_model=Batch, status_code=status.HTTP_201_CREATED)
async def create_batch(
    body: CreateBatchRequest,
    db: AsyncSession = Depends(get_db),
) -> Batch:
    """Create a batch for a plan."""
    plan = await db.get(PlanModel, body.plan_id)
    if plan is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Plan '{body.plan_id}' not found",
        )

    existing = await db.get(BatchModel, body.id)
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Batch '{body.id}' already exists",
        )

    batch = BatchModel(
        id=body.id,
        plan_id=body.plan_id,
        type=body.type,
        status=body.status,
        bricks_refs=body.bricks,
        artifacts=body.artifacts,
        evidence_refs=body.evidence,
    )
    db.add(batch)
    await db.commit()
    await db.refresh(batch)
    return _to_batch_schema(batch)


@router.get("/api/v1/batches/{batch_id}", response_model=Batch)
async def get_batch(
    batch_id: str,
    db: AsyncSession = Depends(get_db),
) -> Batch:
    """Get batch details."""
    b = await db.get(BatchModel, batch_id)
    if b is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Batch '{batch_id}' not found",
        )
    return _to_batch_schema(b)


@router.patch("/api/v1/batches/{batch_id}/status", response_model=Batch)
async def update_batch_status(
    batch_id: str,
    body: UpdateBatchStatusRequest,
    db: AsyncSession = Depends(get_db),
) -> Batch:
    """Update execution status of a batch."""
    b = await db.get(BatchModel, batch_id)
    if b is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Batch '{batch_id}' not found",
        )

    b.status = body.status
    if body.status == "running" and b.started_at is None:
        b.started_at = datetime.datetime.utcnow()
    elif body.status in ("passed", "failed", "blocked"):
        b.finished_at = datetime.datetime.utcnow()

    await db.commit()
    await db.refresh(b)
    return _to_batch_schema(b)
