# -*- coding: utf-8 -*-
"""COS-003: RunControlPlane — Cosmo-native state machine (PostgreSQL-backed).

Портированный RunControlPlane из prettyk-dev с расширением под Cosmo:
  - Состояния: draft → pending → queued → running → succeeded/failed/blocked/cancelled
  - PostgreSQL — SoT (Run.status в БД), Valkey — только транспорт
  - Атомарные переходы + immutable history
  - FIFO-очередь + worker dispatch по capabilities
  - Leasing / heartbeat / stale detection с автоматическим requeue
  - Классификация отказов (infra → retry, validation/target → мгновенный fail)
  - Recovery: после сброса Valkey — восстановление состояния из PostgreSQL

Спецификация: COS-003 § RunControlPlane State Machine.
"""
from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Optional

logger = logging.getLogger("cosmoport.control_plane")


# ── Состояния жизненного цикла ──

class RunState(str, Enum):
    DRAFT = "draft"           # только создан, не готов к запуску
    PENDING = "pending"       # готов, ждёт свободного worker'а
    QUEUED = "queued"         # в FIFO-очереди
    RUNNING = "running"       # исполняется на worker'е
    SUCCEEDED = "succeeded"   # успешно завершён
    FAILED = "failed"         # завершён с ошибкой
    BLOCKED = "blocked"       # заблокирован (gate failure / manual hold)
    CANCELLED = "cancelled"   # отменён оператором


# Атомарные переходы
_VALID_TRANSITIONS: dict[RunState, frozenset[RunState]] = {
    RunState.DRAFT:    frozenset({RunState.PENDING, RunState.CANCELLED}),
    RunState.PENDING:  frozenset({RunState.QUEUED, RunState.CANCELLED}),
    RunState.QUEUED:   frozenset({RunState.RUNNING, RunState.CANCELLED}),
    RunState.RUNNING:  frozenset({RunState.SUCCEEDED, RunState.FAILED, RunState.BLOCKED, RunState.CANCELLED, RunState.QUEUED}),
    RunState.SUCCEEDED: frozenset(),
    RunState.FAILED:   frozenset(),
    RunState.BLOCKED:  frozenset({RunState.QUEUED, RunState.CANCELLED}),
    RunState.CANCELLED: frozenset(),
}

_TERMINAL = frozenset({RunState.SUCCEEDED, RunState.FAILED, RunState.CANCELLED})
_ACTIVE = frozenset({RunState.DRAFT, RunState.PENDING, RunState.QUEUED, RunState.RUNNING, RunState.BLOCKED})


# ── Классификация отказов ──

class FailureClass(str, Enum):
    INFRA = "infra"           # сеть/worker/таймаут → автоматический retry
    VALIDATION = "validation" # ошибка валидации плана → мгновенный fail
    TARGET = "target"         # target недоступен → мгновенный fail
    GATE = "gate"             # gate не пройден → blocked


# ── In-memory record (runtime representation over PG Run) ──

@dataclass
class RunRecord:
    """Runtime-представление запуска (обёртка над PG Run)."""
    id: str
    plan_id: str
    domain_id: str
    trigger: str = "manual"
    state: RunState = RunState.DRAFT
    initiator_user_id: str = "system"
    initiator_role: str = "system"
    batch_id: Optional[str] = None
    capabilities: frozenset[str] = frozenset()
    worker_id: Optional[str] = None
    attempt: int = 1
    failure_class: Optional[FailureClass] = None
    error: Optional[str] = None
    dedup_key: str = ""
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    history: list[tuple[str, float, str]] = field(default_factory=list)

    @property
    def is_terminal(self) -> bool:
        return self.state in _TERMINAL

    @property
    def is_active(self) -> bool:
        return self.state in _ACTIVE


@dataclass
class Worker:
    id: str
    capabilities: frozenset[str] = frozenset()
    busy: bool = False
    current_run_id: Optional[str] = None
    lease_expires_at: Optional[float] = None
    last_heartbeat: float = field(default_factory=time.time)


# ── Run Control Plane ──

