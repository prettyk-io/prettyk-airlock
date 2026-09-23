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

import asyncio
import datetime
import logging
from typing import Optional
from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.cosmo.api.deps import get_current_principal, get_db, require_capability
from orchestrator.cosmo.api.domain_guard import resolve_caller_domain, verify_ownership
from orchestrator.cosmo.domain.rbac import Action, PrincipalContext
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
from orchestrator.cosmo.ledger.hub_verdict_gate import blocked_run_ids
from orchestrator.cosmo.domain.sbom_scan import (
    ReleaseSbomAttachRequest,
    ReleaseSbomAttestationResponse,
)
from orchestrator.cosmo.ledger.sbom_gate import (
    SbomGateError,
    latest_sbom_attestation,
    verify_and_attest_release_sbom,
)
from orchestrator.cosmo.control_plane.transfer_guard import (
    ReleaseTransferGuard,
    bypass_permitted,
    get_transfer_guard,
)
from orchestrator.cosmo.control_plane.deploy_runtime import get_deploy_runtime
from orchestrator.cosmo.adapters.runtime_docker import DockerDeployError
from orchestrator.cosmo.ledger.artifact_record import artifact_records_for_run_ids
from orchestrator.cosmo.domain.artifact_scan import (
    TrivyGateAttachRequest,
    TrivyGateAttestationResponse,
)
from orchestrator.cosmo.ledger.artifact_scan_gate import (
    TrivyGateError,
    latest_trivy_gate,
    trivy_blocker_for_records,
    verify_and_attest_trivy_gate,
)
from orchestrator.cosmo.ledger.release_deploy import (
    record_release_deployed,
    record_release_deploy_failed,
)
from orchestrator.cosmo.domain.transfer_authorization import (
    TransferReplayResponse,
    TransferTransition,
)
from orchestrator.cosmo.domain.promotion import (
    PromotionLandRequest,
    PromotionLandResponse,
    PromotionPackage,
)
from orchestrator.cosmo.ledger.promotion_ledger import (
    PromotionError,
    PromotionMismatchError,
    PromotionNotFoundError,
    land_release_promotion,
    latest_promotion_landing,
    latest_promotion_package,
    pack_release_promotion,
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

logger = logging.getLogger("cosmo.releases")


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
    target_zone: Optional[str] = Field(default=None, description="Целевая зона: zt или zpe")
    # COS-146: оптимистичный CAS — клиент заявляет ожидаемую текущую зону.
    expected_current_zone: Optional[str] = Field(
        default=None,
        description="Ожидаемая текущая зона (CAS); расхождение → 409 Conflict",
    )


class TransferReleaseRequest(BaseModel):
    """SAN-009: расширенный DTO трансфера с цифровой подписью и 2FA."""
    target_zone: str = Field(..., description="Целевая зона: zt или zpe")
    officer_name: str = Field(..., min_length=1, description="ФИО офицера, выполняющего трансфер")
    sign_signature: str = Field(..., min_length=1, description="Цифровая подпись офицера")
    token_2fa: str | None = Field(None, description="Одноразовый 2FA-токен")
    transfer_notes: str | None = Field(None, description="Заметки к трансферу")
    # COS-146: оптимистичный CAS — клиент заявляет ожидаемую текущую зону.
    expected_current_zone: Optional[str] = Field(
        default=None,
        description="Ожидаемая текущая зона (CAS); расхождение → 409 Conflict",
    )


# ── Helpers ────────────────────────────────────────────────────────────

def _to_release_schema(r: ReleaseModel) -> Release:
    return Release(
        id=r.id,
        domain_id=r.domain_id,
        plan_id=r.plan_id,
        run_ids=r.run_ids or [],
        # COS-067: у Release-модели нет колонок trigger/changelog —
        # читаем безопасно, Pydantic-схема имеет дефолты.
        trigger=getattr(r, "trigger", None) or "manual",  # type: ignore
        status=r.status,  # type: ignore
        changelog=getattr(r, "changelog", None) or "",
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


# ── COS-145: fail-closed авторизация межзонного трансфера ──────────────

#: Один инстанс capability-guard'а — FastAPI кэширует зависимость по callable
#: (маршрут и зависимость авторизации используют ровно один RBAC-прогон).
_RELEASE_TRANSFER_GUARD = require_capability(
    Action.RELEASE_TRANSFER, domain_binding="identity",
)


async def enforce_release_transfer_authorization(
    release_id: str,
    principal: PrincipalContext = Depends(_RELEASE_TRANSFER_GUARD),
    db: AsyncSession = Depends(get_db),
    caller_domain: str | None = Header(None, alias="X-Cosmo-Domain"),
    bypass_authorization: bool = Query(
        False,
        alias="bypass_authorization",
        description=(
            "COS-145: обход авторизации — только system admin в dev-окружении, "
            "каждая попытка фиксируется в аудите (BYPASS_ATTEMPT)"
        ),
    ),
    guard: ReleaseTransferGuard = Depends(get_transfer_guard),
) -> None:
    """COS-145: отказать в трансфере (403), если крипто-свидетельства не сходятся.

    Выполняется ДО тела маршрута. Несуществующий релиз и чужой домен — не
    предмет этой проверки: пропускаем, и маршрут отвечает своим 404 (прежняя
    семантика guard-regression сохраняется). Строка релиза читается под
    ``SELECT … FOR UPDATE`` — конкурентные трансферы одного релиза
    сериализуются в рамках транзакции запроса (COS-146).
    """
    rel = await guard.lock_release(db, release_id)
    if rel is None:
        return
    if not principal.is_system_admin:
        verify_ownership(
            rel.domain_id,
            resolve_caller_domain(principal, caller_domain),
            f"Release '{release_id}'",
        )

    target_zone = next_zone(rel.current_zone or "zr")  # type: ignore[arg-type]
    if bypass_authorization:
        permitted = bypass_permitted(principal.is_system_admin)
        guard.record_bypass(
            actor=principal.user_id,
            release_id=release_id,
            target_zone=target_zone,
            permitted=permitted,
        )
        if not permitted:
            raise HTTPException(
                403,
                "Transfer authorization bypass is not permitted "
                "(system administrator + dev environment required)",
            )
        return

    decision = await guard.authorize(
        db, release_id, target_zone=target_zone, actor=principal.user_id,
    )
    if not decision.authorized:
        raise HTTPException(status_code=403, detail=decision.model_dump())


# ── Routes ─────────────────────────────────────────────────────────────

@router.get("", response_model=list[Release])
async def list_releases(
    domain_id: str | None = Query(None),
    status_f: str | None = Query(None, alias="status"),
    # COS-067 UX: заголовок не обязателен — не-админ резолвится по identity
    caller_domain: str | None = Header(None, alias="X-Cosmo-Domain"),
    principal: PrincipalContext = Depends(get_current_principal),
    db: AsyncSession = Depends(get_db),
) -> list[Release]:
    stmt = select(ReleaseModel).order_by(ReleaseModel.created_at.desc())
    # COS-061 + COS-067: scope to caller's domain; не-админ — по identity
    caller = resolve_caller_domain(principal, caller_domain)
    stmt = stmt.where(ReleaseModel.domain_id == caller)
    if status_f:
        stmt = stmt.where(ReleaseModel.status == status_f)
    res = await db.execute(stmt)
    return [_to_release_schema(r) for r in res.scalars().all()]


@router.post("", response_model=Release, status_code=status.HTTP_201_CREATED)
async def create_release(
    body: CreateReleaseRequest,
    caller_domain: str | None = Header(None, alias="X-Cosmo-Domain"),
    db: AsyncSession = Depends(get_db),
    principal: PrincipalContext = Depends(require_capability(Action.RELEASE_CREATE, domain_binding="identity")),
) -> Release:
    domain = await db.get(DomainModel, body.domain_id)
    if domain is None:
        raise HTTPException(404, f"Domain '{body.domain_id}' not found")

    # COS-091: in-body auth-решение заменено единым резолв-контрактом —
    # не-админ создаёт релиз только в своём (резолвнутом) домене
    if not principal.is_system_admin and body.domain_id != resolve_caller_domain(principal, caller_domain):
        raise HTTPException(
            403,
            f"domain_id '{body.domain_id}' does not match authenticated principal domain",
        )

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
        # COS-067: Release-модель не имеет колонок trigger/changelog —
        # передача вызывала TypeError → 500 на валидном теле.
        status="draft",
        version=body.version or "1.0.0",
        artifacts=[],
        approvals=[],
    )
    db.add(rel)
    await db.commit()
    await db.refresh(rel)
    return _to_release_schema(rel)


@router.get("/{release_id}", response_model=Release)
async def get_release(
    release_id: str,
    # COS-067 UX: заголовок не обязателен — не-админ резолвится по identity
    caller_domain: str | None = Header(None, alias="X-Cosmo-Domain"),
    principal: PrincipalContext = Depends(get_current_principal),
    db: AsyncSession = Depends(get_db),
) -> Release:
    rel = await db.get(ReleaseModel, release_id)
    if rel is None:
        raise HTTPException(404, f"Release '{release_id}' not found")
    verify_ownership(rel.domain_id, resolve_caller_domain(principal, caller_domain), f"Release '{release_id}'")
    return _to_release_schema(rel)


@router.post("/{release_id}/submit", response_model=Release)
async def submit_release(
    release_id: str,
    caller_domain: str | None = Header(None, alias="X-Cosmo-Domain"),
    db: AsyncSession = Depends(get_db),
    # COS-091: было анонимно — guard pass 4 ( RELEASE_SUBMIT: lead/relmgr, ЗР)
    principal: PrincipalContext = Depends(require_capability(Action.RELEASE_SUBMIT, domain_binding="identity")),
) -> Release:
    rel = await db.get(ReleaseModel, release_id)
    if rel is None:
        raise HTTPException(404, f"Release '{release_id}' not found")
    # COS-091: ghost-404 по единому резолву для не-админа
    if not principal.is_system_admin:
        verify_ownership(
            rel.domain_id,
            resolve_caller_domain(principal, caller_domain),
            f"Release '{release_id}'",
        )
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
    caller_domain: str | None = Header(None, alias="X-Cosmo-Domain"),
    db: AsyncSession = Depends(get_db),
    # COS-091: было анонимно — guard pass 4 (RELEASE_APPROVE: security officer —
    # SoD: создатель/релиз-менеджер утверждать не может)
    principal: PrincipalContext = Depends(require_capability(Action.RELEASE_APPROVE, domain_binding="identity")),
) -> Release:
    rel = await db.get(ReleaseModel, release_id)
    if rel is None:
        raise HTTPException(404, f"Release '{release_id}' not found")
    # COS-091: ghost-404 по единому резолву для не-админа
    if not principal.is_system_admin:
        verify_ownership(
            rel.domain_id,
            resolve_caller_domain(principal, caller_domain),
            f"Release '{release_id}'",
        )
    if rel.status != "pending_review":
        raise HTTPException(400, f"Release not in pending_review (current: {rel.status})")

    approval = ReleaseApproval(
        decided_by=body.decided_by,
        decision="approved",
        comment=body.comment,
        signature=body.signature,
    )
    # COS-091: mode="json" — decided_at (datetime) сериализуется для JSONB,
    # иначе asyncpg падает на UPDATE approvals.
    approvals = list(rel.approvals or [])
    approvals.append(approval.model_dump(mode="json"))

    rel.status = "approved"
    rel.approvals = approvals
    await db.commit()
    await db.refresh(rel)

    # COS-055: durable notification (non-blocking, не ломает ответ)
    try:
        from orchestrator.cosmo.notifications.integration import notify_release_approved_safe
        notify_release_approved_safe(
            release_id=rel.id,
            domain_id=rel.domain_id or "",
            decided_by=body.decided_by or "",
        )
    except Exception:
        pass

    return _to_release_schema(rel)


