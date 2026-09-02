"""Cosmoport 2.0 — Security Gates REST API endpoints.

Policy definition and decision evaluation for pipeline Gates.

COS-096: Gate decision restricted to admin_sec / admin_abnormal roles (RBAC stub).
"""
from __future__ import annotations

import datetime
from typing import Optional
from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.cosmo.api.deps import get_db, require_capability, require_principal
from orchestrator.cosmo.api.domain_guard import resolve_caller_domain, verify_ownership
from orchestrator.cosmo.domain.rbac import Action, PrincipalContext
from orchestrator.cosmo.db.models import (
    Gate as GateModel,
    PipelinePlan as PlanModel,
)
from orchestrator.cosmo.domain.gate_model import (
    Gate,
    GatePolicy,
    GateType,
    GateDecision,
)

router = APIRouter(prefix="/api/v1/gates", tags=["gates"])


# ── Schemas ────────────────────────────────────────────────────────────

class CreateGateRequest(BaseModel):
    id: str = Field(..., min_length=1)
    plan_id: str = Field(..., min_length=1)
    type: GateType = Field(default="automatic")
    position: int = Field(default=0, ge=0)
    policy: GatePolicy


class UpdateGateRequest(BaseModel):
    type: Optional[GateType] = None
    position: Optional[int] = Field(default=None, ge=0)
    policy: Optional[GatePolicy] = None


class GateDecisionRequest(BaseModel):
    decision: GateDecision
    decided_by: Optional[str] = None
    signature: Optional[str] = None
    # COS-081: durable trail link — контекст решения (опционально, back-compat)
    run_id: Optional[str] = None
    batch_id: Optional[str] = None
    evidence_ids: Optional[list[str]] = None


def _to_gate_schema(g: GateModel) -> Gate:
    return Gate(
        id=g.id,
        type=g.type,  # type: ignore
        position=g.position,
        policy=GatePolicy.model_validate(g.policy_json or {"rules": []}),
        decision=g.decision,  # type: ignore
        decided_by=g.decided_by,
        signature=g.signature,
        decided_at=g.decided_at,
    )


# ── Routes ─────────────────────────────────────────────────────────────

async def _resolve_plan_domain(db: AsyncSession, plan: PlanModel) -> str | None:
    """COS-068: домен плана по цепочке plan.app_id → Application.domain_id.

    PipelinePlan не имеет собственной колонки domain_id (COS-067).
    """
    if plan is not None and getattr(plan, "app_id", None):
        from orchestrator.cosmo.db.models import Application as ApplicationModel
        app = await db.get(ApplicationModel, plan.app_id)
        return app.domain_id if app is not None else None
    return None


@router.get("", response_model=list[Gate])
async def list_gates(
    plan_id: Optional[str] = Query(None, description="Filter by plan ID"),
    db: AsyncSession = Depends(get_db),
    principal: PrincipalContext = Depends(require_principal()),
) -> list[Gate]:
    """List security gates.

    COS-068: authentication required (было — анонимный листинг конфигурации
    security-ворот).
    """
    stmt = select(GateModel)
    if plan_id:
        stmt = stmt.where(GateModel.plan_id == plan_id)
    stmt = stmt.order_by(GateModel.position)

    res = await db.execute(stmt)
    gates = res.scalars().all()
    return [_to_gate_schema(g) for g in gates]


@router.post("", response_model=Gate, status_code=status.HTTP_201_CREATED)
async def create_gate(
    body: CreateGateRequest,
    caller_domain: str | None = Header(None, alias="X-Cosmo-Domain"),
    db: AsyncSession = Depends(get_db),
    principal: PrincipalContext = Depends(
        require_capability(Action.PIPELINE_CONFIGURE, domain_binding="identity")
    ),
) -> Gate:
    """Create a security gate for a plan.

    CLN-007: Separation of Duties — автор релиза не может создавать гейт к своему же плану.
    COS-068/COS-083: PIPELINE_CONFIGURE capability (было — любой аутентифицированный);
    не-админ конфигурирует гейты только для планов своего домена (единый резолв).
    """
    plan = await db.get(PlanModel, body.plan_id)
    if plan is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Plan '{body.plan_id}' not found",
        )

    # COS-068/COS-083: не-админ создаёт гейт только для плана своего домена
    if not principal.is_system_admin:
        plan_domain = await _resolve_plan_domain(db, plan)
        verify_ownership(
            plan_domain,
            resolve_caller_domain(principal, caller_domain),
            f"Plan '{body.plan_id}'",
        )

    # CLN-007: SoD — release author cannot create gates for own release plan
    if principal and principal.user_id and principal.user_id != "system":
        from orchestrator.cosmo.db.models import Release as ReleaseModel, Run as RunModel

        release_stmt = select(ReleaseModel).where(ReleaseModel.plan_id == body.plan_id)
        release_res = await db.execute(release_stmt)
        releases = release_res.scalars().all()

        for rel in releases:
            run_ids = rel.run_ids or []
            if run_ids:
                run_stmt = select(RunModel).where(RunModel.id.in_(run_ids))
                run_res = await db.execute(run_stmt)
                runs = run_res.scalars().all()
                for run in runs:
                    initiator = run.initiator_user_id or "system"
                    if initiator == principal.user_id:
                        raise HTTPException(
                            status_code=status.HTTP_409_CONFLICT,
                            detail=f"SoD violation: release author '{initiator}' cannot create gates for own release plan '{body.plan_id}'. Release: {rel.id}, Run: {run.id}",
                        )

    existing = await db.get(GateModel, body.id)
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Gate '{body.id}' already exists",
        )

    gate = GateModel(
        id=body.id,
        plan_id=body.plan_id,
        type=body.type,
        position=body.position,
        policy_json=body.policy.model_dump(),
    )
    db.add(gate)
    await db.commit()
    await db.refresh(gate)
    return _to_gate_schema(gate)


