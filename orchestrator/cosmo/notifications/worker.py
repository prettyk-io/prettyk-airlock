# -*- coding: utf-8 -*-
"""Notification Delivery Hardening: фоновый outbox worker.

Доставляет уведомления без ручного POST /api/v1/notifications/process.
Endpoint /process остаётся для совместимости и тестов (идемпотентен —
UNIQUE(event_id, recipient_id, channel) исключает дубли при конкурентной
обработке worker'ом и ручным вызовом).

Запуск из FastAPI lifespan (api/startup.py):
    worker = OutboxWorker()
    worker.start()
    ...
    await worker.stop()

Управление:
    COSMO_OUTBOX_WORKER_ENABLED   (default "1")  — выключить для отладки
    COSMO_OUTBOX_WORKER_INTERVAL_S (default "10") — период тика

Отказоустойчивость: PG недоступен → tick логирует warning и ждёт
следующего интервала; durable события не теряются (transactional outbox).
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Optional

from orchestrator.cosmo.notifications.manager import NotificationManager

logger = logging.getLogger("cosmo.notifications.worker")


def _env_flag(name: str, default: str) -> bool:
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes")


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


class OutboxWorker:
    """Периодический tick по NotificationManager.process_outbox."""

    def __init__(
        self,
        manager: Optional[NotificationManager] = None,
        *,
        interval_s: Optional[float] = None,
        batch_size: int = 50,
    ) -> None:
        self._manager = manager or NotificationManager()
        self._interval_s = (
            interval_s
            if interval_s is not None
            else _env_float("COSMO_OUTBOX_WORKER_INTERVAL_S", 10.0)
        )
        self._batch_size = batch_size
        self._task: Optional[asyncio.Task] = None
        self._stop_event = asyncio.Event()

    # ── Свойства для диагностики ──

    @property
    def interval_s(self) -> float:
        return self._interval_s

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    # ── Ядро: один тик ──

    async def tick(self) -> Optional[dict]:
        """Одна итерация обработки outbox.

        Возвращает ProcessReport как dict или None при недоступности PG.
        Ошибки НЕ пробрасываются наверх — worker переживает PG down.
        """
        from orchestrator.cosmo.db.session import get_sessionmaker

        try:
            async with get_sessionmaker()() as session:
                report = await self._manager.process_outbox(
                    session, batch_size=self._batch_size
                )
                await session.commit()
            if report.events_processed:
                logger.info(
                    "[OUTBOX:worker] processed=%s in_app=%s dup=%s email=%s",
                    report.events_processed,
                    report.in_app_delivered,
                    report.in_app_duplicates,
                    report.emails_sent,
                )
            return {
                "events_processed": report.events_processed,
                "in_app_delivered": report.in_app_delivered,
                "in_app_duplicates": report.in_app_duplicates,
                "emails_sent": report.emails_sent,
            }
        except Exception as exc:  # noqa: BLE001 — worker переживает PG down
            logger.warning("[OUTBOX:worker] tick failed (PG unavailable?): %s", exc)
            return None

    # ── Цикл ──

    async def run_forever(self) -> None:
        logger.info(
            "[OUTBOX:worker] started (interval=%ss, batch=%s)",
            self._interval_s,
            self._batch_size,
        )
        while not self._stop_event.is_set():
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(), timeout=self._interval_s
                )
                break  # stop requested
            except asyncio.TimeoutError:
                pass
            await self.tick()
        logger.info("[OUTBOX:worker] stopped")

    # ── Lifecycle ──

    def start(self) -> None:
        if self.running:
            return
        self._stop_event = asyncio.Event()
        self._task = asyncio.create_task(self.run_forever(), name="outbox-worker")

    async def stop(self, timeout: float = 5.0) -> None:
        if self._task is None:
            return
        self._stop_event.set()
        try:
            await asyncio.wait_for(self._task, timeout=timeout)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            self._task.cancel()
        self._task = None


def worker_enabled() -> bool:
    """Env-выключатель (для тестов/отладки)."""
    return _env_flag("COSMO_OUTBOX_WORKER_ENABLED", "1")