@router.post("/{release_id}/reject", response_model=Release)
async def reject_release(
    release_id: str,
    body: ApprovalRequest,
    caller_domain: str | None = Header(None, alias="X-Cosmo-Domain"),
    db: AsyncSession = Depends(get_db),
    # COS-091: было анонимно — guard pass 4 (RELEASE_REJECT: security officer)
    principal: PrincipalContext = Depends(require_capability(Action.RELEASE_REJECT, domain_binding="identity")),
) -> Release:
    rel = await db.get(ReleaseModel, release_id)
    if rel is None:
        raise HTTPException(404, f"Release '{release_id}' not found")
    # COS-091: ghost-404 по единому резолву для не-админа
    if not principal.is_system_admin:
        verify_ownership(
            rel.domain_id,
            resolve_caller_domain(principal, caller_domain),
            f"Release '{release_id}'",
        )
    if rel.status != "pending_review":
        raise HTTPException(400, f"Release not in pending_review (current: {rel.status})")

    approval = ReleaseApproval(
        decided_by=body.decided_by,
        decision="rejected",
        comment=body.comment,
        signature=body.signature,
    )
    # COS-091: mode="json" — см. approve (datetime → JSONB)
    approvals = list(rel.approvals or [])
    approvals.append(approval.model_dump(mode="json"))

    rel.status = "rejected"
    rel.approvals = approvals
    await db.commit()
    await db.refresh(rel)
    return _to_release_schema(rel)