@router.get("/{gate_id}", response_model=Gate)
async def get_gate(
    gate_id: str,
    db: AsyncSession = Depends(get_db),
    principal: PrincipalContext = Depends(require_principal()),
) -> Gate:
    """Get gate details.

    COS-068: authentication required.
    """
    gate = await db.get(GateModel, gate_id)
    if gate is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Gate '{gate_id}' not found",
        )
    return _to_gate_schema(gate)


@router.put("/{gate_id}", response_model=Gate)
async def update_gate(
    gate_id: str,
    body: UpdateGateRequest,
    caller_domain: str | None = Header(None, alias="X-Cosmo-Domain"),
    db: AsyncSession = Depends(get_db),
    principal: PrincipalContext = Depends(
        require_capability(Action.PIPELINE_CONFIGURE, domain_binding="identity")
    ),
) -> Gate:
    """Update gate policy or configuration.

    COS-068/COS-083: PIPELINE_CONFIGURE + ownership (не-админ — только свой
    домен, единый резолв).
    """
    gate = await db.get(GateModel, gate_id)
    if gate is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Gate '{gate_id}' not found",
        )

    # COS-068/COS-083: не-админ изменяет гейт только в своём домене
    if not principal.is_system_admin:
        plan = await db.get(PlanModel, gate.plan_id) if gate.plan_id else None
        plan_domain = await _resolve_plan_domain(db, plan)
        verify_ownership(
            plan_domain,
            resolve_caller_domain(principal, caller_domain),
            f"Gate '{gate_id}'",
        )

    if body.type is not None:
        gate.type = body.type
    if body.position is not None:
        gate.position = body.position
    if body.policy is not None:
        gate.policy_json = body.policy.model_dump()

    await db.commit()
    await db.refresh(gate)
    return _to_gate_schema(gate)


@router.get("/{gate_id}/decisions", response_model=list[dict])
async def gate_decision_trail(
    gate_id: str,
    run_id: Optional[str] = Query(None, description="Filter by run ID"),
    db: AsyncSession = Depends(get_db),
    principal: PrincipalContext = Depends(require_principal()),
) -> list[dict]:
    """COS-081: durable decision trail по gate (новые первыми).

    История переживает рестарт процесса (PG), read-path — по gate_id,
    опционально в контексте одного run. Authentication required (COS-068).
    """
    gate = await db.get(GateModel, gate_id)
    if gate is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Gate '{gate_id}' not found",
        )
    from orchestrator.cosmo.db.gate_trail_repo import trail_for_gate
    return await trail_for_gate(db, gate_id, run_id=run_id)


@router.get("/trail/runs/{run_id}", response_model=list[dict])
async def run_decision_trail(
    run_id: str,
    db: AsyncSession = Depends(get_db),
    principal: PrincipalContext = Depends(require_principal()),
) -> list[dict]:
    """COS-081: trail всех gate-решений прогона (хронологически).

    Acceptance read-path: история по run_id переживает рестарт процесса.
    """
    from orchestrator.cosmo.db.gate_trail_repo import trail_for_run
    return await trail_for_run(db, run_id)


