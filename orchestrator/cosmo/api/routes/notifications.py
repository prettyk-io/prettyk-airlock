"""COS-055 / COS-065: Notification API.

Слои:
  * Webhook config CRUD (COS-065 in-memory placeholder — durable замена вне V1);
  * COS-055 durable endpoints: inbox (BELL), outbox visibility, process tick.

Recipient для inbox — текущий principal (Control Plane auth), не query-параметр.

COS-092: in-body auth унифицирована с deps-guard'ами (образец COS-091):
  * ops-поверхность (webhook-config CRUD, DLQ list/replay, outbox
    visibility, process tick) — require_capability(DOMAIN_CONFIGURE):
    401 аноним, 403 без capability (hold: ADMIN_SEC / SERVICE_ADMIN, ЗР);
  * личная поверхность (inbox read/unread/read-mark/read-all, sse-ticket) —
    require_principal(): recipient резолвится из principal.user_id
    по построению, домен и capability не участвуют.
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.cosmo.api.deps import get_db, require_capability, require_principal
from orchestrator.cosmo.domain.rbac import Action, PrincipalContext
from orchestrator.cosmo.notifications.manager import get_manager
from orchestrator.cosmo.db.models_notifications import NotificationEventRow, NotificationRow

router = APIRouter(prefix="/api/v1/notifications", tags=["notifications"])

# COS-065: In-memory configs — placeholder until webhook config persistence
_configs: dict[str, list[dict]] = {}


class WebhookConfig(BaseModel):
    id: str = Field(..., min_length=1)
    url: str = Field(..., min_length=1)
    channels: list[str] = Field(default_factory=lambda: ["email"])
    enabled: bool = True


@router.get("", response_model=list[WebhookConfig])
async def list_configs(
    domain_id: str | None = None,
    principal: PrincipalContext = Depends(
        require_capability(Action.DOMAIN_CONFIGURE, domain_binding="identity")
    ),
):
    if domain_id:
        return [WebhookConfig(**c) for c in _configs.get(domain_id, [])]
    result = []
    for cfgs in _configs.values():
        for c in cfgs:
            result.append(WebhookConfig(**c))
    return result


@router.post("", status_code=status.HTTP_201_CREATED, response_model=WebhookConfig)
async def create_config(
    domain_id: str,
    body: WebhookConfig,
    principal: PrincipalContext = Depends(
        require_capability(Action.DOMAIN_CONFIGURE, domain_binding="identity")
    ),
):
    _configs.setdefault(domain_id, []).append(body.model_dump())
    return body


@router.delete("/{config_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_config(
    config_id: str,
    domain_id: str,
    principal: PrincipalContext = Depends(
        require_capability(Action.DOMAIN_CONFIGURE, domain_binding="identity")
    ),
):
    cfgs = _configs.get(domain_id, [])
    for i, c in enumerate(cfgs):
        if c["id"] == config_id:
            cfgs.pop(i)
            return
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Config not found")


# ════════════════════════════════════════════════════════════════════
# COS-055: Durable in-app inbox (BELL)
# ════════════════════════════════════════════════════════════════════


class InboxItem(BaseModel):
    id: str
    event_id: str
    event_type: str
    severity: str
    title: str
    message: str
    channel: str
    state: str
    is_read: bool
    read_at: Optional[str] = None
    created_at: str

    @classmethod
    def from_row(cls, row: NotificationRow) -> "InboxItem":
        return cls(
            id=row.id,
            event_id=row.event_id,
            event_type=row.notification_type,
            severity=row.severity,
            title=row.title,
            message=row.message,
            channel=row.channel,
            state=row.state,
            is_read=row.read_at is not None,
            read_at=row.read_at.isoformat() if row.read_at else None,
            created_at=row.created_at.isoformat() if row.created_at else "",
        )


class ReadResult(BaseModel):
    ok: bool
    marked: int = 0


@router.get("/inbox", response_model=list[InboxItem])
async def list_inbox(
    unread_only: bool = Query(False, alias="unread_only"),
    limit: int = Query(100, ge=1, le=500),
    principal: PrincipalContext = Depends(require_principal()),
    db: AsyncSession = Depends(get_db),
):
    """In-app inbox текущего пользователя (recipient = principal.user_id)."""
    manager = get_manager()
    rows = await manager.list_inbox(
        db, recipient_id=principal.user_id, unread_only=unread_only, limit=limit,
    )
    return [InboxItem.from_row(r) for r in rows]


@router.get("/inbox/unread-count")
async def inbox_unread_count(
    principal: PrincipalContext = Depends(require_principal()),
    db: AsyncSession = Depends(get_db),
):
    manager = get_manager()
    count = await manager.unread_count(db, recipient_id=principal.user_id)
    return {"unread": count}


@router.post("/inbox/{notification_id}/read", response_model=ReadResult)
async def mark_notification_read(
    notification_id: str,
    principal: PrincipalContext = Depends(require_principal()),
    db: AsyncSession = Depends(get_db),
):
    manager = get_manager()
    ok = await manager.mark_read(
        db, recipient_id=principal.user_id, notification_id=notification_id,
    )
    if not ok:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found")
    return ReadResult(ok=True, marked=1)


@router.post("/inbox/read-all", response_model=ReadResult)
async def mark_all_inbox_read(
    principal: PrincipalContext = Depends(require_principal()),
    db: AsyncSession = Depends(get_db),
):
    manager = get_manager()
    marked = await manager.mark_all_read(db, recipient_id=principal.user_id)
    return ReadResult(ok=True, marked=marked)


# ════════════════════════════════════════════════════════════════════
# COS-075: SSE stream ticket — auth without bearer-in-URL for EventSource
# ════════════════════════════════════════════════════════════════════


class StreamTicket(BaseModel):
    ticket: str
    recipient_id: str
    expires_in: int


@router.post("/sse-ticket", response_model=StreamTicket)
async def create_stream_ticket(
    principal: PrincipalContext = Depends(require_principal()),
):
    """Выдать short-TTL ticket для SSE-стрима уведомлений.

    EventSource не умеет custom headers — bearer в URL недопустим. Клиент
    получает ticket под обычной bearer-аутентификацией и открывает
    GET /api/v1/notifications/stream?ticket=... Recipient резолвится из
    ticket (привязан к principal.user_id), не из query-параметра.
    """
    from orchestrator.cosmo.api.sse_tickets import TICKET_TTL_S, mint_ticket

    return StreamTicket(
        ticket=mint_ticket(principal.user_id),
        recipient_id=principal.user_id,
        expires_in=TICKET_TTL_S,
    )


# ════════════════════════════════════════════════════════════════════
# COS-079: DLQ visibility + operator replay
# ════════════════════════════════════════════════════════════════════


class DlqItem(BaseModel):
    id: str
    event_id: str
    event_type: str
    severity: str
    title: str
    recipient_id: str
    channel: str
    state: str
    attempts: int
    max_attempts: int
    last_error: Optional[str] = None
    created_at: str
    updated_at: Optional[str] = None

    @classmethod
    def from_row(cls, row: NotificationRow) -> "DlqItem":
        return cls(
            id=row.id,
            event_id=row.event_id,
            event_type=row.notification_type,
            severity=row.severity,
            title=row.title,
            recipient_id=row.recipient_id,
            channel=row.channel,
            state=row.state,
            attempts=row.attempts or 0,
            max_attempts=row.max_attempts or 0,
            last_error=row.last_error,
            created_at=row.created_at.isoformat() if row.created_at else "",
            updated_at=row.updated_at.isoformat() if row.updated_at else None,
        )


class DlqReplayResult(BaseModel):
    id: str
    state: str
    attempts: int
    last_error: Optional[str] = None


@router.get("/dlq", response_model=list[DlqItem])
async def list_dlq(
    limit: int = Query(100, ge=1, le=500),
    principal: PrincipalContext = Depends(
        require_capability(Action.DOMAIN_CONFIGURE, domain_binding="identity")
    ),
    db: AsyncSession = Depends(get_db),
):
    """Терминально неудавшиеся email-доставки (DLQ) — поверхность оператора."""
    manager = get_manager()
    rows = await manager.get_dlq(db, limit=limit)
    return [DlqItem.from_row(r) for r in rows]


@router.post("/dlq/{notification_id}/replay", response_model=DlqReplayResult)
async def replay_dlq(
    notification_id: str,
    principal: PrincipalContext = Depends(
        require_capability(Action.DOMAIN_CONFIGURE, domain_binding="identity")
    ),
    db: AsyncSession = Depends(get_db),
):
    """Одна повторная попытка отправки из DLQ. State после — честный.

    404 если запись не найдена, не в DLQ (state != failed) или не email.
    """
    manager = get_manager()
    row = await manager.replay_dlq(db, notification_id=notification_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="DLQ item not found")
    return DlqReplayResult(
        id=row.id, state=row.state, attempts=row.attempts or 0, last_error=row.last_error,
    )


# ════════════════════════════════════════════════════════════════════
# COS-055: Outbox visibility + processing tick (ops)
# ════════════════════════════════════════════════════════════════════


class OutboxStatus(BaseModel):
    event_id: str
    aggregate_type: str
    aggregate_id: str
    event_type: str
    processed: bool
    correlation_id: Optional[str] = None
    occurred_at: str
    processed_at: Optional[str] = None


class ProcessReportModel(BaseModel):
    report: dict[str, Any]


@router.get("/outbox/{event_id}", response_model=OutboxStatus)
async def get_outbox_status(
    event_id: str,
    principal: PrincipalContext = Depends(
        require_capability(Action.DOMAIN_CONFIGURE, domain_binding="identity")
    ),
    db: AsyncSession = Depends(get_db),
):
    """Visibility статуса события (для оператора и диагностики)."""
    row = await db.get(NotificationEventRow, event_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Event not found")
    return OutboxStatus(
        event_id=row.event_id,
        aggregate_type=row.aggregate_type,
        aggregate_id=row.aggregate_id,
        event_type=row.event_type,
        processed=row.processed,
        correlation_id=row.correlation_id,
        occurred_at=row.occurred_at.isoformat() if row.occurred_at else "",
        processed_at=row.processed_at.isoformat() if row.processed_at else None,
    )


@router.post("/process", response_model=ProcessReportModel)
async def process_outbox_tick(
    batch_size: int = Query(50, ge=1, le=500),
    principal: PrincipalContext = Depends(
        require_capability(Action.DOMAIN_CONFIGURE, domain_binding="identity")
    ),
    db: AsyncSession = Depends(get_db),
):
    """Ручной tick обработки outbox + retries (V1: ops/тесты)."""
    manager = get_manager()
    report = await manager.process_outbox(db, batch_size=batch_size)
    retry_report = await manager.process_retries(db)
    combined = report.as_dict()
    combined["retries"] = retry_report.as_dict()
    return ProcessReportModel(report=combined)
