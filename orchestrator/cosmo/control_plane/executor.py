# -*- coding: utf-8 -*-
"""COS-046/COS-097: Batch Execution Engine — Woodpecker CI integration.

Связывает RunControlPlane с Woodpecker:
  1. Когда run входит в RUNNING → submit каждого batch как pipeline
  2. Отслеживание завершения через polling
  3. Обновление batch.status в PostgreSQL
  4. Gate evaluation trigger когда все batch'и terminal

COS-097 (live cycle, demo without fakes):
  - Durable handles: submit/poll пишет ручки в cosmo_execution_handles
    (handle_store), recover() восстанавливает poll после рестарта API —
    факт прогона не теряется.
  - Honest unknown/degraded: ошибка опроса или неизвестный RAW-статус НЕ
    считается ни pending-навсегда, ни PASS. Подряд unknown_count ≥
    degraded_threshold → честный terminal: batch failed, degraded-причина
    сохранена (pop_degraded_reason для run-уровня), прогон помечен
    degraded в durable-следе.
  - Evidence из реального прогона: batch terminal success → collect логов
    через адаптер → evidence_sink (SHA-256 digest считается на async
    стороне сервиса).
  - Repo resolution per-run: resolve_repo callback (binding приложения,
    COS-096) с fallback на конструкторные repo_owner/repo_name.

Архитектура:
  - BatchExecutor: управление жизненным циклом batch-пайплайнов
  - PipelineHandle: handle на Woodpecker pipeline (batch → job mapping)
  - BatchPollResult: результат одного poll-цикла
  - _STATUS_MAP: Woodpecker status → Batch status
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Optional

from orchestrator.cosmo.adapters.execution_woodpecker import ExecutionAdapter

logger = logging.getLogger("cosmoport.executor")

# ── Woodpecker → Batch status mapping ──

_STATUS_MAP: dict[str, str] = {
    "pending": "pending",
    "running": "running",
    "success": "passed",
    "failure": "failed",
    "killed":   "failed",
    "error":    "failed",
}

# COS-097: расширенные честные маппинги v3.5-статусов вне замороженный
# batch_status_enum {pending, running, passed, failed, blocked}:
#   declined  → blocked  (пайплайн отклонён/ждёт approval — не провал кода)
#   blocked   → blocked  (waiting for approval)
#   skipped   → failed   (прогон не выполнен — PASS'ом выдумывать нельзя)
_EXTENDED_STATUS_MAP: dict[str, str] = {
    "declined": "blocked",
    "blocked":  "blocked",
    "skipped":  "failed",
}

_TERMINAL_WP = frozenset({"success", "failure", "killed", "error", "declined", "skipped"})
_TERMINAL_BATCH = frozenset({"passed", "failed", "blocked"})

DEFAULT_DEGRADED_THRESHOLD = 5


# ── Dataclasses ──

@dataclass
class PipelineHandle:
    """Handle на запущенный Woodpecker pipeline (batch → job mapping)."""
    batch_id: str
    run_id: str
    plan_id: str
    handle: dict[str, Any]  # {job_id, number, repo_id, repo_owner, repo_name, branch}


@dataclass
class BatchPollResult:
    """Результат одного poll-цикла для batch'а."""
    batch_id: str
    run_id: str
    old_status: str
    new_status: str
    terminal: bool
    degraded: bool = False
    raw_status: Optional[str] = None


# ── Handle store protocol (sync; реализация — ExecutionService bridge) ──
#
#   upsert(batch_id, run_id, plan_id, handle) -> None
#   mark_terminal(batch_id, status, *, reason=None, degraded=False) -> None
#   record_unknown(batch_id, raw_status) -> int   # новый unknown_count
#   record_evidence_error(batch_id, error) -> None
#   load_active() -> list[dict]                   # строки с handle_dict+status

HandleStore = Any  # структурная типизация, без жёсткого импорта
RepoResolver = Callable[[str, str, str], Optional[tuple[str, str, str]]]
EvidenceSink = Callable[[str, str, dict[str, list[str]], dict], None]


# ── Batch Executor ──