@router.post("/{release_id}/deploy", response_model=Release)
async def deploy_release(
    release_id: str,
    caller_domain: str | None = Header(None, alias="X-Cosmo-Domain"),
    db: AsyncSession = Depends(get_db),
    # COS-091: было анонимно — guard pass 4 (RELEASE_DEPLOY: lead/relmgr, ЗТ)
    principal: PrincipalContext = Depends(require_capability(Action.RELEASE_DEPLOY, domain_binding="identity")),
) -> Release:
    rel = await db.get(ReleaseModel, release_id)
    if rel is None:
        raise HTTPException(404, f"Release '{release_id}' not found")
    # COS-091: ghost-404 по единому резолву для не-админа
    if not principal.is_system_admin:
        verify_ownership(
            rel.domain_id,
            resolve_caller_domain(principal, caller_domain),
            f"Release '{release_id}'",
        )
    if rel.status != "approved":
        raise HTTPException(400, f"Release must be approved before deploy (current: {rel.status})")

    # COS-165: образ резолвится по durable ArtifactRecord прогонов релиза
    # (digest реально собран/запушен runtime-hook'ом COS-164, а не «последний»).
    records = await artifact_records_for_run_ids(db, list(rel.run_ids or []))
    if not records:
        raise HTTPException(
            409,
            f"No durable artifact record for release '{release_id}' runs — "
            f"a docker_build digest must be captured before deploy",
        )

    # COS-168: DOCKER_AUDIT trivy gate — deploy materialize ТОЛЬКО при PASS
    # (critical=0) каждого durable-образа релиза. BLOCK/отсутствие вердикта → 409.
    blocker = await trivy_blocker_for_records(db, release_id, records)
    if blocker:
        raise HTTPException(409, blocker)

    rel.status = "deploying"
    await db.commit()
    await db.refresh(rel)

    runtime = get_deploy_runtime()
    refs: list[str] = []
    containers: list[str] = []
    try:
        for record in records:
            image_ref = f"{record.qualified_image()}@{record.digest}"
            container_name = _deploy_container_name(record.name, record.version)
            await asyncio.to_thread(
                runtime.deploy,
                image_ref,
                container_name,
                labels={
                    "cosmoport.zone": "zr",
                    "cosmoport.release": release_id,
                    "cosmoport.digest": record.digest,
                },
            )
            refs.append(record.canonical_ref())
            containers.append(container_name)
    except DockerDeployError as exc:
        # COS-165: не healthy → честный rollback + durable alert (не фейковый deployed).
        rel.status = "rollback"
        await db.commit()
        await db.refresh(rel)
        await _record_deploy_outcome(
            db, rel, refs=refs, containers=containers,
            healthy=False, reason=str(exc),
        )
        raise HTTPException(502, f"Release '{release_id}' deploy failed: {exc}")

    # COS-165: статус deployed — ТОЛЬКО после фактического healthy контейнеров.
    rel.status = "deployed"
    artifacts = list(rel.artifacts or [])
    for ref in refs:
        if ref not in artifacts:
            artifacts.append(ref)
    rel.artifacts = artifacts
    await db.commit()
    await db.refresh(rel)
    await _record_deploy_outcome(
        db, rel, refs=refs, containers=containers, healthy=True, reason=None,
    )
    return _to_release_schema(rel)


