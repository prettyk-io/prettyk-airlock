# -*- coding: utf-8 -*-
"""COS-074: Gateway lease/TTL semantics for offline dispatch.

CONTROLLED_GATEWAY_RELAY подразумевает живой gateway-grant. В офлайн-
исполнении gateway недоступен, поэтому "разрешение на отправку"
моделируется явным lease-объектом с TTL:

  - Одновременно не более одного активного lease на revision_key
    (single-active invariant; issue() отзывает предыдущий).
  - Истечение детерминированно: now >= expires_at -> EXPIRED.
  - Dispatch без активного lease запрещён (LeaseRequiredError) —
    диода не пишет чанки в канал без grant; attempts не растут.

Lease-реестр in-memory: durable-требование карточки COS-074 — только
transfer_failed-терминал на registry; lease-политика — runtime-семантика.
"""
from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class LeaseState(str, Enum):
    ACTIVE = "active"
    EXPIRED = "expired"
    REVOKED = "revoked"


class LeaseError(Exception):
    """Базовая ошибка lease-семантики."""


class LeaseRequiredError(LeaseError):
    """Нет активного lease для revision — dispatch запрещён."""

    def __init__(self, revision_key: str, reason: str = "no active lease"):
        self.revision_key = revision_key
        self.reason = reason
        super().__init__(
            f"no active gateway lease for '{revision_key}': {reason}"
        )


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class GatewayLease(BaseModel):
    """Одиночный gateway-grant на отправку одной revision."""
    model_config = ConfigDict(extra="ignore")

    lease_id: str
    revision_key: str
    item_id: str
    gateway_id: str
    issued_at: datetime
    ttl_seconds: int = Field(gt=0)
    expires_at: datetime
    state: LeaseState = LeaseState.ACTIVE

    def is_expired(self, now: datetime) -> bool:
        return now >= self.expires_at


class GatewayLeaseRegistry:
    """In-memory lease-реестр: issue/validate/revoke с инъекцией clock.

    Инвариант single-active: на revision_key ровно один ACTIVE lease;
    новый issue отзывает предыдущий (REVOKED).
    """

    def __init__(self, clock: Callable[[], datetime] | None = None):
        self._clock = clock or _utcnow
        self._leases: dict[str, GatewayLease] = {}  # revision_key -> lease

    def issue(self, revision_key: str, item_id: str, gateway_id: str,
              ttl_seconds: int) -> GatewayLease:
        """Выдать lease; предыдущий активный на ту же revision отзывается."""
        now = self._clock()
        previous = self._leases.get(revision_key)
        if previous is not None and previous.state is LeaseState.ACTIVE:
            previous.state = LeaseState.REVOKED
        lease = GatewayLease(
            lease_id=uuid.uuid4().hex,
            revision_key=revision_key,
            item_id=item_id,
            gateway_id=gateway_id,
            issued_at=now,
            ttl_seconds=ttl_seconds,
            expires_at=now + timedelta(seconds=ttl_seconds),
        )
        self._leases[revision_key] = lease
        return lease

    def get(self, revision_key: str) -> Optional[GatewayLease]:
        return self._leases.get(revision_key)

    def validate(self, revision_key: str) -> GatewayLease:
        """Активный lease или raise. Граница: now >= expires_at -> EXPIRED."""
        lease = self._leases.get(revision_key)
        if lease is None or lease.state is not LeaseState.ACTIVE:
            if lease is not None and lease.state is LeaseState.REVOKED:
                raise LeaseRequiredError(revision_key, "lease revoked")
            raise LeaseRequiredError(revision_key, "no lease issued")
        if lease.is_expired(self._clock()):
            lease.state = LeaseState.EXPIRED
            raise LeaseRequiredError(revision_key, "lease expired (TTL)")
        return lease

    def revoke(self, revision_key: str) -> bool:
        """Идемпотентный revoke. True — если был активный lease."""
        lease = self._leases.get(revision_key)
        if lease is not None and lease.state is LeaseState.ACTIVE:
            lease.state = LeaseState.REVOKED
            return True
        return False

    def reset(self) -> None:
        self._leases.clear()
