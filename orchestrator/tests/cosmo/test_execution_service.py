# -*- coding: utf-8 -*-
"""COS-097: ExecutionService — живой Woodpecker-цикл против real PostgreSQL.

Покрывает accept-критерии карточки:
  1. Submit из ПУ (run → running) персистит durable handle + binding repo.
  2. Poll живых статусов: success → evidence с РЕАЛЬНЫМ SHA-256 digest
     логов + finalize run → succeeded.
  3. Honesty: unknown статусы считаются; sustained unknown → честный
     degraded (batch failed, run failed, alert-evidence в ledger) — не
     выдуманный PASS и не молчаливый hang.
  4. Restart-survival: рестарт cosmo-api не теряет факт прогона —
     recover() возвращает ручки в poll, прогон доигрывается.
  5. Честные маппинги v3.5: declined → blocked, skipped → failed.

Repo-контур — scratch-БД test PG :5433 (COS-073/078), API-контур — общий
pg_client (conftest). Side-таблица cosmo_execution_handles создаётся на
отдельном ExecutionBase через create_all (как models_transfer, COS-070).

Детерминированность: большинство тестов стартуют сервис через
_start_core() (loop/store/tables/recover БЕЗ фонового poll-лупа) и поллят
вручную — иначе фоновый цикл гонится с ручными poll'ами (дважды съедает
состояния FakeWoodpecker и скачет unknown_count). Фоновый poll-loop
покрыт отдельным TestPollLoopIntegration.
"""
from __future__ import annotations

import asyncio
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock
from urllib.parse import urlsplit

import pytest
import pytest_asyncio

import _testpg

_repo = Path(__file__).resolve().parents[3]
_orch = Path(__file__).resolve().parents[2]
for p in (str(_repo), str(_orch)):
    if p not in sys.path:
        sys.path.insert(0, p)

from orchestrator.cosmo.control_plane.executor import BatchExecutor  # noqa: E402
from orchestrator.cosmo.control_plane.execution_service import ExecutionService  # noqa: E402
from orchestrator.cosmo.control_plane.run_control import (  # noqa: E402
    FailureClass,
    RunControlPlane,
    RunRecord,
    RunState,
)
from orchestrator.cosmo.db.models import (  # noqa: E402
    Application,
    Batch as BatchORM,
    Domain,
    EvidenceLedgerEntry,
    PipelinePlan,
    RepositoryBinding,
    Run as RunORM,
)
from orchestrator.cosmo.db.models_execution import (  # noqa: E402
    ExecutionBase,
    ExecutionHandleRow,
)

SCRATCH_DB = _testpg.scratch_name("exec_service")
_POSTGRES_ADMIN_URL = _testpg.admin_dsn()

skip_pg = pytest.mark.skipif(
    not _testpg.pg_available(),
    reason="test PG (:5433) unreachable - docker compose -f services/docker-compose.test-pg.yml up -d",
)

pytestmark = [pytest.mark.asyncio, skip_pg]


def _async_url(dbname: str) -> str:
    parsed = urlsplit(_testpg.TEST_PG_URL)
    return (
        f"postgresql+asyncpg://{parsed.username}:{parsed.password}"
        f"@{parsed.hostname}:{parsed.port}/{dbname}"
    )


# ── Fake Woodpecker adapter (контракт как у v3.5, состояния — очередь) ──


