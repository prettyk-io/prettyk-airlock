# -*- coding: utf-8 -*-
"""COS-055: Notification Manager V1 — unit + integration tests.

Unit (no DB): policy, scrubbing, backoff, recipient resolution.
Integration (PG via pg_client, auto-skip): happy path, duplicate event,
restart/recovery, provider failure, unknown recipient, concurrent delivery.
"""
from __future__ import annotations

import datetime
import logging
from typing import List, Optional

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from orchestrator.cosmo.notifications.policy import (
    SubscriptionPolicy,
    extract_member_ids,
    inbox_dedup_key,
    looks_like_email,
    merge_membership,
    next_backoff_seconds,
    resolve_recipients,
    safe_log_line,
    scrub_payload,
)
from orchestrator.cosmo.notifications.providers import (
    ConfiguredEmailProvider,
    EmailDeliveryResult,
    LoggingEmailProvider,
)
from orchestrator.cosmo.notifications.manager import NotificationManager
from orchestrator.cosmo.db.models_notifications import (
    NotificationEventRow,
    NotificationRow,
)

# ══════════════════════════════════════════════════════════════════
# Unit: policy (no DB)
# ══════════════════════════════════════════════════════════════════


class TestSubscriptionPolicy:
    def test_policy_all_allows_everything(self):
        p = SubscriptionPolicy(user_id="u1", mode="all")
        assert p.allows("run_failed") is True
        assert p.allows("gate_blocked") is True

    def test_policy_selected_allows_only_chosen(self):
        p = SubscriptionPolicy(user_id="u1", mode="selected", selected_event_types=["run_failed"])
        assert p.allows("run_failed") is True
        assert p.allows("run_succeeded") is False

    def test_policy_blocklist_blocks_chosen(self):
        p = SubscriptionPolicy(user_id="u1", mode="blocklist", blocked_event_types=["gate_passed"])
        assert p.allows("gate_passed") is False
        assert p.allows("run_failed") is True


class TestDedupKey:
    def test_dedup_key_stable(self):
        assert inbox_dedup_key("e1", "u1", "in_app") == inbox_dedup_key("e1", "u1", "in_app")

    def test_dedup_key_distinct_per_recipient(self):
        assert inbox_dedup_key("e1", "u1", "in_app") != inbox_dedup_key("e1", "u2", "in_app")


class TestBackoff:
    def test_backoff_progression(self):
        assert next_backoff_seconds(1) == 30.0
        assert next_backoff_seconds(2) == 60.0
        assert next_backoff_seconds(3) == 120.0

    def test_backoff_caps_at_3600(self):
        assert next_backoff_seconds(20) == 3600.0


class TestScrubPayload:
    def test_scrub_removes_token(self):
        result = scrub_payload({"token": "sk-live-abc", "name": "test"})
        assert result["token"] == "[REDACTED]"
        assert result["name"] == "test"

    def test_scrub_removes_nested_secret(self):
        result = scrub_payload({"meta": {"api_key": "xyz", "status": "ok"}})
        assert result["meta"]["api_key"] == "[REDACTED]"
        assert result["meta"]["status"] == "ok"

    def test_scrub_truncates_long_values(self):
        result = scrub_payload({"body": "x" * 500})
        assert len(result["body"]) <= 204

    def test_safe_log_line_contains_no_secret(self):
        line = safe_log_line("[TEST]", {"password": "hunter2", "user": "admin"})
        assert "hunter2" not in line
        assert "admin" in line


class TestRecipientResolution:
    def test_explicit_wins(self):
        result = resolve_recipients(["admin@x.io"], project_members=["dev@x.io"])
        assert result == ["admin@x.io"]

    def test_project_members_fallback(self):
        result = resolve_recipients(None, project_members=["dev@x.io"])
        assert result == ["dev@x.io"]

    def test_no_recipients_returns_none(self):
        assert resolve_recipients(None) is None

    def test_membership_merge_with_exclusions(self):
        inherited = [{"user_id": "a@x.io"}, {"user_id": "b@x.io"}]
        local = [{"user_id": "c@x.io"}]
        result = merge_membership(inherited, local, exclusions=["b@x.io"])
        assert "a@x.io" in result
        assert "b@x.io" not in result
        assert "c@x.io" in result

    def test_extract_member_ids_prefers_user_id(self):
        members = [{"user_id": "u1", "email": "u1@x.io"}, {"email": "u2@x.io"}]
        result = extract_member_ids(members)
        assert result == ["u1", "u2@x.io"]

    def test_looks_like_email(self):
        assert looks_like_email("user@company.io") is True
        assert looks_like_email("not-an-email") is False


# ══════════════════════════════════════════════════════════════════
# Integration (PG, auto-skip if PG down)
# ══════════════════════════════════════════════════════════════════


import _testpg

_TEST_PG_SKIP_REASON = "test PG (:5433) unreachable - docker compose -f services/docker-compose.test-pg.yml up -d"


