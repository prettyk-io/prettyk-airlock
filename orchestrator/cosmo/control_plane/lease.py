# -*- coding: utf-8 -*-
"""COS-034: Lease + Heartbeat tracker for RunControlPlane.

Мониторинг живых worker'ов:
  - `register_worker(id, capabilities)` → LeaseRecord
  - `heartbeat(worker_id)` → продлить lease на TTL секунд
  - `is_worker_alive(worker_id)` → проверка живости по таймстемпу
  - `detect_dead_workers()` → список просроченных worker'ов
  - `reclaim_orphaned_runs()` → requeue осиротевших run'ов
  - `worker_health_snapshot()` → сводка по всем worker'ам
  - `recover_from_pg()` → после сброса Redis/Valkey восстанавливает состояние

Инварианты:
  - Два run не могут получить один порт одновременно
  - Lease просрочен → worker помечается dead, run возвращается в очередь
  - Heartbeat сбрасывает TTL, отодвигает `lease_expires_at`
  - Если Valkey доступен → lease дублируется в Valkey key с TTL
  - При сбросе Valkey → lease восстанавливается из in-memory state
"""
from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

logger = logging.getLogger("cosmoport.lease")


# ── Lease Record ──

@dataclass
class LeaseRecord:
    """Запись lease одного worker'а."""
    worker_id: str
    capabilities: frozenset[str] = frozenset()
    # scanner, playwright, ...
    busy: bool = False                            # занят ли worker run'ом
    current_run_id: Optional[str] = None           # какой run обслуживает
    lease_expires_at: Optional[float] = None       # когда истекает lease
    last_heartbeat: float = field(default_factory=time.time)
    registered_at: float = field(default_factory=time.time)
    stale_count: int = 0                          # сколько раз был dead подряд
    total_heartbeats: int = 0                     # всего принято heartbeat'ов
    health_history: list[tuple[float, str]] = field(default_factory=list)
    # (ts, "alive" | "dead" | "recovered" | "terminated")

    @property
    def is_alive(self) -> bool:
        """Worker жив, если lease не истёк и он зарегистрирован."""
        if self.lease_expires_at is None:
            return True  # ещё не назначался на run — считается живым
        return time.time() < self.lease_expires_at

    @property
    def is_expired(self) -> bool:
        """Lease истёк — worker мёртв."""
        if self.lease_expires_at is None:
            return False
        return time.time() >= self.lease_expires_at

    @property
    def seconds_since_last_heartbeat(self) -> float:
        return max(0.0, time.time() - self.last_heartbeat)


# ── Lease Tracker ──