class FakeWoodpecker:
    """Состояния по номеру pipeline (RAW v3.5), pop по poll.

    Ключи — str(number): submit нумерует pipeline'ы с 1, restore после
    «рестарта» возвращает handle с тем же number.
    """

    def __init__(self, statuses: dict[str, list[str]] | None = None,
                 logs: dict[str, list[str]] | None = None,
                 fail_poll: bool = False):
        self.statuses = statuses or {}
        self.logs = logs or {"scan": ["line-1", "line-2"]}
        self.fail_poll = fail_poll
        self.submitted: list[dict] = []
        self.cancelled: list[dict] = []
        self._counter = 0

    def generate_pipeline_yaml(self, batch: dict) -> str:
        return "steps: {}"

    def submit_run(self, repo_owner: str, repo_name: str, branch: str = "main") -> dict:
        self._counter += 1
        handle = {
            "job_id": 9000 + self._counter,
            "number": self._counter,
            "repo_id": 42,
            "repo_owner": repo_owner,
            "repo_name": repo_name,
            "branch": branch,
        }
        self.submitted.append(handle)
        return handle

    def get_status(self, handle: dict) -> str:
        if self.fail_poll:
            raise ConnectionError("woodpecker unreachable")
        seq = self.statuses.get(str(handle.get("number")), [])
        return seq.pop(0) if seq else "running"

    def collect_all_logs(self, handle: dict, settle_empty_s: float = 0.0,
                         settle_attempts: int = 3) -> dict[str, list[str]]:
        return dict(self.logs)

    def get_logs(self, handle: dict, step: int = 0) -> list[str]:
        return []

    def cancel_run(self, handle: dict) -> bool:
        self.cancelled.append(handle)
        return True


# ── Fixtures ──


@pytest.fixture(scope="module")
def _scratch():
    """Scratch-БД + create_all shared Base + ExecutionBase (schema-level)."""
    import psycopg2
    from sqlalchemy import create_engine

    def _admin():
        return psycopg2.connect(_POSTGRES_ADMIN_URL)

    def _drop():
        conn = _admin()
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname = %s AND pid <> pg_backend_pid()",
            (SCRATCH_DB,),
        )
        cur.execute(f"DROP DATABASE IF EXISTS {SCRATCH_DB}")
        conn.close()

    _drop()
    conn = _admin()
    conn.autocommit = True
    conn.cursor().execute(f"CREATE DATABASE {SCRATCH_DB}")
    conn.close()

    engine = create_engine(_testpg.psycopg2_url(SCRATCH_DB))
    from orchestrator.cosmo.db.models import Base as CosmoBase
    CosmoBase.metadata.create_all(engine)
    ExecutionBase.metadata.create_all(engine)
    engine.dispose()
    yield SCRATCH_DB
    _drop()


@pytest_asyncio.fixture()
async def env(_scratch):
    """Per-test: async sessionmaker + sync factory на scratch-БД."""
    from sqlalchemy import create_engine
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    engine = create_async_engine(_async_url(_scratch))
    # bind — обязателен: ExecutionService._ensure_tables берёт sf.kw["bind"],
    # иначе create_all уходит в get_engine() → dev stand на :5432 (COS-078).
    maker = async_sessionmaker(bind=engine, expire_on_commit=False)
    sync_engine = create_engine(_testpg.psycopg2_url(_scratch))

    # Изоляция: recover() в _start_core читает ВСЕ не-terminal строки
    # handle-таблицы — остатки предыдущих тестов стали бы «зомби»-ручками
    # и съели очередь статусов FakeWoodpecker текущего теста.
    from sqlalchemy import text
    async with maker() as s:
        await s.execute(text("DELETE FROM cosmo_execution_handles"))
        await s.commit()

    def sync_factory():
        from sqlalchemy.orm import Session
        return Session(bind=sync_engine, autoflush=False, autocommit=False)

    yield {"maker": maker, "sync_factory": sync_factory, "engine": engine}
    await engine.dispose()
    sync_engine.dispose()


# ── Seed helpers (уникальные id per-test: module-scoped scratch) ──


async def _seed_plan_with_run(maker, *, batches: int = 1,
                              status: str = "running",
                              binding: str | None = None) -> dict:
    tag = uuid.uuid4().hex[:8]
    ids = {
        "domain": f"dom-{tag}",
        "plan": f"plan-{tag}",
        "run": f"run-{tag}",
        "batches": [f"batch-{tag}-{i}" for i in range(batches)],
    }
    async with maker() as s:
        s.add(Domain(id=ids["domain"], label=f"Domain {tag}",
                     forge_url="https://git.example.local",
                     forge_token_ref=f"ref/forge-{tag}"))
        # apps ↔ pipeline_plans — циклическая FK: app сначала без plan-link.
        s.add(Application(id=f"app-{tag}", domain_id=ids["domain"], level=0))
        await s.flush()
        s.add(PipelinePlan(id=ids["plan"], app_id=f"app-{tag}",
                           level="app", scope_id=f"scope-{tag}",
                           compiled_hash=f"hash-{tag}"))
        await s.flush()
        if binding:
            s.add(RepositoryBinding(id=f"bind-{tag}", app_id=f"app-{tag}",
                                    forge_id=f"forge-{tag}",
                                    repo_path=binding, default_branch="main"))
        s.add(RunORM(id=ids["run"], plan_id=ids["plan"], trigger="manual",
                     domain_id=ids["domain"], status=status))
        for bid in ids["batches"]:
            s.add(BatchORM(id=bid, plan_id=ids["plan"], type="build",
                           status="pending", bricks_refs=[], artifacts=[],
                           evidence_refs=[]))
        await s.commit()
    return ids


