# -*- coding: utf-8 -*-
"""COS-055: Notification Manager — durable ядро поверх PostgreSQL.

Модели: cosmo/db/models_notifications.py (NotificationEventRow, NotificationRow,
NotificationSubscription, NotificationChannelConfig).

Фазы (packet scope):
  record_event()    — запись в durable event journal (idempotent по event_id);
  process_outbox()  — recipient resolution + in-app write + email fan-out;
  process_retries() — повтор retryable_failure до max_attempts, потом failed/DLQ;
  inbox operations  — list/mark_read/mark_all_read/unread_count;
  get_dlq()         — visibility терминальных failures.

Delivery semantics:
  notification_inbox write (in_app, state=delivered) = in-app delivered;
  email provider accept (state=sent)                 = sent;
  transient failure (state=retryable_failure)        = retry;
  exhausted retry (state=failed)                     = DLQ;
  повтор одного event_id                             = без дублей (UNIQUE).

Логи: payload scrubbed — секреты и чувствительные данные не попадают в лог.
"""
from __future__ import annotations

import datetime
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional, Sequence

from sqlalchemy import select, update, func
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.cosmo.db.models_notifications import (
    NotificationChannelConfig,
    NotificationEventRow,
    NotificationRow,
    NotificationSubscription,
)
from orchestrator.cosmo.notifications.policy import (
    EVENT_TYPES_V1,
    merge_membership,
    next_backoff_seconds,
    policy_from_row,
    resolve_recipients,
    safe_log_line,
    scrub_payload,
)
from orchestrator.cosmo.notifications.providers import (
    EmailProvider,
    default_provider,
)
from orchestrator.cosmo.notifications.redaction import hash_identifier

logger = logging.getLogger("cosmoport.notifications")

MemberResolver = Callable[
    [AsyncSession, str, str, Dict[str, Any]], Awaitable[Optional[List[str]]]
]


def _uid() -> str:
    return uuid.uuid4().hex[:16]


def _utcnow() -> datetime.datetime:
    """Naive UTC — соответствует DateTime (без timezone) в models_notifications."""
    return datetime.datetime.utcnow()


# ── Processing report ──


@dataclass
class ProcessReport:
    """Итог одного process_outbox / process_retries прогона."""

    events_processed: int = 0
    in_app_delivered: int = 0
    in_app_duplicates: int = 0
    emails_sent: int = 0
    emails_retryable: int = 0
    emails_failed: int = 0
    no_recipient: int = 0
    notes: List[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "events_processed": self.events_processed,
            "in_app_delivered": self.in_app_delivered,
            "in_app_duplicates": self.in_app_duplicates,
            "emails_sent": self.emails_sent,
            "emails_retryable": self.emails_retryable,
            "emails_failed": self.emails_failed,
            "no_recipient": self.no_recipient,
            "notes": self.notes,
        }


# ── Notification Manager ──