def _pg_available() -> bool:
    """COS-078: unified on _testpg.pg_available (single resolution point)."""
    return _testpg.pg_available()


pg_needed = pytest.mark.skipif(not _pg_available(), reason=_TEST_PG_SKIP_REASON)


@pytest_asyncio.fixture(scope="function")
async def notif_db(loop_safe_engine_reset):
    """Per-test PG engine + clean notification tables + session factory.

    loop_safe_engine_reset (COS-075): сброс глобального engine — синглтон
    rebind'ится на текущий event loop (см. conftest).
    """
    from orchestrator.cosmo.db.session import Base as CosmoBase
    engine = create_async_engine(
        _testpg.TEST_PG_URL, echo=False,
    )
    async with engine.begin() as conn:
        await conn.run_sync(CosmoBase.metadata.create_all)
    async with engine.begin() as conn:
        for tbl in ("notification_inbox", "notification_events",
                    "notification_subscriptions", "notification_channel_configs"):
            await conn.exec_driver_sql(f'DELETE FROM "{tbl}"')
    session_maker = async_sessionmaker(engine, expire_on_commit=False)
    yield session_maker
    await engine.dispose()


class ScriptedEmailProvider:
    """Тестовый double: программируемый результат для transient/terminal."""

    def __init__(self, results: Optional[List[EmailDeliveryResult]] = None):
        self._results = list(results or [])
        self.calls: List[dict] = []

    def send(self, to: str, subject: str, body: str) -> EmailDeliveryResult:
        self.calls.append({"to": to, "subject": subject})
        if self._results:
            return self._results.pop(0)
        return EmailDeliveryResult(accepted=True)


def _make_manager(provider=None, resolver=None) -> NotificationManager:
    return NotificationManager(email_provider=provider, membership_resolver=resolver)


@pg_needed
class TestHappyPath:
    @pytest.mark.asyncio
    async def test_record_and_process_delivers_in_app(self, notif_db):
        """Happy path: record_event → process_outbox → inbox row (delivered)."""
        async with notif_db() as session:
            mgr = _make_manager()
            ev, created = await mgr.record_event(
                session,
                event_type="run_failed", aggregate_type="run", aggregate_id="r-100",
                title="Run r-100 failed", message="SAST found 3 critical",
                explicit_recipients=["lead@company.io"],
            )
            await session.commit()
            assert created is True
            assert ev.processed is False

            report = await mgr.process_outbox(session)
            assert report.events_processed == 1
            assert report.in_app_delivered == 1
            assert report.no_recipient == 0

            inbox = await mgr.list_inbox(session, recipient_id="lead@company.io")
            assert len(inbox) == 1
            assert inbox[0].notification_type == "run_failed"
            assert inbox[0].state == "delivered"
            assert inbox[0].read_at is None  # unread

    @pytest.mark.asyncio
    async def test_unread_read_state_persists(self, notif_db):
        async with notif_db() as session:
            mgr = _make_manager()
            await mgr.record_event(
                session, event_type="gate_blocked", aggregate_type="gate",
                aggregate_id="g-1", explicit_recipients=["u1@x.io"],
            )
            await mgr.process_outbox(session)

            rows = await mgr.list_inbox(session, recipient_id="u1@x.io", unread_only=True)
            assert len(rows) == 1

            ok = await mgr.mark_read(session, recipient_id="u1@x.io", notification_id=rows[0].id)
            assert ok is True

            unread = await mgr.list_inbox(session, recipient_id="u1@x.io", unread_only=True)
            assert len(unread) == 0


@pg_needed
class TestDuplicateEvent:
    @pytest.mark.asyncio
    async def test_duplicate_event_id_no_duplicate_notification(self, notif_db):
        """Повтор record_event с тем же event_id + повтор process → 1 inbox."""
        async with notif_db() as session:
            mgr = _make_manager()
            ev1, created1 = await mgr.record_event(
                session, event_type="gate_blocked", aggregate_type="gate",
                aggregate_id="g-1", event_id="evt-fixed-001",
                explicit_recipients=["u1@x.io"],
            )
            await session.commit()
            assert created1 is True

            ev2, created2 = await mgr.record_event(
                session, event_type="gate_blocked", aggregate_type="gate",
                aggregate_id="g-1", event_id="evt-fixed-001",
                explicit_recipients=["u1@x.io"],
            )
            assert created2 is False
            assert ev2.event_id == ev1.event_id

            await mgr.process_outbox(session)
            report2 = await mgr.process_outbox(session)
            assert report2.events_processed == 0

            inbox = await mgr.list_inbox(session, recipient_id="u1@x.io")
            assert len(inbox) == 1


