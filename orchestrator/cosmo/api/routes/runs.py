"""Cosmoport 2.0 — Runs & Batches REST API endpoints.

Lifecycle management for pipeline Runs and execution Batches.
"""
from __future__ import annotations

import datetime
from typing import Optional
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select, delete
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.cosmo.api.deps import get_current_principal, get_db, require_capability
from orchestrator.cosmo.api.domain_guard import resolve_caller_domain, verify_ownership
from orchestrator.cosmo.domain.rbac import Action, PrincipalContext
from orchestrator.cosmo.db.models import (
    Run as RunModel,
    Batch as BatchModel,
    PipelinePlan as PlanModel,
    Domain as DomainModel,
    Gate as GateModel,
    Application as ApplicationModel,
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
    # COS-067 UX: заголовок не обязателен — не-админ резолвится по identity
    caller_domain: str | None = Header(None, alias="X-Cosmo-Domain"),
    principal: PrincipalContext = Depends(get_current_principal),
    db: AsyncSession = Depends(get_db),
) -> list[Run]:
    """List pipeline runs (scoped to caller's domain)."""
    stmt = select(RunModel)
    # COS-061 + COS-067: filter by caller's domain; не-админ — по identity
    caller = resolve_caller_domain(principal, caller_domain)
    stmt = stmt.where(RunModel.domain_id == caller)
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
    caller_domain: str | None = Header(None, alias="X-Cosmo-Domain"),
    db: AsyncSession = Depends(get_db),
    principal: PrincipalContext = Depends(require_capability(Action.SCAN_START, domain_binding="identity")),
) -> Run:
    """Create and trigger a new pipeline run."""
    # Check domain exists
    domain = await db.get(DomainModel, body.domain_id)
    if domain is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Domain '{body.domain_id}' not found",
        )

    # COS-091: in-body auth-решение заменено единым резолв-контрактом —
    # не-админ создаёт прогон только в своём (резолвнутом) домене
    if not principal.is_system_admin and body.domain_id != resolve_caller_domain(principal, caller_domain):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"domain_id '{body.domain_id}' does not match authenticated principal domain",
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
    # COS-067 UX: заголовок не обязателен — не-админ резолвится по identity
    caller_domain: str | None = Header(None, alias="X-Cosmo-Domain"),
    principal: PrincipalContext = Depends(get_current_principal),
    db: AsyncSession = Depends(get_db),
) -> Run:
    """Get run details by ID with batches and gates."""
    run = await db.get(RunModel, run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Run '{run_id}' not found")
    # COS-061 + COS-067: verify domain ownership (не-админ — по identity)
    verify_ownership(run.domain_id, resolve_caller_domain(principal, caller_domain), f"Run '{run_id}'")

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
    request: Request,
    caller_domain: str | None = Header(None, alias="X-Cosmo-Domain"),
    principal: PrincipalContext = Depends(require_capability(Action.SCAN_START, domain_binding="identity")),
    db: AsyncSession = Depends(get_db),
) -> Run:
    """Update status of a run.

    COS-091: был write только с principal (гибрид) — добавлен capability
    scan:start (исполнительный план: кто запускает прогоны, тот и ведёт
    статусы). Ghost-404 сохранён.

    COS-097: run → running при включённом ExecutionService триггерит
    submit plan-batch'ей как Woodpecker pipelines (живой цикл из ПУ).
    """
    run = await db.get(RunModel, run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Run '{run_id}' not found")
    # COS-067: verify domain ownership (не-админ — по identity)
    verify_ownership(run.domain_id, resolve_caller_domain(principal, caller_domain), f"Run '{run_id}'")

    run.status = body.status
    if body.status == "running" and run.started_at is None:
        run.started_at = datetime.datetime.utcnow()
    elif body.status in ("succeeded", "failed", "cancelled", "blocked"):
        run.finished_at = datetime.datetime.utcnow()

    await db.commit()
    await db.refresh(run)

    # COS-055: durable notification для значимых переходов (non-blocking)
    try:
        from orchestrator.cosmo.notifications.integration import notify_run_status_safe
        notify_run_status_safe(
            run_id=run.id,
            domain_id=run.domain_id,
            status=body.status,
            plan_id=run.plan_id or "",
            initiator=run.initiator_user_id or "",
        )
    except Exception:
        pass

    # COS-097: run → running → живой Woodpecker-цикл (если включён).
    if body.status == "running":
        exec_service = getattr(request.app.state, "execution_service", None)
        if exec_service is not None:
            try:
                await exec_service.submit_run(run.id)
            except Exception:
                # Submit — fire-and-forget; сбой виден в логах сервиса.
                pass

    return _to_run_schema(run)


@router.post("/api/v1/runs/{run_id}/cancel", response_model=Run)
async def cancel_run(
    run_id: str,
    caller_domain: str | None = Header(None, alias="X-Cosmo-Domain"),
    db: AsyncSession = Depends(get_db),
    principal: PrincipalContext = Depends(require_capability(Action.SCAN_STOP, domain_binding="identity")),
) -> Run:
    """Cancel an active run."""
    run = await db.get(RunModel, run_id)
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Run '{run_id}' not found",
        )

    # COS-067/COS-083: domain binding — ownership по единому резолву для не-админа
    if not principal.is_system_admin:
        verify_ownership(
            run.domain_id,
            resolve_caller_domain(principal, caller_domain),
            f"Run '{run_id}'",
        )

    run.status = "cancelled"
    run.finished_at = datetime.datetime.utcnow()
    await db.commit()
    await db.refresh(run)
    return _to_run_schema(run)


# ── Batches ────────────────────────────────────────────────────────────

