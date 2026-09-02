# -*- coding: utf-8 -*-
"""COS-097: ExecutionService — живой Woodpecker run-цикл в API.

Клеит BatchExecutor (sync, thread-based) к async-приложению:
  - HandleStoreBridge: durable-след ручек (cosmo_execution_handles) через
    async-сессии; executor-потоки зовут sync-фасад, корутины едут в главный
    loop через run_coroutine_threadsafe.
  - Poll loop: раз в COSMO_EXECUTOR_POLL_INTERVAL executor.poll() в треде
    (run_coroutine_threadsafe из треда требует свободный loop — поэтому
    все sync-входы executor'а только через asyncio.to_thread).
  - Finalize: все batch'и terminal → честный run-статус в PG:
      passed + not degraded → succeeded
      degraded              → failed  (ExecutionClass.INFRA-семантика,
                                причина в durable-следе + alert-evidence)
      batch failure         → blocked (parity COS-046 RCP)
  - Evidence: реальный SHA-256 digest логов прогона → EvidenceLedgerEntry
    (канонический commit_evidence_entry), Batch.evidence_refs обновляется.
  - Recover: на старте executor.recover() из durable-следа — рестарт API
    не теряет факт прогона (accept COS-097).

Включение: COSMO_EXECUTOR_ENABLED=1 (default off — unit-сеты и стенды без
Woodpecker не должны менять поведение). Woodpecker v3.5: PK_WOODPECKER_URL
(или COSMO_WOODPECKER_URL) + COSMO_WOODPECKER_TOKEN.

Out of scope (COS-097): gates на живых findings (мост), UI логов, RCP
dispatch/leases (executor потребляет статусы в PG SoT; полная RCP-wiring —
отдельная поверхность COS-003).
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import threading
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, Optional

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from orchestrator.cosmo.adapters.execution_woodpecker import WoodpeckerAdapter
from orchestrator.cosmo.control_plane.executor import (
    DEFAULT_DEGRADED_THRESHOLD,
    BatchExecutor,
)
from orchestrator.cosmo.db.models import Batch as BatchORM
from orchestrator.cosmo.db.models import Run as RunORM
from orchestrator.cosmo.db.models import EvidenceLedgerEntry
from orchestrator.cosmo.db.models_execution import (
    TERMINAL_STORED_STATUSES,
    ExecutionBase,
    ExecutionHandleRow,
)

logger = logging.getLogger("cosmo.execution")

DEFAULT_POLL_INTERVAL = 10.0
_BRIDGE_TIMEOUT = 30.0


def execution_enabled() -> bool:
    """COS-097: живой execution-контур включается только явно."""
    return os.getenv("COSMO_EXECUTOR_ENABLED", "").strip().lower() in ("1", "true", "yes")


def _env_repo_default() -> tuple[str, str]:
    raw = os.getenv("COSMO_WOODPECKER_REPO", "cosmo/default")
    owner, _, name = raw.partition("/")
    return (owner or "cosmo", name or "default")


# ── Durable handle store: sync facade → async session ──


class HandleStoreBridge:
    """Sync-фасад над cosmo_execution_handles для executor-потоков.

    Все executor-входы идут через asyncio.to_thread, поэтому главный loop
    свободен и run_coroutine_threadsafe(...).result() безопасен.
    """

    def __init__(self, session_factory: Any, loop: asyncio.AbstractEventLoop):
        self._sf = session_factory
        self._loop = loop

    def _run(self, coro: Any) -> Any:
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result(
            timeout=_BRIDGE_TIMEOUT)

    # ── sync API (вызывается из executor-потоков) ──

    def upsert(self, batch_id: str, run_id: str, plan_id: str, handle: dict) -> None:
        self._run(self._upsert_async(batch_id, run_id, plan_id, handle))

    def mark_terminal(self, batch_id: str, status: str, *,
                      reason: Optional[str] = None,
                      degraded: bool = False) -> None:
        self._run(self._mark_terminal_async(batch_id, status, reason, degraded))

    def record_unknown(self, batch_id: str, raw_status: str) -> int:
        return self._run(self._record_unknown_async(batch_id, raw_status))

    def record_evidence_error(self, batch_id: str, error: str) -> None:
        self._run(self._record_evidence_error_async(batch_id, error))

    def load_active(self) -> list[dict]:
        return self._run(self._load_active_async())

    def get_active(self, batch_id: str) -> Optional[dict]:
        """COS-097 resubmit-guard: не-terminal строка ручки (или None)."""
        return self._run(self._get_active_async(batch_id))

    # ── async implementations ──

    async def _upsert_async(self, batch_id: str, run_id: str, plan_id: str,
                            handle: dict) -> None:
        values = {
            "batch_id": batch_id,
            "run_id": run_id,
            "plan_id": plan_id or "",
            "repo_id": handle.get("repo_id"),
            "repo_owner": str(handle.get("repo_owner", "")),
            "repo_name": str(handle.get("repo_name", "")),
            "branch": str(handle.get("branch", "main")),
            "wp_number": handle.get("number"),
            "wp_pipeline_id": handle.get("job_id"),
            "last_status": "running",
            "unknown_count": 0,
            "degraded": False,
            "reason": None,
            "evidence_error": None,
        }
        async with self._sf() as s:
            stmt = pg_insert(ExecutionHandleRow).values(**values).on_conflict_do_update(
                index_elements=[ExecutionHandleRow.batch_id],
                set_={
                    "run_id": values["run_id"],
                    "plan_id": values["plan_id"],
                    "repo_id": values["repo_id"],
                    "repo_owner": values["repo_owner"],
                    "repo_name": values["repo_name"],
                    "branch": values["branch"],
                    "wp_number": values["wp_number"],
                    "wp_pipeline_id": values["wp_pipeline_id"],
                    "last_status": "running",
                    "unknown_count": 0,
                    "degraded": False,
                    "reason": None,
                    "evidence_error": None,
                },
            )
            await s.execute(stmt)
            await s.commit()

    async def _mark_terminal_async(self, batch_id: str, status: str,
                                   reason: Optional[str],
                                   degraded: bool) -> None:
        async with self._sf() as s:
            await s.execute(
                update(ExecutionHandleRow)
                .where(ExecutionHandleRow.batch_id == batch_id)
                .values(last_status=status, reason=reason, degraded=degraded)
            )
            await s.commit()

    async def _record_unknown_async(self, batch_id: str, raw_status: str) -> int:
        async with self._sf() as s:
            row = (await s.execute(
                update(ExecutionHandleRow)
                .where(ExecutionHandleRow.batch_id == batch_id)
                .values(last_status=raw_status if raw_status != "unknown" else None,
                        unknown_count=ExecutionHandleRow.unknown_count + 1)
                .returning(ExecutionHandleRow.unknown_count)
            )).first()
            await s.commit()
            return int(row[0]) if row else 0

    async def _record_evidence_error_async(self, batch_id: str, error: str) -> None:
        async with self._sf() as s:
            await s.execute(
                update(ExecutionHandleRow)
                .where(ExecutionHandleRow.batch_id == batch_id)
                .values(evidence_error=error[:2000])
            )
            await s.commit()

    async def _get_active_async(self, batch_id: str) -> Optional[dict]:
        async with self._sf() as s:
            row = await s.get(ExecutionHandleRow, batch_id)
            if row is None or (row.last_status or "") in TERMINAL_STORED_STATUSES:
                return None
            return {
                "batch_id": row.batch_id,
                "run_id": row.run_id,
                "plan_id": row.plan_id,
                "last_status": row.last_status,
            }

    async def _load_active_async(self) -> list[dict]:
        async with self._sf() as s:
            rows = (await s.execute(select(ExecutionHandleRow))).scalars().all()
            out = []
            for r in rows:
                if (r.last_status or "") in TERMINAL_STORED_STATUSES:
                    continue
                out.append({
                    "batch_id": r.batch_id,
                    "run_id": r.run_id,
                    "plan_id": r.plan_id,
                    "last_status": r.last_status,
                    "handle": r.as_handle_dict(),
                })
            return out


# ── ExecutionService ──


class ExecutionService:
    """Живой Woodpecker-контур: poll loop + finalize + evidence + recover."""

    def __init__(
        self,
        session_factory: Any,
        adapter: Optional[WoodpeckerAdapter] = None,
        *,
        poll_interval: float | None = None,
        degraded_threshold: int = DEFAULT_DEGRADED_THRESHOLD,
        repo_owner: str | None = None,
        repo_name: str | None = None,
        sync_session_factory: Any = None,
    ) -> None:
        self._sf = session_factory
        self._sync_db = sync_session_factory or self._default_sync_session
        self._poll_interval = float(
            poll_interval or os.getenv("COSMO_EXECUTOR_POLL_INTERVAL", "") or DEFAULT_POLL_INTERVAL)
        owner = repo_owner if repo_owner is not None else _env_repo_default()[0]
        name = repo_name if repo_name is not None else _env_repo_default()[1]

        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._stopping = threading.Event()
        self._poll_task: Optional[asyncio.Task] = None

        self._store: Optional[HandleStoreBridge] = None
        self._executor = BatchExecutor(
            adapter=adapter or WoodpeckerAdapter(),
            db_session_factory=self._sync_db,
            repo_owner=owner,
            repo_name=name,
            dry_run=False,
            handle_store=None,   # подключается в start() после capture loop
            resolve_repo=self._resolve_repo_sync,
            evidence_sink=self._evidence_sink_sync,
            degraded_threshold=degraded_threshold,
        )

    # ── sync session factory для executor'а (psycopg2, SoT batch.status) ──

    @staticmethod
    def _default_sync_session() -> Any:
        from orchestrator.cosmo.db.session import get_sync_session
        return get_sync_session()

    # ── lifecycle ──

    async def start(self) -> None:
        await self._start_core()
        self._poll_task = asyncio.create_task(
            self._poll_loop(), name="cosmo-executor-poll")
        logger.info("COS-097 ExecutionService started (poll every %.1fs)",
                    self._poll_interval)

    async def _start_core(self) -> None:
        """Всё, кроме фонового poll-лупа: loop/store/tables/recover.

        Тесты зовут напрямую (детерминированные ручные poll'ы без гонки с
        фоновым циклом); start() = _start_core() + poll task.
        """
        self._loop = asyncio.get_running_loop()
        self._stopping.clear()
        self._store = HandleStoreBridge(self._sf, self._loop)
        self._executor._store = self._store
        # COS-097: terminal всех batch'ей → finalize (честный run-статус).
        self._executor._on_all_terminal = self._on_all_terminal_sync

        await self._ensure_tables()
        recovered = await asyncio.to_thread(self._executor.recover)
        if recovered:
            logger.warning("COS-097: recovered %d active pipeline handle(s) "
                           "after restart — продолжаем поллить", recovered)

    async def stop(self) -> None:
        self._stopping.set()
        if self._poll_task is not None:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass
            except Exception as exc:
                logger.error("Poll task stop error: %s", exc)
            self._poll_task = None
        logger.info("COS-097 ExecutionService stopped")

    async def _ensure_tables(self) -> None:
        """Idempotent create_all для side-таблицы (как gate trail в lifespan)."""
        from orchestrator.cosmo.db.session import get_engine
        bind = getattr(self._sf, "kw", {}).get("bind") or get_engine()
        async with bind.begin() as conn:
            await conn.run_sync(ExecutionBase.metadata.create_all)

    # ── публичные входы (runs API) ──

    async def submit_run(self, run_id: str) -> None:
        """Run → running в ПУ: submit plan-batch'ей как Woodpecker pipelines.

        Fire-and-forget: API не блокируется на HTTP к Woodpecker.
        """
        if self._poll_task is None:
            return
        asyncio.create_task(self._submit_async(run_id), name=f"cosmo-submit-{run_id}")

    async def cancel_run(self, run_id: str) -> None:
        run_like = SimpleNamespace(id=run_id)
        await asyncio.to_thread(self._executor.cancel_batches, run_like)

    async def _submit_async(self, run_id: str) -> None:
        try:
            async with self._sf() as s:
                run = await s.get(RunORM, run_id)
            if run is None:
                logger.warning("Submit skip: run %s not found", run_id)
                return
            if run.status != "running":
                logger.info("Submit skip: run %s status=%s (не running)",
                            run_id, run.status)
                return
            run_like = SimpleNamespace(id=run.id, plan_id=run.plan_id)
            await asyncio.to_thread(self._executor.submit_batches, run_like)
        except Exception as exc:
            logger.error("Submit failed for run %s: %s", run_id, exc)

    # ── poll loop ──

    async def _poll_loop(self) -> None:
        while not self._stopping.is_set():
            try:
                await asyncio.to_thread(self._executor.poll)
            except Exception as exc:
                logger.error("Executor poll cycle failed: %s", exc)
            # COS-097: sleep, не threading.Event.wait() — Event.wait БЕЗ
            # таймаута блокирует поток loop'а синхронно (ловилось
            # faulthandler-дампом: loop заморожен, все bridge-futures
            # висят). stop().cancel() прерывает sleep сразу.
            await asyncio.sleep(self._poll_interval)

    # ── executor callbacks (из to_thread-потоков) ──

    def _on_all_terminal_sync(self, run_id: str, all_passed: bool) -> None:
        assert self._loop is not None
        fut = asyncio.run_coroutine_threadsafe(
            self.finalize_run(run_id, all_passed), self._loop)
        fut.add_done_callback(self._log_bg_failure)

    @staticmethod
    def _log_bg_failure(fut: Any) -> None:
        exc = fut.exception()
        if exc is not None:
            logger.error("Background finalize failed: %s", exc)

    def _resolve_repo_sync(self, run_id: str, plan_id: str,
                           batch_id: str) -> Optional[tuple[str, str, str]]:
        """Binding приложения (COS-096) → (owner, name, branch)."""
        assert self._loop is not None
        fut = asyncio.run_coroutine_threadsafe(
            self._resolve_repo_async(plan_id), self._loop)
        try:
            return fut.result(timeout=_BRIDGE_TIMEOUT)
        except Exception as exc:
            logger.warning("Repo resolution failed for run %s: %s", run_id, exc)
            return None

    async def _resolve_repo_async(self, plan_id: str) -> Optional[tuple[str, str, str]]:
        from orchestrator.cosmo.db.models import PipelinePlan, RepositoryBinding
        if not plan_id:
            return None
        async with self._sf() as s:
            plan = await s.get(PipelinePlan, plan_id)
            if plan is None or not plan.app_id:
                return None
            row = (await s.execute(
                select(RepositoryBinding)
                .where(RepositoryBinding.app_id == plan.app_id)
                .limit(1)
            )).scalars().first()
            if row is None or not row.repo_path or "/" not in row.repo_path:
                return None
            owner, _, name = row.repo_path.partition("/")
            return owner, name, row.default_branch or "main"

    def _evidence_sink_sync(self, run_id: str, batch_id: str,
                            logs: dict[str, list[str]], meta: dict) -> None:
        assert self._loop is not None
        fut = asyncio.run_coroutine_threadsafe(
            self.write_run_evidence(run_id, batch_id, logs, meta), self._loop)
        fut.result(timeout=_BRIDGE_TIMEOUT)  # executor поймает и запишет след

    # ── evidence (реальный digest прогона) ──

    @staticmethod
    def _logs_digest(logs: dict[str, list[str]]) -> tuple[str, bytes]:
        """SHA-256 по канону: '## step\\nline\\n...' — детерминированно."""
        parts: list[str] = []
        for step_name in sorted(logs):
            parts.append(f"## {step_name}")
            parts.extend(logs[step_name])
        content = ("\n".join(parts) + "\n").encode("utf-8")
        return hashlib.sha256(content).hexdigest(), content

    async def write_run_evidence(self, run_id: str, batch_id: str,
                                 logs: dict[str, list[str]], meta: dict) -> str:
        """COS-097: EvidenceLedgerEntry из РЕАЛЬНОГО прогона (SHA-256 логов).

        Канонический write-path: commit_evidence_entry (append → seal →
        commit → publish_head). Обновляет Batch.evidence_refs в той же
        транзакции.
        """
        digest, _content = self._logs_digest(logs)
        repo = f"{meta.get('repo_owner', '')}/{meta.get('repo_name', '')}"
        entry = EvidenceLedgerEntry(
            run_id=run_id,
            batch_id=batch_id,
            type="log",
            content_ref=f"woodpecker://{repo}/{meta.get('number')}",
            content_hash=digest,
            provenance_json={
                "source": "woodpecker",
                "repo": repo,
                "number": meta.get("number"),
                "branch": meta.get("branch", "main"),
                "raw_status": meta.get("raw_status"),
                "steps": sorted(logs.keys()),
                "total_lines": sum(len(v) for v in logs.values()),
                "collected_at": datetime.now(timezone.utc).isoformat(),
                "degraded": False,
            },
        )
        from orchestrator.cosmo.ledger.evidence_writer import commit_evidence_entry
        async with self._sf() as s:
            entry_hash = await commit_evidence_entry(s, entry)
            batch = await s.get(BatchORM, batch_id)
            if batch is not None:
                refs = list(batch.evidence_refs or [])
                refs.append(entry.id)
                batch.evidence_refs = refs
                await s.commit()
        logger.info("COS-097 evidence sealed: run=%s batch=%s digest=%s",
                    run_id, batch_id, digest[:16])
        return entry_hash

    async def write_degraded_evidence(self, run_id: str, reason: str,
                                      meta: dict) -> str:
        """COS-097: честный degraded-след — alert-запись в tamper-evident
        ledger (не выдуманный PASS и не молчаливый hang)."""
        payload = json.dumps(
            {"degraded": True, "reason": reason, **meta},
            sort_keys=True, ensure_ascii=False).encode("utf-8")
        digest = hashlib.sha256(payload).hexdigest()
        repo = meta.get("repo", "")
        entry = EvidenceLedgerEntry(
            run_id=run_id,
            batch_id=None,
            type="alert",
            content_ref=f"woodpecker://{repo}" if repo else "woodpecker://degraded",
            content_hash=digest,
            provenance_json={
                "source": "woodpecker",
                "degraded": True,
                "reason": reason,
                "recorded_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        from orchestrator.cosmo.ledger.evidence_writer import commit_evidence_entry
        async with self._sf() as s:
            entry_hash = await commit_evidence_entry(s, entry)
        return entry_hash

    # ── finalize: честный run-статус из живых статусов ──

    async def finalize_run(self, run_id: str, all_passed: bool) -> None:
        executor = self._executor
        degraded_reason = executor.pop_degraded_reason(run_id)

        async with self._sf() as s:
            run = await s.get(RunORM, run_id)
            if run is None:
                logger.warning("Finalize skip: run %s not found", run_id)
                return
            if run.status in ("succeeded", "failed", "cancelled"):
                logger.info("Finalize skip: run %s уже terminal (%s)",
                            run_id, run.status)
                return

            # Колонки TIMESTAMP WITHOUT TIME ZONE — naive UTC (конвенция
            # models.py); aware datetime asyncpg отвергает.
            now = datetime.utcnow()
            if run.started_at is None:
                run.started_at = now

            if degraded_reason:
                run.status = "failed"
                final_status = "failed"
                notify_status = "failed"
            elif all_passed:
                run.status = "succeeded"
                final_status = "succeeded"
                notify_status = "succeeded"
            else:
                # Batch failure без degraded → blocked (parity COS-046).
                run.status = "blocked"
                final_status = "blocked"
                notify_status = "blocked"
            run.finished_at = now
            # expire_on_commit=False, но поля нужны после close — фиксируем.
            run_domain_id = run.domain_id
            run_plan_id = run.plan_id
            await s.commit()

        logger.info("COS-097 run %s finalized: %s (degraded=%s)",
                    run_id, final_status, bool(degraded_reason))

        # Честный durable-след degraded + уведомления (best-effort).
        if degraded_reason:
            try:
                await self.write_degraded_evidence(run_id, degraded_reason, {})
            except Exception as exc:
                logger.error("Degraded evidence failed for run %s: %s",
                             run_id, exc)

        try:
            from orchestrator.cosmo.notifications.integration import notify_run_status_safe
            notify_run_status_safe(
                run_id=run_id,
                domain_id=run_domain_id,
                status=notify_status,
                plan_id=run_plan_id,
                initiator="execution-service",
            )
        except Exception as exc:
            logger.warning("Notify failed for run %s: %s", run_id, exc)

    # ── introspection (tests/health) ──

    def active_batches(self) -> dict[str, Any]:
        return self._executor.active_batches()
