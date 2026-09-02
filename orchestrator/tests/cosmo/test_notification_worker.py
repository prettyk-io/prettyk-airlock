# -*- coding: utf-8 -*-
"""Notification Delivery Hardening: тесты фонового outbox worker.

Покрывает:
  * tick() обрабатывает записанное событие → inbox row (deliverability
    без ручного POST /process);
  * tick() переживает PG down (возвращает None, не бросает);
  * run_forever() автоматически обрабатывает событие за интервал;
  * start/stop lifecycle (idempotent, cancel-safe).

Integration-тесты требуют PostgreSQL (auto-skip если PG недоступен).
"""
from __future__ import annotations

import asyncio

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from orchestrator.cosmo.notifications.manager import NotificationManager
from orchestrator.cosmo.notifications.worker import OutboxWorker, worker_enabled


import _testpg

_TEST_PG_SKIP_REASON = "test PG (:5433) unreachable - docker compose -f services/docker-compose.test-pg.yml up -d"


def _pg_available() -> bool:
    """COS-078: unified on _testpg.pg_available (single resolution point)."""
    return _testpg.pg_available()


pg_needed = pytest.mark.skipif(not _pg_available(), reason=_TEST_PG_SKIP_REASON)


@pytest_asyncio.fixture(scope="function")
async def notif_db(loop_safe_engine_reset):
    """Per-test PG engine + clean notification tables + session factory.

    loop_safe_engine_reset (COS-075): сбрасывает глобальный engine до
    создания локального — синглтон rebind'ится на текущий event loop.
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


@pytest.mark.asyncio
@pg_needed
async def test_worker_tick_delivers_event_without_manual_process(notif_db):
    """Событие в outbox → worker.tick() → уведомление в inbox оператора."""
    manager = NotificationManager()
    worker = OutboxWorker(manager, interval_s=0.05)

    async with notif_db() as session:
        await manager.record_event(
            session,
            event_type="run_failed",
            aggregate_type="run",
            aggregate_id="run-worker-tick-1",
            title="Worker tick delivery",
            message="should land in inbox via worker",
            explicit_recipients=["operator"],
        )
        await session.commit()

    report = await worker.tick()

    assert report is not None
    assert report["events_processed"] >= 1
    assert report["in_app_delivered"] >= 1

    async with notif_db() as session:
        rows = await manager.list_inbox(session, recipient_id="operator")
    assert any(r.notification_type == "run_failed" for r in rows)


@pytest.mark.asyncio
async def test_worker_tick_survives_pg_down(monkeypatch):
    """PG недоступен → tick возвращает None, не бросает исключение."""
    from orchestrator.cosmo.db import session as db_session_module

    class _Broken:
        def __call__(self, *a, **kw):
            raise RuntimeError("simulated PG outage")

    monkeypatch.setattr(db_session_module, "get_sessionmaker", _Broken())

    worker = OutboxWorker(NotificationManager(), interval_s=0.05)
    report = await worker.tick()
    assert report is None


@pytest.mark.asyncio
@pg_needed
async def test_worker_run_forever_auto_delivers(notif_db):
    """Событие записано → run_forever доставляет без ручного вызова /process."""
    manager = NotificationManager()
    worker = OutboxWorker(manager, interval_s=0.2)
    task = asyncio.create_task(worker.run_forever())
    try:
        await asyncio.sleep(0.05)
        async with notif_db() as session:
            await manager.record_event(
                session,
                event_type="gate_blocked",
                aggregate_type="gate",
                aggregate_id="gate-worker-auto-1",
                title="Auto delivery",
                message="worker picked it up",
                explicit_recipients=["operator"],
            )
            await session.commit()

        rows: list = []
        for _ in range(50):
            await asyncio.sleep(0.2)
            async with notif_db() as session:
                rows = await manager.list_inbox(session, recipient_id="operator")
            if any(r.notification_type == "gate_blocked" for r in rows):
                break
        assert any(r.notification_type == "gate_blocked" for r in rows), (
            "worker must deliver automatically within a few intervals"
        )
    finally:
        await worker.stop()


@pytest.mark.asyncio
async def test_worker_lifecycle_start_stop():
    """start idempotent; stop завершает таск; повторный stop безопасен."""
    worker = OutboxWorker(interval_s=60.0)  # длинный интервал — тик не случится
    worker.start()
    assert worker.running
    first_task = worker._task
    worker.start()
    assert worker._task is first_task, "start must be idempotent while running"

    await worker.stop(timeout=2.0)
    assert not worker.running
    await worker.stop()  # повторный stop — no-op


@pytest.mark.asyncio
async def test_worker_stop_does_not_hang_on_active_tick():
    """stop во время активных тиков завершает worker за timeout."""
    worker = OutboxWorker(interval_s=0.05)
    worker.start()
    await asyncio.sleep(0.15)  # дать сделать несколько тиков
    await asyncio.wait_for(worker.stop(timeout=2.0), timeout=3.0)
    assert not worker.running


def test_worker_enabled_env_flag(monkeypatch):
    monkeypatch.setenv("COSMO_OUTBOX_WORKER_ENABLED", "0")
    assert worker_enabled() is False
    monkeypatch.setenv("COSMO_OUTBOX_WORKER_ENABLED", "1")
    assert worker_enabled() is True
    monkeypatch.delenv("COSMO_OUTBOX_WORKER_ENABLED")
    assert worker_enabled() is True  # default on
