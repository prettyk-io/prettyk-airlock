# -*- coding: utf-8 -*-
"""COS-088: SSE event backlog — reconnect без потери событий.

Юниты (без PG):
  * FakeValkey stream-double — xadd/xrange/expire + инъекция сбоев;
  * publish/replay roundtrip, id-инвариант (SSE id == backlog id);
  * gap-детекция: неизвестный id, TTL-вытеснение, клиент впереди, пустой stream;
  * degraded-режим: memory ring, transient valkey-сбой → None без фолбэка;
  * restart: valkey-история переживает «рестарт», memory — gap → resync.

Интеграция (тестовый PG, auto-skip без него):
  * драйв _run_stream/_domain_stream/_notification_stream через Request-двойку:
    initial с id, replay без дублей, gap → resync, pre-seed без run_created-дюпов.
"""
from __future__ import annotations

import json

import pytest
import pytest_asyncio
from sqlalchemy import insert, select, text
from sqlalchemy.ext.asyncio import create_async_engine

from orchestrator.cosmo.api import sse_backlog
from orchestrator.cosmo.api.routes import sse as sse_routes

import _testpg

_TEST_PG_SKIP_REASON = (
    "test PG (:5433) unreachable - "
    "docker compose -f services/docker-compose.test-pg.yml up -d"
)


def _pg_available() -> bool:
    return _testpg.pg_available()


pg_needed = pytest.mark.skipif(not _pg_available(), reason=_TEST_PG_SKIP_REASON)


# ══════════════════════════════════════════════════════════════════
# Test doubles & helpers
# ══════════════════════════════════════════════════════════════════

class FakeValkey:
    """Stream-double: xadd/xrange/expire/ping с инъекцией сбоев (COS-088)."""

    def __init__(self) -> None:
        self.streams: dict[str, list[tuple[str, dict[str, str]]]] = {}
        self._ms = 1_700_000_000_000
        self._seq = 0
        self.fail_xadd = False
        self.fail_xrange = False

    def ping(self) -> bool:
        return True

    def xadd(self, stream, fields, maxlen=None, approximate=True):
        if self.fail_xadd:
            raise RuntimeError("valkey xadd down")
        self._ms += 1
        self._seq += 1
        event_id = f"{self._ms}-{self._seq}"
        self.streams.setdefault(stream, []).append((event_id, dict(fields)))
        return event_id

    def expire(self, stream, ttl) -> bool:
        return True

    def xrange(self, stream, min="-", max="+"):
        if self.fail_xrange:
            raise RuntimeError("valkey xrange down")
        return list(self.streams.get(stream, []))


@pytest.fixture(autouse=True)
def _isolate_backlog(monkeypatch):
    """Изоляция backlog-состояния между тестами (глобальные кольца/клиент)."""
    monkeypatch.setattr(sse_backlog, "_valkey_client", None)
    sse_backlog.reset_backlog()
    yield
    sse_backlog.reset_backlog()


@pytest.fixture()
def memory_mode(monkeypatch):
    """Деградация без valkey-клиента (детерминированно, независимо от хоста)."""
    monkeypatch.setattr(sse_backlog, "_get_valkey", lambda: None)
    return sse_backlog


@pytest.fixture()
def fake_valkey():
    double = FakeValkey()
    sse_backlog.set_valkey_double(double)
    return double


class _StubRequest:
    """Request-двойка для драйва SSE-генераторов (is_disconnected по счётчику)."""

    def __init__(self, checks_before_disconnect: int = 1) -> None:
        self.headers: dict[str, str] = {}
        self._checks_left = checks_before_disconnect

    async def is_disconnected(self) -> bool:
        if self._checks_left <= 0:
            return True
        self._checks_left -= 1
        return False


async def _drive(gen, limit: int = 200) -> list[dict]:
    events: list[dict] = []
    async for item in gen:
        events.append(item)
        if len(events) >= limit:
            break
    return events


def _request_with_headers(headers: dict[str, str] | None = None):
    from starlette.requests import Request

    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": [
            (k.lower().encode(), v.encode()) for k, v in (headers or {}).items()
        ],
        "query_string": b"",
        "server": ("test", 80),
        "scheme": "http",
    }
    return Request(scope)


# ══════════════════════════════════════════════════════════════════
# Юниты: publish / replay / gap (valkey double)
# ══════════════════════════════════════════════════════════════════