class BatchExecutor:
    """COS-046: Submit batches as Woodpecker CI pipelines.

    Жизненный цикл:
      1. submit_batches(run)             → submit каждого batch как pipeline
      2. poll()                          → проверить статусы, обновить PG
      3. _check_run_terminal(run_id)     → когда все terminal → callback
      4. cancel_batches(run)             → остановить активные pipeline'ы
      5. recover()                       → восстановить активные из store

    Dry-run mode: без реального Woodpecker (для тестов).
    _status_override: для инъекции статусов в тестах.
    """

    def __init__(
        self,
        adapter: ExecutionAdapter,
        db_session_factory: Callable[[], Any] | None = None,
        repo_owner: str = "cosmo",
        repo_name: str = "default",
        dry_run: bool = False,
        on_all_terminal: Callable[[str, bool], None] | None = None,
        *,
        handle_store: HandleStore | None = None,
        resolve_repo: RepoResolver | None = None,
        evidence_sink: EvidenceSink | None = None,
        degraded_threshold: int = DEFAULT_DEGRADED_THRESHOLD,
    ) -> None:
        self._adapter = adapter
        self._db_session_factory = db_session_factory
        self._repo_owner = repo_owner
        self._repo_name = repo_name
        self._dry_run = dry_run
        self._on_all_terminal = on_all_terminal

        # COS-097: durable handles / repo binding / evidence / honesty.
        self._store = handle_store
        self._resolve_repo = resolve_repo
        self._evidence_sink = evidence_sink
        self._degraded_threshold = max(1, int(degraded_threshold))
        self._degraded_reasons: dict[str, str] = {}   # run_id → reason

        self._lock = threading.RLock()
        self._active: dict[str, PipelineHandle] = {}   # batch_id → handle
        self._run_batches: dict[str, set[str]] = {}    # run_id → {batch_ids}
        self._run_plans: dict[str, str] = {}           # run_id → plan_id (для _check_run_terminal без PG)
        self._mem_unknown: dict[str, int] = {}         # unknown-счётчик при store=None (unit-режим)

        # Test helpers
        self._status_override: dict[str, str] = {}     # batch_id → JobStatus
        self._submit_fail_batch_ids: set[str] = set()  # batch_id'ы которые «не засабмитились»

    # ── Public API ──

    def submit_batches(self, run: Any) -> list[str]:
        """Submit все batch'и для plan'а запуска как Woodpecker pipeline'ы.

        Вызывается после перехода run → RUNNING.
        Не блокирует стейт-машину (fire-and-forget через daemon thread).

        Returns: список batch_id, которые были засабмичены.
        """
        plan_id = getattr(run, "plan_id", "")
        run_id = getattr(run, "id", "")
        batch_orms = self._query_batches(plan_id)

        submitted: list[str] = []
        for orm in batch_orms:
            batch_id = orm["id"]
            batch_type = orm.get("type", "build")

            # Test: симулировать ошибку submit
            if batch_id in self._submit_fail_batch_ids:
                logger.warning("Batch %s submit simulated failure (test)", batch_id)
                continue

            # COS-097: resubmit-guard — повторный PATCH running / рестарт с
            # recover() не должен плодить дубли pipeline'ов в Woodpecker.
            if self._already_in_flight(batch_id):
                logger.info("Batch %s already in-flight — resubmit skipped", batch_id)
                continue

            # Сгенерировать YAML (для аудита)
            try:
                yaml_config = self._adapter.generate_pipeline_yaml(orm)
                logger.debug("Pipeline YAML for batch %s (%s): %d chars",
                            batch_id, batch_type, len(yaml_config))
            except Exception as exc:
                logger.warning("YAML generation failed for batch %s: %s", batch_id, exc)

            # COS-097: repo per-run (binding приложения) с fallback ctor.
            owner, name, branch = self._repo_for_run(run_id, plan_id, batch_id)

            # Submit pipeline
            if self._dry_run:
                handle = {
                    "job_id": f"dry-{batch_id}",
                    "number": 1,
                    "repo_id": None,
                    "repo_owner": owner,
                    "repo_name": name,
                    "branch": branch,
                }
            else:
                try:
                    handle = self._adapter.submit_run(owner, name, branch)
                except Exception as exc:
                    logger.error("Submit failed for batch %s: %s", batch_id, exc)
                    # COS-097: честный durable-след — пайплайн НЕ запущен.
                    if self._store is not None:
                        try:
                            self._store.mark_terminal(
                                batch_id, "submit_failed",
                                reason=f"submit failed: {exc}")
                        except Exception as store_exc:
                            logger.error("Store mark_terminal failed for %s: %s",
                                         batch_id, store_exc)
                    continue

            ph = PipelineHandle(
                batch_id=batch_id,
                run_id=run_id,
                plan_id=plan_id,
                handle=handle,
            )

            with self._lock:
                self._active[batch_id] = ph
                self._run_batches.setdefault(run_id, set()).add(batch_id)
                self._run_plans[run_id] = plan_id

            if self._store is not None:
                try:
                    self._store.upsert(batch_id, run_id, plan_id, handle)
                except Exception as store_exc:
                    # Ручка не пережила бы рестарт — это WARN, не сбой прогона.
                    logger.error("Store upsert failed for batch %s: %s",
                                 batch_id, store_exc)

            self._update_batch_pg(batch_id, "running")
            submitted.append(batch_id)
            logger.info("Batch %s (%s) submitted as pipeline #%s (repo %s/%s)",
                        batch_id, batch_type, handle.get("number"), owner, name)

        return submitted

    def _already_in_flight(self, batch_id: str) -> bool:
        """COS-097: batch уже выполняется (не нужно повторять submit)?

        Порядок: in-memory _active → durable store (не-terminal строка) →
        PG SoT batch.status (не pending = уже стартовал/terminal).
        """
        with self._lock:
            if batch_id in self._active:
                return True
        if self._store is not None:
            try:
                if self._store.get_active(batch_id) is not None:
                    return True
            except Exception as exc:
                logger.warning("Store get_active failed for %s: %s",
                               batch_id, exc)
        pg_status = self._get_batch_pg_status(batch_id)
        return pg_status is not None and pg_status != "pending"

    def submit_batches_async(self, run: Any) -> None:
        """Submit batch'и в фоновом daemon-потоке (не блокирует вызывающего)."""
        t = threading.Thread(
            target=self.submit_batches,
            args=(run,),
            daemon=True,
            name=f"batch-submit-{getattr(run, 'id', '?')}",
        )
        t.start()

    def poll(self) -> list[BatchPollResult]:
        """Poll статусы всех активных pipeline'ов. Обновляет batch.status в PG.

        COS-097 honesty:
          - ошибка опроса / неизвестный RAW-статус → 'unknown': счётчик
            подряд-неизвестных растёт в durable-следе; по достижении
            degraded_threshold — честный terminal (batch failed, degraded
            причина сохранена). Никогда не выдумывается PASS.
          - batch terminal success → collect логов → evidence_sink.
        """
        results: list[BatchPollResult] = []
        runs_to_check: set[str] = set()

        with self._lock:
            active_snapshot = dict(self._active)

        for batch_id, ph in active_snapshot.items():
            raw_status = self._get_job_status(batch_id, ph)
            batch_status = self._map_status(raw_status)
            old_status = self._get_batch_pg_status(batch_id) or "running"

            if raw_status in _TERMINAL_WP:
                self._finish_terminal(batch_id, ph, raw_status, batch_status,
                                      old_status, results, runs_to_check)
            elif batch_status == "unknown":
                self._handle_unknown(batch_id, ph, raw_status, old_status,
                                     results, runs_to_check)
            elif batch_status != old_status:
                # COS-097: PG уже terminal — stale-наблюдение (параллельный
                # poll-цикл прочитал raw до terminal-pop) не имеет права
                # откатывать статус назад (passed → running).
                if old_status in _TERMINAL_BATCH:
                    with self._lock:
                        self._active.pop(batch_id, None)
                    continue
                self._update_batch_pg(batch_id, batch_status)
                results.append(BatchPollResult(
                    batch_id=batch_id, run_id=ph.run_id,
                    old_status=old_status, new_status=batch_status,
                    terminal=False, raw_status=raw_status))

        # Проверить run'ы, у которых появились terminal batch'и
        for run_id in runs_to_check:
            self._check_run_terminal(run_id)

        return results

    def recover(self) -> int:
        """COS-097: восстановить активные пайплайны из durable-следа.

        Вызывается на старте API (ExecutionService.start): ручки не-terminal
        строк cosmo_execution_handles возвращаются в poll-цикл — рестарт
        cosmo-api не теряет факт прогона.
        """
        if self._store is None:
            return 0
        rows = self._store.load_active()
        recovered = 0
        with self._lock:
            for row in rows:
                batch_id = row["batch_id"]
                if batch_id in self._active:
                    continue
                handle = row.get("handle") or {}
                if not handle.get("number"):
                    logger.warning("Recovery skip %s: handle без number", batch_id)
                    continue
                ph = PipelineHandle(
                    batch_id=batch_id,
                    run_id=row.get("run_id", ""),
                    plan_id=row.get("plan_id", ""),
                    handle=handle,
                )
                self._active[batch_id] = ph
                run_id = row.get("run_id", "")
                if run_id:
                    self._run_batches.setdefault(run_id, set()).add(batch_id)
                if row.get("plan_id"):
                    self._run_plans[run_id] = row["plan_id"]
                recovered += 1
        if recovered:
            logger.info("COS-097 recovery: %d active pipeline handle(s) restored",
                        recovered)
        return recovered

    def degraded_reason(self, run_id: str) -> Optional[str]:
        """COS-097: honest degraded-причина run'а (без удаления)."""
        with self._lock:
            return self._degraded_reasons.get(run_id)

    def pop_degraded_reason(self, run_id: str) -> Optional[str]:
        """COS-097: honest degraded-причина run'а (consume-once)."""
        with self._lock:
            return self._degraded_reasons.pop(run_id, None)

    def cancel_batches(self, run: Any) -> list[str]:
        """Отменить все активные pipeline'ы для run'а."""
        run_id = getattr(run, "id", "")
        cancelled: list[str] = []

        with self._lock:
            batch_ids = list(self._run_batches.get(run_id, set()))

        for batch_id in batch_ids:
            ph = self._active.get(batch_id)
            if ph is not None:
                if not self._dry_run:
                    try:
                        self._adapter.cancel_run(ph.handle)
                    except Exception as exc:
                        logger.warning("Cancel failed for batch %s: %s", batch_id, exc)
                self._update_batch_pg_terminal(batch_id, "blocked")
                if self._store is not None:
                    try:
                        self._store.mark_terminal(batch_id, "cancelled",
                                                  reason="cancelled via API")
                    except Exception as store_exc:
                        logger.error("Store mark_terminal failed for %s: %s",
                                     batch_id, store_exc)
                with self._lock:
                    self._active.pop(batch_id, None)
                cancelled.append(batch_id)
                logger.info("Batch %s cancelled", batch_id)

        return cancelled

    def active_batches(self) -> dict[str, PipelineHandle]:
        with self._lock:
            return dict(self._active)

    def reset(self) -> None:
        """Test helper: полный сброс."""
        with self._lock:
            self._active.clear()
            self._run_batches.clear()
            self._run_plans.clear()
            self._status_override.clear()
            self._submit_fail_batch_ids.clear()
            self._degraded_reasons.clear()

    # ── Internal: status mapping & honesty ──

    def _map_status(self, raw_status: str) -> str:
        """RAW-статус Woodpecker → batch-статус (честно, без выдумок).

        Неизвестное значение → 'unknown' (не pending-навсегда и не PASS):
        poller посчитает подряд-неизвестные и честно деградирует прогон.
        """
        if raw_status == "unknown":
            return "unknown"
        if raw_status in _STATUS_MAP:
            return _STATUS_MAP[raw_status]
        if raw_status in _EXTENDED_STATUS_MAP:
            return _EXTENDED_STATUS_MAP[raw_status]
        logger.warning("Unknown Woodpecker status %r — treating as unknown",
                       raw_status)
        return "unknown"

    def _get_job_status(self, batch_id: str, ph: PipelineHandle) -> str:
        """RAW-статус pipeline (с поддержкой test overrides).

        COS-097: ошибка транспорта → 'unknown' (в прототипе было 'pending'
        — вечный фальшивый оптимизм; честный unknown деградирует по
        threshold'у вместо тихого зависания).
        """
        if batch_id in self._status_override:
            return self._status_override[batch_id]
        if self._dry_run:
            return "success"  # dry-run: always succeed
        try:
            return self._adapter.get_status(ph.handle)
        except Exception as exc:
            logger.warning("Status poll failed for batch %s: %s", batch_id, exc)
            return "unknown"

    def _handle_unknown(self, batch_id: str, ph: PipelineHandle,
                        raw_status: str, old_status: str,
                        results: list[BatchPollResult],
                        runs_to_check: set[str]) -> None:
        unknown_count = 0
        if self._store is not None:
            try:
                unknown_count = self._store.record_unknown(batch_id, raw_status)
            except Exception as exc:
                logger.error("Store record_unknown failed for %s: %s",
                             batch_id, exc)
                unknown_count = self._degraded_threshold  # fail-safe: деградировать
        else:
            # Без store счётчик честности ведём в памяти процесса.
            unknown_count = self._mem_unknown.get(batch_id, 0) + 1
            self._mem_unknown[batch_id] = unknown_count

        if unknown_count < self._degraded_threshold:
            logger.info(
                "Batch %s unknown status (raw=%r) %d/%d",
                batch_id, raw_status, unknown_count, self._degraded_threshold)
            results.append(BatchPollResult(
                batch_id=batch_id, run_id=ph.run_id,
                old_status=old_status, new_status="running",
                terminal=False, degraded=False, raw_status=raw_status))
            return

        # Честный degraded terminal: batch failed, причина сохранена.
        reason = (f"execution degraded: {unknown_count} consecutive unknown "
                  f"polls (last raw status={raw_status!r})")
        logger.error("Batch %s DEGRADED: %s", batch_id, reason)
        # COS-097: атомарный claim — как в _finish_terminal.
        with self._lock:
            if self._active.get(batch_id) is not ph:
                return  # уже обработан другим poll'ом
            self._active.pop(batch_id, None)
            self._degraded_reasons[ph.run_id] = reason
        if self._store is not None:
            try:
                self._store.mark_terminal(batch_id, "degraded",
                                          reason=reason, degraded=True)
            except Exception as exc:
                logger.error("Store mark_terminal(degraded) failed for %s: %s",
                             batch_id, exc)
        self._update_batch_pg_terminal(batch_id, "failed")
        results.append(BatchPollResult(
            batch_id=batch_id, run_id=ph.run_id,
            old_status=old_status, new_status="failed",
            terminal=True, degraded=True, raw_status=raw_status))
        runs_to_check.add(ph.run_id)

    def _finish_terminal(self, batch_id: str, ph: PipelineHandle,
                         raw_status: str, batch_status: str, old_status: str,
                         results: list[BatchPollResult],
                         runs_to_check: set[str]) -> None:
        """Terminal-ветка: PG update, durable след, evidence на success.

        COS-097: атомарный claim — параллельный poll-цикл (фон-луп + ручной)
        не может обработать тот же batch дважды (двойной evidence/PG write).
        """
        with self._lock:
            if self._active.get(batch_id) is not ph:
                return  # уже обработан другим poll'ом
            self._active.pop(batch_id, None)

        self._update_batch_pg_terminal(batch_id, batch_status)
        if self._store is not None:
            try:
                self._store.mark_terminal(
                    batch_id, raw_status,
                    reason=None if batch_status == "passed" else
                    f"pipeline finished with raw status {raw_status!r}",
                    degraded=False)
            except Exception as exc:
                logger.error("Store mark_terminal failed for %s: %s",
                             batch_id, exc)

        if batch_status == "passed" and self._evidence_sink is not None:
            self._emit_evidence(batch_id, ph, raw_status)

        results.append(BatchPollResult(
            batch_id=batch_id, run_id=ph.run_id,
            old_status=old_status, new_status=batch_status,
            terminal=True, degraded=False, raw_status=raw_status))
        runs_to_check.add(ph.run_id)

    def _emit_evidence(self, batch_id: str, ph: PipelineHandle,
                       raw_status: str) -> None:
        """COS-097: собрал реальные логи прогона → evidence_sink.

        Фейл сбора/доставки улик не роняет poll-цикл и не ломает batch —
        но виден в логах и durable-следе (record_evidence_error).
        """
        try:
            logs = self._adapter.collect_all_logs(ph.handle)
            meta = {
                "raw_status": raw_status,
                "repo_owner": ph.handle.get("repo_owner", ""),
                "repo_name": ph.handle.get("repo_name", ""),
                "repo_id": ph.handle.get("repo_id"),
                "number": ph.handle.get("number"),
                "branch": ph.handle.get("branch", "main"),
            }
            self._evidence_sink(ph.run_id, batch_id, logs, meta)
            logger.info("Evidence collected for batch %s (pipeline #%s, %d steps)",
                        batch_id, meta["number"], len(logs))
        except Exception as exc:
            logger.error("Evidence collection failed for batch %s: %s",
                         batch_id, exc)
            if self._store is not None:
                try:
                    self._store.record_evidence_error(batch_id, str(exc))
                except Exception as store_exc:
                    logger.error("Store record_evidence_error failed: %s", store_exc)

    def _repo_for_run(self, run_id: str, plan_id: str,
                      batch_id: str) -> tuple[str, str, str]:
        """COS-097: repo прогона — resolve_repo callback (binding) → fallback."""
        if self._resolve_repo is not None:
            try:
                resolved = self._resolve_repo(run_id, plan_id, batch_id)
            except Exception as exc:
                logger.warning("Repo resolution failed for batch %s: %s — fallback",
                               batch_id, exc)
                resolved = None
            if resolved:
                owner, name, branch = resolved
                if owner and name:
                    return owner, name, branch or "main"
        return self._repo_owner, self._repo_name, "main"

    # ── Internal: PostgreSQL ──

    def _query_batches(self, plan_id: str) -> list[dict[str, Any]]:
        """Query batches from PG by plan_id."""
        if self._db_session_factory is None or not plan_id:
            return []
        s = self._db_session_factory()
        try:
            from orchestrator.cosmo.db.models import Batch as BatchORM
            orms = s.query(BatchORM).filter(BatchORM.plan_id == plan_id).all()
            return [
                {
                    "id": o.id, "plan_id": o.plan_id, "type": o.type,
                    "status": o.status, "bricks": o.bricks_refs or [],
                    "artifacts": o.artifacts or [],
                }
                for o in orms
            ]
        finally:
            s.close()

    def _update_batch_pg(self, batch_id: str, status: str) -> None:
        if self._db_session_factory is None:
            return
        s = self._db_session_factory()
        try:
            from orchestrator.cosmo.db.models import Batch as BatchORM
            orm = s.query(BatchORM).filter(BatchORM.id == batch_id).first()
            if orm is not None:
                orm.status = status
                if status == "running" and orm.started_at is None:
                    # COS-097 fix: было "runing" — started_at никогда не ставился.
                    orm.started_at = datetime.utcnow()
                s.commit()
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    def _update_batch_pg_terminal(self, batch_id: str, status: str) -> None:
        if self._db_session_factory is None:
            return
        s = self._db_session_factory()
        try:
            from orchestrator.cosmo.db.models import Batch as BatchORM
            orm = s.query(BatchORM).filter(BatchORM.id == batch_id).first()
            if orm is not None:
                orm.status = status
                orm.finished_at = datetime.utcnow()
                s.commit()
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    def _get_batch_pg_status(self, batch_id: str) -> str | None:
        if self._db_session_factory is None:
            return None
        s = self._db_session_factory()
        try:
            from orchestrator.cosmo.db.models import Batch as BatchORM
            orm = s.query(BatchORM).filter(BatchORM.id == batch_id).first()
            return orm.status if orm else None
        finally:
            s.close()

    # ── Internal: Run terminal check ──

    def _check_run_terminal(self, run_id: str) -> None:
        """Проверить, все ли batch'и run'а terminal. Если да — callback.

        PG-free: использует _run_batches для списка batch'ей и _get_batch_pg_status для статуса.
        """
        plan_id = self._run_plans.get(run_id)
        if plan_id is None:
            return

        with self._lock:
            batch_ids = set(self._run_batches.get(run_id, set()))
        if not batch_ids:
            return

        all_terminal = True
        all_passed = True
        for bid in batch_ids:
            status = self._get_batch_pg_status(bid) or "pending"
            if status not in _TERMINAL_BATCH:
                all_terminal = False
                break
            if status != "passed":
                all_passed = False

        if not all_terminal:
            return

        logger.info("Run %s: all %d batches terminal (all_passed=%s)",
                    run_id, len(batch_ids), all_passed)

        if self._on_all_terminal is not None:
            self._on_all_terminal(run_id, all_passed)
