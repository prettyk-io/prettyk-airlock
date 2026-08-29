"""COS-036/COS-054: Release API routes — создание, review, approval, deploy, transfer.

Endpoints:
  GET    /api/v1/releases               — список релизов
  POST   /api/v1/releases               — создать релиз
  GET    /api/v1/releases/{release_id}  — детали релиза
  POST   /api/v1/releases/{release_id}/submit       — отправить на review
  POST   /api/v1/releases/{release_id}/approve      — утвердить
  POST   /api/v1/releases/{release_id}/reject       — отклонить
  POST   /api/v1/releases/{release_id}/deploy       — начать деплой
  POST   /api/v1/releases/{release_id}/transfer     — межзонный трансфер (COS-054)
"""
from __future__ import annotations

import datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.cosmo.api.deps import get_db
from orchestrator.cosmo.api.domain_guard import require_domain, verify_ownership
from orchestrator.cosmo.db.models import (
    Release as ReleaseModel,
    Run as RunModel,
    Domain as DomainModel,
    PipelinePlan as PlanModel,
)
from orchestrator.cosmo.domain.release_model import (
    Release,
    ReleaseApproval,
    ReleaseStatus,
    ReleaseTrigger,
    TransferRecord,
    ReleaseZone,
    next_zone,
)

try:
    from cosmo.ledger.release_envelope import (
        DigitalReleaseEnvelope,
        ReleaseEnvelopeService,
        seal_envelope,
        verify_envelope,
        verify_envelope_body,
    )
except ImportError:
    from orchestrator.cosmo.ledger.release_envelope import (  # type: ignore
        DigitalReleaseEnvelope,
        ReleaseEnvelopeService,
        seal_envelope,
        verify_envelope,
        verify_envelope_body,
    )

router = APIRouter(prefix="/api/v1/releases", tags=["releases"])


# ── Schemas ────────────────────────────────────────────────────────────

class CreateReleaseRequest(BaseModel):
    id: str = Field(..., min_length=1)
    domain_id: str = Field(..., min_length=1)
    plan_id: str = Field(..., min_length=1)
    run_ids: list[str] = Field(..., min_length=1, description="ID прогонов, входящих в релиз")
    trigger: ReleaseTrigger = Field(default="manual")
    changelog: str = Field(default="")
    version: str = Field(default="")


class ApprovalRequest(BaseModel):
    decided_by: str = Field(default="sec_expert", min_length=1, description="ID оператора")
    comment: str = Field(default="")
    signature: str | None = None


class VerifyEnvelopeResponse(BaseModel):
    """COS-109: результат проверки цифрового конверта."""
    verified: bool
    envelope_id: str | None = None
    release_id: str | None = None
    error: str | None = None


class UpdateReleaseRequest(BaseModel):
    changelog: str | None = None
    version: str | None = None


class TransferRequest(BaseModel):
    """COS-054: запрос на межзонный трансфер."""
    initiated_by: str = Field(..., min_length=1, description="ID оператора")
    comment: str = Field(default="", description="Комментарий к трансферу")


# ── Helpers ────────────────────────────────────────────────────────────

def _to_release_schema(r: ReleaseModel) -> Release:
    return Release(
        id=r.id,
        domain_id=r.domain_id,
        plan_id=r.plan_id,
        run_ids=r.run_ids or [],
        trigger=r.trigger,  # type: ignore
        status=r.status,  # type: ignore
        changelog=r.changelog or "",
        version=r.version or "",
        artifacts=r.artifacts or [],
        approvals=[
            ReleaseApproval.model_validate(a) if isinstance(a, dict) else a
            for a in (r.approvals or [])
        ],
        current_zone=r.current_zone or "zr",  # type: ignore
        transfer_history=[
            TransferRecord.model_validate(t) if isinstance(t, dict) else t
            for t in (r.transfer_history or [])
        ],
    )


# ── Routes ─────────────────────────────────────────────────────────────

@router.get("", response_model=list[Release])
async def list_releases(
    domain_id: str | None = Query(None),
    status_f: str | None = Query(None, alias="status"),
    caller_domain: str = Depends(require_domain),
    db: AsyncSession = Depends(get_db),
) -> list[Release]:
    stmt = select(ReleaseModel).order_by(ReleaseModel.created_at.desc())
    # COS-061: scope to caller's domain
    stmt = stmt.where(ReleaseModel.domain_id == caller_domain)
    if status_f:
        stmt = stmt.where(ReleaseModel.status == status_f)
    res = await db.execute(stmt)
    return [_to_release_schema(r) for r in res.scalars().all()]