class TestPublishReplayValkey:
    def test_publish_returns_monotonic_ids(self, fake_valkey):
        id1 = sse_backlog.publish("run", "r1", "status_change", '{"status":"queued"}')
        id2 = sse_backlog.publish("run", "r1", "status_change", '{"status":"running"}')
        assert id1 and id2
        assert id1.endswith("-1") and id2.endswith("-2")

    def test_replay_after_id_no_gap(self, fake_valkey):
        id1 = sse_backlog.publish("run", "r1", "status_change", "a")
        id2 = sse_backlog.publish("run", "r1", "batch_complete", "b")
        id3 = sse_backlog.publish("run", "r1", "finding", "c")
        result = sse_backlog.replay("run", "r1", id1)
        assert result is not None and not result.gap
        assert [r.id for r in result.records] == [id2, id3]

    def test_sse_id_equals_backlog_id(self, fake_valkey):
        """Ключевой инвариант: publish вернул id, под которым запись лежит."""
        event_id = sse_backlog.publish("run", "r1", "finding", '{"count":1}')
        result = sse_backlog.replay("run", "r1", "0-0")
        # "0-0" меньше всех — все записи после него; но presence не подтверждён
        assert result is not None and result.gap  # unknown id → gap
        result2 = sse_backlog.replay("run", "r1", event_id)
        assert result2 is not None and not result2.gap
        assert all(r.id != event_id for r in result2.records)  # строго после

    def test_unknown_id_is_gap(self, fake_valkey):
        sse_backlog.publish("run", "r1", "status_change", "a")
        result = sse_backlog.replay("run", "r1", "1234567890123-99")
        assert result is not None and result.gap and result.records == []

    def test_client_ahead_is_not_gap(self, fake_valkey):
        last = None
        for i in range(3):
            last = sse_backlog.publish("run", "r1", "status_change", str(i))
        result = sse_backlog.replay("run", "r1", "9999999999999-0")
        assert result is not None and not result.gap and result.records == []

    def test_empty_stream_is_gap(self, fake_valkey):
        result = sse_backlog.replay("run", "never-published", "0-1")
        assert result is not None and result.gap

    def test_ttl_eviction_is_gap(self, fake_valkey):
        """TTL-вытеснение: after_id исчез из stream → gap, не тишина."""
        id1 = sse_backlog.publish("run", "r1", "status_change", "a")
        sse_backlog.publish("run", "r1", "status_change", "b")
        # симуляция вытеснения: убрали запись id1 из stream (MAXLEN/TTL)
        fake_valkey.streams[sse_backlog._stream_key("run", "r1")] = [
            (eid, f) for eid, f in fake_valkey.streams[sse_backlog._stream_key("run", "r1")]
            if eid != id1
        ]
        result = sse_backlog.replay("run", "r1", id1)
        assert result is not None and result.gap

    def test_limit_capped(self, fake_valkey):
        first = sse_backlog.publish("run", "r1", "finding", "start")
        for i in range(5):
            sse_backlog.publish("run", "r1", "finding", str(i))
        result = sse_backlog.replay("run", "r1", first, limit=2)
        assert result is not None and len(result.records) == 2

    def test_event_type_and_data_roundtrip(self, fake_valkey):
        data = json.dumps({"status": "running", "previous": "queued"})
        id1 = sse_backlog.publish("run", "r1", "status_change", data)
        id2 = sse_backlog.publish("run", "r1", "finding", '{"count":3}')
        id3 = sse_backlog.publish("run", "r1", "status_change", "x")
        result = sse_backlog.replay("run", "r1", id2)
        assert result is not None and not result.gap
        assert [r.id for r in result.records] == [id3]
        assert result.records[0].event_type == "status_change"
        assert result.records[0].data == "x"


class TestDegraded:
    def test_transient_xadd_failure_returns_none(self, fake_valkey):
        """Valkey-сбой → None БЕЗ фолбэка в memory (id-пространства не мешать)."""
        fake_valkey.fail_xadd = True
        assert sse_backlog.publish("run", "r1", "status_change", "a") is None
        fake_valkey.fail_xadd = False
        # восстановление — следующий publish успешен, memory-кольцо не записано
        event_id = sse_backlog.publish("run", "r1", "status_change", "b")
        assert event_id
        assert sse_backlog._stream_key("run", "r1") not in sse_backlog._rings

    def test_replay_failure_returns_none(self, fake_valkey):
        sse_backlog.publish("run", "r1", "status_change", "a")
        fake_valkey.fail_xrange = True
        assert sse_backlog.replay("run", "r1", "0-1") is None

    def test_backlog_mode_reflects_store(self, fake_valkey):
        assert sse_backlog.backlog_mode() == "valkey"

    def test_backlog_mode_memory_when_no_client(self, memory_mode):
        assert sse_backlog.backlog_mode() == "memory"