async def _get_run(maker, run_id: str) -> RunORM:
    async with maker() as s:
        return await s.get(RunORM, run_id)


async def _get_batch(maker, batch_id: str) -> BatchORM:
    async with maker() as s:
        return await s.get(BatchORM, batch_id)


async def _handle_row(maker, batch_id: str) -> dict | None:
    from sqlalchemy import select
    async with maker() as s:
        row = (await s.execute(
            select(ExecutionHandleRow).where(
                ExecutionHandleRow.batch_id == batch_id)
        )).scalars().first()
        if row is None:
            return None
        return {
            "batch_id": row.batch_id, "run_id": row.run_id,
            "last_status": row.last_status, "degraded": row.degraded,
            "reason": row.reason, "unknown_count": row.unknown_count,
            "evidence_error": row.evidence_error,
            "repo_owner": row.repo_owner, "repo_name": row.repo_name,
            "wp_number": row.wp_number, "branch": row.branch,
        }


def _make_service(env, adapter, *, degraded_threshold=3) -> ExecutionService:
    return ExecutionService(
        env["maker"],
        adapter=adapter,
        poll_interval=0.05,
        degraded_threshold=degraded_threshold,
        repo_owner="fallback-owner",
        repo_name="fallback-repo",
        sync_session_factory=env["sync_factory"],
    )


async def _drain(loop_cycles: int = 8) -> None:
    """Дать запланированным через run_coroutine_threadsafe корутинам доехать."""
    for _ in range(loop_cycles):
        await asyncio.sleep(0.05)


# ── Tests ──


class TestSubmitViaService:
    async def test_submit_persists_durable_handle(self, env):
        """Run → running: handle в PG, binding-repo резолвится, batch running."""
        ids = await _seed_plan_with_run(
            env["maker"], batches=1, binding="bindowner/bindrepo")
        adapter = FakeWoodpecker()
        svc = _make_service(env, adapter)
        await svc._start_core()
        try:
            await svc._submit_async(ids["run"])
            assert len(adapter.submitted) == 1
            assert adapter.submitted[0]["repo_owner"] == "bindowner"
            assert adapter.submitted[0]["repo_name"] == "bindrepo"

            row = await _handle_row(env["maker"], ids["batches"][0])
            assert row is not None
            assert row["repo_owner"] == "bindowner"
            assert row["wp_number"] == 1
            assert row["last_status"] == "running"
            assert row["degraded"] is False
        finally:
            await svc.stop()

    async def test_resubmit_guard_skips_inflight(self, env):
        """Повторный submit (двойной PATCH running) не создаёт второй pipeline."""
        ids = await _seed_plan_with_run(env["maker"], batches=1)
        adapter = FakeWoodpecker()
        svc = _make_service(env, adapter)
        await svc._start_core()
        try:
            await svc._submit_async(ids["run"])
            await svc._submit_async(ids["run"])  # повтор
            assert len(adapter.submitted) == 1
        finally:
            await svc.stop()

    async def test_submit_skips_non_running_run(self, env):
        ids = await _seed_plan_with_run(env["maker"], batches=1, status="pending")
        adapter = FakeWoodpecker()
        svc = _make_service(env, adapter)
        await svc._start_core()
        try:
            await svc._submit_async(ids["run"])
            assert adapter.submitted == []
        finally:
            await svc.stop()