@router.post("/{gate_id}/decision", response_model=Gate)
async def record_gate_decision(
    gate_id: str,
    body: GateDecisionRequest,
    caller_domain: str | None = Header(None, alias="X-Cosmo-Domain"),
    db: AsyncSession = Depends(get_db),
    principal: PrincipalContext = Depends(require_capability(Action.GATE_DECIDE, domain_binding="identity")),
) -> Gate:
    """Record a manual or automated gate decision."""
    gate = await db.get(GateModel, gate_id)
    if gate is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Gate '{gate_id}' not found",
        )

    # COS-067/COS-083: domain binding — ownership по единому резолву для не-админа.
    # Gate не имеет собственной колонки domain_id: домен резолвится по цепочке
    # gate.plan_id → PipelinePlan.app_id → Application.domain_id.
    if not principal.is_system_admin:
        from orchestrator.cosmo.db.models import Application as ApplicationModel
        gate_domain: str | None = None
        plan = await db.get(PlanModel, gate.plan_id)
        if plan is not None and getattr(plan, "app_id", None):
            app = await db.get(ApplicationModel, plan.app_id)
            gate_domain = app.domain_id if app is not None else None
        verify_ownership(
            gate_domain,
            resolve_caller_domain(principal, caller_domain),
            f"Gate '{gate_id}'",
        )

    if gate.type == "manual" and not body.decided_by:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Manual gate decision requires 'decided_by'",
        )

    if gate.type == "automatic" and body.decision == "manual_required":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Automatic gate cannot have 'manual_required' decision",
        )

    # SAN-008 / CLN-007: Separation of Duties — gate decider cannot be the release initiator
    principal_id = principal.user_id
    decider = body.decided_by or principal_id
    if decider and gate.plan_id:
        from orchestrator.cosmo.db.models import Release as ReleaseModel, Run as RunModel
        release_stmt = select(ReleaseModel).where(ReleaseModel.plan_id == gate.plan_id)
        release_res = await db.execute(release_stmt)
        releases = release_res.scalars().all()

        for rel in releases:
            rel_author = getattr(rel, "initiator_user_id", None)
            if rel_author and (rel_author == decider or (principal_id and rel_author == principal_id)):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        f"SoD violation: release author '{rel_author}' "
                        f"cannot approve own gate decision for gate '{gate_id}'. "
                        f"Release: {rel.id}"
                    ),
                )
            run_ids = rel.run_ids or []
            if run_ids:
                run_stmt = select(RunModel).where(RunModel.id.in_(run_ids))
                run_res = await db.execute(run_stmt)
                runs = run_res.scalars().all()
                for run in runs:
                    initiator = run.initiator_user_id or "system"
                    if initiator == decider or (principal_id and initiator == principal_id):
                        raise HTTPException(
                            status_code=status.HTTP_409_CONFLICT,
                            detail=(
                                f"SoD violation: release author '{initiator}' "
                                f"cannot approve own gate decision for gate '{gate_id}'. "
                                f"Release: {rel.id}, Run: {run.id}"
                            ),
                        )

    gate.decision = body.decision
    gate.decided_by = body.decided_by
    gate.signature = body.signature
    gate.decided_at = datetime.datetime.utcnow()

    # COS-081: durable gate decision trail — append В ТОЙ ЖЕ транзакции,
    # решение фиксируется в PG до возврата API-ответа (atomic write-before-
    # response). policy_snapshot — политика gate на момент решения.
    from orchestrator.cosmo.db.gate_trail_repo import append_gate_decision
    await append_gate_decision(
        db,
        gate_id=gate.id,
        plan_id=gate.plan_id or "",
        decision=body.decision,
        decided_by=body.decided_by or "",
        initiator=principal.user_id or "",
        signature=body.signature,
        policy_snapshot=dict(gate.policy_json or {}),
        run_id=body.run_id,
        batch_id=body.batch_id,
        evidence_ids=body.evidence_ids,
        decided_at=gate.decided_at,
    )

    await db.commit()
    await db.refresh(gate)

    # COS-055: durable notification о решении gate (non-blocking)
    try:
        from orchestrator.cosmo.notifications.integration import notify_gate_decision_safe
        notify_gate_decision_safe(
            gate_id=gate.id,
            plan_id=gate.plan_id or "",
            decision=body.decision,
            decided_by=body.decided_by or "",
        )
    except Exception:
        pass

    return _to_gate_schema(gate)


@router.delete("/{gate_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_gate(
    gate_id: str,
    caller_domain: str | None = Header(None, alias="X-Cosmo-Domain"),
    db: AsyncSession = Depends(get_db),
    principal: PrincipalContext = Depends(
        require_capability(Action.PIPELINE_CONFIGURE, domain_binding="identity")
    ),
) -> None:
    """Delete a gate.

    COS-068/COS-083: PIPELINE_CONFIGURE + ownership (не-админ — только свой
    домен, единый резолв).
    """
    gate = await db.get(GateModel, gate_id)
    if gate is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Gate '{gate_id}' not found",
        )

    # COS-068/COS-083: не-админ удаляет гейт только в своём домене
    if not principal.is_system_admin:
        plan = await db.get(PlanModel, gate.plan_id) if gate.plan_id else None
        plan_domain = await _resolve_plan_domain(db, plan)
        verify_ownership(
            plan_domain,
            resolve_caller_domain(principal, caller_domain),
            f"Gate '{gate_id}'",
        )

    await db.delete(gate)
    await db.commit()
