# -*- coding: utf-8 -*-
"""Hub-поверхность Cosmoport: Contract A (приём вердиктов) + Contract B
(инициация внешней оценки релиза).

Contract A — ``POST /api/v1/hub/verdicts/ingest``: Gatekeeper (Hub) присылает
вердикт Quality Gate по прогону. Cosmoport:

  1. валидирует конверт Contract A (Pydantic, ``extra="forbid"``);
  2. проверяет существование run (FK ``evidence_ledger.run_id``);
  3. дедуплицирует по ``idempotency_key`` и ``sha256(run_id:hub_verdict)``;
  4. запечатывает запись в ``evidence_ledger`` (``type='decision'``,
     ``provenance.source='prettyk-hub'``, ``provenance_hash``) — крипто-якорь;
  5. вердикт становится источником promotion-gate релиза (BLOCK/PASS) —
     см. ``ledger/hub_verdict_gate.py``.

Идемпотентность: повтор с тем же ключом/вердиктом возвращает ту же запись
ledger со ``status="duplicate"`` и НЕ создаёт второй записи.

Contract B (COS-139) — ``POST /api/v1/hub/evaluations/dispatch`` инициирует
внешнюю оценку релиза в PrettyK Hub, ``GET /api/v1/hub/evaluations/{id}``
читает статус отправленной оценки. Clearance gate, идемпотентность и аудит —
в ``control_plane/hub_dispatcher.py``. COS-153: статус durable — ``GET``
читает якорь из ``evidence_ledger`` (``ledger/hub_evaluation_ledger.py``) и
переживает рестарт процесса; in-memory реестра-дубликата нет.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.cosmo.adapters.hub_client import HubDispatchError
from orchestrator.cosmo.api.deps import get_db, require_principal
from orchestrator.cosmo.control_plane.hub_dispatcher import (
    HubEvaluationDispatcher,
)
from orchestrator.cosmo.db.models import (
    EvidenceLedgerEntry,
    Run as RunModel,
)
from orchestrator.cosmo.domain.hub_clearance import (
    HubClearanceConflictError,
    HubClearanceIngestRequest,
    HubClearanceIngestResponse,
)
from orchestrator.cosmo.domain.hub_evaluation import (
    HubEvaluationContextError,
    HubEvaluationDispatchResponse,
    HubEvaluationRequest,
)
from orchestrator.cosmo.domain.hub_verdict import (
    HubVerdictIngestRequest,
    HubVerdictIngestResponse,
    provenance_hash,
    verdict_hash,
)
from orchestrator.cosmo.domain.rbac import PrincipalContext
from orchestrator.cosmo.ledger.evidence_writer import commit_evidence_entry
from orchestrator.cosmo.ledger.hub_clearance_gate import HubClearanceGateManager
from orchestrator.cosmo.ledger.hub_verdict_gate import HUB_SOURCE

router = APIRouter(prefix="/api/v1/hub", tags=["hub"])

#: Процесс-синглтон диспетчера Contract B (durable-якорь — в ledger, COS-153).
_hub_dispatcher: HubEvaluationDispatcher | None = None

#: Процесс-синглтон clearance-гейта Contract C (чтение/запись ledger).
_clearance_gate: HubClearanceGateManager | None = None


def get_hub_dispatcher() -> HubEvaluationDispatcher:
    """FastAPI dependency: диспетчер оценок (override в тестах)."""
    global _hub_dispatcher
    if _hub_dispatcher is None:
        _hub_dispatcher = HubEvaluationDispatcher()
    return _hub_dispatcher


def get_clearance_gate() -> HubClearanceGateManager:
    """FastAPI dependency: clearance-гейт Contract C (override в тестах)."""
    global _clearance_gate
    if _clearance_gate is None:
        _clearance_gate = HubClearanceGateManager()
    return _clearance_gate


def _build_provenance(body: HubVerdictIngestRequest) -> dict:
    """Канонический provenance конверта вердикта (до запечатывания хэша)."""
    return {
        "source": HUB_SOURCE,
        "contract": "A",
        "contract_version": "1.0",
        "idempotency_key": body.idempotency_key,
        "verdict_hash": verdict_hash(body.run_id, body.hub_verdict),
        "hub_verdict": body.hub_verdict,
        "box_verdict": body.box_verdict,
        "finding_ids": list(body.finding_ids),
        "evidence_hashes": list(body.evidence_hashes),
        "provenance_metadata": dict(body.provenance_metadata),
    }


async def _find_duplicate(
    db: AsyncSession, body: HubVerdictIngestRequest,
) -> EvidenceLedgerEntry | None:
    """Существующая запись Hub по ``idempotency_key`` ИЛИ ``verdict_hash``."""
    vhash = verdict_hash(body.run_id, body.hub_verdict)
    stmt = (
        select(EvidenceLedgerEntry)
        .where(EvidenceLedgerEntry.type == "decision")
        .where(EvidenceLedgerEntry.provenance_json["source"].astext == HUB_SOURCE)
        .where(
            (EvidenceLedgerEntry.provenance_json["idempotency_key"].astext
             == body.idempotency_key)
            | (EvidenceLedgerEntry.provenance_json["verdict_hash"].astext == vhash)
        )
        .order_by(
            EvidenceLedgerEntry.created_at.desc(),
            EvidenceLedgerEntry.id.desc(),
        )
        .limit(1)
    )
    return (await db.execute(stmt)).scalars().first()


@router.post(
    "/verdicts/ingest",
    response_model=HubVerdictIngestResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Ingest PrettyK Hub quality-gate verdict (Contract A)",
)
async def ingest_hub_verdict(
    body: HubVerdictIngestRequest,
    db: AsyncSession = Depends(get_db),
    principal: PrincipalContext = Depends(require_principal()),
) -> HubVerdictIngestResponse:
    """Принять вердикт Hub: дедуп → крипто-запись в ledger → статус."""
    run = (
        await db.execute(select(RunModel).where(RunModel.id == body.run_id))
    ).scalar_one_or_none()
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Run '{body.run_id}' not found",
        )

    duplicate = await _find_duplicate(db, body)
    if duplicate is not None:
        return HubVerdictIngestResponse(
            accepted=True,
            ledger_entry_id=duplicate.id,
            run_id=body.run_id,
            status="duplicate",
        )

    provenance = _build_provenance(body)
    p_hash = provenance_hash(provenance)
    provenance["provenance_hash"] = p_hash

    entry = EvidenceLedgerEntry(
        run_id=body.run_id,
        batch_id=run.batch_id,
        type="decision",
        content_ref=f"hub://verdict/{body.run_id}/{body.idempotency_key}",
        content_hash=p_hash,
        provenance_json=provenance,
    )
    await commit_evidence_entry(db, entry)

    return HubVerdictIngestResponse(
        accepted=True,
        ledger_entry_id=entry.id,
        run_id=body.run_id,
        status=body.hub_verdict,
    )


# ── Contract B (COS-139): Control Plane → Hub evaluation ─────────────────


@router.post(
    "/evaluations/dispatch",
    response_model=HubEvaluationDispatchResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Dispatch release evaluation to PrettyK Hub (Contract B)",
)
async def dispatch_hub_evaluation(
    body: HubEvaluationRequest,
    db: AsyncSession = Depends(get_db),
    principal: PrincipalContext = Depends(require_principal()),
    dispatcher: HubEvaluationDispatcher = Depends(get_hub_dispatcher),
) -> HubEvaluationDispatchResponse:
    """Инициировать внешнюю QG-оценку релиза (идемпотентно по evaluation_id)."""
    run = (
        await db.execute(select(RunModel).where(RunModel.id == body.run_id))
    ).scalar_one_or_none()
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Run '{body.run_id}' not found",
        )
    try:
        return await dispatcher.dispatch(
            body, session=db, actor=principal.user_id,
        )
    except HubEvaluationContextError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except HubDispatchError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc


@router.get(
    "/evaluations/{evaluation_id}",
    response_model=HubEvaluationDispatchResponse,
    summary="Read dispatched Hub evaluation status (Contract B)",
)
async def get_hub_evaluation(
    evaluation_id: str,
    db: AsyncSession = Depends(get_db),
    principal: PrincipalContext = Depends(require_principal()),
    dispatcher: HubEvaluationDispatcher = Depends(get_hub_dispatcher),
) -> HubEvaluationDispatchResponse:
    """Durable-статус ранее отправленной оценки (404 — не отправлялась)."""
    record = await dispatcher.get(db, evaluation_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Evaluation '{evaluation_id}' not found",
        )
    return record


# ── Contract C (COS-141): Hub → Control Plane quality-gate clearance ─────


@router.post(
    "/clearance/ingest",
    response_model=HubClearanceIngestResponse,
    summary="Ingest PrettyK Hub quality-gate clearance (Contract C)",
)
async def ingest_hub_clearance(
    body: HubClearanceIngestRequest,
    db: AsyncSession = Depends(get_db),
    principal: PrincipalContext = Depends(require_principal()),
    gate: HubClearanceGateManager = Depends(get_clearance_gate),
) -> HubClearanceIngestResponse:
    """Принять клиренс Quality Gate: дедуп/дрейф → крипто-якорь в ledger."""
    run = (
        await db.execute(select(RunModel).where(RunModel.id == body.run_id))
    ).scalar_one_or_none()
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Run '{body.run_id}' not found",
        )
    try:
        return await gate.ingest(db, body)
    except HubClearanceConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.get(
    "/clearance/by-evaluation/{evaluation_id}",
    response_model=HubClearanceIngestResponse,
    summary="Read clearance by evaluation id (Contract C)",
)
async def get_hub_clearance_by_evaluation(
    evaluation_id: str,
    db: AsyncSession = Depends(get_db),
    principal: PrincipalContext = Depends(require_principal()),
    gate: HubClearanceGateManager = Depends(get_clearance_gate),
) -> HubClearanceIngestResponse:
    """Актуальный клиренс по ID оценки (404 — клиренса не было)."""
    found = await gate.latest_for_evaluation(db, evaluation_id)
    if found is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Clearance for evaluation '{evaluation_id}' not found",
        )
    return found


@router.get(
    "/clearance/{release_id}",
    response_model=HubClearanceIngestResponse,
    summary="Read latest release clearance status (Contract C)",
)
async def get_hub_clearance(
    release_id: str,
    db: AsyncSession = Depends(get_db),
    principal: PrincipalContext = Depends(require_principal()),
    gate: HubClearanceGateManager = Depends(get_clearance_gate),
) -> HubClearanceIngestResponse:
    """Актуальный клиренс релиза (404 — клиренса не было)."""
    found = await gate.latest_for_release(db, release_id)
    if found is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Clearance for release '{release_id}' not found",
        )
    return found
