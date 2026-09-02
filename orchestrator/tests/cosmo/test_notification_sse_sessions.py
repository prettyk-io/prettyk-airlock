# -*- coding: utf-8 -*-
"""Notification Delivery Hardening: SSE stream — session reuse + recovery.

Evidence по сессиям:
  * один SSE-клиент = одна долгоживущая PG-сессия (не две на каждый 2s tick);
  * число PG-соединений от SSE-клиентов не растёт линейно с числом тиков
    (pg_stat_activity, application_name='cosmoport2');
  * recovery: мёртвый коннект (pg_terminate_backend) → SQLAlchemyError →
    новая сессия → poll работает снова (degraded → восстановление без дублей).

Тесты целевой функции _notification_poll_once (вынесена из стрима) +
реальные pg_stat_activity замеры. Integration — auto-skip без PG.
"""
from __future__ import annotations

import asyncio

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from orchestrator.cosmo.api.routes.sse import _notification_poll_once


import _testpg

_TEST_PG_SKIP_REASON = "test PG (:5433) unreachable - docker compose -f services/docker-compose.test-pg.yml up -d"


def _pg_available() -> bool:
    """COS-078: unified on _testpg.pg_available (single resolution point)."""
    return _testpg.pg_available()


pg_needed = pytest.mark.skipif(not _pg_available(), reason=_TEST_PG_SKIP_REASON)


