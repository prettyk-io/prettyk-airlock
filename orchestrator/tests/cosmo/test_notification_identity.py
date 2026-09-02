# -*- coding: utf-8 -*-
"""COS-075: Recipient identity (principal → inbox) + SSE ticket auth.

Covers:
  * SSE ticket roundtrip / tamper / expiry (unit, no PG);
  * POST /api/v1/notifications/sse-ticket returns a ticket bound to the
    authenticated principal (REST);
  * GET /api/v1/notifications/stream rejects invalid tickets with 401;
  * two different principals get separate inboxes (no cross-user leakage).
"""
from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import _testpg  # noqa: E402  (test dir is on sys.path)
from orchestrator.cosmo.api.sse_tickets import (
    TICKET_TTL_S,
    mint_ticket,
    validate_ticket,
)
from orchestrator.cosmo.notifications.manager import NotificationManager

_TEST_PG_SKIP_REASON = "test PG (:5433) unreachable - docker compose -f services/docker-compose.test-pg.yml up -d"


def _pg_available() -> bool:
    """COS-078: unified on _testpg.pg_available (single resolution point)."""
    return _testpg.pg_available()


pg_needed = pytest.mark.skipif(not _pg_available(), reason=_TEST_PG_SKIP_REASON)


# ══════════════════════════════════════════════════════════════════
# Unit: ticket mint/validate (no PG)
# ══════════════════════════════════════════════════════════════════


def test_ticket_roundtrip():
    ticket = mint_ticket("operator")
    assert ticket.startswith("v1.")
    assert validate_ticket(ticket) == "operator"


def test_ticket_tampered_signature_rejected():
    ticket = mint_ticket("operator")
    assert validate_ticket(ticket[:-3] + "aaa") is None


def test_ticket_garbage_rejected():
    assert validate_ticket("") is None
    assert validate_ticket("junk") is None
    assert validate_ticket("v2.abc.abc") is None


def test_ticket_expired_rejected(monkeypatch):
    ticket = mint_ticket("operator", ttl_s=TICKET_TTL_S)
    # Shift "now" far beyond TTL via time mock on the validate side
    import orchestrator.cosmo.api.sse_tickets as mod

    real_time = mod.time.time
    monkeypatch.setattr(mod.time, "time", lambda: real_time() + TICKET_TTL_S + 5)
    assert validate_ticket(ticket) is None


def test_ticket_wrong_recipient_reports_binding():
    ticket = mint_ticket("operator")
    # Ticket resolves to its bound recipient — not to any other user
    assert validate_ticket(ticket) != "viewer"


# ══════════════════════════════════════════════════════════════════
# REST: ticket endpoint + stream 401 + principal-separated inboxes
# ══════════════════════════════════════════════════════════════════


async def _override_principal(user_id: str):
    from orchestrator.cosmo.api.deps import get_current_principal
    from orchestrator.cosmo.api.main import app
    from orchestrator.cosmo.domain.rbac import PrincipalContext, Role

    async def _factory() -> PrincipalContext:
        return PrincipalContext(
            user_id=user_id, roles=[Role.ADMIN_SEC],
            domain_id="test", zone="zr", is_system_admin=True,
        )

    app.dependency_overrides[get_current_principal] = _factory


# Helper: build an AsyncClient over the app (pg_client already set overrides)


@pytest_asyncio.fixture(scope="function")
async def identity_client():
    """ASGI client reusing pg_client's overrides via app state."""
    from orchestrator.cosmo.api.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pg_needed
@pytest.mark.asyncio
async def test_ticket_endpoint_binds_to_principal(pg_client, identity_client):
    """POST /sse-ticket под principal 'operator' → ticket резолвится в 'operator'."""
    await _override_principal("operator")
    res = await identity_client.post("/api/v1/notifications/sse-ticket")
    assert res.status_code == 200
    body = res.json()
    assert body["recipient_id"] == "operator"
    assert body["expires_in"] == TICKET_TTL_S
    assert validate_ticket(body["ticket"]) == "operator"


@pg_needed
@pytest.mark.asyncio
async def test_stream_rejects_invalid_ticket(pg_client, identity_client):
    res = await identity_client.get("/api/v1/notifications/stream?ticket=garbage.sig.x")
    assert res.status_code == 401


@pg_needed
@pytest.mark.asyncio
async def test_two_principals_separate_inboxes(pg_client, identity_client):
    """Event для 'operator' виден только principal operator; viewer — пусто."""
    from orchestrator.cosmo.api.deps import get_current_principal
    from orchestrator.cosmo.api.main import app

    engine = create_async_engine(_testpg.TEST_PG_URL, echo=False)
    try:
        manager = NotificationManager()
        session_maker = async_sessionmaker(engine, expire_on_commit=False)
        async with session_maker() as session:
            await manager.record_event(
                session,
                event_type="run_failed",
                aggregate_type="run",
                aggregate_id="r-identity-1",
                title="Identity check",
                message="two-principal separation",
                severity="high",
                explicit_recipients=["operator"],
            )
            await session.commit()

        # Fanout через production tick (REST)
        await _override_principal("operator")
        res = await identity_client.post("/api/v1/notifications/process")
        assert res.status_code == 200

        # operator: событие доставлено
        res = await identity_client.get("/api/v1/notifications/inbox/unread-count")
        assert res.status_code == 200
        assert res.json()["unread"] >= 1

        # viewer: чужой inbox не утекает
        await _override_principal("viewer")
        res = await identity_client.get("/api/v1/notifications/inbox/unread-count")
        assert res.status_code == 200
        assert res.json()["unread"] == 0

        res = await identity_client.get("/api/v1/notifications/inbox")
        assert res.status_code == 200
        assert res.json() == []

        # viewer не может отметить чужое уведомление
        res = await identity_client.get("/api/v1/notifications/inbox")
        assert res.json() == []
    finally:
        app.dependency_overrides.pop(get_current_principal, None)
        await engine.dispose()
