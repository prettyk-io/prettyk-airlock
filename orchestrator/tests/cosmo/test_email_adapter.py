# -*- coding: utf-8 -*-
"""COS-057: Email provider adapter — contract tests + provider surface offline hygiene.

Unit (no DB): SMTP outcome classification, invalid recipient, redaction
(recipients/secrets never in errors or logs), FakeEmailProvider contract,
TLS config edge cases, provider result mapping edge cases.

Integration (PG via notif_db pattern, auto-skip): adapter through the real
NotificationManager — sent / retryable → sent / terminal → DLQ visibility /
redaction in durable last_error and logs.
"""
from __future__ import annotations

import datetime
import logging
from typing import List, Optional

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from orchestrator.cosmo.notifications.email_adapter import (
    FakeEmailProvider,
    SmtpEmailProvider,
    TransportOutcome,
    safe_error_text,
)
from orchestrator.cosmo.notifications.providers import EmailDeliveryResult
from orchestrator.cosmo.notifications.manager import NotificationManager
from orchestrator.cosmo.notifications.policy import looks_like_email
from orchestrator.cosmo.db.models_notifications import NotificationRow

from orchestrator.cosmo.adapters.tls_config import (
    TLSConfig,
    TLSVerificationStatus,
    verify_tls_config,
)
from orchestrator.cosmo.adapters.provider_capability import OpResult, OpStatus, ProviderCapability
from orchestrator.cosmo.adapters.provider_result_mapping import to_transfer_outcome
from orchestrator.cosmo.transfer.contract import TransferFailureClass, TransferItemStatus

RECIPIENT = "ops@company.io"

# ══════════════════════════════════════════════════════════════════
# Unit: SMTP outcome classification (no DB)
# ══════════════════════════════════════════════════════════════════


class _StaticTransport:
    """Возвращает один и тот же TransportOutcome (или бросает)."""

    def __init__(self, outcome: Optional[TransportOutcome] = None,
                 exc: Optional[Exception] = None):
        self._outcome = outcome
        self._exc = exc
        self.calls: List[dict] = []

    def deliver(self, to: str, subject: str, body: str) -> TransportOutcome:
        self.calls.append({"to": to, "subject": subject, "body_len": len(body or "")})
        if self._exc is not None:
            raise self._exc
        assert self._outcome is not None
        return self._outcome


def _send(transport) -> EmailDeliveryResult:
    return SmtpEmailProvider(transport).send(
        RECIPIENT, subject="Sub", body="Body",
    )


class TestSmtpClassification:
    def test_2xx_accepted(self):
        assert _send(_StaticTransport(TransportOutcome(250))).accepted is True

    def test_4xx_transient(self):
        r = _send(_StaticTransport(TransportOutcome(451, "try later")))
        assert r.accepted is False and r.transient is True
        assert "451" in r.error

    def test_3xx_transient(self):
        assert _send(_StaticTransport(TransportOutcome(354))).transient is True

    def test_5xx_permanent(self):
        r = _send(_StaticTransport(TransportOutcome(550, "mailbox unavailable")))
        assert r.accepted is False and r.transient is False
        assert "550" in r.error

    def test_unknown_code_transient_not_permanent(self):
        r = _send(_StaticTransport(TransportOutcome(999)))
        assert r.transient is True

    def test_none_code_transient(self):
        """Транспорт без SMTP-кода → transient (не маскируем под success/DLQ)."""
        r = _send(_StaticTransport(TransportOutcome(code=None)))
        assert r.accepted is False
        assert r.transient is True
        assert "no code" in r.error

    def test_transport_exception_transient(self):
        r = _send(_StaticTransport(exc=RuntimeError("connection refused")))
        assert r.accepted is False
        assert r.transient is True
        assert "connection refused" in r.error

    def test_transport_not_called_on_invalid_recipient(self):
        transport = _StaticTransport(TransportOutcome(250))
        provider = SmtpEmailProvider(transport)
        r = provider.send("not-an-email", subject="s", body="b")
        assert r.accepted is False and r.transient is False  # permanent
        assert transport.calls == []  # транспорт не дёргается


