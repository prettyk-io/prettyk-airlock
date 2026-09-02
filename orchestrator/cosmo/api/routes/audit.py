"""Cosmoport 2.0 — Audit Log REST API endpoints.

Tracks security events, user operations, state transitions, and compliance audit trail.
"""
from __future__ import annotations

import datetime
import uuid
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.cosmo.api.deps import get_db, require_principal, require_system_admin
from orchestrator.cosmo.domain.rbac import PrincipalContext

router = APIRouter(prefix="/api/v1/audit", tags=["audit"])


# ── Schemas ────────────────────────────────────────────────────────────

class AuditEvent(BaseModel):
    id: str
    timestamp: datetime.datetime
    user_id: str
    role: str = "operator"
    action: str = Field(..., description="login | trigger_run | gate_decision | transfer_zone | create_app | commit_push")
    resource_type: str = Field(..., description="run | gate | release | app | domain | repo")
    resource_id: str
    status: str = Field(default="success", description="success | failed | blocked")
    ip_address: str = "127.0.0.1"
    details_json: dict = Field(default_factory=dict)


class CreateAuditEventRequest(BaseModel):
    user_id: str = Field(..., min_length=1)
    role: str = "operator"
    action: str = Field(..., min_length=1)
    resource_type: str = Field(..., min_length=1)
    resource_id: str = Field(..., min_length=1)
    status: str = "success"
    ip_address: str = "127.0.0.1"
    details_json: dict = Field(default_factory=dict)


# ── In-memory fallback / audit seed records ────────────────────────────

_AUDIT_LOG_RECORDS: list[AuditEvent] = [
  AuditEvent(
    id="aud-001",
    timestamp=datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=15),
    user_id="operator@cosmo.local",
    role="secops-lead",
    action="gate_decision",
    resource_type="gate",
    resource_id="gate-qg",
    status="success",
    ip_address="192.168.1.104",
    details_json={
      "decision": "pass",
      "signature": "sig-sha256-verified-8890",
      "reason": "Все SAST/DAST проверки пройдены без блокирующих замечаний",
    },
  ),
  AuditEvent(
    id="aud-002",
    timestamp=datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=45),
    user_id="devops-lead@cbr.ru",
    role="devops",
    action="transfer_zone",
    resource_type="release",
    resource_id="rel-cbr-2026-q3",
    status="success",
    ip_address="10.200.4.12",
    details_json={
      "from_zone": "ЗР",
      "to_zone": "ЗТ",
      "target_env": "stage-banking",
    },
  ),
  AuditEvent(
    id="aud-003",
    timestamp=datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=2),
    user_id="developer@payments.io",
    role="developer",
    action="commit_push",
    resource_type="repo",
    resource_id="payments/api",
    status="success",
    ip_address="172.16.0.50",
    details_json={
      "branch": "main",
      "commit": "fa482c1",
      "file": "scenarios/auth.wire",
    },
  ),
  AuditEvent(
    id="aud-004",
    timestamp=datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=3, minutes=10),
    user_id="cron-service",
    role="system",
    action="trigger_run",
    resource_type="run",
    resource_id="run-101",
    status="success",
    ip_address="127.0.0.1",
    details_json={
      "plan_id": "plan-steel",
      "trigger": "scheduled",
    },
  ),
  AuditEvent(
    id="aud-005",
    timestamp=datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=5),
    user_id="unknown_attacker",
    role="guest",
    action="login_attempt",
    resource_type="auth",
    resource_id="portal01",
    status="failed",
    ip_address="45.142.122.9",
    details_json={
      "error": "invalid_credentials",
      "attempts": 3,
    },
  ),
]


def record_system_event(
    *,
    user_id: str,
    action: str,
    resource_type: str,
    resource_id: str,
    status: str = "success",
    details: Optional[dict] = None,
) -> AuditEvent:
    """COS-096: системная audit-запись без HTTP-запроса (webhook и т.п.).

    Тот же in-memory surface, что и POST /audit: видно в /api/v1/audit
    и CSV-экспорте. Переживает только процесс приложения (честная
    граница; durable-таблица — follow-up вне миграционного freeze).
    """
    event = AuditEvent(
        id=f"aud-sys-{uuid.uuid4().hex[:12]}",
        timestamp=datetime.datetime.now(datetime.timezone.utc),
        user_id=user_id,
        role="forge",
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        status=status,
        details_json=details or {},
    )
    _AUDIT_LOG_RECORDS.insert(0, event)
    return event


# ── Endpoints ──────────────────────────────────────────────────────────

@router.get("", response_model=list[AuditEvent])
async def list_audit_events(
    user_id: Optional[str] = Query(None, description="Filter by user ID"),
    action: Optional[str] = Query(None, description="Filter by action name"),
    resource_type: Optional[str] = Query(None, description="Filter by resource type"),
    audit_status: Optional[str] = Query(None, alias="status", description="Filter by status"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    principal: PrincipalContext = Depends(require_principal()),
) -> list[AuditEvent]:
    """List audit trail events with optional filtering.

    COS-068: authentication required — audit trail содержит IP-адреса
    и персональные действия пользователей.
    """
    results = list(_AUDIT_LOG_RECORDS)

    if user_id:
        results = [e for e in results if user_id.lower() in e.user_id.lower()]
    if action:
        results = [e for e in results if action.lower() in e.action.lower()]
    if resource_type:
        results = [e for e in results if resource_type.lower() in e.resource_type.lower()]
    if audit_status:
        results = [e for e in results if e.status == audit_status]

    # Sort newest first
    results.sort(key=lambda x: x.timestamp, reverse=True)
    return results[offset : offset + limit]


@router.post("", response_model=AuditEvent, status_code=status.HTTP_201_CREATED)
async def create_audit_event(
    body: CreateAuditEventRequest,
    principal: PrincipalContext = Depends(require_system_admin()),
) -> AuditEvent:
    """Record an audit event.

    COS-068: system-admin only — анонимная запись в audit trail позволяла
    подделывать/отравлять журнал аудита (integrity hole).
    """
    event = AuditEvent(
        id=f"aud-{uuid.uuid4().hex[:8]}",
        timestamp=datetime.datetime.now(datetime.timezone.utc),
        user_id=body.user_id,
        role=body.role,
        action=body.action,
        resource_type=body.resource_type,
        resource_id=body.resource_id,
        status=body.status,
        ip_address=body.ip_address,
        details_json=body.details_json,
    )
    _AUDIT_LOG_RECORDS.insert(0, event)
    return event


@router.get("/{event_id}", response_model=AuditEvent)
async def get_audit_event(
    event_id: str,
    principal: PrincipalContext = Depends(require_principal()),
) -> AuditEvent:
    """Get detailed audit event.

    COS-068: authentication required.
    """
    found = next((e for e in _AUDIT_LOG_RECORDS if e.id == event_id), None)
    if found is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Audit event '{event_id}' not found",
        )
    return found


@router.get("/export/csv")
async def export_audit_csv(
    principal: PrincipalContext = Depends(require_principal()),
) -> Response:
    """Export audit log as CSV formatted stream.

    COS-068: authentication required (полный экспорт журнала).
    """
    lines = ["id,timestamp,user_id,role,action,resource_type,resource_id,status,ip_address"]
    for e in _AUDIT_LOG_RECORDS:
        ts = e.timestamp.isoformat()
        lines.append(f"{e.id},{ts},{e.user_id},{e.role},{e.action},{e.resource_type},{e.resource_id},{e.status},{e.ip_address}")
    csv_content = "\n".join(lines)
    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=cosmo_audit_events.csv"},
    )