class TestMemoryMode:
    def test_publish_replay_roundtrip(self, memory_mode):
        id1 = sse_backlog.publish("run", "r1", "status_change", "a")
        id2 = sse_backlog.publish("run", "r1", "status_change", "b")
        result = sse_backlog.replay("run", "r1", id1)
        assert result is not None and not result.gap
        assert [r.id for r in result.records] == [id2]

    def test_memory_unknown_id_gap(self, memory_mode):
        sse_backlog.publish("run", "r1", "status_change", "a")
        result = sse_backlog.replay("run", "r1", "1234567890123-99")
        assert result is not None and result.gap

    def test_memory_client_ahead_not_gap(self, memory_mode):
        sse_backlog.publish("run", "r1", "status_change", "a")
        result = sse_backlog.replay("run", "r1", "9999999999999-0")
        assert result is not None and not result.gap

    def test_memory_restart_is_gap_not_silence(self, memory_mode):
        """Рестарт процесса (memory-режим): история потеряна → gap → resync."""
        event_id = sse_backlog.publish("run", "r1", "status_change", "a")
        sse_backlog.reset_backlog()  # «рестарт»: чистые глобалы
        result = sse_backlog.replay("run", "r1", event_id)
        assert result is not None and result.gap


class TestRestartValkeySurvives:
    def test_valkey_history_survives_restart(self, fake_valkey):
        """Рестарт cosmo-api: чистые глобалы, тот же valkey — история жива."""
        id1 = sse_backlog.publish("run", "r1", "status_change", "a")
        id2 = sse_backlog.publish("run", "r1", "status_change", "b")
        sse_backlog.reset_backlog()            # «рестарт»: сброс _valkey_client/колец
        sse_backlog.set_valkey_double(fake_valkey)  # новое подключение к тому же store
        result = sse_backlog.replay("run", "r1", id1)
        assert result is not None and not result.gap
        assert [r.id for r in result.records] == [id2]


# ══════════════════════════════════════════════════════════════════
# Юниты: SSE-контракт (formatter id, resolve last-event-id, хелперы)
# ══════════════════════════════════════════════════════════════════

class TestSseContractCos088:
    @pytest.mark.asyncio
    async def test_formatter_emits_id_line_before_event(self):
        async def gen():
            yield {"event": "status_change", "data": "x", "id": "1700000000000-1"}

        lines = []
        async for line in sse_routes._sse_formatter(gen()):
            lines.append(line)
        block = lines[0]
        assert block.startswith("id: 1700000000000-1\n")
        assert "event: status_change" in block

    @pytest.mark.asyncio
    async def test_formatter_no_id_line_without_id(self):
        async def gen():
            yield {"event": "stream_backlog", "data": '{"mode":"memory"}'}

        lines = []
        async for line in sse_routes._sse_formatter(gen()):
            lines.append(line)
        assert not lines[0].startswith("id:")

    def test_resolve_last_event_id_query_wins(self):
        request = _request_with_headers({"Last-Event-ID": "1-1"})
        assert sse_routes._resolve_last_event_id(request, "2-2") == "2-2"

    def test_resolve_last_event_id_header_fallback(self):
        request = _request_with_headers({"Last-Event-ID": "1-1"})
        assert sse_routes._resolve_last_event_id(request, "") == "1-1"

    def test_resolve_last_event_id_empty(self):
        request = _request_with_headers({})
        assert sse_routes._resolve_last_event_id(request, "") == ""

    def test_backlog_item_attaches_id(self, memory_mode):
        item = sse_routes._backlog_item("run", "r1", "finding", '{"count":1}')
        assert item["event"] == "finding"
        assert item["id"]

    def test_backlog_item_without_id_on_publish_failure(self, fake_valkey):
        fake_valkey.fail_xadd = True
        item = sse_routes._backlog_item("run", "r1", "finding", '{"count":1}')
        assert "id" not in item  # событие доставлено, но без id

    def test_backlog_flag_event_shape(self):
        flag = sse_routes._backlog_flag_event("memory")
        assert flag["event"] == "stream_backlog"
        assert json.loads(flag["data"]) == {"mode": "memory"}
        assert "id" not in flag

    def test_sse_response_carries_backlog_header(self, memory_mode):
        async def gen():
            yield {"event": "x", "data": "y"}
            return

        resp = sse_routes._sse_response(
            gen(), extra_headers={"X-Cosmo-Backlog": sse_backlog.backlog_mode()}
        )
        assert resp.headers["x-cosmo-backlog"] == "memory"

    def test_run_initial_payload_shape(self):
        snap = {
            "run": {"status": "running", "id": "r1"},
            "batches": [{"id": "b1", "type": "build", "status": "passed"}],
            "gates": [{"id": "g1", "decision": "pass"}],
            "findings_count": 2,
            "evidence_count": 5,
        }
        payload = json.loads(sse_routes._run_initial_payload(snap))
        assert payload["status"] == "running"
        assert payload["batches"][0]["id"] == "b1"
        assert payload["findings_count"] == 2


