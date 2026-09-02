"""COS-060: Evidence Chain Verification API endpoint.

GET /api/v1/runs/{run_id}/evidence — загружает evidence-записи из PG,
перестраивает SHA-256 цепочку, проверяет целостность + tamper + replay.

COS-069: GOST-Act endpoints.
GET /api/v1/runs/{run_id}/gost-act — JSON-модель акта.
GET /api/v1/runs/{run_id}/gost-act/html — HTML для печати.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.cosmo.api.deps import get_db, require_principal
from orchestrator.cosmo.api.domain_guard import resolve_caller_domain, verify_ownership
from orchestrator.cosmo.domain.rbac import PrincipalContext
from orchestrator.cosmo.ledger.evidence_chain import EvidenceLedger

router = APIRouter(tags=["evidence"])


@router.get("/api/v1/runs/{run_id}/evidence", summary="Get evidence chain with verification")
async def get_evidence_chain(
    run_id: str,
    caller_domain: str | None = Header(None, alias="X-Cosmo-Domain"),
    db: AsyncSession = Depends(get_db),
    principal: PrincipalContext = Depends(require_principal()),
):
    """Возвращает evidence-цепочку с результатом верификации.

    Response (COS-082: верификация против СОХРАНЁННЫХ якорей, не пересчёт
    от мутированных строк):
      - chain: полная цепочка записей (entries, length, verified, last_hash)
      - verified: bool — якоря целы, связность не нарушена, все запечатаны
      - integrity: "ok" | "tampered" | "unsealed"
      - tampered_entries: list[int] — индексы строк с hash mismatch
      - tampered_details: [{index, entry_id, reason, stored_hash, recomputed_hash}]
      - broken_links: [{index, entry_id, expected_prev_hash, stored_prev_hash}]
      - unsealed_entries: list[str] — id строк без якорей
      - tampered_chain: bool — нарушена связность цепочки
      - replay_count: int — количество дубликатов
      - total_entries: int — общее количество записей

    COS-068: authentication required + domain-scoping (не-админ читает
    evidence только своего домена, ghost-404 — анти-дисклеймер).
    """
    # Проверить, что run существует
    try:
        from orchestrator.cosmo.db.models import Run as RunModel
        from sqlalchemy import select
        result = await db.execute(select(RunModel).where(RunModel.id == run_id))
        run = result.scalar_one_or_none()
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Run {run_id} not found")

    # COS-068/COS-083: не-админ видит evidence только своего домена
    if not principal.is_system_admin:
        verify_ownership(
            run.domain_id,
            resolve_caller_domain(principal, caller_domain),
            f"Run '{run_id}'",
        )

    # Синхронный db_session_factory
    from orchestrator.cosmo.db.session import get_sync_session
    sync_factory = get_sync_session

    result = EvidenceLedger.verify_and_get(sync_factory, run_id)

    return result


# ── COS-069: GOST-Act endpoints ──

@router.get("/api/v1/runs/{run_id}/gost-act", summary="Get GOST Act JSON")
async def get_gost_act_json(
    run_id: str,
    findings_json: str | None = Query(None, alias="findings", description="JSON findings array (inline)"),
    caller_domain: str | None = Header(None, alias="X-Cosmo-Domain"),
    db: AsyncSession = Depends(get_db),
    principal: PrincipalContext = Depends(require_principal()),
):
    """Возвращает ГОСТ-Акт в JSON.

    COS-068: authentication required + domain-scoping.
    """
    # Check run exists
    from orchestrator.cosmo.db.models import Run as RunModel
    from sqlalchemy import select
    result = await db.execute(select(RunModel).where(RunModel.id == run_id))
    run = result.scalar_one_or_none()
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Run {run_id} not found")

    # COS-068/COS-083: не-админ видит ГОСТ-Акт только своего домена
    if not principal.is_system_admin:
        verify_ownership(
            run.domain_id,
            resolve_caller_domain(principal, caller_domain),
            f"Run '{run_id}'",
        )

    # Sync factory for assembler
    from orchestrator.cosmo.db.session import get_sync_session
    from orchestrator.cosmo.ledger.gost_assembler import GOSTActAssembler

    assembler = GOSTActAssembler(db_session_factory=get_sync_session)

    # Parse findings if provided
    import json as _json
    findings = []
    if findings_json:
        try:
            findings = _json.loads(findings_json)
        except Exception:
            pass

    act = assembler.assemble_act(run_id, findings=findings)
    return act.model_dump(mode="json")


@router.get("/api/v1/runs/{run_id}/gost-act/html", summary="Get GOST Act HTML", response_class=HTMLResponse)
async def get_gost_act_html(
    run_id: str,
    findings_json: str | None = Query(None, alias="findings", description="JSON findings array (inline)"),
    caller_domain: str | None = Header(None, alias="X-Cosmo-Domain"),
    db: AsyncSession = Depends(get_db),
    principal: PrincipalContext = Depends(require_principal()),
):
    """Возвращает ГОСТ-Акт в HTML (для печати/просмотра).

    COS-068: authentication required + domain-scoping.
    """
    from orchestrator.cosmo.db.models import Run as RunModel
    from sqlalchemy import select
    result = await db.execute(select(RunModel).where(RunModel.id == run_id))
    run = result.scalar_one_or_none()
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Run {run_id} not found")

    # COS-068/COS-083: не-админ видит ГОСТ-Акт только своего домена
    if not principal.is_system_admin:
        verify_ownership(
            run.domain_id,
            resolve_caller_domain(principal, caller_domain),
            f"Run '{run_id}'",
        )

    from orchestrator.cosmo.db.session import get_sync_session
    from orchestrator.cosmo.ledger.gost_assembler import GOSTActAssembler

    assembler = GOSTActAssembler(db_session_factory=get_sync_session)

    import json as _json
    findings = []
    if findings_json:
        try:
            findings = _json.loads(findings_json)
        except Exception:
            pass

    html = assembler.generate_html_report(run_id, findings=findings)
    return HTMLResponse(content=html, status_code=200)