class NotificationManager:
    """Durable notification manager одного портала (bounded module)."""

    def __init__(
        self,
        email_provider: Optional[EmailProvider] = None,
        membership_resolver: Optional[MemberResolver] = None,
        default_max_attempts: int = 5,
    ) -> None:
        self._email_provider: EmailProvider = email_provider or default_provider()
        self._membership_resolver = membership_resolver
        self._default_max_attempts = default_max_attempts

    # ══════════════════════════════════════════════════════════════
    # Phase 1: record_event — durable event journal (transactional outbox)
    # ══════════════════════════════════════════════════════════════

    async def record_event(
        self,
        session: AsyncSession,
        *,
        event_type: str,
        aggregate_type: str,
        aggregate_id: str,
        payload: Optional[Dict[str, Any]] = None,
        correlation_id: Optional[str] = None,
        event_id: Optional[str] = None,
        occurred_at: Optional[datetime.datetime] = None,
        title: str = "",
        message: str = "",
        severity: Optional[str] = None,
        explicit_recipients: Optional[Sequence[str]] = None,
        domain_id: Optional[str] = None,
        project_id: Optional[str] = None,
        app_id: Optional[str] = None,
    ) -> tuple[NotificationEventRow, bool]:
        """Записать событие в durable journal. Idempotent по event_id.

        Вызывается В ТОЙ ЖЕ транзакции, что и изменение агрегата
        (transactional outbox). Возвращает (event_row, created).
        """
        from orchestrator.cosmo.notifications.policy import DEFAULT_SEVERITY

        if event_type not in EVENT_TYPES_V1:
            raise ValueError(
                f"Unknown event_type '{event_type}'. V1 taxonomy: {sorted(EVENT_TYPES_V1)}"
            )
        if not aggregate_id:
            raise ValueError("aggregate_id is required")

        eid = event_id or f"evt-{uuid.uuid4().hex}"
        existing = await session.get(NotificationEventRow, eid)
        if existing is not None:
            logger.info(safe_log_line("[OUTBOX:dedup]", {"event_id": eid}))
            return existing, False

        safe_payload = dict(payload or {})
        safe_payload["title"] = title or f"{event_type}: {aggregate_id}"
        safe_payload["message"] = message
        safe_payload["recipients_explicit"] = list(explicit_recipients or [])
        safe_payload["severity"] = severity or DEFAULT_SEVERITY.get(event_type, "info")

        row = NotificationEventRow(
            event_id=eid,
            event_type=event_type,
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            occurred_at=occurred_at or _utcnow(),
            payload=safe_payload,
            correlation_id=correlation_id,
            domain_id=domain_id,
            project_id=project_id,
            app_id=app_id,
            processed=False,
        )
        session.add(row)
        logger.info(safe_log_line("[OUTBOX:recorded]", {
            "event_id": eid, "event_type": event_type,
            "aggregate": f"{aggregate_type}/{aggregate_id}",
        }))
        return row, True

    # ══════════════════════════════════════════════════════════════
    # Phase 2: process_outbox
    # ══════════════════════════════════════════════════════════════

    async def process_outbox(
        self,
        session: AsyncSession,
        *,
        batch_size: int = 50,
        now: Optional[datetime.datetime] = None,
    ) -> ProcessReport:
        """Обработать unprocessed-события. FOR UPDATE SKIP LOCKED — без дублей."""
        report = ProcessReport()
        now = now or _utcnow()

        rows = (
            await session.execute(
                select(NotificationEventRow)
                .where(NotificationEventRow.processed.is_(False))
                .order_by(NotificationEventRow.occurred_at)
                .limit(batch_size)
                .with_for_update(skip_locked=True)
            )
        ).scalars().all()

        for event_row in rows:
            report.events_processed += 1
            payload: Dict[str, Any] = dict(event_row.payload or {})

            # ── Recipient resolution ──
            explicit = payload.get("recipients_explicit") or []
            members: Optional[List[str]] = None
            if not explicit and self._membership_resolver is not None:
                members = await self._membership_resolver(
                    session, event_row.aggregate_type, event_row.aggregate_id, payload
                )
            recipients = resolve_recipients(
                explicit=[str(r) for r in explicit if str(r).strip()],
                project_members=members,
            )

            if not recipients:
                # Явная фиксация: событие с no_recipient не теряется молча.
                event_row.processed = True
                event_row.processed_at = now
                report.no_recipient += 1
                logger.warning(safe_log_line("[OUTBOX:no_recipient]", {
                    "event_id": event_row.event_id,
                    "event_type": event_row.event_type,
                }))
                continue

            # ── Subscription filter ──
            filtered: List[str] = []
            for recipient in recipients:
                if await self._subscription_allows(session, recipient, event_row.event_type):
                    filtered.append(recipient)

            if not filtered:
                event_row.processed = True
                event_row.processed_at = now
                report.notes.append(f"event {event_row.event_id}: filtered by subscriptions")
                continue

            # ── Fan-out: in-app + email ──
            title = str(payload.get("title") or f"{event_row.event_type}: {event_row.aggregate_id}")
            message = str(payload.get("message") or "")
            severity = str(payload.get("severity") or "info")
            safe_payload = scrub_payload(payload)

            for recipient in filtered:
                # In-app: write = delivered
                inbox_row = NotificationRow(
                    event_id=event_row.event_id,
                    recipient_id=recipient,
                    channel="in_app",
                    notification_type=event_row.event_type,
                    severity=severity,
                    title=title,
                    message=message,
                    state="delivered",
                )
                session.add(inbox_row)

                # Email: lifecycle через state (если адрес похож на email)
                from orchestrator.cosmo.notifications.policy import looks_like_email
                if looks_like_email(recipient):
                    email_row = NotificationRow(
                        event_id=event_row.event_id,
                        recipient_id=recipient,
                        channel="email",
                        notification_type=event_row.event_type,
                        severity=severity,
                        title=title,
                        message=message,
                        state="pending",
                        max_attempts=self._default_max_attempts,
                    )
                    session.add(email_row)

            try:
                await session.flush()
                report.in_app_delivered += len(filtered)
            except Exception:
                await session.rollback()
                # Конкурентный worker уже записал эти строки → dedup by UNIQUE.
                report.in_app_duplicates += len(filtered)
                logger.info(safe_log_line("[INBOX:dedup-concurrent]", {
                    "event_id": event_row.event_id,
                }))
                continue

            # ── Email delivery attempt ──
            email_result = await session.execute(
                select(NotificationRow).where(
                    NotificationRow.event_id == event_row.event_id,
                    NotificationRow.channel == "email",
                    NotificationRow.state == "pending",
                )
            )
            email_rows = email_result.scalars().all()

            for email_row in email_rows:
                await self._attempt_email_send(email_row, now=now, report=report)

            event_row.processed = True
            event_row.processed_at = now

        await session.commit()
        return report

    # ══════════════════════════════════════════════════════════════
    # Email retry
    # ══════════════════════════════════════════════════════════════

    async def process_retries(
        self,
        session: AsyncSession,
        *,
        now: Optional[datetime.datetime] = None,
        batch_size: int = 100,
    ) -> ProcessReport:
        """Повторить retryable_failure с наступившим next_retry_at."""
        report = ProcessReport()
        now = now or _utcnow()

        rows = (
            await session.execute(
                select(NotificationRow)
                .where(
                    NotificationRow.state == "retryable_failure",
                    NotificationRow.next_retry_at <= now,
                    NotificationRow.channel == "email",
                )
                .order_by(NotificationRow.next_retry_at)
                .limit(batch_size)
                .with_for_update(skip_locked=True)
            )
        ).scalars().all()

        for row in rows:
            row.state = "sending"
            await self._attempt_email_send_on_row(row, now=now, report=report)

        await session.commit()
        return report

    async def _attempt_email_send(
        self, email_row: NotificationRow, *, now: datetime.datetime, report: ProcessReport,
    ) -> None:
        email_row.state = "sending"
        email_row.attempts = (email_row.attempts or 0) + 1
        await self._attempt_email_send_on_row(email_row, now=now, report=report)

    async def _attempt_email_send_on_row(
        self, row: NotificationRow, *, now: datetime.datetime, report: ProcessReport,
    ) -> None:
        """Одна попытка → sent | retryable_failure | failed."""
        row.attempts = (row.attempts or 0) + 1
        try:
            result = self._email_provider.send(
                to=row.recipient_id, subject=row.title, body=row.message,
            )
        except Exception as exc:
            # Provider library бросила исключение → transient.
            class _R:
                accepted = False
                transient = True
                error = str(exc)
            result = _R()

        if result.accepted:
            row.state = "sent"
            row.last_error = None
            row.next_retry_at = None
            row.claimed_at = now
            report.emails_sent += 1
        elif result.transient and row.attempts < row.max_attempts:
            delay = next_backoff_seconds(row.attempts)
            row.state = "retryable_failure"
            row.last_error = (result.error or "transient")[:500]
            row.next_retry_at = now + datetime.timedelta(seconds=delay)
            report.emails_retryable += 1
            logger.warning(safe_log_line("[EMAIL:retryable]", {
                "event_id": row.event_id,
                # COS-079: recipient_id не появляется в логах в открытом виде
                "recipient_sha": hash_identifier(row.recipient_id),
                "attempt": row.attempts, "retry_in_s": delay,
            }))
        else:
            row.state = "failed"
            row.last_error = (result.error or "terminal/exhausted")[:500]
            row.next_retry_at = None
            report.emails_failed += 1
            logger.error(safe_log_line("[EMAIL:failed→DLQ]", {
                "event_id": row.event_id,
                # COS-079: recipient_id не появляется в логах в открытом виде
                "recipient_sha": hash_identifier(row.recipient_id),
                "attempts": row.attempts,
            }))

    # ══════════════════════════════════════════════════════════════
    # In-app inbox operations
    # ══════════════════════════════════════════════════════════════

    async def list_inbox(
        self,
        session: AsyncSession,
        *,
        recipient_id: str,
        channel: str = "in_app",
        unread_only: bool = False,
        limit: int = 100,
    ) -> List[NotificationRow]:
        stmt = (
            select(NotificationRow)
            .where(
                NotificationRow.recipient_id == recipient_id,
                NotificationRow.channel == channel,
            )
            .order_by(NotificationRow.created_at.desc())
            .limit(limit)
        )
        if unread_only:
            stmt = stmt.where(NotificationRow.read_at.is_(None))
        return list((await session.execute(stmt)).scalars().all())

    async def unread_count(
        self, session: AsyncSession, *, recipient_id: str, channel: str = "in_app",
    ) -> int:
        result = await session.execute(
            select(func.count(NotificationRow.id)).where(
                NotificationRow.recipient_id == recipient_id,
                NotificationRow.channel == channel,
                NotificationRow.read_at.is_(None),
            )
        )
        return int(result.scalar_one())

    async def mark_read(
        self, session: AsyncSession, *, recipient_id: str, notification_id: str,
    ) -> bool:
        row = await session.get(NotificationRow, notification_id)
        if row is None or row.recipient_id != recipient_id:
            return False
        if row.read_at is None:
            row.read_at = _utcnow()
            await session.commit()
        return True

    async def mark_all_read(self, session: AsyncSession, *, recipient_id: str) -> int:
        result = await session.execute(
            update(NotificationRow)
            .where(
                NotificationRow.recipient_id == recipient_id,
                NotificationRow.read_at.is_(None),
            )
            .values(read_at=_utcnow())
        )
        await session.commit()
        return int(result.rowcount or 0)

    # ══════════════════════════════════════════════════════════════
    # DLQ visibility
    # ══════════════════════════════════════════════════════════════

    async def get_dlq(
        self, session: AsyncSession, *, limit: int = 100,
    ) -> List[NotificationRow]:
        """Терминально неудавшиеся доставки — явная очередь мёртвых писем."""
        rows = await session.execute(
            select(NotificationRow)
            .where(NotificationRow.state == "failed")
            .order_by(NotificationRow.updated_at.desc())
            .limit(limit)
        )
        return list(rows.scalars().all())

    async def replay_dlq(
        self, session: AsyncSession, *, notification_id: str,
    ) -> Optional[NotificationRow]:
        """COS-079: повторная отправка письма из DLQ одним действием оператора.

        State после возврата честный: sent | retryable_failure | failed.
        """
        row = await session.get(NotificationRow, notification_id)
        if row is None or row.state != "failed" or row.channel != "email":
            return None
        report = ProcessReport()
        now = _utcnow()
        await self._attempt_email_send_on_row(row, now=now, report=report)
        await session.commit()
        return row

    # ══════════════════════════════════════════════════════════════
    # Subscription policy
    # ══════════════════════════════════════════════════════════════

    async def _subscription_allows(
        self, session: AsyncSession, user_id: str, event_type: str,
    ) -> bool:
        row = await session.get(NotificationSubscription, user_id)
        if row is None:
            return True  # нет записи = ALL
        policy = policy_from_row(
            row.user_id, row.policy, row.selected_event_types or [],
            row.blocked_event_types or [],
        )
        return policy.allows(event_type)


# ── Module-level singleton (один Manager на портал) ──

_manager: Optional[NotificationManager] = None


def get_manager() -> NotificationManager:
    """Один логический Manager на процесс портала."""
    global _manager
    if _manager is None:
        _manager = NotificationManager()
    return _manager


def set_manager(manager: NotificationManager) -> None:
    """Переопределить singleton (тесты, ops-конфигурация провайдера)."""
    global _manager
    _manager = manager