async def _batch_domain_map(
    db: AsyncSession, batches: list[BatchModel]
) -> dict[str, str]:
    """COS-091: якорь batch_id → domain_id через batch.plan_id → plan.app_id
    → Application.domain_id (тот же паттерн, что list_plans в COS-086).
    Batch не имеет собственного domain_id — видимость выводится из плана."""
    if not batches:
        return {}
    plan_ids = {b.plan_id for b in batches if b.plan_id}
    if not plan_ids:
        return {}
    plan_res = await db.execute(
        select(PlanModel.id, PlanModel.app_id).where(PlanModel.id.in_(plan_ids))
    )
    plan_app = {row[0]: row[1] for row in plan_res.all()}
    app_ids = {app_id for app_id in plan_app.values() if app_id}
    app_domain: dict[str, str] = {}
    if app_ids:
        app_res = await db.execute(
            select(ApplicationModel.id, ApplicationModel.domain_id).where(
                ApplicationModel.id.in_(app_ids)
            )
        )
        app_domain = {row[0]: (row[1] or "") for row in app_res.all()}
    return {
        b.id: app_domain.get(plan_app.get(b.plan_id, ""), "")
        for b in batches
    }


async def _batch_caller_domain(
    db: AsyncSession, batch: BatchModel
) -> str:
    """Резолв домена одного batch (для ghost-404)."""
    mapping = await _batch_domain_map(db, [batch])
    return mapping.get(batch.id, "")


@router.get("/api/v1/batches", response_model=list[Batch])
async def list_batches(
    plan_id: Optional[str] = Query(None, description="Filter by plan ID"),
    caller_domain: str | None = Header(None, alias="X-Cosmo-Domain"),
    principal: PrincipalContext = Depends(get_current_principal),
    db: AsyncSession = Depends(get_db),
) -> list[Batch]:
    """List execution batches (COS-091: был анонимным — require_principal +
    доменный scoping через план, не-админ видит только свой домен)."""
    stmt = select(BatchModel)
    if plan_id:
        stmt = stmt.where(BatchModel.plan_id == plan_id)
    stmt = stmt.order_by(BatchModel.id)

    res = await db.execute(stmt)
    batches = list(res.scalars().all())

    if not principal.is_system_admin and batches:
        caller = resolve_caller_domain(principal, caller_domain)
        dom_map = await _batch_domain_map(db, batches)
        batches = [b for b in batches if dom_map.get(b.id, "") == caller]

    return [_to_batch_schema(b) for b in batches]


@router.post("/api/v1/batches", response_model=Batch, status_code=status.HTTP_201_CREATED)
async def create_batch(
    body: CreateBatchRequest,
    caller_domain: str | None = Header(None, alias="X-Cosmo-Domain"),
    db: AsyncSession = Depends(get_db),
    # COS-091: было анонимно — guard pass 4 (scan:start — исполнительный план)
    principal: PrincipalContext = Depends(require_capability(Action.SCAN_START, domain_binding="identity")),
) -> Batch:
    """Create a batch for a plan."""
    plan = await db.get(PlanModel, body.plan_id)
    if plan is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Plan '{body.plan_id}' not found",
        )

    # COS-091: ghost-404 по якорю план → приложение → домен для не-админа
    if not principal.is_system_admin:
        app = await db.get(ApplicationModel, plan.app_id) if plan.app_id else None
        verify_ownership(
            app.domain_id if app else "",
            resolve_caller_domain(principal, caller_domain),
            f"Plan '{body.plan_id}'",
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
    caller_domain: str | None = Header(None, alias="X-Cosmo-Domain"),
    principal: PrincipalContext = Depends(get_current_principal),
    db: AsyncSession = Depends(get_db),
) -> Batch:
    """Get batch details (COS-091: был анонимным — require_principal +
    ghost-404 для чужого домена)."""
    b = await db.get(BatchModel, batch_id)
    if b is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Batch '{batch_id}' not found",
        )
    # COS-091: ghost-404 по якорю план → приложение → домен для не-админа
    if not principal.is_system_admin:
        verify_ownership(
            await _batch_caller_domain(db, b),
            resolve_caller_domain(principal, caller_domain),
            f"Batch '{batch_id}'",
        )
    return _to_batch_schema(b)


@router.patch("/api/v1/batches/{batch_id}/status", response_model=Batch)
async def update_batch_status(
    batch_id: str,
    body: UpdateBatchStatusRequest,
    caller_domain: str | None = Header(None, alias="X-Cosmo-Domain"),
    db: AsyncSession = Depends(get_db),
    # COS-091: было анонимно — guard pass 4 (scan:start — исполнительный план)
    principal: PrincipalContext = Depends(require_capability(Action.SCAN_START, domain_binding="identity")),
) -> Batch:
    """Update execution status of a batch."""
    b = await db.get(BatchModel, batch_id)
    if b is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Batch '{batch_id}' not found",
        )
    # COS-091: ghost-404 по якорю план → приложение → домен для не-админа
    if not principal.is_system_admin:
        verify_ownership(
            await _batch_caller_domain(db, b),
            resolve_caller_domain(principal, caller_domain),
            f"Batch '{batch_id}'",
        )

    b.status = body.status
    if body.status == "running" and b.started_at is None:
        b.started_at = datetime.datetime.utcnow()
    elif body.status in ("passed", "failed", "blocked"):
        b.finished_at = datetime.datetime.utcnow()

    await db.commit()
    await db.refresh(b)

    # COS-055: durable notification о падении batch (non-blocking)
    try:
        from orchestrator.cosmo.notifications.integration import notify_batch_status_safe
        notify_batch_status_safe(
            batch_id=b.id,
            plan_id=b.plan_id or "",
            status=body.status,
        )
    except Exception:
        pass

    return _to_batch_schema(b)
