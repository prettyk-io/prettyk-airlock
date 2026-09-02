"""
COS-055: Notification Manager — durable ORM models.

Таблицы:
  notification_events            — durable event/outbox journal (source of processing)
  notification_inbox             — per-recipient notification journal (in_app + email)
  notification_subscriptions     — V1 subscription policy (ALL / SELECTED / blocklist)
  notification_channel_configs   — durable provider/channel configs (замена in-memory stub)

Правила:
  - PostgreSQL — durable source of truth; Valkey допускается только для live/SSE projection.
  - Dedup: UNIQUE(event_id, recipient_id, channel) — повторная обработка event_id
    не создаёт дубликатов.
  - Состояния inbox: created -> pending -> sending -> sent (email)
    / delivered (in_app) / retryable_failure -> failed (DLQ).
"""
from __future__ import annotations

import datetime
import uuid
from typing import Any, Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from orchestrator.cosmo.db.session import Base


def _uid() -> str:
    return uuid.uuid4().hex[:12]


# ══════════════════════════════════════════════════════════════════════════════
# COS-055: notification_events — durable outbox
# ══════════════════════════════════════════════════════════════════════════════

class NotificationEventRow(Base):
    """Durable event journal (transactional outbox). PK = event_id (idempotency)."""
    __tablename__ = "notification_events"
    __table_args__ = (
        Index("ix_notif_events_type", "event_type"),
        Index("ix_notif_events_correlation", "correlation_id"),
        Index("ix_notif_events_occurred", "occurred_at"),
        Index("ix_notif_events_processed", "processed"),
        {"comment": "COS-055: durable event/outbox journal уведомлений"},
    )

    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    aggregate_type: Mapped[str] = mapped_column(String(32), nullable=False, default="system")
    aggregate_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    occurred_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.utcnow, nullable=False
    )
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    correlation_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    domain_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    project_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    app_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    recipient_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    processed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    processed_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.utcnow, nullable=False
    )


# ══════════════════════════════════════════════════════════════════════════════
# COS-055: notification_inbox — per-recipient journal
# ══════════════════════════════════════════════════════════════════════════════

class NotificationRow(Base):
    """Одно уведомление для одного (recipient, channel). Dedup по уникальному ключу."""
    __tablename__ = "notification_inbox"
    __table_args__ = (
        UniqueConstraint("event_id", "recipient_id", "channel", name="uq_notif_dedup"),
        Index("ix_notif_inbox_recipient", "recipient_id", "channel", "state"),
        Index("ix_notif_inbox_state", "state"),
        Index("ix_notif_inbox_next_retry", "next_retry_at"),
        Index("ix_notif_inbox_created", "created_at"),
        CheckConstraint("channel IN ('in_app','email')", name="ck_notif_channel"),
        {"comment": "COS-055: inbox journal уведомлений (in_app + email delivery)"},
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uid)
    event_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("notification_events.event_id", ondelete="CASCADE"), nullable=False
    )
    recipient_id: Mapped[str] = mapped_column(String(128), nullable=False)
    channel: Mapped[str] = mapped_column(String(16), nullable=False)

    # Denormalized snapshot — inbox читается без join на event
    notification_type: Mapped[str] = mapped_column(String(64), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False, default="info")
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False, default="")

    # created -> pending -> sending -> sent | retryable_failure -> failed
    # in_app: created -> delivered (write = delivered)
    state: Mapped[str] = mapped_column(String(32), nullable=False, default="created")
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=5, nullable=False)
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # redacted
    provider_message_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    claimed_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime, nullable=True)
    next_retry_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime, nullable=True)

    # in-app unread/read state
    read_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime, nullable=True)

    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.utcnow,
        onupdate=datetime.datetime.utcnow, nullable=False,
    )


# ══════════════════════════════════════════════════════════════════════════════
# COS-055: notification_subscriptions — V1 policy
# ══════════════════════════════════════════════════════════════════════════════

class NotificationSubscription(Base):
    """Подписка пользователя. Нет строки = in-app ALL (без email)."""
    __tablename__ = "notification_subscriptions"
    __table_args__ = (
        CheckConstraint("policy IN ('all','selected')", name="ck_notif_sub_policy"),
        {"comment": "COS-055: подписки пользователей (V1: all/selected + blocklist)"},
    )

    user_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    policy: Mapped[str] = mapped_column(String(16), default="all", nullable=False)
    selected_event_types: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    blocked_event_types: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    domain_scope: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    email_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.utcnow,
        onupdate=datetime.datetime.utcnow, nullable=False,
    )


# ══════════════════════════════════════════════════════════════════════════════
# COS-055: notification_channel_configs — durable provider configs
# ══════════════════════════════════════════════════════════════════════════════

class NotificationChannelConfig(Base):
    """Durable конфиг канала/провайдера (замена in-memory _configs stub COS-065)."""
    __tablename__ = "notification_channel_configs"
    __table_args__ = (
        Index("ix_notif_cfg_domain", "domain_id"),
        {"comment": "COS-055: durable конфиги каналов доставки"},
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uid)
    domain_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    channel: Mapped[str] = mapped_column(String(32), nullable=False, default="webhook")
    endpoint: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    channels: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    secret_ref: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)  # только ref
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.utcnow, nullable=False
    )