class TestLiveCycleHonesty:
    async def test_success_writes_real_evidence_and_finalizes(self, env):
        """Accept: прогон → статус/логи → evidence с реальным digest → succeeded."""
        ids = await _seed_plan_with_run(env["maker"], batches=1)
        adapter = FakeWoodpecker(
            statuses={"1": ["running", "success"]})
        svc = _make_service(env, adapter)
        await svc._start_core()
        try:
            await svc._submit_async(ids["run"])
            await asyncio.to_thread(svc._executor.poll)   # running
            await asyncio.to_thread(svc._executor.poll)   # success + evidence + finalize
            await _drain()

            batch = await _get_batch(env["maker"], ids["batches"][0])
            assert batch.status == "passed"
            run = await _get_run(env["maker"], ids["run"])
            assert run.status == "succeeded"
            assert run.finished_at is not None

            # Evidence: тип log, SHA-256 от РЕАЛЬНЫХ логов адаптера
            from sqlalchemy import select
            async with env["maker"]() as s:
                rows = (await s.execute(
                    select(EvidenceLedgerEntry).where(
                        EvidenceLedgerEntry.run_id == ids["run"])
                )).scalars().all()
            assert len(rows) == 1
            ev = rows[0]
            expected_digest, _ = svc._logs_digest({"scan": ["line-1", "line-2"]})
            assert ev.content_hash == expected_digest
            assert ev.type == "log"
            assert ev.provenance_json["source"] == "woodpecker"
            assert ev.provenance_json["degraded"] is False
            assert batch.evidence_refs == [ev.id]

            row = await _handle_row(env["maker"], ids["batches"][0])
            assert row["last_status"] == "success"
        finally:
            await svc.stop()

    async def test_sustained_unknown_degrades_honestly(self, env):
        """Honesty: 3 подряд unknown → degraded terminal, НЕ PASS.

        batch failed, run failed, alert-evidence в ledger, durable-след
        degraded=True с причиной. Никакого выдуманного succeeded.
        """
        ids = await _seed_plan_with_run(env["maker"], batches=1)
        adapter = FakeWoodpecker(fail_poll=True)  # каждый poll — транспортный сбой
        svc = _make_service(env, adapter, degraded_threshold=3)
        await svc._start_core()
        try:
            await svc._submit_async(ids["run"])

            await asyncio.to_thread(svc._executor.poll)
            await _drain()
            run = await _get_run(env["maker"], ids["run"])
            assert run.status == "running"  # ещё не деградировал
            row = await _handle_row(env["maker"], ids["batches"][0])
            assert row["unknown_count"] == 1

            await asyncio.to_thread(svc._executor.poll)
            await asyncio.to_thread(svc._executor.poll)  # threshold достигнут
            await _drain()

            batch = await _get_batch(env["maker"], ids["batches"][0])
            assert batch.status == "failed"
            run = await _get_run(env["maker"], ids["run"])
            assert run.status == "failed"

            row = await _handle_row(env["maker"], ids["batches"][0])
            assert row["degraded"] is True
            assert "execution degraded" in (row["reason"] or "")

            # Честный след в tamper-evident ledger: alert-запись
            from sqlalchemy import select
            async with env["maker"]() as s:
                alerts = (await s.execute(
                    select(EvidenceLedgerEntry).where(
                        EvidenceLedgerEntry.run_id == ids["run"])
                )).scalars().all()
            assert len(alerts) == 1
            assert alerts[0].type == "alert"
            assert alerts[0].provenance_json["degraded"] is True
            assert "execution degraded" in alerts[0].provenance_json["reason"]
        finally:
            await svc.stop()

    async def test_declined_maps_to_blocked(self, env):
        """v3.5 declined (отклонён/ждёт approval) → batch blocked → run blocked."""
        ids = await _seed_plan_with_run(env["maker"], batches=1)
        adapter = FakeWoodpecker(statuses={"1": ["declined"]})
        svc = _make_service(env, adapter)
        await svc._start_core()
        try:
            await svc._submit_async(ids["run"])
            await asyncio.to_thread(svc._executor.poll)
            await _drain()

            batch = await _get_batch(env["maker"], ids["batches"][0])
            assert batch.status == "blocked"
            run = await _get_run(env["maker"], ids["run"])
            assert run.status == "blocked"
        finally:
            await svc.stop()

    async def test_skipped_is_not_pass(self, env):
        """v3.5 skipped: прогон не выполнялся — PASS выдумать нельзя.

        batch failed (не passed); run — blocked (парити finalize COS-046:
        batch failure без degraded → blocked, не выдуманный succeeded).
        """
        ids = await _seed_plan_with_run(env["maker"], batches=1)
        adapter = FakeWoodpecker(statuses={"1": ["skipped"]})
        svc = _make_service(env, adapter)
        await svc._start_core()
        try:
            await svc._submit_async(ids["run"])
            await asyncio.to_thread(svc._executor.poll)
            await _drain()

            batch = await _get_batch(env["maker"], ids["batches"][0])
            assert batch.status == "failed"
            run = await _get_run(env["maker"], ids["run"])
            assert run.status == "blocked"
        finally:
            await svc.stop()