@router.post("", response_model=Release, status_code=status.HTTP_201_CREATED)
async def create_release(
    body: CreateReleaseRequest,
    db: AsyncSession = Depends(get_db),
) -> Release:
    domain = await db.get(DomainModel, body.domain_id)
    if domain is None:
        raise HTTPException(404, f"Domain '{body.domain_id}' not found")

    plan = await db.get(PlanModel, body.plan_id)
    if plan is None:
        raise HTTPException(404, f"Plan '{body.plan_id}' not found")

    existing = await db.get(ReleaseModel, body.id)
    if existing:
        raise HTTPException(409, f"Release '{body.id}' already exists")

    # COS-052: batch-validate run_ids одним запросом вместо N+1
    run_stmt = select(RunModel).where(RunModel.id.in_(body.run_ids))
    run_res = await db.execute(run_stmt)
    runs = {r.id: r for r in run_res.scalars().all()}

    for rid in body.run_ids:
        run = runs.get(rid)
        if run is None:
            raise HTTPException(404, f"Run '{rid}' not found")
        if run.plan_id != body.plan_id:
            raise HTTPException(400, f"Run '{rid}' belongs to plan '{run.plan_id}', not '{body.plan_id}'")

    rel = ReleaseModel(
        id=body.id,
        domain_id=body.domain_id,
        plan_id=body.plan_id,
        run_ids=body.run_ids,
        trigger=body.trigger,
        status="draft",
        changelog=body.changelog,
        version=body.version,
        artifacts=[],
        approvals=[],
    )
    db.add(rel)
    await db.commit()
    await db.refresh(rel)
    return _to_release_schema(rel)


@router.get("/{release_id}", response_model=Release)
async def get_release(release_id: str, caller_domain: str = Depends(require_domain), db: AsyncSession = Depends(get_db)) -> Release:
    rel = await db.get(ReleaseModel, release_id)
    if rel is None:
        raise HTTPException(404, f"Release '{release_id}' not found")
    verify_ownership(rel.domain_id, caller_domain, f"Release '{release_id}'")
    return _to_release_schema(rel)


@router.post("/{release_id}/submit", response_model=Release)
async def submit_release(release_id: str, db: AsyncSession = Depends(get_db)) -> Release:
    rel = await db.get(ReleaseModel, release_id)
    if rel is None:
        raise HTTPException(404, f"Release '{release_id}' not found")
    if rel.status != "draft":
        raise HTTPException(400, f"Release not in draft status (current: {rel.status})")
    rel.status = "pending_review"
    await db.commit()
    await db.refresh(rel)
    return _to_release_schema(rel)


@router.post("/{release_id}/approve", response_model=Release)
async def approve_release(
    release_id: str,
    body: ApprovalRequest,
    db: AsyncSession = Depends(get_db),
) -> Release:
    rel = await db.get(ReleaseModel, release_id)
    if rel is None:
        raise HTTPException(404, f"Release '{release_id}' not found")
    if rel.status != "pending_review":
        raise HTTPException(400, f"Release not in pending_review (current: {rel.status})")

    approval = ReleaseApproval(
        decided_by=body.decided_by,
        decision="approved",
        comment=body.comment,
        signature=body.signature,
    )
    approvals = list(rel.approvals or [])
    approvals.append(approval.model_dump())

    rel.status = "approved"
    rel.approvals = approvals
    await db.commit()
    await db.refresh(rel)
    return _to_release_schema(rel)


@router.post("/{release_id}/reject", response_model=Release)
async def reject_release(
    release_id: str,
    body: ApprovalRequest,
    db: AsyncSession = Depends(get_db),
) -> Release:
    rel = await db.get(ReleaseModel, release_id)
    if rel is None:
        raise HTTPException(404, f"Release '{release_id}' not found")
    if rel.status != "pending_review":
        raise HTTPException(400, f"Release not in pending_review (current: {rel.status})")

    approval = ReleaseApproval(
        decided_by=body.decided_by,
        decision="rejected",
        comment=body.comment,
        signature=body.signature,
    )
    approvals = list(rel.approvals or [])
    approvals.append(approval.model_dump())

    rel.status = "rejected"
    rel.approvals = approvals
    await db.commit()
    await db.refresh(rel)
    return _to_release_schema(rel)


@router.post("/{release_id}/deploy", response_model=Release)
async def deploy_release(
    release_id: str,
    db: AsyncSession = Depends(get_db),
) -> Release:
    rel = await db.get(ReleaseModel, release_id)
    if rel is None:
        raise HTTPException(404, f"Release '{release_id}' not found")
    if rel.status != "approved":
        raise HTTPException(400, f"Release must be approved before deploy (current: {rel.status})")
    rel.status = "deploying"
    await db.commit()
    await db.refresh(rel)
    return _to_release_schema(rel)