class RunControlPlane:
    """Cosmo Run Control Plane — PostgreSQL + Valkey-backed state machine.

    PG = Source of Truth (Run.status).
    Valkey = transport (lease/heartbeat/queue notifications) — опционально.

    Recovery: при старте → load_active_runs_from_pg() восстанавливает
    in-memory состояние из БД, перестраивает очередь.
    """

    def __init__(
        self,
        max_concurrent: int = 3,
        lease_timeout_sec: float = 60.0,
        max_retries: int = 3,
        clock: Callable[[], float] = time.time,
        db_session_factory: Optional[Callable[[], Any]] = None,
    ) -> None:
        self._max_concurrent = max_concurrent
        self._lease_timeout_sec = lease_timeout_sec
        self._max_retries = max_retries
        self._clock = clock
        self._db_session_factory = db_session_factory

        # COS-034: делегировать lease-tracking в LeaseTracker
        from orchestrator.cosmo.control_plane.lease import LeaseTracker
        self._lease_tracker = LeaseTracker(
            default_ttl_seconds=lease_timeout_sec,
            clock=clock,
            on_worker_dead=self._on_worker_dead_callback,
        )

        # COS-046: batch execution engine (lazy-set через set_executor)
        self._executor: Optional[Any] = None
        # COS-055: gate policy engine (lazy-set через set_gate_engine)
        self._gate_engine: Optional[Any] = None
        self._findings_provider: Optional[Callable[[str], list[dict[str, Any]]]] = None
        # COS-092: distributed concurrency guard
        self._concurrency_guard: Optional[Any] = None

        self._lock = threading.RLock()
        self._runs: dict[str, RunRecord] = {}
        self._workers: dict[str, Worker] = {}  # legacy — остаётся для тестов
        self._queue: list[str] = []
        # COS-061: per-domain queues for multi-tenancy isolation
        self._queue_by_domain: dict[str, list[str]] = {}
        self._active_runs_by_domain: dict[str, int] = {}

    # ── RUN-CTL-1: жизненный цикл + атомарные переходы ──

    def _transition(self, run: RunRecord, target: RunState) -> None:
        allowed = _VALID_TRANSITIONS[run.state]
        if target not in allowed:
            raise ValueError(
                f"Invalid transition: {run.state.value} → {target.value} (run {run.id})"
            )
        previous = run.state.value
        run.history.append((previous, self._clock(), target.value))
        run.state = target
        self._persist_state(run)
        # COS-033: Valkey PubSub — best-effort, не блокирует стейт-машину
        self._publish_transition(run, previous, target.value)

    def register_worker(self, worker_id: str, capabilities: frozenset[str] | None = None) -> Worker:
        with self._lock:
            w = Worker(id=worker_id, capabilities=capabilities or frozenset())
            self._workers[worker_id] = w
            # COS-034: mirrored в LeaseTracker
            self._lease_tracker.register_worker(worker_id, capabilities or frozenset())
            return w

    # ── COS-046: Batch Execution Engine integration ──

    def set_executor(self, executor: Any) -> None:
        """Подключить BatchExecutor для Woodpecker CI-интеграции.

        executor: BatchExecutor | None — None отключает.
        """
        self._executor = executor
        if executor is not None:
            executor._on_all_terminal = self._on_batches_terminal
            if self._db_session_factory is not None and executor._db_session_factory is None:
                executor._db_session_factory = self._db_session_factory

    # ── COS-055: Gate Policy Engine integration ──

    def set_gate_engine(self, engine: Any) -> None:
        """Подключить GatePolicyEngine для оценки security gates.

        engine: GatePolicyEngine | None — None отключает.
        """
        self._gate_engine = engine
        if engine is not None and engine._db_session_factory is None:
            engine._db_session_factory = self._db_session_factory

    def set_findings_provider(
        self, provider: Callable[[str], list[dict[str, Any]]] | None
    ) -> None:
        """Установить провайдер findings для gate evaluation.

        provider: функция run_id → list[dict] (finding dicts с полем severity).
        """
        self._findings_provider = provider

    # ── COS-092: Distributed Lock & Concurrency Guard ──

    def set_concurrency_guard(self, guard: Any) -> None:
        """Подключить ConcurrencyGuard для distributed lock перед _assign."""
        self._concurrency_guard = guard

    def _on_batches_terminal(self, run_id: str, all_passed: bool) -> None:
        """Callback: все batch'и run'а достигли terminal state.

        Вызывается из BatchExecutor.poll().
        all_passed=True  → gate evaluation → SUCCEEDED / BLOCKED
        all_passed=False → BLOCKED (batch failure = gate failure)

        COS-055: если подключён GatePolicyEngine, при all_passed=True
        оцениваем plan gates против findings. Gate может заблокировать даже
        успешный прогон (напр. Critial finding).
        """
        with self._lock:
            run = self._runs.get(run_id)
            if run is None or run.is_terminal or run.state != RunState.RUNNING:
                return

            if not all_passed:
                # COS-097: честный degraded — sustained unknown статусы
                # Woodpecker (не выдуманный PASS, не молчаливый hang).
                # failed + FailureClass.INFRA с сохранённой причиной;
                # обычный batch failure остаётся BLOCKED (parity COS-046).
                degraded_reason = None
                if self._executor is not None:
                    pop_degraded = getattr(self._executor, "pop_degraded_reason", None)
                    if callable(pop_degraded):
                        degraded_reason = pop_degraded(run_id)

                self._release_worker_by_run_id(run_id)
                if degraded_reason:
                    run.failure_class = FailureClass.INFRA
                    run.error = degraded_reason
                    run.finished_at = self._clock()
                    self._transition(run, RunState.FAILED)
                else:
                    run.failure_class = FailureClass.GATE
                    run.error = "batch execution failed"
                    run.finished_at = self._clock()
                    self._transition(run, RunState.BLOCKED)
                self._dispatch()
                return

            # COS-055: gate evaluation before final success
            # Release worker first (batches done, worker free)
            self._release_worker_by_run_id(run_id)

            gate_blocked = False
            if self._gate_engine is not None and self._findings_provider is not None:
                try:
                    findings = self._findings_provider(run_id)
                    plan_id = getattr(run, "plan_id", "")
                    decisions = self._gate_engine.evaluate_plan_gates(
                        plan_id, findings, run_id=run_id,
                    )
                    gate_blocked = any(d == "block" for d in decisions.values())
                except Exception as exc:
                    logger.warning("Gate evaluation failed for %s: %s", run_id, exc)
                    # Ошибка gate engine — не блокируем run (fail-open)
                    gate_blocked = False

            if gate_blocked:
                run.failure_class = FailureClass.GATE
                run.error = "gate blocked by policy"
                run.finished_at = self._clock()
                self._transition(run, RunState.BLOCKED)
            else:
                run.finished_at = self._clock()
                self._transition(run, RunState.SUCCEEDED)
            self._dispatch()

    def poll_batches(self) -> list[Any]:
        """Poll статусы batch-пайплайнов (делегирование в BatchExecutor).

        Returns: list[BatchPollResult] — результаты poll-цикла.
        """
        if self._executor is None:
            return []
        return self._executor.poll()

    def unregister_worker(self, worker_id: str) -> None:
        with self._lock:
            w = self._workers.pop(worker_id, None)
            if w and w.current_run_id:
                self._release_worker_by_run_id(w.current_run_id)
            # COS-034: mirrored в LeaseTracker
            self._lease_tracker.deregister_worker(worker_id)

    # ── RUN-CTL-2: защита от дублирования ──

    @staticmethod
    def _dedup_key(params: dict[str, Any]) -> str:
        canonical = json_dumps_sorted(params)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:32]

    def create_run(
        self,
        params: dict[str, Any],
        capabilities: frozenset[str] | None = None,
        *,
        initiator: str = "system",
    ) -> tuple[RunRecord, bool]:
        """Идемпотентно создать запуск. Возвращает (run, is_new)."""
        key = self._dedup_key(params)
        with self._lock:
            for existing in self._runs.values():
                if existing.dedup_key == key and not existing.is_terminal:
                    return existing, False

            run = RunRecord(
                id=f"run-{uuid.uuid4().hex[:12]}",
                plan_id=params.get("plan_id", ""),
                domain_id=params.get("domain_id", ""),
                trigger=params.get("trigger", "manual"),
                dedup_key=key,
                capabilities=capabilities or frozenset(),
                initiator_user_id=initiator,
                initiator_role=params.get("initiator_role", "system"),
                batch_id=params.get("batch_id"),
                state=RunState.DRAFT,
            )
            run.history.append(("__init__", self._clock(), RunState.DRAFT.value))
            self._runs[run.id] = run
            self._persist_create(run)
            return run, True

    def submit_run(self, run_id: str) -> None:
        """DRAFT → PENDING: заявка готова к планированию."""
        with self._lock:
            run = self._runs.get(run_id)
            if run is None or run.state != RunState.DRAFT:
                return
            self._transition(run, RunState.PENDING)

    def enqueue_run(self, run_id: str) -> None:
        """PENDING → QUEUED: поместить в очередь."""
        with self._lock:
            run = self._runs.get(run_id)
            if run is None or run.state != RunState.PENDING:
                return
            self._transition(run, RunState.QUEUED)
            self._queue.append(run.id)
            # COS-061: per-domain queue isolation
            domain_id = getattr(run, "domain_id", "default")
            self._queue_by_domain.setdefault(domain_id, []).append(run.id)
            self._dispatch()

    def queue_length_for_domain(self, domain_id: str) -> int:
        """COS-061: длина очереди для конкретного домена."""
        with self._lock:
            return len(self._queue_by_domain.get(domain_id, []))

    # ── RUN-CTL-3: FIFO-очередь ──

    def queue_position(self, run_id: str) -> int | None:
        with self._lock:
            if run_id not in self._queue:
                return None
            return self._queue.index(run_id)

    def queue_length(self) -> int:
        with self._lock:
            return len(self._queue)

    # ── RUN-CTL-4: worker dispatch ──

    def _worker_fits(self, worker: Worker, caps: frozenset[str]) -> bool:
        if not caps:
            return True
        return caps.issubset(worker.capabilities)

    def _find_free_worker(self, caps: frozenset[str]) -> Worker | None:
        for w in self._workers.values():
            if not w.busy and self._worker_fits(w, caps):
                return w
        return None

    def _active_workers_count(self) -> int:
        return sum(1 for w in self._workers.values() if w.busy)

    def _dispatch(self) -> None:
        while self._queue and self._active_workers_count() < self._max_concurrent:
            run_id = self._queue[0]
            run = self._runs.get(run_id)
            if run is None:
                self._queue.pop(0)
                continue
            worker = self._find_free_worker(run.capabilities)
            if worker is None:
                return
            self._queue.pop(0)
            self._assign(run, worker)

    def _assign(self, run: RunRecord, worker: Worker) -> None:
        # COS-092: try-acquire distributed lock before transition
        if self._concurrency_guard is not None:
            if not self._concurrency_guard.try_acquire_run(run.id, ttl_seconds=60):
                return  # другой worker уже захватил лок — skip dispatch
        try:
            self._transition(run, RunState.RUNNING)
            run.worker_id = worker.id
            run.started_at = self._clock()
            run.attempt = getattr(run, 'attempt', 1)
            worker.busy = True
            worker.current_run_id = run.id
            worker.last_heartbeat = self._clock()
            worker.lease_expires_at = self._clock() + self._lease_timeout_sec
            # COS-034: mirrored в LeaseTracker
            self._lease_tracker.assign_worker(worker.id, run.id)
            # COS-046: fire-and-forget submit batches to Woodpecker
            if self._executor is not None:
                self._executor.submit_batches_async(run)
        except Exception:
            # Release lock on failure
            if self._concurrency_guard is not None:
                self._concurrency_guard.release_run_lock(run.id)
            raise

    # ── RUN-CTL-5: lease + heartbeat + stale detection ──

    def heartbeat(self, worker_id: str) -> None:
        """Продлить lease worker'а (делегировано в LeaseTracker)."""
        self._lease_tracker.heartbeat(worker_id)
        # Sync legacy worker record
        with self._lock:
            w = self._workers.get(worker_id)
            if w is not None:
                w.last_heartbeat = self._clock()
                w.lease_expires_at = self._clock() + self._lease_timeout_sec

    def detect_stale(self) -> list[str]:
        """Найти мёртвых worker'ов и вернуть id осиротевших run'ов."""
        # Синхронизировать legacy state → LeaseTracker (для тестов)
        now = self._clock()
        with self._lock:
            for w in self._workers.values():
                if w.busy and w.lease_expires_at is not None and now >= w.lease_expires_at:
                    lt_rec = self._lease_tracker.get_worker(w.id)
                    if lt_rec is not None:
                        lt_rec.lease_expires_at = w.lease_expires_at

        orphaned = self._lease_tracker.reclaim_orphaned_runs()
        # Синхронизировать legacy state
        with self._lock:
            for run_id in orphaned:
                run = self._runs.get(run_id)
                if run is not None:
                    self._release_stale_run(run)
        return orphaned

    def _on_worker_dead_callback(self, lease_rec, orphaned_run_id):
        """Callback из LeaseTracker при обнаружении мёртвого worker'а."""
        with self._lock:
            w = self._workers.get(lease_rec.worker_id)
            if w is not None:
                w.busy = False
                w.current_run_id = None
                w.lease_expires_at = None

    def _release_stale_run(self, run: RunRecord) -> None:
        run.worker_id = None
        run.started_at = None
        if run.attempt < self._max_retries:
            run.attempt += 1
            self._transition(run, RunState.QUEUED)
            self._queue.append(run.id)
        else:
            run.failure_class = FailureClass.INFRA
            run.error = "worker stale (lease expired)"
            run.finished_at = self._clock()
            self._transition(run, RunState.FAILED)

    # ── RUN-CTL-6: retry с классификацией ──

    def fail_run(self, run_id: str, failure_class: FailureClass, error: str = "") -> None:
        with self._lock:
            run = self._runs.get(run_id)
            if run is None or run.is_terminal:
                return
            run.failure_class = failure_class
            run.error = error
            self._release_worker_by_run_id(run_id)

            if failure_class == FailureClass.INFRA and run.attempt < self._max_retries:
                run.attempt += 1
                run.started_at = None
                self._transition(run, RunState.QUEUED)
                self._queue.append(run.id)
            elif failure_class == FailureClass.GATE:
                run.finished_at = self._clock()
                self._transition(run, RunState.BLOCKED)
            else:
                run.finished_at = self._clock()
                self._transition(run, RunState.FAILED)
            self._dispatch()

    def succeed_run(self, run_id: str) -> None:
        with self._lock:
            run = self._runs.get(run_id)
            if run is None or run.is_terminal:
                return
            self._release_worker_by_run_id(run_id)
            run.finished_at = self._clock()
            self._transition(run, RunState.SUCCEEDED)
            self._dispatch()

    def cancel_run(self, run_id: str) -> None:
        with self._lock:
            run = self._runs.get(run_id)
            if run is None or run.is_terminal:
                return
            if run.state in (RunState.QUEUED, RunState.PENDING):
                try:
                    self._queue.remove(run_id)
                except ValueError:
                    pass
                self._transition(run, RunState.CANCELLED)
            elif run.state in (RunState.RUNNING, RunState.BLOCKED):
                self._release_worker_by_run_id(run_id)
                run.finished_at = self._clock()
                self._transition(run, RunState.CANCELLED)
            elif run.state == RunState.DRAFT:
                self._transition(run, RunState.CANCELLED)
            self._dispatch()

    def _release_worker_by_run_id(self, run_id: str) -> None:
        run = self._runs.get(run_id)
        if run is None:
            return
        worker_id = run.worker_id
        run.worker_id = None
        if worker_id:
            w = self._workers.get(worker_id)
            if w is not None:
                w.busy = False
                w.current_run_id = None
                w.lease_expires_at = None
            # COS-034: mirrored в LeaseTracker
            self._lease_tracker.release_worker(worker_id)

    # ── Чтение ──

    def get_run(self, run_id: str) -> RunRecord | None:
        with self._lock:
            return self._runs.get(run_id)

    def list_runs(self, *, active_only: bool = False) -> list[RunRecord]:
        with self._lock:
            runs = list(self._runs.values())
        if active_only:
            return [r for r in runs if r.is_active]
        return runs

    def find_by_dedup_key(self, params: dict[str, Any]) -> RunRecord | None:
        key = self._dedup_key(params)
        with self._lock:
            for r in self._runs.values():
                if r.dedup_key == key and not r.is_terminal:
                    return r
        return None

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            by_state: dict[str, int] = {}
            for r in self._runs.values():
                by_state[r.state.value] = by_state.get(r.state.value, 0) + 1
            result = {
                "total": len(self._runs),
                "active": sum(1 for r in self._runs.values() if r.is_active),
                "terminal": sum(1 for r in self._runs.values() if r.is_terminal),
                "queue_depth": len(self._queue),
                "workers": sum(1 for w in self._workers.values() if w.busy),
                "by_state": by_state,
            }
        # COS-034: добавить lease health (вне лока чтобы не дедлокиться)
        result["lease"] = self._lease_tracker.health_snapshot()
        return result

    # ── PostgeSQL persistence ──

    def _persist_create(self, run: RunRecord) -> None:
        try:
            self._sync_to_pg(run, is_new=True)
        except Exception as exc:
            logger.warning("PG persist_create failed for %s: %s", run.id, exc)

    def _persist_state(self, run: RunRecord) -> None:
        try:
            self._sync_to_pg(run, is_new=False)
        except Exception as exc:
            logger.warning("PG persist_state failed for %s: %s", run.id, exc)

    def _sync_to_pg(self, run: RunRecord, *, is_new: bool) -> None:
        if self._db_session_factory is None:
            return
        from orchestrator.cosmo.db.models import Run as RunORM
        from datetime import datetime as dt

        s = self._db_session_factory()
        try:
            orm = s.query(RunORM).filter(RunORM.id == run.id).first()
            if orm is None:
                if not is_new:
                    return  # run not in DB yet, cannot update
                orm = RunORM(
                    id=run.id,
                    plan_id=run.plan_id,
                    domain_id=run.domain_id,
                    trigger=run.trigger,
                    status=run.state.value,
                    initiator_user_id=run.initiator_user_id,
                    initiator_role=run.initiator_role,
                    batch_id=run.batch_id,
                )
                s.add(orm)
            else:
                orm.status = run.state.value
            if run.started_at:
                orm.started_at = dt.fromtimestamp(run.started_at, tz=timezone.utc)
            if run.finished_at:
                orm.finished_at = dt.fromtimestamp(run.finished_at, tz=timezone.utc)
            s.commit()
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    # ── PostgreSQL → in-memory recovery ──

    def recover_from_pg(self) -> int:
        """Восстановить состояние из PG после сброса Valkey. Возвращает число загруженных."""
        if self._db_session_factory is None:
            return 0
        from orchestrator.cosmo.db.models import Run as RunORM

        s = self._db_session_factory()
        try:
            active_orms = s.query(RunORM).filter(
                RunORM.status.in_([s.value for s in _ACTIVE])
            ).all()
        finally:
            s.close()

        count = 0
        with self._lock:
            for orm in active_orms:
                if orm.id in self._runs:
                    continue
                rec = RunRecord(
                    id=orm.id,
                    plan_id=orm.plan_id,
                    domain_id=orm.domain_id,
                    trigger=orm.trigger,
                    state=RunState(orm.status),
                    initiator_user_id=orm.initiator_user_id,
                    initiator_role=orm.initiator_role,
                    batch_id=orm.batch_id,
                )
                if orm.started_at:
                    rec.started_at = orm.started_at.timestamp()
                self._runs[orm.id] = rec
                if rec.state == RunState.QUEUED and orm.id not in self._queue:
                    self._queue.append(orm.id)
                if rec.state == RunState.RUNNING:
                    self._queue.insert(0, orm.id)  # приоритет — доиграть running
                count += 1
        # Передиспатчить очередь
        self._dispatch()
        return count

    def reset(self) -> None:
        """Test helper: сбросить всё in-memory состояние."""
        with self._lock:
            self._runs.clear()
            self._workers.clear()
            self._queue.clear()
            # COS-061: reset per-domain state
            self._queue_by_domain.clear()
            self._active_runs_by_domain.clear()
        # COS-034: reset lease tracker too
        self._lease_tracker.reset()
        # COS-046: reset executor
        if self._executor is not None:
            self._executor.reset()
        # COS-055: reset gate engine
        if self._gate_engine is not None:
            self._gate_engine.reset()
        self._findings_provider = None

    # ── COS-033: Valkey PubSub — best-effort, не блокирует стейт-машину ──

    @staticmethod
    def _publish_transition(run: RunRecord, previous: str, current: str) -> None:
        """Опубликовать переход статуса в Valkey (best-effort, no-op если недоступен)."""
        try:
            from orchestrator.cosmo.control_plane.events import publish_status_change
            publish_status_change(run.id, previous, current)
        except Exception:
            pass  # Valkey — транспорт, не SoT


# ── Стабильная канонизация параметров ──

def json_dumps_sorted(obj: Any) -> str:
    def canonical(value: Any) -> Any:
        if isinstance(value, dict):
            return {k: canonical(v) for k, v in sorted(value.items())}
        if isinstance(value, (list, tuple)):
            return [canonical(v) for v in value]
        if isinstance(value, set):
            return sorted(canonical(v) for v in value)
        return value

    return json.dumps(canonical(obj), ensure_ascii=False, sort_keys=True, default=str)