class TestRestartSurvival:
    async def test_restart_does_not_lose_run(self, env):
        """Accept: рестарт cosmo-api не теряет факт прогона.

        Service A: submit → стоп (эмуляция рестарта). Service B на той же
        БД: recover() возвращает ручку в poll → прогон доигрывается до
        succeeded с evidence.
        """
        ids = await _seed_plan_with_run(env["maker"], batches=1)
        adapter = FakeWoodpecker(statuses={"1": ["success"]})
        svc_a = _make_service(env, adapter)
        await svc_a._start_core()
        await svc_a._submit_async(ids["run"])
        await svc_a.stop()  # ← «рестарт»

        # Ничего не потеряно: durable-след живёт в PG
        row = await _handle_row(env["maker"], ids["batches"][0])
        assert row is not None
        assert row["last_status"] == "running"

        svc_b = _make_service(env, adapter)
        await svc_b._start_core()  # recover() внутри
        try:
            assert len(svc_b.active_batches()) == 1
            await asyncio.to_thread(svc_b._executor.poll)
            await _drain()

            run = await _get_run(env["maker"], ids["run"])
            assert run.status == "succeeded"
            batch = await _get_batch(env["maker"], ids["batches"][0])
            assert batch.status == "passed"
            from sqlalchemy import select
            async with env["maker"]() as s:
                evs = (await s.execute(
                    select(EvidenceLedgerEntry).where(
                        EvidenceLedgerEntry.run_id == ids["run"])
                )).scalars().all()
            assert len(evs) == 1
        finally:
            await svc_b.stop()

    async def test_terminal_rows_not_recovered(self, env):
        ids = await _seed_plan_with_run(env["maker"], batches=1)
        adapter = FakeWoodpecker(statuses={"1": ["success"]})
        svc_a = _make_service(env, adapter)
        await svc_a._start_core()
        await svc_a._submit_async(ids["run"])
        await asyncio.to_thread(svc_a._executor.poll)
        await _drain()
        await svc_a.stop()

        svc_b = _make_service(env, adapter)
        await svc_b._start_core()
        try:
            assert svc_b.active_batches() == {}
        finally:
            await svc_b.stop()


class TestCancelAndEvidenceFailure:
    async def test_cancel_marks_durable_trace(self, env):
        ids = await _seed_plan_with_run(env["maker"], batches=1)
        adapter = FakeWoodpecker()
        svc = _make_service(env, adapter)
        await svc._start_core()
        try:
            await svc._submit_async(ids["run"])
            await svc.cancel_run(ids["run"])

            batch = await _get_batch(env["maker"], ids["batches"][0])
            assert batch.status == "blocked"
            row = await _handle_row(env["maker"], ids["batches"][0])
            assert row["last_status"] == "cancelled"
            assert len(adapter.cancelled) == 1
        finally:
            await svc.stop()

    async def test_evidence_failure_is_visible_not_fatal(self, env):
        """Фейл evidence не роняет poll-цикл и фиксируется в durable-следе."""
        ids = await _seed_plan_with_run(env["maker"], batches=1)
        adapter = FakeWoodpecker(statuses={"1": ["success"]})

        def broken_sink(run_id, batch_id, logs, meta):
            raise RuntimeError("evidence backend down")

        svc = _make_service(env, adapter)
        svc._executor._evidence_sink = broken_sink
        await svc._start_core()
        try:
            await svc._submit_async(ids["run"])
            await asyncio.to_thread(svc._executor.poll)
            await _drain()

            batch = await _get_batch(env["maker"], ids["batches"][0])
            assert batch.status == "passed"  # цикл не сломан
            row = await _handle_row(env["maker"], ids["batches"][0])
            assert "evidence backend down" in (row["evidence_error"] or "")
        finally:
            await svc.stop()