def _deploy_container_name(image_name: str, version: str) -> str:
    """Безопасное имя контейнера из ``<name>-<version>`` (docker naming)."""
    safe = "".join(c if c.isalnum() or c in "_.-" else "-" for c in version)
    return f"{image_name}-{safe}"


async def _record_deploy_outcome(
    db: AsyncSession,
    rel: ReleaseModel,
    *,
    refs: list[str],
    containers: list[str],
    healthy: bool,
    reason: str | None,
) -> None:
    """Durable-след deploy: decision (healthy) / alert (rollback)."""
    run_ids = list(rel.run_ids or [])
    if not run_ids:
        return
    try:
        if healthy:
            await record_release_deployed(
                db, run_id=run_ids[0], release_id=rel.id,
                canonical_refs=refs, container_names=containers,
            )
        else:
            await record_release_deploy_failed(
                db, run_id=run_ids[0], release_id=rel.id,
                reason=reason or "deploy did not become healthy",
            )
    except Exception as exc:  # noqa: BLE001 — улика не должна ломать статус
        logger.warning(
            "deploy evidence write failed for release %s: %s", rel.id, exc,
        )


@router.delete("/{release_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_release(
    release_id: str,
    caller_domain: str | None = Header(None, alias="X-Cosmo-Domain"),
    db: AsyncSession = Depends(get_db),
    # COS-091: было анонимно — guard pass 4. Отдельного release:delete нет —
    # владелец жизненного цикла определяется RELEASE_CREATE (автор управляет
    # своим релизом); зонная матрица ЗР допускает.
    principal: PrincipalContext = Depends(require_capability(Action.RELEASE_CREATE, domain_binding="identity")),
) -> None:
    rel = await db.get(ReleaseModel, release_id)
    if rel is None:
        raise HTTPException(404, f"Release '{release_id}' not found")
    # COS-091: ghost-404 по единому резолву для не-админа
    if not principal.is_system_admin:
        verify_ownership(
            rel.domain_id,
            resolve_caller_domain(principal, caller_domain),
            f"Release '{release_id}'",
        )
    await db.delete(rel)
    await db.commit()


# ═══════════════════════════════════════════════════════════════════════
# COS-054: Межзонный трансфер
# ═══════════════════════════════════════════════════════════════════════