# ══════════════════════════════════════════════════════════════════
# Интеграция (тестовый PG): драйв генераторов стримов
# ══════════════════════════════════════════════════════════════════

RUN_ID = "run-bl-1"
DOMAIN_ID = "dom-bl"
APP_ID = "app-bl"
PLAN_ID = "plan-bl"


async def _seed_run(engine, status: str = "pending") -> None:
    from orchestrator.cosmo.db.models import (
        Application, Domain, PipelinePlan, Run,
    )

    async with engine.begin() as conn:
        await conn.execute(insert(Domain).values(
            id=DOMAIN_ID, label="BL", forge_url="https://forge.example",
            forge_token_ref="ref-bl",
        ))
        await conn.execute(insert(Application).values(
            id=APP_ID, domain_id=DOMAIN_ID, level=0,
        ))
        await conn.execute(insert(PipelinePlan).values(
            id=PLAN_ID, app_id=APP_ID, level="app", scope_id=APP_ID,
            compiled_hash="hash-bl",
        ))
        await conn.execute(insert(Run).values(
            id=RUN_ID, plan_id=PLAN_ID, trigger="manual",
            domain_id=DOMAIN_ID, status=status,
        ))


async def _set_run_status(engine, status: str) -> None:
    from orchestrator.cosmo.db.models import Run

    async with engine.begin() as conn:
        await conn.execute(
            text("UPDATE runs SET status = :s WHERE id = :r"),
            {"s": status, "r": RUN_ID},
        )


async def _cleanup_run(engine) -> None:
    async with engine.begin() as conn:
        await conn.exec_driver_sql(
            "DELETE FROM notification_inbox WHERE recipient_id = 'operator-bl'"
        )
        await conn.exec_driver_sql(
            "DELETE FROM notification_events WHERE event_type = 'run_succeeded'"
        )
        await conn.exec_driver_sql(
            "DELETE FROM evidence_ledger WHERE run_id = 'run-bl-1'"
        )
        await conn.exec_driver_sql("DELETE FROM runs WHERE id = 'run-bl-1'")
        await conn.exec_driver_sql("DELETE FROM batches WHERE plan_id = 'plan-bl'")
        await conn.exec_driver_sql("DELETE FROM gates WHERE plan_id = 'plan-bl'")
        await conn.exec_driver_sql("DELETE FROM plan_bricks WHERE plan_id = 'plan-bl'")
        await conn.exec_driver_sql("DELETE FROM pipeline_plans WHERE id = 'plan-bl'")
        await conn.exec_driver_sql("DELETE FROM apps WHERE id = 'app-bl'")
        await conn.exec_driver_sql("DELETE FROM domains WHERE id = 'dom-bl'")


@pytest_asyncio.fixture(scope="function")
async def sse_db(loop_safe_engine_reset):
    """Per-test PG engine (global engine rebinds to the live loop)."""
    from orchestrator.cosmo.db.session import Base as CosmoBase

    engine = create_async_engine(_testpg.TEST_PG_URL, echo=False)
    async with engine.begin() as conn:
        await conn.execute(text("SELECT pg_advisory_xact_lock(7241965813)"))
        await conn.run_sync(CosmoBase.metadata.create_all)
        from orchestrator.cosmo.db.models_gate_trail import GateTrailBase
        await conn.run_sync(GateTrailBase.metadata.create_all)
        from orchestrator.cosmo.db.models_transfer import TransferRegistryBase
        await conn.run_sync(TransferRegistryBase.metadata.create_all)
    await _cleanup_run(engine)
    yield engine
    await _cleanup_run(engine)
    await engine.dispose()


