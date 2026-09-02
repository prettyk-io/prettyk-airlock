# -*- coding: utf-8 -*-
"""COS-079: SSE guards, redaction/log hygiene, DLQ visibility + replay.

Covers:
  * redact_text masks sensitive key=value pairs (value, not just the key);
  * hash_identifier — stable short hash, raw recipient never in logs;
  * [EMAIL:retryable] / [EMAIL:failed->DLQ] logs carry recipient_sha and
    never the raw recipient_id;
  * one-time SSE tickets via a fake Valkey double (mint/validate/burn,
    fallback to HMAC when Valkey is unavailable);
  * SSE guards: run/domain streams reject missing/invalid tickets (401);
  * DLQ: replay sends honestly (sent when provider accepts, stays failed
    when provider refuses), REST endpoints list + replay.
"""
from __future__ import annotations

import datetime
import logging

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import _testpg  # noqa: E402  (test dir is on sys.path)
from orchestrator.cosmo.api.sse_tickets import (
    TICKET_TTL_S,
    mint_ticket,
    validate_ticket,
)
from orchestrator.cosmo.notifications.providers import EmailDeliveryResult
from orchestrator.cosmo.notifications.manager import NotificationManager
from orchestrator.cosmo.notifications.redaction import hash_identifier, redact_details, redact_text
from orchestrator.cosmo.db.models_notifications import NotificationEventRow, NotificationRow

_TEST_PG_SKIP_REASON = "test PG (:5433) unreachable - docker compose -f services/docker-compose.test-pg.yml up -d"


def _pg_available() -> bool:
    import asyncio

    try:
        import asyncpg

        loop = asyncio.new_event_loop()
        try:
            conn = loop.run_until_complete(asyncpg.connect(
                _testpg.asyncpg_dsn(), timeout=3,
            ))
            loop.run_until_complete(conn.close())
            return True
        finally:
            loop.close()
    except Exception:
        return False


pg_needed = pytest.mark.skipif(not _pg_available(), reason=_TEST_PG_SKIP_REASON)


# ══════════════════════════════════════════════════════════════════
# Unit: redaction (no PG)
# ══════════════════════════════════════════════════════════════════


class TestRedaction:
    def test_redact_text_masks_value_not_just_key(self):
        # COS-079 regression: previously only the KEY was masked — the
        # value ("hunter2") survived into logs.
        cleaned = redact_text("auth ok password=hunter2 done")
        assert "hunter2" not in cleaned
        assert "[sensitive]" in cleaned

    def test_redact_text_masks_colon_form(self):
        cleaned = redact_text("request failed token: abc123 retry")
        assert "abc123" not in cleaned

    def test_redact_text_keeps_non_sensitive_text(self):
        cleaned = redact_text("run r-1 failed: 3 findings")
        assert cleaned == "run r-1 failed: 3 findings"

    def test_redact_text_stops_value_at_separator(self):
        cleaned = redact_text("password=hunter2&next=1")
        assert "hunter2" not in cleaned
        assert "next=1" in cleaned

    def test_redact_details_masks_nested_value(self):
        cleaned = redact_details({"smtp_password": "s3cret", "user": "ops"})
        assert "s3cret" not in cleaned
        assert cleaned["user"] == "ops"

    def test_hash_identifier_stable_and_unrevealing(self):
        h1 = hash_identifier("ops@company.io")
        h2 = hash_identifier("ops@company.io")
        assert h1 == h2
        assert h1.startswith("sha256:")
        assert "ops@company.io" not in h1
        assert len(h1) == len("sha256:") + 12
        assert hash_identifier("") == ""


# ══════════════════════════════════════════════════════════════════
# Unit: one-time SSE tickets (fake Valkey double, no PG)
# ══════════════════════════════════════════════════════════════════


class FakeValkey:
    """In-memory double of the valkey client surface used by sse_tickets."""

    def __init__(self, fail_getdel: bool = False):
        self._store: dict[str, str] = {}
        self.fail_getdel = fail_getdel

    def set(self, key: str, value: str, ex: int | None = None):
        self._store[key] = value
        return True

    def getdel(self, key: str):
        if self.fail_getdel:
            raise RuntimeError("valkey down")
        return self._store.pop(key, None)