@router.post(
    "/{release_id}/transfer",
    response_model=Release | TransferReplayResponse,
    dependencies=[Depends(enforce_release_transfer_authorization)],
)
async def transfer_release(
    release_id: str,
    body: TransferRequest,
    caller_domain: str | None = Header(None, alias="X-Cosmo-Domain"),
    db: AsyncSession = Depends(get_db),
    principal: PrincipalContext = Depends(_RELEASE_TRANSFER_GUARD),  # require_capability(Action.RELEASE_TRANSFER)
) -> Release | TransferReplayResponse:
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

    # COS-067/COS-083: domain binding — ownership по единому резолву для не-админа
    if not principal.is_system_admin:
        verify_ownership(
            rel.domain_id,
            resolve_caller_domain(principal, caller_domain),
            f"Release '{release_id}'",
        )

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

    # 2b. COS-136: Contract A — Hub BLOCK держит релиз в текущей зоне.
    # PASS после BLOCK снимает блокировку by construction (последний вердикт).
    hub_blocked = await blocked_run_ids(db, list(rel.run_ids or []))
    if hub_blocked:
        raise HTTPException(
            400,
            f"Promotion blocked by Hub verdict BLOCK for runs: {hub_blocked}. "
            f"A PASS verdict from PrettyK Hub is required before transfer.",
        )

    # 3. COS-146: CAS-переход — конфликт ожиданий или идемпотентный replay.
    # Повтор уже выполненного перехода отдаёт 200 duplicate_success без
    # второй записи в transfer_history и без повторной эмиссии уведомлений.
    transition = get_transfer_guard().evaluate_transition(
        rel,
        target_zone=body.target_zone,
        expected_current_zone=body.expected_current_zone,
    )
    if transition is TransferTransition.CONFLICT:
        raise HTTPException(
            409,
            f"Transfer state conflict: release '{rel.id}' is in zone "
            f"'{rel.current_zone or 'zr'}', expected "
            f"'{body.expected_current_zone}'.",
        )
    if transition is TransferTransition.REPLAY:
        return get_transfer_guard().replay_payload(rel)

    # 4. SAN-009 / CLN-008: Linear zone promotion validation
    current = rel.current_zone or "zr"
    valid_paths = {"zr": "zt", "zt": "zpe"}
    expected_next = valid_paths.get(current)
    if expected_next is None:
        raise HTTPException(
            400,
            f"Release already in final zone ({current}). No further transfer possible.",
        )

    target = body.target_zone or expected_next
    if target != expected_next:
        raise HTTPException(
            400,
            f"Invalid zone promotion. Strict path is ZR -> ZT -> ZPE. "
            f"Cannot transfer from '{current}' directly to '{target}'. "
            f"Expected next zone: '{expected_next}'.",
        )

    # 5. Создаём TransferRecord
    transfer = TransferRecord(
        from_zone=current,  # type: ignore
        to_zone=target,
        initiated_by=body.initiated_by,
        gate_check_passed=len(blocked_gates) == 0 and len(pending_gates) == 0,
        comment=body.comment,
    )

    # 5. Обновляем release
    # COS-095: mode="json" для единообразия с approve/reject (COS-091) —
    # datetime-поля сериализуются, JSONB-запись не зависит от типов Python
    history = list(rel.transfer_history or [])
    history.append(transfer.model_dump(mode="json"))
    rel.transfer_history = history
    rel.current_zone = target

    # COS-055: transactional outbox — событие transfer в той же транзакции,
    # что и сам transfer. Перезапуск процесса не теряет событие.
    from orchestrator.cosmo.notifications.manager import get_manager
    manager = get_manager()
    await manager.record_event(
        db,
        event_type="transfer_completed",
        aggregate_type="transfer",
        aggregate_id=f"{rel.id}:{current}->{target}",
        correlation_id=rel.id,
        title=f"Release {rel.id} transferred to {target.upper()}",
        message=f"Release {rel.id}: {current.upper()} → {target.upper()}",
        payload={
            "release_id": rel.id,
            "domain_id": rel.domain_id,
            "plan_id": rel.plan_id,
            "from_zone": current,
            "to_zone": target,
            "initiated_by": body.initiated_by,
        },
    )

    await db.commit()
    await db.refresh(rel)

    # COS-065: in-memory каналы о трансфере (log/webhook — legacy fan-out)
    _try_notify_transfer(rel, current, target, body.initiated_by)

    return _to_release_schema(rel)