@pg_needed
@pytest.mark.asyncio
async def test_run_stream_initial_has_id_and_reconnect_replays(sse_db, memory_mode):
    """Reconnect с last-event-id: пропущенные события доставлены, без дублей.

    connect#1 (fresh) → initial status_change с backlog-id X0;
    «офлайн»-период: статус run в PG изменился + live-loop это публикует;
    connect#2 с last_event_id=X0 → сначала replay недоставленного, затем
    initial — но state идемпотентен, события с монотонными id.
    """
    await _seed_run(sse_db, status="pending")

    # connect#1: flag → initial (id X0) → один тик (без изменений) → break
    events = await _drive(sse_routes._run_stream(RUN_ID, _StubRequest(1), ""))
    assert events[0]["event"] == "stream_backlog"
    initial = [e for e in events if e.get("event") == "status_change"]
    assert len(initial) == 1 and initial[0].get("id")
    x0 = initial[0]["id"]

    # «офлайн»: статус сменился; live-loop при подключённом клиенте публикует
    # status_change в backlog (тот же код-путь, что _backlog_item в стриме)
    await _set_run_status(sse_db, "running")
    missed_id = sse_backlog.publish(
        "run", RUN_ID, "status_change",
        json.dumps({"status": "running", "previous": "pending"}),
    )
    assert missed_id and missed_id > x0

    # connect#2 с last-event-id X0: replay доставляет недоставленное
    events2 = await _drive(
        sse_routes._run_stream(RUN_ID, _StubRequest(1), x0)
    )
    replayed = [e for e in events2 if e.get("id") == missed_id]
    assert len(replayed) == 1, f"missed event must be replayed once: {events2}"
    assert replayed[0]["event"] == "status_change"

    # хвост: initial status_change с id > X0 (state-based повтор безопасен)
    ids = [e["id"] for e in events2 if e.get("id")]
    assert all(i > x0 for i in ids)
    # gap нет → resync не эмитится
    assert not any(e.get("event") == "resync" for e in events2)


@pg_needed
@pytest.mark.asyncio
async def test_run_stream_gap_after_memory_reset_leads_to_resync(sse_db, memory_mode):
    """TTL-вытеснение/рестарт в memory-режиме → gap → resync-снапшот, не тишина."""
    await _seed_run(sse_db, status="pending")

    events = await _drive(sse_routes._run_stream(RUN_ID, _StubRequest(1), ""))
    initial = [e for e in events if e.get("event") == "status_change"]
    x0 = initial[0]["id"]

    # «рестарт» в memory-режиме: кольца пусты, X0 вне backlog
    sse_backlog.reset_backlog()
    await _set_run_status(sse_db, "running")

    events2 = await _drive(
        sse_routes._run_stream(RUN_ID, _StubRequest(1), x0)
    )
    resyncs = [e for e in events2 if e.get("event") == "resync"]
    assert len(resyncs) == 1, f"gap must trigger exactly one resync: {events2}"
    body = json.loads(resyncs[0]["data"])
    assert body["status"] == "running"  # снапшот актуального state


@pg_needed
@pytest.mark.asyncio
async def test_run_stream_valkey_restart_resample(sse_db, fake_valkey):
    """Рестарт cosmo-api при живом клиенте (valkey): события доставляются ×2."""
    await _seed_run(sse_db, status="pending")

    events = await _drive(sse_routes._run_stream(RUN_ID, _StubRequest(1), ""))
    initial = [e for e in events if e.get("event") == "status_change"]
    x0 = initial[0]["id"]
    assert json.loads(initial[0]["data"])["status"] == "pending"

    # офлайн-период: событие в valkey (переживёт рестарт API)
    missed = sse_backlog.publish(
        "run", RUN_ID, "finding", json.dumps({"count": 1, "delta": 1})
    )
    # «рестарт»: глобалы чисты, тот же valkey
    sse_backlog.reset_backlog()
    sse_backlog.set_valkey_double(fake_valkey)

    events2 = await _drive(
        sse_routes._run_stream(RUN_ID, _StubRequest(1), x0)
    )
    replayed = [e for e in events2 if e.get("id") == missed]
    assert len(replayed) == 1, "missed finding must survive restart via valkey"
    assert json.loads(replayed[0]["data"])["count"] == 1
    assert not any(e.get("event") == "resync" for e in events2)