@pg_needed
class TestRestartRecovery:
    @pytest.mark.asyncio
    async def test_outbox_survives_session_close(self, notif_db):
        """Перезапуск: запись в одной session, обработка в другой."""
        async with notif_db() as session:
            mgr = _make_manager()
            await mgr.record_event(
                session, event_type="release_approved", aggregate_type="release",
                aggregate_id="rel-1", explicit_recipients=["lead@x.io"],
            )
            await session.commit()

        async with notif_db() as session2:
            mgr2 = _make_manager()
            report = await mgr2.process_outbox(session2)
            assert report.events_processed == 1
            assert report.in_app_delivered == 1

            inbox = await mgr2.list_inbox(session2, recipient_id="lead@x.io")
            assert len(inbox) == 1


@pg_needed
class TestProviderFailure:
    @pytest.mark.asyncio
    async def test_transient_failure_retries(self, notif_db):
        """Transient provider failure → retryable → повтор → sent."""
        provider = ScriptedEmailProvider([
            EmailDeliveryResult(accepted=False, transient=True, error="timeout"),
            EmailDeliveryResult(accepted=True),
        ])
        async with notif_db() as session:
            mgr = _make_manager(provider=provider)
            await mgr.record_event(
                session, event_type="run_failed", aggregate_type="run",
                aggregate_id="r-1", explicit_recipients=["ops@x.io"],
            )
            await mgr.process_outbox(session)

            # Email row should be retryable_failure
            email_rows = await session.execute(
                select(NotificationRow).where(
                    NotificationRow.channel == "email",
                    NotificationRow.state == "retryable_failure",
                )
            )
            retryable = email_rows.scalars().all()
            assert len(retryable) == 1

            # Retry after backoff (naive UTC — models use naive DateTime)
            future = datetime.datetime.utcnow() + datetime.timedelta(hours=1)
            report = await mgr.process_retries(session, now=future)
            assert report.emails_sent == 1

    @pytest.mark.asyncio
    async def test_exhausted_retry_goes_to_dlq(self, notif_db):
        """Exhausted retry → failed (DLQ visible)."""
        provider = ScriptedEmailProvider([
            EmailDeliveryResult(accepted=False, transient=True, error="smtp down"),
        ] * 10)
        async with notif_db() as session:
            mgr = NotificationManager(email_provider=provider, default_max_attempts=2)
            await mgr.record_event(
                session, event_type="run_failed", aggregate_type="run",
                aggregate_id="r-1", explicit_recipients=["ops@x.io"],
            )
            await mgr.process_outbox(session)

            future = datetime.datetime.utcnow() + datetime.timedelta(hours=2)
            await mgr.process_retries(session, now=future)
            await mgr.process_retries(session, now=future)

            dlq = await mgr.get_dlq(session)
            assert len(dlq) == 1
            assert dlq[0].state == "failed"
            assert dlq[0].attempts >= 2


@pg_needed
class TestUnknownRecipient:
    @pytest.mark.asyncio
    async def test_no_recipient_marked_explicitly(self, notif_db):
        """Unknown/no recipient → processed=True но 0 inbox rows (не silently dropped — no_recipient counter)."""
        async with notif_db() as session:
            mgr = _make_manager()
            ev, _ = await mgr.record_event(
                session, event_type="batch_failed", aggregate_type="batch",
                aggregate_id="b-1",
            )
            report = await mgr.process_outbox(session)

            assert report.no_recipient == 1
            row = await session.get(NotificationEventRow, ev.event_id)
            assert row.processed is True  # обработано, но результат — no_recipient
            assert report.in_app_delivered == 0


@pg_needed
class TestConcurrentDelivery:
    @pytest.mark.asyncio
    async def test_double_process_no_duplicate(self, notif_db):
        """Concurrent delivery attempt: process_outbox дважды → 1 inbox на recipient."""
        async with notif_db() as session:
            mgr = _make_manager()
            await mgr.record_event(
                session, event_type="gate_blocked", aggregate_type="gate",
                aggregate_id="g-1", explicit_recipients=["u1@x.io", "u2@x.io"],
            )
            await session.commit()

            await mgr.process_outbox(session)
            report2 = await mgr.process_outbox(session)
            assert report2.events_processed == 0

            inbox_u1 = await mgr.list_inbox(session, recipient_id="u1@x.io")
            inbox_u2 = await mgr.list_inbox(session, recipient_id="u2@x.io")
            assert len(inbox_u1) == 1
            assert len(inbox_u2) == 1


@pg_needed
class TestLogHygiene:
    @pytest.mark.asyncio
    async def test_logs_contain_no_secrets(self, notif_db, caplog):
        """Logs не содержат credentials и чувствительный payload."""
        async with notif_db() as session:
            mgr = _make_manager()
            with caplog.at_level(logging.DEBUG, logger="cosmoport.notifications"):
                await mgr.record_event(
                    session, event_type="run_failed", aggregate_type="run",
                    aggregate_id="r-1", explicit_recipients=["ops@x.io"],
                    payload={"forge_token_ref": "VAULT/super-secret", "password": "hunter2"},
                )
                await mgr.process_outbox(session)

            log_text = " ".join(r.getMessage() for r in caplog.records)
            assert "super-secret" not in log_text
            assert "hunter2" not in log_text