@router.post(
    "/{release_id}/transfer-v2",
    response_model=Release | TransferReplayResponse,
    dependencies=[Depends(enforce_release_transfer_authorization)],
)
async def transfer_release_v2(
    release_id: str,
    body: TransferReleaseRequest,
    caller_domain: str | None = Header(None, alias="X-Cosmo-Domain"),
    db: AsyncSession = Depends(get_db),
    principal: PrincipalContext = Depends(_RELEASE_TRANSFER_GUARD),  # require_capability(Action.RELEASE_TRANSFER)
) -> Release | TransferReplayResponse:
    """SAN-009: Трансфер релиза с цифровой подписью, 2FA и линейной валидацией зон.

    Строгий линейный путь: ЗР → ЗТ → ЗПЭ.
    Прямой перескок ЗР → ЗПЭ блокируется (HTTP 400).
    """
    from orchestrator.cosmo.db.models import Gate as GateModel

    rel = await db.get(ReleaseModel, release_id)
    if rel is None:
        raise HTTPException(404, f"Release '{release_id}' not found")

    # COS-067/COS-083: domain binding — ownership по единому резолву для не-админа
    if not principal.is_system_admin:
        verify_ownership(
            rel.domain_id,
            resolve_caller_domain(principal, caller_domain),
            f"Release '{release_id}'",
        )

    if rel.status != "deployed":
        raise HTTPException(400, f"Release must be deployed before transfer (current: {rel.status})")

    # Validate gates
    gate_stmt = select(GateModel).where(GateModel.plan_id == rel.plan_id)
    gate_res = await db.execute(gate_stmt)
    gates = gate_res.scalars().all()

    blocked_gates = [g for g in gates if g.decision != "pass" and g.decision is not None]
    pending_gates = [g for g in gates if g.decision is None]

    if blocked_gates or pending_gates:
        raise HTTPException(400, "All gates must have decision='pass' before transfer.")

    # COS-136: Contract A — Hub BLOCK держит релиз в текущей зоне.
    hub_blocked = await blocked_run_ids(db, list(rel.run_ids or []))
    if hub_blocked:
        raise HTTPException(
            400,
            f"Promotion blocked by Hub verdict BLOCK for runs: {hub_blocked}. "
            f"A PASS verdict from PrettyK Hub is required before transfer.",
        )

    # COS-146: CAS-переход — конфликт ожиданий или идемпотентный replay.
    transition = get_transfer_guard().evaluate_transition(
        rel,
        target_zone=body.target_zone,
        expected_current_zone=body.expected_current_zone,
    )
    if transition is TransferTransition.CONFLICT:
        raise HTTPException(
            409,
            f"Transfer state conflict: release '{rel.id}' is in zone "
            f"'{rel.current_zone or 'zr'}', expected "
            f"'{body.expected_current_zone}'.",
        )
    if transition is TransferTransition.REPLAY:
        return get_transfer_guard().replay_payload(rel)

    # SAN-009: Strict linear zone promotion
    current = rel.current_zone or "zr"
    valid_paths = {"zr": "zt", "zt": "zpe"}
    expected_next = valid_paths.get(current)

    if expected_next is None:
        raise HTTPException(400, f"Release already in final zone '{current}'. No further transfer possible.")

    if body.target_zone != expected_next:
        raise HTTPException(
            400,
            f"Invalid zone promotion. Strict path is ZR -> ZT -> ZPE. "
            f"Cannot transfer from '{current}' directly to '{body.target_zone}'. "
            f"Expected next zone: '{expected_next}'.",
        )

    # SAN-009: Record transfer with officer credentials
    transfer = TransferRecord(
        from_zone=current,  # type: ignore
        to_zone=expected_next,  # type: ignore
        initiated_by=body.officer_name,
        gate_check_passed=True,
        comment=body.transfer_notes or "",
    )
    # Add SAN-009 fields to the transfer record
    # COS-095: mode="json" — см. transfer v1 (единообразие сериализации)
    transfer_dict = transfer.model_dump(mode="json")
    transfer_dict["officer_name"] = body.officer_name
    transfer_dict["signature"] = body.sign_signature
    transfer_dict["token_2fa"] = body.token_2fa
    transfer_dict["timestamp"] = datetime.datetime.utcnow().isoformat()

    history = list(rel.transfer_history or [])
    history.append(transfer_dict)
    rel.transfer_history = history
    rel.current_zone = expected_next

    # COS-055: transactional outbox (v2 transfer, SAN-009 signature flow)
    from orchestrator.cosmo.notifications.manager import get_manager
    manager = get_manager()
    await manager.record_event(
        db,
        event_type="transfer_completed",
        aggregate_type="transfer",
        aggregate_id=f"{rel.id}:{current}->{expected_next}",
        correlation_id=rel.id,
        title=f"Release {rel.id} transferred to {expected_next.upper()}",
        message=f"Release {rel.id}: {current.upper()} → {expected_next.upper()}",
        payload={
            "release_id": rel.id,
            "domain_id": rel.domain_id,
            "plan_id": rel.plan_id,
            "from_zone": current,
            "to_zone": expected_next,
            "initiated_by": body.officer_name,
            "signed": True,
        },
    )

    await db.commit()
    await db.refresh(rel)

    # COS-065: in-memory каналы (legacy fan-out)
    _try_notify_transfer(rel, current, expected_next, body.officer_name)

    return _to_release_schema(rel)


# ── COS-109: Digital Release Envelope Endpoints ────────────────────────