class TestOneTimeTickets:
    @pytest.fixture()
    def fake_valkey(self, monkeypatch):
        import orchestrator.cosmo.api.sse_tickets as mod

        fake = FakeValkey()
        monkeypatch.setattr(mod, "_get_valkey", lambda: fake)
        return fake

    def test_one_time_roundtrip_and_single_use(self, fake_valkey):
        ticket = mint_ticket("operator")
        assert ticket.startswith("ot1.")
        assert validate_ticket(ticket) == "operator"
        # Burned: the second validate of the same ticket is rejected
        assert validate_ticket(ticket) is None

    def test_one_time_unknown_token_rejected(self, fake_valkey):
        assert validate_ticket("ot1." + "x" * 40) is None

    def test_one_time_fail_closed_on_store_error(self, fake_valkey):
        fake_valkey.fail_getdel = True
        ticket = mint_ticket("operator")
        assert validate_ticket(ticket) is None

    def test_fallback_to_hmac_without_valkey(self, monkeypatch):
        import orchestrator.cosmo.api.sse_tickets as mod

        monkeypatch.setattr(mod, "_get_valkey", lambda: None)
        ticket = mint_ticket("operator")
        assert ticket.startswith("v1.")
        assert validate_ticket(ticket) == "operator"

    def test_one_time_short_token_rejected(self):
        assert validate_ticket("ot1.short") is None


# ══════════════════════════════════════════════════════════════════
# Integration: SSE guards (401) + log hygiene + DLQ (PG)
# ══════════════════════════════════════════════════════════════════


class ScriptedEmailProvider:
    def __init__(self, results=None):
        self._results = list(results or [])
        self.calls = []

    def send(self, to: str, subject: str, body: str) -> EmailDeliveryResult:
        self.calls.append({"to": to, "subject": subject})
        if self._results:
            return self._results.pop(0)
        return EmailDeliveryResult(accepted=True)


def _make_manager(provider=None) -> NotificationManager:
    return NotificationManager(email_provider=provider)