@pg_needed
@pytest.mark.asyncio
async def test_domain_stream_preseed_no_run_created_dupes(sse_db, memory_mode):
    """Reconnect домен-стрима: run_created не пере-выводится для известного run."""
    await _seed_run(sse_db, status="pending")

    # connect#1 (fresh): первый тик → run_created
    events = await _drive(sse_routes._domain_stream(DOMAIN_ID, _StubRequest(1), ""))
    created = [e for e in events if e.get("event") == "run_created"]
    assert len(created) == 1
    x0 = created[0]["id"]
    assert json.loads(created[0]["data"])["run_id"] == RUN_ID

    # connect#2 с last-event-id: replay пуст (gap=False) → pre-seed →
    # live-цикл НЕ пере-выводит run_created
    events2 = await _drive(
        sse_routes._domain_stream(DOMAIN_ID, _StubRequest(1), x0)
    )
    created2 = [e for e in events2 if e.get("event") == "run_created"]
    assert created2 == [], f"pre-seed must suppress run_created dupes: {events2}"
    assert not any(e.get("event") == "resync" for e in events2)


@pg_needed
@pytest.mark.asyncio
async def test_notification_stream_replay_and_poll_dedup(
    sse_db, memory_mode, monkeypatch
):
    """Notification reconnect: replay из backlog + poll-дедуп по seed.

    Вторая нотификация была опубликована в backlog «живым» соединением,
    пока клиент был офлайн; reconnect с last-event-id доставляет её из
    replay, а последующий poll НЕ дублирует (last_known_ids засеян).
    """
    from orchestrator.cosmo.db.models_notifications import NotificationRow
    from orchestrator.cosmo.notifications.manager import NotificationManager

    monkeypatch.setattr(sse_routes, "_NOTIFICATION_POLL_S", 0.01)

    async def _seed_notification(title: str) -> str:
        from orchestrator.cosmo.db.session import get_sessionmaker

        sm = get_sessionmaker()
        async with sm() as s:
            mgr = NotificationManager()
            await mgr.record_event(
                s,
                event_type="run_succeeded",
                aggregate_type="run",
                aggregate_id=f"run-bl-{title}",
                title=title,
                message="",
                explicit_recipients=["operator-bl"],
            )
            await s.commit()
            await mgr.process_outbox(s)
            await s.commit()
            rows = await s.execute(
                select(NotificationRow.id).where(
                    NotificationRow.recipient_id == "operator-bl",
                    NotificationRow.title == title,
                )
            )
            return rows.scalar_one()

    # Первая нотификация в PG — connect#1 доставит её poll'ом
    first_row_id = await _seed_notification("First event")

    # connect#1: flag → initial → poll → notification_new с id X1
    events = await _drive(
        sse_routes._notification_stream("operator-bl", _StubRequest(2), "")
    )
    news = [e for e in events if e.get("event") == "notification_new"]
    assert len(news) == 1 and news[0].get("id"), f"no id on notification_new: {events}"
    x1 = news[0]["id"]

    # офлайн: вторая нотификация записана в PG и опубликована в backlog
    # «живым» соединением (publish — тот же код-путь, что в стриме)
    row_id = await _seed_notification("Offline event")
    offline_payload = json.dumps({
        "id": row_id, "event_id": "", "notification_type": "run_succeeded",
        "severity": "info", "title": "Offline event", "message": "",
        "created_at": "",
    })
    published = sse_backlog.publish("notif", "operator-bl", "notification_new", offline_payload)
    assert published and published > x1

    # connect#2 с last-event-id X1: replay доставляет офлайн-событие ровно
    # один раз (из backlog), poll НЕ дублирует его (last_known_ids засеян
    # из replay). First event пере-приходит poll'ом — по дизайну durable
    # inbox пере-доставляет последние 20, клиент дедуплицирует по data.id.
    events2 = await _drive(
        sse_routes._notification_stream("operator-bl", _StubRequest(2), x1)
    )
    news2 = [e for e in events2 if e.get("event") == "notification_new"]
    replayed = [e for e in news2 if e.get("id") == published]
    assert len(replayed) == 1, (
        f"replay must deliver the offline event exactly once: {events2}"
    )
    assert json.loads(replayed[0]["data"])["id"] == row_id
    titles = [json.loads(e["data"]).get("title") for e in news2]
    assert titles.count("Offline event") == 1, (
        f"replayed event must not be re-delivered by poll: {titles}"
    )