class TestPollLoopIntegration:
    """Полный lifecycle с фоновым poll-лупом (как в бою, COSMO_EXECUTOR_ENABLED)."""

    async def test_background_loop_drives_run_to_succeeded(self, env):
        ids = await _seed_plan_with_run(env["maker"], batches=1)
        adapter = FakeWoodpecker(
            statuses={"1": ["running", "running", "success"]})
        svc = _make_service(env, adapter)
        await svc.start()  # фоновый poll каждые 0.05s
        try:
            await svc._submit_async(ids["run"])
            # Ждём, пока фоновый цикл сам доиграет прогон до finalize.
            deadline = asyncio.get_running_loop().time() + 10.0
            run_status = "running"
            while asyncio.get_running_loop().time() < deadline:
                run = await _get_run(env["maker"], ids["run"])
                run_status = run.status
                if run_status in ("succeeded", "failed", "blocked", "cancelled"):
                    break
                await asyncio.sleep(0.1)

            assert run_status == "succeeded"
            batch = await _get_batch(env["maker"], ids["batches"][0])
            assert batch.status == "passed"
        finally:
            await svc.stop()


class TestRcpDegradedBranch:
    """COS-097: RCP потребляет честный degraded — FAILED/INFRA, не BLOCKED."""

    def _make_rcp_with_degraded_executor(self) -> tuple[RunControlPlane, RunRecord, BatchExecutor]:
        statuses: dict[str, str] = {}
        executor = BatchExecutor(
            adapter=MagicMock(), dry_run=False, degraded_threshold=3)
        executor._query_batches = MagicMock(
            return_value=[{"id": "batch-build", "plan_id": "p",
                           "type": "build", "status": "pending",
                           "bricks": [], "artifacts": []}])
        executor._update_batch_pg = MagicMock()
        executor._update_batch_pg_terminal = MagicMock(
            side_effect=lambda bid, st: statuses.__setitem__(bid, st))
        executor._get_batch_pg_status = MagicMock(
            side_effect=lambda bid: statuses.get(bid, "pending"))
        executor._status_override["batch-build"] = "unknown"

        c = RunControlPlane()
        c.register_worker("w1", frozenset({"dast"}))
        c.set_executor(executor)

        run, _ = c.create_run({"plan_id": "p", "domain_id": "d"},
                              frozenset({"dast"}))
        c.submit_run(run.id)
        c.enqueue_run(run.id)
        assert run.state == RunState.RUNNING

        # COS-097 wiring: RCP вызывает submit при входе в RUNNING — здесь
        # синхронно, чтобы _run_plans/_run_batches были заполнены как в бою.
        run_like = SimpleNamespace(id=run.id, plan_id="p", domain_id="d")
        executor.submit_batches(run_like)
        return c, run, executor

    def test_degraded_run_fails_with_infra_class(self):
        c, run, executor = self._make_rcp_with_degraded_executor()

        for _ in range(3):  # threshold
            executor.poll()

        assert run.state == RunState.FAILED
        assert run.failure_class == FailureClass.INFRA
        assert "execution degraded" in (run.error or "")
        # consume-once: повторный вызов причины не возвращает
        assert executor.pop_degraded_reason(run.id) is None

    def test_batch_failure_without_degraded_stays_blocked(self):
        """Parity COS-046: обычный batch failure → BLOCKED/GATE (не сломан)."""
        c, run, executor = self._make_rcp_with_degraded_executor()
        executor._status_override["batch-build"] = "failure"

        executor.poll()

        assert run.state == RunState.BLOCKED
        assert run.failure_class == FailureClass.GATE
        assert run.error == "batch execution failed"