@router.post("/envelope/verify", response_model=VerifyEnvelopeResponse)
async def verify_release_envelope(
    body: dict,
    # COS-091: было анонимно — закрытие crypto-oracle (ENVELOPE_VERIFY:
    # qa/relmgr/auditors); pure-функция, доменного якоря нет
    principal: PrincipalContext = Depends(require_capability(Action.ENVELOPE_VERIFY, domain_binding="identity")),
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
    # COS-067 UX: заголовок не обязателен — не-админ резолвится по identity
    caller_domain: str | None = Header(None, alias="X-Cosmo-Domain"),
    principal: PrincipalContext = Depends(get_current_principal),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """COS-109: Выгрузить подписанный криптографический цифровой конверт релиза."""
    rel = await db.get(ReleaseModel, release_id)
    if rel is None:
        raise HTTPException(404, f"Release '{release_id}' not found")
    verify_ownership(rel.domain_id, resolve_caller_domain(principal, caller_domain), f"Release '{release_id}'")

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
    """COS-055: durable notification о трансфере (не блокирует ответ).

    Event идёт в NotificationManager outbox (PostgreSQL) + legacy in-memory
    dispatcher внутри менеджера. Ошибки не ломают ответ.
    """
    try:
        from orchestrator.cosmo.notifications.integration import notify_transfer_durable_safe

        notify_transfer_durable_safe(
            release_id=rel.id,
            domain_id=rel.domain_id or "",
            from_zone=from_zone,
            to_zone=to_zone,
            initiated_by=initiated_by or "",
        )
    except Exception:
        pass  # нотификация не должна ломать ответ


# ── COS-138: PK-C-003.6 SBOM & Grype Attestation Gate ──────────────────

@router.post(
    "/{release_id}/sbom/attach",
    response_model=ReleaseSbomAttestationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Attach and attest release bundle SBOM + Grype scan",
)
async def attach_release_sbom(
    release_id: str,
    body: ReleaseSbomAttachRequest,
    caller_domain: str | None = Header(None, alias="X-Cosmo-Domain"),
    db: AsyncSession = Depends(get_db),
    principal: PrincipalContext = Depends(
        require_capability(Action.GATE_DECIDE, domain_binding="identity")
    ),
) -> ReleaseSbomAttestationResponse:
    """COS-138: принять Syft SBOM + Grype-скан, сверить digest и аттестовать.

    critical > 0 → gate_verdict=BLOCK / clearance=DENIED (аттестация всё
    равно фиксируется в ledger); digest mismatch → 422; неизвестный релиз →
    404. Supply-chain гейт, поэтому capability — GATE_DECIDE.
    """
    rel = await db.get(ReleaseModel, release_id)
    if rel is None:
        raise HTTPException(404, f"Release '{release_id}' not found")
    if not principal.is_system_admin:
        verify_ownership(
            rel.domain_id,
            resolve_caller_domain(principal, caller_domain),
            f"Release '{release_id}'",
        )
    try:
        return await verify_and_attest_release_sbom(db, release_id, body)
    except SbomGateError as exc:
        raise HTTPException(exc.status_code, str(exc))


@router.get(
    "/{release_id}/sbom",
    response_model=ReleaseSbomAttestationResponse,
    summary="Read latest release SBOM attestation",
)
async def get_release_sbom(
    release_id: str,
    caller_domain: str | None = Header(None, alias="X-Cosmo-Domain"),
    principal: PrincipalContext = Depends(get_current_principal),
    db: AsyncSession = Depends(get_db),
) -> ReleaseSbomAttestationResponse:
    """COS-138: последняя аттестация SBOM релиза (404, если её не было)."""
    rel = await db.get(ReleaseModel, release_id)
    if rel is None:
        raise HTTPException(404, f"Release '{release_id}' not found")
    if not principal.is_system_admin:
        verify_ownership(
            rel.domain_id,
            resolve_caller_domain(principal, caller_domain),
            f"Release '{release_id}'",
        )
    attestation = await latest_sbom_attestation(db, release_id)
    if attestation is None:
        raise HTTPException(404, f"No SBOM attestation for release '{release_id}'")
    return attestation


# ── COS-168: PK-C-003.6 / DOCKER_AUDIT Trivy Container Scan Gate ───────

@router.post(
    "/{release_id}/trivy/attach",
    response_model=TrivyGateAttestationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Attach and attest release image Trivy container scan",
)
async def attach_release_trivy(
    release_id: str,
    body: TrivyGateAttachRequest,
    caller_domain: str | None = Header(None, alias="X-Cosmo-Domain"),
    db: AsyncSession = Depends(get_db),
    principal: PrincipalContext = Depends(
        require_capability(Action.GATE_DECIDE, domain_binding="identity")
    ),
) -> TrivyGateAttestationResponse:
    """COS-168: принять trivy-отчёт, сверить digest и аттестовать образ.

    critical > 0 → gate_verdict=BLOCK / clearance=DENIED (вердикт фиксируется
    durable в Evidence Ledger); digest mismatch конверта/отчёта/образа → 422;
    неизвестный релиз → 404. Container-scan гейт → capability GATE_DECIDE.
    """
    rel = await db.get(ReleaseModel, release_id)
    if rel is None:
        raise HTTPException(404, f"Release '{release_id}' not found")
    if not principal.is_system_admin:
        verify_ownership(
            rel.domain_id,
            resolve_caller_domain(principal, caller_domain),
            f"Release '{release_id}'",
        )
    try:
        return await verify_and_attest_trivy_gate(db, release_id, body)
    except TrivyGateError as exc:
        raise HTTPException(exc.status_code, str(exc))


@router.get(
    "/{release_id}/trivy",
    response_model=TrivyGateAttestationResponse,
    summary="Read latest release Trivy gate decision",
)
async def get_release_trivy(
    release_id: str,
    caller_domain: str | None = Header(None, alias="X-Cosmo-Domain"),
    principal: PrincipalContext = Depends(get_current_principal),
    db: AsyncSession = Depends(get_db),
) -> TrivyGateAttestationResponse:
    """COS-168: последнее trivy gate-решение релиза (404, если его не было)."""
    rel = await db.get(ReleaseModel, release_id)
    if rel is None:
        raise HTTPException(404, f"Release '{release_id}' not found")
    if not principal.is_system_admin:
        verify_ownership(
            rel.domain_id,
            resolve_caller_domain(principal, caller_domain),
            f"Release '{release_id}'",
        )
    attestation = await latest_trivy_gate(db, release_id)
    if attestation is None:
        raise HTTPException(404, f"No trivy gate decision for release '{release_id}'")
    return attestation


# ── COS-169/170: Promotion packing + landing (ЗР→ЗТ→ЗПЭ) ─────────────

@router.post(
    "/{release_id}/promote",
    response_model=PromotionPackage,
    summary="Pack release into an idempotent promotion package (next zone)",
)
async def promote_release(
    release_id: str,
    caller_domain: str | None = Header(None, alias="X-Cosmo-Domain"),
    db: AsyncSession = Depends(get_db),
    # COS-169: promotion — та же поверхность, что и межзонный трансфер
    principal: PrincipalContext = Depends(_RELEASE_TRANSFER_GUARD),  # require_capability(Action.RELEASE_TRANSFER)
) -> PromotionPackage:
    """COS-169: упаковать deployed-релиз в transfer-пакет для следующей зоны.

    Пакет (digest-pin + SBOM + trivy gate + evidence) idempotent; gate обязателен
    (BLOCK/отсутствие trivy или отсутствие SBOM → 409).
    """
    rel = await db.get(ReleaseModel, release_id)
    if rel is None:
        raise HTTPException(404, f"Release '{release_id}' not found")
    if not principal.is_system_admin:
        verify_ownership(
            rel.domain_id,
            resolve_caller_domain(principal, caller_domain),
            f"Release '{release_id}'",
        )
    if rel.status != "deployed":
        raise HTTPException(400, f"Release must be deployed before promotion (current: {rel.status})")

    target_zone = next_zone(rel.current_zone or "zr")  # type: ignore[arg-type]
    if target_zone is None:
        raise HTTPException(
            400, f"Release already in final zone '{rel.current_zone}'. No further promotion possible.")

    try:
        return await pack_release_promotion(db, rel, target_zone)
    except PromotionError as exc:
        raise HTTPException(exc.status_code, str(exc))


@router.post(
    "/{release_id}/promote/land",
    response_model=PromotionLandResponse,
    summary="Land a packed promotion package in the target zone (digest-matching)",
)
async def land_release_promotion_route(
    release_id: str,
    body: PromotionLandRequest,
    caller_domain: str | None = Header(None, alias="X-Cosmo-Domain"),
    db: AsyncSession = Depends(get_db),
    principal: PrincipalContext = Depends(_RELEASE_TRANSFER_GUARD),  # require_capability(Action.RELEASE_TRANSFER)
) -> PromotionLandResponse:
    """COS-169/170: принять пакет в целевой зоне и перевести релиз (promoted).

    digest-matching (incoming manifest == пакетный) + повторная сверка SBOM +
    trivy gate. mismatch → 422, blocked/missing → 409, нелинейный переход → 409.
    """
    rel = await db.get(ReleaseModel, release_id)
    if rel is None:
        raise HTTPException(404, f"Release '{release_id}' not found")
    if not principal.is_system_admin:
        verify_ownership(
            rel.domain_id,
            resolve_caller_domain(principal, caller_domain),
            f"Release '{release_id}'",
        )
    if rel.status != "deployed":
        raise HTTPException(400, f"Release must be deployed before landing (current: {rel.status})")

    try:
        return await land_release_promotion(db, rel, body, actor=principal.user_id)
    except PromotionNotFoundError as exc:
        raise HTTPException(404, str(exc))
    except PromotionMismatchError as exc:
        raise HTTPException(422, exc.report if exc.report else str(exc))
    except PromotionError as exc:
        raise HTTPException(exc.status_code, exc.report if exc.report else str(exc))


@router.get(
    "/{release_id}/promotion",
    response_model=PromotionPackage,
    summary="Read latest promotion package for a zone",
)
async def get_release_promotion(
    release_id: str,
    target_zone: str = Query(..., description="Целевая зона пакета: zt или zpe"),
    caller_domain: str | None = Header(None, alias="X-Cosmo-Domain"),
    principal: PrincipalContext = Depends(get_current_principal),
    db: AsyncSession = Depends(get_db),
) -> PromotionPackage:
    """COS-169: актуальный промо-пакет релиза (latest wins, restart-survival)."""
    rel = await db.get(ReleaseModel, release_id)
    if rel is None:
        raise HTTPException(404, f"Release '{release_id}' not found")
    if not principal.is_system_admin:
        verify_ownership(
            rel.domain_id,
            resolve_caller_domain(principal, caller_domain),
            f"Release '{release_id}'",
        )
    package = await latest_promotion_package(db, release_id, target_zone)
    if package is None:
        raise HTTPException(404, f"No promotion package for release '{release_id}' → '{target_zone}'")
    return package


@router.get(
    "/{release_id}/promotion/land",
    response_model=PromotionLandResponse,
    summary="Read latest promotion landing report for a zone",
)
async def get_release_promotion_landing(
    release_id: str,
    target_zone: str = Query(..., description="Целевая зона landing: zt или zpe"),
    caller_domain: str | None = Header(None, alias="X-Cosmo-Domain"),
    principal: PrincipalContext = Depends(get_current_principal),
    db: AsyncSession = Depends(get_db),
) -> PromotionLandResponse:
    """COS-169/170: актуальный landing-отчёт релиза (latest wins, durable)."""
    rel = await db.get(ReleaseModel, release_id)
    if rel is None:
        raise HTTPException(404, f"Release '{release_id}' not found")
    if not principal.is_system_admin:
        verify_ownership(
            rel.domain_id,
            resolve_caller_domain(principal, caller_domain),
            f"Release '{release_id}'",
        )
    landing = await latest_promotion_landing(db, release_id, target_zone)
    if landing is None:
        raise HTTPException(404, f"No promotion landing for release '{release_id}' → '{target_zone}'")
    return landing