class LeaseTracker:
    """Мониторинг lease'ов worker'ов с heartbeat, dead detection и requeue.

    Подключается к RunControlPlane как отдельный компонент.
    """

    def __init__(
        self,
        default_ttl_seconds: float = 60.0,
        max_stale_count: int = 5,
        clock: Callable[[], float] = time.time,
        on_worker_dead: Optional[Callable[[LeaseRecord, Optional[str]], None]] = None,
        # callback: (worker, orphaned_run_id)
    ) -> None:
        self._default_ttl = default_ttl_seconds
        self._max_stale_count = max_stale_count
        self._clock = clock
        self._on_worker_dead = on_worker_dead

        self._lock = threading.RLock()
        self._workers: dict[str, LeaseRecord] = {}

    # ── Регистрация / дерегистрация ──

    def register_worker(
        self, worker_id: str, capabilities: frozenset[str] | None = None
    ) -> LeaseRecord:
        """Зарегистрировать worker (идемпотентно)."""
        with self._lock:
            existing = self._workers.get(worker_id)
            if existing is not None:
                # Обновить capabilities, если изменились
                if capabilities is not None:
                    existing.capabilities = capabilities
                return existing

            rec = LeaseRecord(
                worker_id=worker_id,
                capabilities=capabilities or frozenset(),
                registered_at=self._clock(),
            )
            self._workers[worker_id] = rec
            logger.info("Worker registered: %s (caps: %s)", worker_id, rec.capabilities)
            return rec

    def deregister_worker(self, worker_id: str) -> Optional[LeaseRecord]:
        """Дерегистрировать worker. Возвращает запись если была."""
        with self._lock:
            rec = self._workers.pop(worker_id, None)
            if rec is not None:
                rec.health_history.append((self._clock(), "terminated"))
                logger.info("Worker deregistered: %s", worker_id)
            return rec

    # ── Heartbeat ──

    def heartbeat(self, worker_id: str, ttl_seconds: float | None = None) -> bool:
        """Продлить lease worker'а. Возвращает True если worker зарегистрирован."""
        with self._lock:
            rec = self._workers.get(worker_id)
            if rec is None:
                return False

            ttl = ttl_seconds if ttl_seconds is not None else self._default_ttl
            now = self._clock()

            # Сбросить stale counter если worker был dead
            if rec.stale_count > 0:
                rec.health_history.append((now, "recovered"))
                rec.stale_count = 0

            rec.last_heartbeat = now
            rec.lease_expires_at = now + ttl
            rec.total_heartbeats += 1
            rec.health_history.append((now, "alive"))

            # СОС-033: продублировать lease в Valkey (best-effort)
            self._publish_lease_to_valkey(rec, ttl)
            return True

    def _publish_lease_to_valkey(self, rec: LeaseRecord, ttl: float) -> None:
        """Дублировать lease в Valkey key с TTL (опционально)."""
        try:
            from orchestrator.cosmo.control_plane.events import _get_valkey
            v = _get_valkey()
            if v is None:
                return
            key = f"cosmo:lease:{rec.worker_id}"
            payload = json.dumps({
                "worker_id": rec.worker_id,
                "busy": rec.busy,
                "current_run_id": rec.current_run_id,
                "lease_expires": rec.lease_expires_at,
                "ts": time.time(),
            }, default=str)
            v.setex(key, int(tl), payload)
        except Exception as exc:
            logger.debug("Valkey lease publish skipped: %s", exc)

    # ── Dead Worker Detection ──

    def detect_dead_workers(self) -> list[LeaseRecord]:
        """Найти worker'ов с истекшим lease."""
        with self._lock:
            dead = []
            for rec in self._workers.values():
                if rec.busy and rec.is_expired:
                    dead.append(rec)
                    rec.stale_count += 1
                    rec.health_history.append((self._clock(), "dead"))
                    logger.warning(
                        "Dead worker detected: %s (stale=%d/%d, run=%s, idle=%.1fs)",
                        rec.worker_id, rec.stale_count, self._max_stale_count,
                        rec.current_run_id, rec.seconds_since_last_heartbeat,
                    )
            return dead

    def reclaim_orphaned_runs(self) -> list[str]:
        """Найти осиротевшие run'ы у мёртвых worker'ов.

        Для каждого осиротевшего run'а:
          - освободить worker (busy=False)
          - вернуть run_id вызывающему для requeue

        Возвращает список run_id, которые нуждаются в requeue.
        """
        with self._lock:
            orphaned_runs: list[str] = []
            dead = self.detect_dead_workers()

            for rec in dead:
                orphaned_run_id = rec.current_run_id
                # Освободить worker
                rec.busy = False
                rec.current_run_id = None
                rec.lease_expires_at = None

                if orphaned_run_id is not None:
                    orphaned_runs.append(orphaned_run_id)

                # Вызвать callback если задан
                if self._on_worker_dead is not None:
                    try:
                        self._on_worker_dead(rec, orphaned_run_id)
                    except Exception:
                        pass

                # Есле worker стабильно мёртв > max_stale_count — дерегистрируем
                if rec.stale_count >= self._max_stale_count:
                    logger.error(
                        "Worker %s dead after %d stale cycles — deregistering",
                        rec.worker_id, rec.stale_count,
                    )
                    self._workers.pop(rec.worker_id, None)

            return orphaned_runs

    # ── Worker Assignment ──

    def assign_worker(self, worker_id: str, run_id: str) -> bool:
        """Назначить worker на run."""
        with self._lock:
            rec = self._workers.get(worker_id)
            if rec is None:
                return False
            rec.busy = True
            rec.current_run_id = run_id
            rec.lease_expires_at = self._clock() + self._default_ttl
            rec.last_heartbeat = self._clock()
            return True

    def release_worker(self, worker_id: str) -> Optional[str]:
        """Освободить worker от run'а. Возвращает run_id если был назначен."""
        with self._lock:
            rec = self._workers.get(worker_id)
            if rec is None:
                return None
            orphaned = rec.current_run_id
            rec.busy = False
            rec.current_run_id = None
            rec.lease_expires_at = None
            return orphaned

    # ── Чтение / диагностика ──

    def get_worker(self, worker_id: str) -> Optional[LeaseRecord]:
        with self._lock:
            return self._workers.get(worker_id)

    def is_worker_alive(self, worker_id: str) -> bool:
        with self._lock:
            rec = self._workers.get(worker_id)
            return rec is not None and rec.is_alive

    def list_workers(self) -> list[LeaseRecord]:
        with self._lock:
            return list(self._workers.values())

    def count_active(self) -> int:
        """Число занятых worker'ов."""
        with self._lock:
            return sum(1 for w in self._workers.values() if w.busy)

    def count_alive(self) -> int:
        """Число живых worker'ов."""
        with self._lock:
            return sum(1 for w in self._workers.values() if w.is_alive)

    def count_dead(self) -> int:
        """Число мёртвых worker'ов."""
        with self._lock:
            return sum(1 for w in self._workers.values() if w.is_expired and w.busy)

    def health_snapshot(self) -> dict[str, Any]:
        """Сводка состояния всех worker'ов (для /health)."""
        with self._lock:
            workers = []
            for rec in self._workers.values():
                workers.append({
                    "worker_id": rec.worker_id,
                    "capabilities": list(rec.capabilities),
                    "busy": rec.busy,
                    "current_run_id": rec.current_run_id,
                    "alive": rec.is_alive,
                    "stale_count": rec.stale_count,
                    "total_heartbeats": rec.total_heartbeats,
                    "last_heartbeat_ago_s": rec.seconds_since_last_heartbeat,
                    "registered_at": rec.registered_at,
                })

            return {
                "total": len(workers),
                "alive": sum(1 for w in self._workers.values() if w.is_alive),
                "busy": sum(1 for w in self._workers.values() if w.busy),
                "dead": sum(1 for w in self._workers.values() if w.is_expired and w.busy),
                "workers": workers,
            }

    # ── Recovery ──

    def recover_from_valkey(self) -> int:
        """Восстановить состояние lease'ов из Valkey после сбоя.
        
        Читает все ключи cosmo:lease:* и восстанавливает LeaseRecord.
        Возвращает число восстановленных worker'ов.
        """
        try:
            from orchestrator.cosmo.control_plane.events import _get_valkey
            v = _get_valkey()
            if v is None:
                return 0

            count = 0
            for key in v.scan_iter("cosmo:lease:*"):
                data = v.get(key)
                if data is None:
                    continue
                try:
                    payload = json.loads(data)
                except json.JSONDecodeError:
                    continue

                worker_id = payload.get("worker_id")
                if not worker_id:
                    continue

                with self._lock:
                    existing = self._workers.get(worker_id)
                    if existing is not None:
                        continue  # уже есть in-memory

                    rec = LeaseRecord(
                        worker_id=worker_id,
                        busy=payload.get("busy", False),
                        current_run_id=payload.get("current_run_id"),
                        lease_expires_at=payload.get("lease_expires"),
                        last_heartbeat=payload.get("ts", self._clock()),
                        registered_at=self._clock(),
                    )
                    self._workers[worker_id] = rec
                    count += 1

            logger.info("LeaseTracker recovered %d workers from Valkey", count)
            return count
        except Exception as exc:
            logger.warning("LeaseTracker recover from Valkey failed: %s", exc)
            return 0

    def recover_from_pg(self, db_session_factory) -> int:
        """Восстановить состояние lease'ов из PostgreSQL.
        
        Загружает всех worker'ов, у которых есть активные run'ы (status=running).
        Возвращает число восстановленных worker'ов.
        """
        if db_session_factory is None:
            return 0

        try:
            from orchestrator.cosmo.db.models import Run as RunORM

            s = db_session_factory()
            active_runs = []
            try:
                active_runs = s.query(RunORM).filter(RunORM.status == "running").all()
            finally:
                s.close()

            count = 0
            with self._lock:
                for orm in active_runs:
                    worker_id = f"recovered-{orm.id}"
                    if worker_id in self._workers:
                        continue

                    rec = LeaseRecord(
                        worker_id=worker_id,
                        busy=True,
                        current_run_id=orm.id,
                        lease_expires_at=self._clock() + self._default_ttl,
                        last_heartbeat=self._clock(),
                        registered_at=self._clock(),
                    )
                    rec.health_history.append((self._clock(), "recovered_from_pg"))
                    self._workers[worker_id] = rec
                    count += 1

            logger.info("LeaseTracker recovered %d workers from PG", count)
            return count
        except Exception as exc:
            logger.warning("LeaseTracker recover from PG failed: %s", exc)
            return 0

    # ── Reset ──

    def reset(self) -> None:
        """Тестовый helper: сбросить все состояние."""
        with self._lock:
            self._workers.clear()