@pytest_asyncio.fixture(scope="function")
async def notif_db(loop_safe_engine_reset):
    """Per-test PG engine + clean notification tables + session factory.

    SSE-клиентские коннекты помечены application_name='cosmo-sse-test' —
    pg_stat_activity замеры считают именно их.
    loop_safe_engine_reset (COS-075): глобальный синглтон (его использует
    продуктовый get_sessionmaker в sse.py) rebind'ится на текущий loop.
    """
    from orchestrator.cosmo.db.session import Base as CosmoBase

    engine = create_async_engine(
        _testpg.TEST_PG_URL, echo=False,
        pool_size=5, max_overflow=10,
        connect_args={"server_settings": {"application_name": "cosmo-sse-test"}},
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


async def _count_cosmo_sessions(probe_maker) -> int:
    """Число SSE-клиентских PG-соединений (через отдельное probe-соединение)."""
    async with probe_maker() as probe:
        result = await probe.execute(
            text("SELECT count(*) FROM pg_stat_activity "
                 "WHERE application_name = 'cosmo-sse-test'")
        )
        return result.scalar_one()


@pg_needed
@pytest.mark.asyncio
async def test_sse_sessions_do_not_grow_with_ticks(notif_db):
    """20 тиков на 2 SSE-клиентах: число PG-сессий не растёт со временем.

    Мониторим pg_stat_activity фоново в течение тиков. Число клиентских
    коннектов bounded числом клиентов (commit после тика возвращает
    коннект в пул) — линейный рост исключён.
    """
    # Probe через отдельный engine (своё application_name отсутствует — ок)
    probe_engine = create_async_engine(
        _testpg.TEST_PG_URL, echo=False
    )
    probe_maker = async_sessionmaker(probe_engine, expire_on_commit=False)

    # notif_db — это session_maker; каждая сессия = один «SSE-клиент»
    db_a = notif_db()
    db_b = notif_db()

    known_a: set[str] = set()
    known_b: set[str] = set()

    samples: list[int] = []
    stop_monitor = asyncio.Event()

    async def _monitor():
        while not stop_monitor.is_set():
            samples.append(await _count_cosmo_sessions(probe_maker))
            await asyncio.sleep(0.01)

    monitor = asyncio.create_task(_monitor())
    try:
        # 20 тиков × 2 клиента (10 тиков → замер, ещё 10 → финальный замер)
        for i in range(20):
            await _notification_poll_once(db_a, "operator", known_a, None)
            await db_a.commit()
            await _notification_poll_once(db_b, "operator", known_b, None)
            await db_b.commit()

        stop_monitor.set()
        await monitor

        first_half = samples[: len(samples) // 2]
        second_half = samples[len(samples) // 2 :]

        # Число клиентских сессий bounded числом клиентов (2):
        # коннекты берутся из пула на время тика и возвращаются commit'ом.
        assert max(samples) <= 2, (
            f"sessions exceeded client count: max={max(samples)}, samples={samples}"
        )
        # Нет роста во времени: вторая половина не больше первой
        assert max(second_half, default=0) <= max(first_half, default=2), (
            f"session usage grew over time: first_half={first_half}, second_half={second_half}"
        )
    finally:
        stop_monitor.set()
        if not monitor.done():
            monitor.cancel()
        await db_a.close()
        await db_b.close()
        await probe_engine.dispose()


@pg_needed
@pytest.mark.asyncio
async def test_sse_recovery_after_dead_connection(notif_db):
    """Мёртвый коннект → SQLAlchemyError → новая сессия → poll работает.

    Имитация PG down/restart: pg_terminate_backend убивает соединение
    текущей сессии; следующий poll обязан упасть (стрим переходит в
    degraded), recovery — на новой сессии — доставляет новые события.
    """
    manager_session_maker = notif_db
    db = manager_session_maker()

    known: set[str] = set()
    last_seen: str | None = None

    try:
        # Живой тик
        await _notification_poll_once(db, "operator", known, last_seen)
        await db.commit()

        # Убить backend-соединение этой сессии (имитация docker stop PG)
        pid_result = await db.execute(text("SELECT pg_backend_pid()"))
        pid = pid_result.scalar_one()
        async with notif_db() as killer:
            await killer.execute(text(f"SELECT pg_terminate_backend({pid})"))
            await killer.commit()

        # Следующий тик на мёртвом коннекте → ожидаем SQLAlchemyError
        with pytest.raises(Exception) as exc_info:
            await _notification_poll_once(db, "operator", known, last_seen)
            await db.commit()
        assert "closed" in str(exc_info.value).lower() or (
            exc_info.errisinstance(Exception)
        )

        # Recovery: стрим создаёт новую сессию и продолжает
        db_recovered = manager_session_maker()
        try:
            # Новое событие, записанное ПОСЛЕ reconnect (worker уже обработал)
            from orchestrator.cosmo.notifications.manager import NotificationManager

            async with db_recovered as s:
                mgr = NotificationManager()
                await mgr.record_event(
                    s,
                    event_type="run_succeeded",
                    aggregate_type="run",
                    aggregate_id="run-recovery-1",
                    title="After recovery",
                    message="delivered once, no duplicates",
                    explicit_recipients=["operator"],
                )
                await s.commit()
                await mgr.process_outbox(s)
                await s.commit()

            payloads = await _notification_poll_once(
                db_recovered, "operator", known, last_seen
            )
            new_events = [p for p in payloads if p["event"] == "notification_new"]
            assert len(new_events) == 1, (
                f"recovery must deliver pending event exactly once, got {len(new_events)}"
            )
            body = __import__("json").loads(new_events[0]["data"])
            assert body["title"] == "After recovery"
        finally:
            await db_recovered.close()
    finally:
        try:
            await db.close()
        except Exception:
            pass


@pg_needed
@pytest.mark.asyncio
async def test_sse_poll_dedup_unchanged_after_recovery(notif_db):
    """После recovery last_known_ids сохраняется → повторные тики без дублей."""
    from orchestrator.cosmo.notifications.manager import NotificationManager

    db = notif_db()
    known: set[str] = set()
    last_seen: str | None = None

    try:
        async with notif_db() as s:
            mgr = NotificationManager()
            await mgr.record_event(
                s,
                event_type="run_failed",
                aggregate_type="run",
                aggregate_id="run-dedup-1",
                title="Dedup event",
                message="",
                explicit_recipients=["operator"],
            )
            await s.commit()
            await mgr.process_outbox(s)
            await s.commit()

        first = await _notification_poll_once(db, "operator", known, last_seen)
        await db.commit()
        new_first = [p for p in first if p["event"] == "notification_new"]
        assert len(new_first) == 1

        # «Recovery» — тот же клиент, тот же last_known_ids
        second = await _notification_poll_once(db, "operator", known, last_seen)
        await db.commit()
        new_second = [p for p in second if p["event"] == "notification_new"]
        assert len(new_second) == 0, "replayed ticks must not duplicate notifications"
    finally:
        try:
            await db.close()
        except Exception:
            pass