class TestInvalidRecipientError:
    def test_error_has_no_recipient_address(self):
        provider = SmtpEmailProvider(_StaticTransport(TransportOutcome(250)))
        r = provider.send("victim@company.io", subject="s", body="b")
        assert "victim@company.io" not in (r.error or "")
        assert r.transient is False


class TestRedactionInErrors:
    def test_recipient_in_transport_message_scrubbed(self):
        msg = "550 5.1.1 ops@company.io recipient rejected"
        r = _send(_StaticTransport(TransportOutcome(550, msg)))
        assert "ops@company.io" not in r.error
        assert "[recipient]" in r.error
        assert "rejected" in r.error  # остальная диагностика сохранена

    def test_secret_key_value_scrubbed(self):
        msg = "451 deferred token=sk-live-secret123"
        r = _send(_StaticTransport(TransportOutcome(451, msg)))
        assert "sk-live-secret123" not in r.error

    def test_safe_error_text_truncates(self):
        long = "x" * 5000
        assert len(safe_error_text(long)) <= 500

    def test_safe_error_text_empty(self):
        assert safe_error_text("") == ""


class TestLogHygiene:
    def test_logs_contain_no_recipient_or_secret(self, caplog):
        transport = _StaticTransport(TransportOutcome(550, "550 user unknown"))
        provider = SmtpEmailProvider(transport)
        with caplog.at_level(logging.DEBUG, logger="cosmoport.notifications.email"):
            provider.send(RECIPIENT, subject="Sub with password=hunter2", body="b")
            provider.send("broken-address", subject="s", body="b")
        text = " ".join(rec.getMessage() for rec in caplog.records)
        assert RECIPIENT not in text
        assert "hunter2" not in text
        assert text  # логи реально писались


class TestFakeProvider:
    def test_default_accepted_after_script_exhausted(self):
        fake = FakeEmailProvider([FakeEmailProvider.transient()])
        r1 = fake.send("a@x.io", "s", "b")
        r2 = fake.send("a@x.io", "s", "b")
        assert r1.transient is True
        assert r2.accepted is True
        assert fake.call_count == 2
        assert fake.calls[0]["to"] == "a@x.io"

    def test_exception_in_script(self):
        fake = FakeEmailProvider([RuntimeError("smtp down")])
        with pytest.raises(RuntimeError, match="smtp down"):
            fake.send("a@x.io", "s", "b")

    def test_permanent_helper(self):
        fake = FakeEmailProvider([FakeEmailProvider.permanent()])
        r = fake.send("a@x.io", "s", "b")
        assert r.accepted is False and r.transient is False

    def test_call_log_records(self):
        fake = FakeEmailProvider()
        fake.send("a@x.io", "subject-x", "body")
        assert fake.calls == [{"to": "a@x.io", "subject": "subject-x", "body_len": 4}]


class TestLooksLikeEmailSeamReuse:
    """Adapter валидирует адрес тем же предикатом policy (COS-055), не своим regex."""

    def test_consistency(self):
        assert looks_like_email(RECIPIENT) is True
        assert looks_like_email("nope") is False


# ══════════════════════════════════════════════════════════════════
# Hygiene: TLS config edge cases (COS-060 surface, offline)
# ══════════════════════════════════════════════════════════════════


class TestTLSConfigHygiene:
    def test_pem_body_in_key_ref_invalid(self):
        v = verify_tls_config(TLSConfig(client_cert_ref="file:/c.pem",
                                        client_key_ref="-----BEGIN PRIVATE KEY-----"))
        assert v.status == TLSVerificationStatus.INVALID
        assert any("PEM" in p for p in v.problems)

    def test_tls_verify_false_without_allow_insecure_invalid(self):
        v = verify_tls_config(TLSConfig(tls_verify=False))
        assert v.status == TLSVerificationStatus.INVALID
        assert v.ok is False

    def test_tls_verify_false_with_allow_insecure_explicit(self):
        v = verify_tls_config(TLSConfig(tls_verify=False, allow_insecure=True))
        assert v.status == TLSVerificationStatus.INSECURE_EXPLICIT
        assert v.ok is False  # insecure — не "valid"

    def test_cert_without_key_invalid(self):
        v = verify_tls_config(TLSConfig(client_cert_ref="vault:secret/certs/c"))
        assert v.status == TLSVerificationStatus.INVALID
        assert any("BOTH" in p for p in v.problems)

    def test_logsafe_dict_leaks_no_full_refs(self):
        v = verify_tls_config(TLSConfig(
            ca_cert_ref="vault:secret/pki/very-long-secret-path"))
        d = v.logsafe_config
        assert "very-long-secret-path" not in str(d)
        assert d["ca_cert_ref"].startswith("vault:")  # префикс + отпечаток

    def test_default_verify_without_ca_is_valid_with_note(self):
        v = verify_tls_config(TLSConfig())
        assert v.status == TLSVerificationStatus.VALID
        assert any("trust store" in n for n in v.notes)