@router.delete("/{release_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_release(release_id: str, db: AsyncSession = Depends(get_db)) -> None:
    rel = await db.get(ReleaseModel, release_id)
    if rel is None:
        raise HTTPException(404, f"Release '{release_id}' not found")
    await db.delete(rel)
    await db.commit()


# ═══════════════════════════════════════════════════════════════════════
# COS-054: Межзонный трансфер
# ═══════════════════════════════════════════════════════════════════════

@router.post("/{release_id}/transfer", response_model=Release)
async def transfer_release(
    release_id: str,
    body: TransferRequest,
    db: AsyncSession = Depends(get_db),
) -> Release:
    """COS-054: трансфер релиза в следующую зону (ЗР→ЗТ→ЗПЭ).

    Требования:
      - Релиз должен быть в статусе deployed
      - Все gates релиза должны быть пройдены (decision=pass)
      - Зоны идут строго по порядку: ЗР → ЗТ → ЗПЭ
      - ЗПЭ — конечная зона, дальше трансфер невозможен
      - Audit log: TransferRecord фиксируется в transfer_history
    """
    from orchestrator.cosmo.db.models import Gate as GateModel

    rel = await db.get(ReleaseModel, release_id)
    if rel is None:
        raise HTTPException(404, f"Release '{release_id}' not found")

    # 1. Статус должен быть deployed
    if rel.status != "deployed":
        raise HTTPException(
            400,
            f"Release must be deployed before transfer (current: {rel.status})",
        )

    # 2. Все gates должны быть pass
    gate_stmt = select(GateModel).where(GateModel.plan_id == rel.plan_id)
    gate_res = await db.execute(gate_stmt)
    gates = gate_res.scalars().all()

    blocked_gates = [g for g in gates if g.decision != "pass" and g.decision is not None]
    pending_gates = [g for g in gates if g.decision is None]

    if blocked_gates:
        gate_ids = [g.id for g in blocked_gates]
        raise HTTPException(
            400,
            f"Gates not passed: {gate_ids}. All gates must have decision='pass' before transfer.",
        )

    if pending_gates:
        gate_ids = [g.id for g in pending_gates]
        raise HTTPException(
            400,
            f"Gates pending decision: {gate_ids}. All gates must be evaluated before transfer.",
        )

    # 3. Определяем следующую зону
    current = rel.current_zone or "zr"
    target = next_zone(current)  # type: ignore
    if target is None:
        raise HTTPException(
            400,
            f"Release already in final zone ({current}). No further transfer possible.",
        )

    # 4. Создаём TransferRecord
    transfer = TransferRecord(
        from_zone=current,  # type: ignore
        to_zone=target,
        initiated_by=body.initiated_by,
        gate_check_passed=len(blocked_gates) == 0 and len(pending_gates) == 0,
        comment=body.comment,
    )

    # 5. Обновляем release
    history = list(rel.transfer_history or [])
    history.append(transfer.model_dump())
    rel.transfer_history = history
    rel.current_zone = target

    await db.commit()
    await db.refresh(rel)

    # COS-065: нотификация о трансфере
    _try_notify_transfer(rel, current, target, body.initiated_by)

    return _to_release_schema(rel)


# ── COS-109: Digital Release Envelope Endpoints ────────────────────────

@router.post("/envelope/verify", response_model=VerifyEnvelopeResponse)
async def verify_release_envelope(
    body: dict,
) -> VerifyEnvelopeResponse:
    """COS-109: Проверить цифровую подпись и целостность конверта релиза."""
    is_valid = verify_envelope_body(body)
    rel_id = body.get("release_id") or body.get("envelope_id")
    return VerifyEnvelopeResponse(
        verified=is_valid,
        envelope_id=rel_id,
        release_id=rel_id,
        error=None if is_valid else "Envelope signature verification failed or data corrupted",
    )


@router.get("/{release_id}/envelope")
async def get_release_envelope(
    release_id: str,
    signer: str = Query("sec_officer", description="ID оператора/офицера ИБ для подписи"),
    caller_domain: str = Depends(require_domain),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """COS-109: Выгрузить подписанный криптографический цифровой конверт релиза."""
    rel = await db.get(ReleaseModel, release_id)
    if rel is None:
        raise HTTPException(404, f"Release '{release_id}' not found")
    verify_ownership(rel.domain_id, caller_domain, f"Release '{release_id}'")

    current_z = rel.current_zone or "zr"
    target_z = next_zone(current_z) or current_z

    envelope = seal_envelope(
        release_id=rel.id,
        signer=signer,
        version=rel.version or "1.0.0",
        domain_id=rel.domain_id,
        source_zone=current_z,  # type: ignore
        target_zone=target_z,   # type: ignore
        run_ids=rel.run_ids or [],
        changelog=rel.changelog or "",
        approvals_count=len(rel.approvals or []),
        transfer_history_count=len(rel.transfer_history or []),
    )
    return envelope.to_dict()


def _try_notify_transfer(rel: ReleaseModel, from_zone: str, to_zone: str, initiated_by: str) -> None:
    """COS-065: фоновая нотификация о трансфере (не блокирует ответ)."""
    try:
        from cosmo.notifications.service import get_dispatcher, notify_transfer_completed

        dispatcher = get_dispatcher()
        notify_transfer_completed(
            dispatcher,
            domain_id=rel.domain_id,
            run_id="",
            plan_id=rel.plan_id,
            release_id=rel.id,
            from_zone=from_zone,
            to_zone=to_zone,
        )
    except Exception:
        pass  # нотификация не должна ломать ответ