@pytest_asyncio.fixture(scope="function")
async def ops_db(loop_safe_engine_reset):
    from orchestrator.cosmo.db.session import Base as CosmoBase

    engine = create_async_engine(_testpg.TEST_PG_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(CosmoBase.metadata.create_all)
    async with engine.begin() as conn:
        for tbl in ("notification_inbox", "notification_events",
                    "notification_subscriptions", "notification_channel_configs"):
            await conn.exec_driver_sql(f'DELETE FROM "{tbl}"')
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


@pg_needed
class TestSseGuards:
    @pytest.mark.asyncio
    async def test_run_stream_requires_ticket(self, pg_client):
        res = await pg_client.get("/api/v1/runs/r-404/stream")
        assert res.status_code == 401

    @pytest.mark.asyncio
    async def test_run_stream_rejects_garbage_ticket(self, pg_client):
        res = await pg_client.get("/api/v1/runs/r-404/stream?ticket=garbage.sig.x")
        assert res.status_code == 401

    @pytest.mark.asyncio
    async def test_domain_stream_requires_ticket(self, pg_client):
        res = await pg_client.get("/api/v1/domains/d-404/events/stream")
        assert res.status_code == 401

    @pytest.mark.asyncio
    async def test_domain_stream_rejects_garbage_ticket(self, pg_client):
        res = await pg_client.get("/api/v1/domains/d-404/events/stream?ticket=garbage.sig.x")
        assert res.status_code == 401


# COS-084: ops/mutation-эндпоинты notification-поверхности требуют principal.
_COS084_ROUTES = [
    ("GET", "/api/v1/notifications/dlq"),
    ("POST", "/api/v1/notifications/dlq/n-401/replay"),
    ("POST", "/api/v1/notifications/process"),
    ("GET", "/api/v1/notifications"),
    ("POST", "/api/v1/notifications?domain_id=d-401"),
    ("DELETE", "/api/v1/notifications/cfg-401?domain_id=d-401"),
    ("GET", "/api/v1/notifications/outbox/ev-401"),
]


@pytest_asyncio.fixture
async def anon_client(pg_client):
    """pg_client с снятым admin-override'ом auth — реальные 401-сценарии."""
    from orchestrator.cosmo.api.deps import get_current_principal
    from orchestrator.cosmo.api.main import app

    saved = app.dependency_overrides.get(get_current_principal)
    app.dependency_overrides.pop(get_current_principal, None)
    try:
        yield pg_client
    finally:
        if saved is not None:
            app.dependency_overrides[get_current_principal] = saved


@pg_needed
class TestCOS084ApiGuards:
    """COS-084: без валидного principal — 401 на всех ops/mutation-роутах.

    Заметка про "Bearer garbage": deps.get_current_principal по legacy-контракту
    принимает ЛЮБОЙ opaque bearer (не содержащий invalid/expired/corrupted/null/
    none/0000) как user_authenticated (Role.USER). Поэтому garbage-токен здесь —
    rejected-токен ("invalid-token"). Полный запрет opaque-токенов — решение по
    поверхности deps.py (вне scope COS-084), отрепортировано.
    """

    @pytest.mark.asyncio
    @pytest.mark.parametrize("method,url", _COS084_ROUTES)
    async def test_routes_require_principal(self, anon_client, method, url):
        res = await anon_client.request(method, url)
        assert res.status_code == 401

    @pytest.mark.asyncio
    @pytest.mark.parametrize("method,url", _COS084_ROUTES)
    async def test_routes_reject_rejected_bearer(self, anon_client, method, url):
        res = await anon_client.request(
            method, url, headers={"Authorization": "Bearer invalid-token"},
        )
        assert res.status_code == 401


@pg_needed
class TestLogHygiene:
    @pytest.mark.asyncio
    async def test_retry_and_dlq_logs_hide_recipient(self, ops_db, caplog):
        """COS-079: [EMAIL:retryable]/[EMAIL:failed->DLQ] carry recipient_sha,
        never the raw recipient_id.

        COS-076: caplog (не прямой handler) — мина в alembic/env.py
        (fileConfig disable_existing_loggers) снята фиксом на поверхности;
        после in-process alembic_cycle caplog ловит записи нормально.
        """
        provider = ScriptedEmailProvider([
            EmailDeliveryResult(accepted=False, transient=True, error="smtp down"),
        ] * 10)
        # default max_attempts=5; each send attempt counts twice
        # (wrapper + on_row) — 1 outbox + 3 retries reaches DLQ.
        mgr = NotificationManager(email_provider=provider)
        async with ops_db() as session:
            await mgr.record_event(
                session, event_type="run_failed", aggregate_type="run",
                aggregate_id="r-log-1", explicit_recipients=["ops-secret@company.io"],
            )
            await session.commit()

        with caplog.at_level(logging.INFO, logger="cosmoport.notifications"):
            async with ops_db() as session:
                await mgr.process_outbox(session)
                # Backoff grows (60/120/240s) — each retry needs a later now.
                for i in range(3):
                    future = datetime.datetime.utcnow() + datetime.timedelta(hours=1 + 2 * i)
                    await mgr.process_retries(session, now=future)

        text = " ".join(r.getMessage() for r in caplog.records)
        assert "[EMAIL:retryable]" in text
        assert "[EMAIL:failed" in text  # DLQ line (arrow may be a unicode glyph)
        assert "ops-secret@company.io" not in text  # raw recipient never logged
        assert "recipient_sha" in text
        assert "sha256:" in text


@pg_needed
class TestDlqReplay:
    async def _seed_failed_row(self, ops_db) -> NotificationRow:
        """Seed one terminal-failed email notification directly."""
        async with ops_db() as session:
            session.add(NotificationEventRow(
                event_id="evt-dlq-1", event_type="run_failed",
                aggregate_type="run", aggregate_id="r-dlq-1",
                occurred_at=datetime.datetime.utcnow(), payload={},
            ))
            row = NotificationRow(
                id="dlq-seed-1", event_id="evt-dlq-1",
                recipient_id="ops@company.io", channel="email",
                notification_type="run_failed", severity="high",
                title="Run failed", message="see logs",
                state="failed", attempts=5, max_attempts=5,
                last_error="smtp down",
            )
            session.add(row)
            await session.commit()
            return row

    @pytest.mark.asyncio
    async def test_replay_success_state_is_sent(self, ops_db):
        """Provider accepts → row honestly leaves the DLQ (state=sent)."""
        row = await self._seed_failed_row(ops_db)
        provider = ScriptedEmailProvider([EmailDeliveryResult(accepted=True)])
        mgr = _make_manager(provider)
        async with ops_db() as session:
            result = await mgr.replay_dlq(session, notification_id=row.id)
            assert result is not None
            assert result.state == "sent"
            assert result.attempts == 6
            assert result.last_error is None
            dlq = await mgr.get_dlq(session)
            assert dlq == []

    @pytest.mark.asyncio
    async def test_replay_failure_stays_honestly_failed(self, ops_db):
        """Provider still refuses (terminal) → row stays in DLQ, honest."""
        row = await self._seed_failed_row(ops_db)
        provider = ScriptedEmailProvider([
            EmailDeliveryResult(accepted=False, transient=False, error="mailbox unknown"),
        ])
        mgr = _make_manager(provider)
        async with ops_db() as session:
            result = await mgr.replay_dlq(session, notification_id=row.id)
            assert result is not None
            assert result.state == "failed"
            assert result.attempts == 6
            assert result.last_error == "mailbox unknown"
            dlq = await mgr.get_dlq(session)
            assert len(dlq) == 1

    @pytest.mark.asyncio
    async def test_replay_unknown_or_wrong_state_returns_none(self, ops_db):
        async with ops_db() as session:
            mgr = _make_manager()
            assert await mgr.replay_dlq(session, notification_id="no-such-id") is None

    @pytest.mark.asyncio
    async def test_replay_rejects_in_app_row(self, ops_db):
        """Only failed EMAIL rows are replayable from the DLQ."""
        async with ops_db() as session:
            session.add(NotificationEventRow(
                event_id="evt-dlq-2", event_type="run_failed",
                aggregate_type="run", aggregate_id="r-dlq-2",
                occurred_at=datetime.datetime.utcnow(), payload={},
            ))
            session.add(NotificationRow(
                id="dlq-inapp-1", event_id="evt-dlq-2",
                recipient_id="ops@company.io", channel="in_app",
                notification_type="run_failed", severity="high",
                title="Run failed", message="see logs",
                state="delivered", attempts=1, max_attempts=1,
            ))
            await session.commit()

        async with ops_db() as session:
            mgr = _make_manager()
            assert await mgr.replay_dlq(session, notification_id="dlq-inapp-1") is None


@pg_needed
class TestDlqRest:
    @pytest.fixture(autouse=True)
    def default_manager(self):
        """REST routes use the module singleton — pin a default manager for
        the duration of each test (LoggingEmailProvider always accepts)."""
        from orchestrator.cosmo.notifications.manager import set_manager

        set_manager(NotificationManager())
        yield
        set_manager(NotificationManager())

    @pytest.mark.asyncio
    async def test_rest_dlq_list_and_replay(self, pg_client, ops_db):
        """GET /dlq lists the seeded row; POST /dlq/{id}/replay sends it
        (LoggingEmailProvider) and the row leaves the DLQ."""
        async with ops_db() as session:
            session.add(NotificationEventRow(
                event_id="evt-dlq-3", event_type="run_failed",
                aggregate_type="run", aggregate_id="r-dlq-3",
                occurred_at=datetime.datetime.utcnow(), payload={},
            ))
            session.add(NotificationRow(
                id="dlq-rest-1", event_id="evt-dlq-3",
                recipient_id="ops@company.io", channel="email",
                notification_type="run_failed", severity="high",
                title="Run failed", message="see logs",
                state="failed", attempts=5, max_attempts=5,
                last_error="smtp down",
            ))
            await session.commit()

        res = await pg_client.get("/api/v1/notifications/dlq")
        assert res.status_code == 200
        items = res.json()
        assert len(items) == 1
        item = items[0]
        assert item["id"] == "dlq-rest-1"
        assert item["state"] == "failed"
        assert item["attempts"] == 5
        assert item["recipient_id"] == "ops@company.io"

        res = await pg_client.post("/api/v1/notifications/dlq/dlq-rest-1/replay")
        assert res.status_code == 200
        body = res.json()
        assert body["state"] == "sent"
        assert body["attempts"] == 6

        res = await pg_client.get("/api/v1/notifications/dlq")
        assert res.json() == []

    @pytest.mark.asyncio
    async def test_rest_replay_unknown_id_404(self, pg_client):
        res = await pg_client.post("/api/v1/notifications/dlq/no-such/replay")
        assert res.status_code == 404


# TTL constant unchanged (COS-075 contract)
def test_ticket_ttl_contract():
    assert TICKET_TTL_S == 60
