# -*- coding: utf-8 -*-
"""COS-046: Batch Execution Engine — Woodpecker CI integration.

Связывает RunControlPlane с Woodpecker:
  1. Когда run входит в RUNNING → submit каждого batch как pipeline
  2. Отслеживание завершения через polling
  3. Обновление batch.status в PostgreSQL
  4. Gate evaluation trigger когда все batch'и terminal

Архитектура:
  - BatchExecutor: управление жизненным циклом batch-пайплайнов
  - PipelineHandle: handle на Woodpecker pipeline (batch → job mapping)
  - BatchPollResult: результат одного poll-цикла
  - _STATUS_MAP: Woodpecker status → Batch status
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
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

_TERMINAL_WP = frozenset({"success", "failure", "killed", "error"})
_TERMINAL_BATCH = frozenset({"passed", "failed", "blocked"})


# ── Dataclasses ──

@dataclass
class PipelineHandle:
    """Handle на запущенный Woodpecker pipeline (batch → job mapping)."""
    batch_id: str
    run_id: str
    plan_id: str
    handle: dict[str, Any]  # {job_id, number, repo_owner, repo_name}


@dataclass
class BatchPollResult:
    """Результат одного poll-цикла для batch'а."""
    batch_id: str
    run_id: str
    old_status: str
    new_status: str
    terminal: bool


# ── Batch Executor ──

class BatchExecutor:
    """COS-046: Submit batches as Woodpecker CI pipelines.

    Жизненный цикл:
      1. submit_batches(run)             → submit каждого batch как pipeline
      2. poll()                          → проверить статусы, обновить PG
      3. _check_run_terminal(run_id)     → когда все terminal → callback
      4. cancel_batches(run)             → остановить активные pipeline'ы

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
    ) -> None:
        self._adapter = adapter
        self._db_session_factory = db_session_factory
        self._repo_owner = repo_owner
        self._repo_name = repo_name
        self._dry_run = dry_run
        self._on_all_terminal = on_all_terminal

        self._lock = threading.RLock()
        self._active: dict[str, PipelineHandle] = {}   # batch_id → handle
        self._run_batches: dict[str, set[str]] = {}    # run_id → {batch_ids}
        self._run_plans: dict[str, str] = {}           # run_id → plan_id (для _check_run_terminal без PG)

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

            # Сгенерировать YAML (для аудита)
            try:
                yaml_config = self._adapter.generate_pipeline_yaml(orm)
                logger.debug("Pipeline YAML for batch %s (%s): %d chars",
                            batch_id, batch_type, len(yaml_config))
            except Exception as exc:
                logger.warning("YAML generation failed for batch %s: %s", batch_id, exc)

            # Submit pipeline
            if self._dry_run:
                handle = {
                    "job_id": f"dry-{batch_id}",
                    "number": 1,
                    "repo_owner": self._repo_owner,
                    "repo_name": self._repo_name,
                }
            else:
                try:
                    handle = self._adapter.submit_run(
                        self._repo_owner, self._repo_name
                    )
                except Exception as exc:
                    logger.error("Submit failed for batch %s: %s", batch_id, exc)
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

            self._update_batch_pg(batch_id, "running")
            submitted.append(batch_id)
            logger.info("Batch %s (%s) submitted as pipeline #%s",
                        batch_id, batch_type, handle.get("number"))

        return submitted

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

        Когда все batch'и для run'а становятся terminal — вызывает on_all_terminal.
        """
        results: list[BatchPollResult] = []
        runs_to_check: set[str] = set()

        with self._lock:
            active_snapshot = dict(self._active)

        for batch_id, ph in active_snapshot.items():
            job_status = self._get_job_status(batch_id, ph)
            batch_status = _STATUS_MAP.get(job_status, "failed")
            old_status = self._get_batch_pg_status(batch_id) or "running"

            if job_status in _TERMINAL_WP:
                self._update_batch_pg_terminal(batch_id, batch_status)
                with self._lock:
                    self._active.pop(batch_id, None)
                results.append(BatchPollResult(
                    batch_id=batch_id, run_id=ph.run_id,
                    old_status=old_status, new_status=batch_status,
                    terminal=True))
                runs_to_check.add(ph.run_id)
            elif batch_status != old_status:
                self._update_batch_pg(batch_id, batch_status)
                results.append(BatchPollResult(
                    batch_id=batch_id, run_id=ph.run_id,
                    old_status=old_status, new_status=batch_status,
                    terminal=False))

        # Проверить run'ы, у которых появились terminal batch'и
        for run_id in runs_to_check:
            self._check_run_terminal(run_id)

        return results

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
                if status == "runing" and orm.started_at is None:
                    orm.started_at = datetime.now(timezone.utc)
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
                orm.finished_at = datetime.now(timezone.utc)
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

    # ── Internal: Status polling ──

    def _get_job_status(self, batch_id: str, ph: PipelineHandle) -> str:
        """Получить статус pipeline (с поддержкой test overrides)."""
        if batch_id in self._status_override:
            return self._status_override[batch_id]
        if self._dry_run:
            return "success"  # dry-run: always succeed
        try:
            return self._adapter.get_status(ph.handle)
        except Exception as exc:
            logger.warning("Status poll failed for batch %s: %s", batch_id, exc)
            return "pending"  # assume still running

    def _check_run_terminal(self, run_id: str) -> None:
        """Проверить, все ли batch'и run'а terminal. Если да — callback.

        PG-free: использует _run_batches для списка batch'ей и _get_batch_pg_status для статуса.
        """
        plan_id = self._run_plans.get(run_id)
        if plan_id is None:
            return

        batch_ids = self._run_batches.get(run_id, set())
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