# ══════════════════════════════════════════════════════════════════
# Hygiene: provider result mapping edge cases (COS-060 surface)
# ══════════════════════════════════════════════════════════════════


def _op(status, **kw) -> OpResult:
    return OpResult(status=status, capability=ProviderCapability.RAW_PUSH,
                    provider_id="sfera", **kw)


class TestResultMappingHygiene:
    def test_unsupported_failed_without_kernel_class(self):
        out = to_transfer_outcome(_op(OpStatus.UNSUPPORTED, detail="no endpoint"))
        assert out.item_status == TransferItemStatus.FAILED
        assert out.failure_class is None
        assert "UNSUPPORTED" in out.detail
        assert out.retryable is False

    def test_unmapped_status_failed_not_masked(self):
        """Будущий/неизвестный OpStatus → FAILED + TRANSPORT_FAILURE + detail."""
        out = to_transfer_outcome(_op("future_status_v9"))
        assert out.item_status == TransferItemStatus.FAILED
        assert out.failure_class == TransferFailureClass.TRANSPORT_FAILURE
        assert "future_status_v9" in out.detail

    def test_ok_keeps_digest_and_location_verbatim(self):
        out = to_transfer_outcome(_op(OpStatus.OK, digest="sha256:abc",
                                      location_ref="raw/repo/x"))
        assert out.item_status == TransferItemStatus.DISPATCHED
        assert out.digest == "sha256:abc"
        assert out.location_ref == "raw/repo/x"

    def test_transient_maps_to_retry(self):
        out = to_transfer_outcome(_op(OpStatus.TRANSIENT_FAILURE))
        assert out.retryable is True
        assert out.failure_class == TransferFailureClass.TRANSPORT_FAILURE


# ══════════════════════════════════════════════════════════════════
# Integration (PG, auto-skip): adapter through real NotificationManager
# ══════════════════════════════════════════════════════════════════


import _testpg

_TEST_PG_SKIP_REASON = "test PG (:5433) unreachable - docker compose -f services/docker-compose.test-pg.yml up -d"


def _pg_available() -> bool:
    """COS-078: unified on _testpg.pg_available (single resolution point)."""
    return _testpg.pg_available()


pg_needed = pytest.mark.skipif(not _pg_available(), reason=_TEST_PG_SKIP_REASON)


@pytest_asyncio.fixture(scope="function")
async def notif_db():
    """Per-test PG engine + clean notification tables + session factory."""
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


class _ScriptedSmtpTransport:
    """SMTP-транспорт с программируемыми TransportOutcome/exception."""

    def __init__(self, outcomes: List):
        self._outcomes = list(outcomes)
        self.calls: List[dict] = []

    def deliver(self, to: str, subject: str, body: str) -> TransportOutcome:
        self.calls.append({"to": to})
        if self._outcomes:
            item = self._outcomes.pop(0)
            if isinstance(item, Exception):
                raise item
            return item
        return TransportOutcome(code=250)


@pg_needed
class TestAdapterThroughManager:
    @pytest.mark.asyncio
    async def test_transient_then_ok_retries_to_sent(self, notif_db):
        """451 → retryable_failure; retry по backoff → 250 → sent."""
        transport = _ScriptedSmtpTransport([
            TransportOutcome(451, "temporary local problem"),
        ])
        provider = SmtpEmailProvider(transport)
        async with notif_db() as session:
            mgr = NotificationManager(email_provider=provider)
            await mgr.record_event(
                session, event_type="run_failed", aggregate_type="run",
                aggregate_id="r-cos057", explicit_recipients=[RECIPIENT],
            )
            await mgr.process_outbox(session)

            rows = (await session.execute(
                select(NotificationRow).where(
                    NotificationRow.channel == "email",
                    NotificationRow.state == "retryable_failure",
                )
            )).scalars().all()
            assert len(rows) == 1
            assert transport.calls[-1]["to"] == RECIPIENT

            future = datetime.datetime.utcnow() + datetime.timedelta(hours=1)
            report = await mgr.process_retries(session, now=future)
            assert report.emails_sent == 1

    @pytest.mark.asyncio
    async def test_5xx_goes_to_dlq_with_visible_last_error(self, notif_db):
        """550 → terminal → failed (DLQ-видимость); last_error без адресата."""
        transport = _ScriptedSmtpTransport([
            TransportOutcome(550, "5.1.1 user unknown"),
        ])
        provider = SmtpEmailProvider(transport)
        async with notif_db() as session:
            mgr = NotificationManager(email_provider=provider)
            await mgr.record_event(
                session, event_type="run_failed", aggregate_type="run",
                aggregate_id="r-cos057-dlq", explicit_recipients=[RECIPIENT],
            )
            await mgr.process_outbox(session)

            dlq = await mgr.get_dlq(session)
            assert len(dlq) == 1
            assert dlq[0].state == "failed"
            assert "550" in (dlq[0].last_error or "")
            assert RECIPIENT not in (dlq[0].last_error or "")

    @pytest.mark.asyncio
    async def test_invalid_recipient_is_terminal_no_retry_loop(self, notif_db):
        """Невалидный адрес → terminal, без retry-циклов и без транспорта.

        Manager гейтит email-канал по looks_like_email (COS-055) — до
        провайдера плохой адрес не доходит; adapter-гвардия — контрактный
        safety net для прямых вызовов send().
        """
        transport = _ScriptedSmtpTransport([])
        provider = SmtpEmailProvider(transport)
        async with notif_db() as session:
            mgr = NotificationManager(email_provider=provider)
            await mgr.record_event(
                session, event_type="run_failed", aggregate_type="run",
                aggregate_id="r-cos057-badaddr", explicit_recipients=["not-an-email"],
            )
            await mgr.process_outbox(session)

            # Manager не создал email-строку: DLQ пуст, ретраев нет.
            dlq = await mgr.get_dlq(session)
            assert len(dlq) == 0
            email_rows = (await session.execute(
                select(NotificationRow).where(NotificationRow.channel == "email")
            )).scalars().all()
            assert len(email_rows) == 0
            assert transport.calls == []

            # Прямой вызов adapter.send() с плохим адресом — честный
            # permanent без транспорта (contract-level гвардия).
            direct = provider.send("not-an-email", subject="s", body="b")
            assert direct.accepted is False and direct.transient is False
            assert transport.calls == []

    @pytest.mark.asyncio
    async def test_adapter_logs_have_no_recipient(self, notif_db, caplog):
        """Логи adapter'а при живой доставке не содержат адресата."""
        transport = _ScriptedSmtpTransport([TransportOutcome(550, "user unknown")])
        provider = SmtpEmailProvider(transport)
        async with notif_db() as session:
            mgr = NotificationManager(email_provider=provider)
            with caplog.at_level(logging.DEBUG, logger="cosmoport.notifications.email"):
                await mgr.record_event(
                    session, event_type="run_failed", aggregate_type="run",
                    aggregate_id="r-cos057-logs", explicit_recipients=[RECIPIENT],
                )
                await mgr.process_outbox(session)
        text = " ".join(rec.getMessage() for rec in caplog.records
                        if rec.name == "cosmoport.notifications.email")
        assert text
        assert RECIPIENT not in text
        # NB: manager.py намеренно логирует recipient_id в [EMAIL:failed→DLQ]
        # (дизайн COS-055, вне scope адаптера) — зафиксировано в evidence-доке.
