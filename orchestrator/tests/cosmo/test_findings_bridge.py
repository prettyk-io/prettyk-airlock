# -*- coding: utf-8 -*-
"""COS-101: Мост Findings ↔ Quality Gates против real PostgreSQL.

Покрывает:
  1. Нормализацию severity: сканеры пишут в любом регистре, gate engine
     ожидает канон Critical|High|Medium|Low|Info.
  2. PgFindingsProvider: run_id → findings из runs.findings_refs,
     fail-open (ошибка чтения/несуществующий run → [], не raise).
  3. attach_findings: валидация severity, append в канонический носитель.
  4. Gate hook в ExecutionService.finalize_run: gate block по РЕАЛЬНЫМ
     findings → run blocked (parity RCP COS-055); ошибка engine —
     fail-open; bridge off (конструктор) — hook инертен.
  5. API ingest POST /api/v1/runs/{run_id}/findings (scan-сторона моста):
     201 + персистенция, 422 на невалидный severity, 404 на ghost run.

Repo-контур — scratch-БД test PG :5433 (COS-073/078), API-контур — общий
pg_client (conftest).
"""
from __future__ import annotations

import sys
import uuid
from pathlib import Path
from urllib.parse import urlsplit

import pytest
import pytest_asyncio

import _testpg

_repo = Path(__file__).resolve().parents[3]
_orch = Path(__file__).resolve().parents[2]
for p in (str(_repo), str(_orch)):
    if p not in sys.path:
        sys.path.insert(0, p)

from orchestrator.cosmo.control_plane.findings_bridge import (  # noqa: E402
    PgFindingsProvider,
    attach_findings,
    normalize_finding,
    normalize_severity,
)
from orchestrator.cosmo.control_plane.execution_service import ExecutionService  # noqa: E402
from orchestrator.cosmo.db.models import (  # noqa: E402
    Application,
    Batch as BatchORM,
    Domain,
    EvidenceLedgerEntry,
    Gate as GateORM,
    PipelinePlan,
    Run as RunORM,
)
from sqlalchemy import select  # noqa: E402

SCRATCH_DB = _testpg.scratch_name("findings_bridge")
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


# ── Fixtures (паттерн test_execution_service) ──


@pytest.fixture(scope="module")
def _scratch():
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
    from orchestrator.cosmo.db.models_execution import ExecutionBase
    CosmoBase.metadata.create_all(engine)
    # Side-таблицы cosmo_execution_* — отдельный ExecutionBase
    # (см. models_transfer, COS-070).
    ExecutionBase.metadata.create_all(engine)
    engine.dispose()
    yield SCRATCH_DB
    _drop()


@pytest_asyncio.fixture()
async def env(_scratch):
    from sqlalchemy import create_engine
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    engine = create_async_engine(_async_url(_scratch))
    # bind обязателен: ExecutionService._ensure_tables берёт sf.kw["bind"],
    # иначе create_all уходит в get_engine() → dev stand :5432 (COS-078).
    maker = async_sessionmaker(bind=engine, expire_on_commit=False)
    sync_engine = create_engine(_testpg.psycopg2_url(_scratch))

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


async def _seed_plan_with_run(maker, *, findings: list[dict] | None = None,
                              status: str = "running") -> dict:
    tag = uuid.uuid4().hex[:8]
    ids = {"domain": f"dom-{tag}", "plan": f"plan-{tag}", "run": f"run-{tag}"}
    async with maker() as s:
        s.add(Domain(id=ids["domain"], label=f"Domain {tag}",
                     forge_url="https://git.example.local",
                     forge_token_ref=f"ref/forge-{tag}"))
        s.add(Application(id=f"app-{tag}", domain_id=ids["domain"], level=0))
        await s.flush()
        s.add(PipelinePlan(id=ids["plan"], app_id=f"app-{tag}",
                           level="app", scope_id=f"scope-{tag}",
                           compiled_hash=f"hash-{tag}"))
        await s.flush()
        s.add(RunORM(id=ids["run"], plan_id=ids["plan"], trigger="manual",
                     domain_id=ids["domain"], status=status,
                     findings_refs=list(findings or [])))
        await s.commit()
    return ids


async def _seed_gate(maker, plan_id: str, policy: dict,
                     *, gate_type: str = "automatic") -> str:
    tag = uuid.uuid4().hex[:8]
    gid = f"gate-{tag}"
    async with maker() as s:
        s.add(GateORM(id=gid, plan_id=plan_id, type=gate_type, position=0,
                      policy_json=policy))
        await s.commit()
    return gid


def _make_service(env, *, gate_bridge: bool | None = None) -> ExecutionService:
    class _NoAdapter:
        def generate_pipeline_yaml(self, batch):
            return "steps: {}"

    return ExecutionService(
        env["maker"],
        adapter=_NoAdapter(),
        poll_interval=0.05,
        repo_owner="fallback-owner",
        repo_name="fallback-repo",
        sync_session_factory=env["sync_factory"],
        gate_bridge=gate_bridge,
    )


# ── Нормализация severity ──


class TestNormalizeSeverity:
    def test_case_insensitive_canon(self):
        assert normalize_severity("critical") == "Critical"
        assert normalize_severity("CRITICAL") == "Critical"
        assert normalize_severity("High") == "High"
        assert normalize_severity(" low ") == "Low"

    def test_info(self):
        assert normalize_severity("INFO") == "Info"

    def test_unknown_passthrough(self):
        assert normalize_severity("P1") == "P1"
        assert normalize_severity("") == ""

    def test_non_string(self):
        assert normalize_severity(None) == ""
        assert normalize_severity(3) == ""

    def test_normalize_finding_does_not_mutate_input(self):
        f = {"severity": "high", "title": "t"}
        out = normalize_finding(f)
        assert out["severity"] == "High"
        assert f["severity"] == "high"


# ── PgFindingsProvider ──


class TestPgFindingsProvider:
    async def test_reads_and_normalizes(self, env):
        ids = await _seed_plan_with_run(env["maker"], findings=[
            {"severity": "critical", "title": "SQLi", "cwe_ids": ["CWE-89"]},
            {"severity": "High", "title": "XSS"},
        ])
        provider = PgFindingsProvider(env["maker"])
        got = await provider(ids["run"])
        assert [f["severity"] for f in got] == ["Critical", "High"]
        assert got[0]["title"] == "SQLi"

    async def test_missing_run_fail_open(self, env):
        provider = PgFindingsProvider(env["maker"])
        assert await provider("run-ghost") == []

    async def test_empty_refs(self, env):
        ids = await _seed_plan_with_run(env["maker"])
        provider = PgFindingsProvider(env["maker"])
        assert await provider(ids["run"]) == []

    async def test_non_dict_entries_skipped(self, env):
        ids = await _seed_plan_with_run(env["maker"], findings=[
            "garbage-string",
            {"severity": "medium", "title": "ok"},
        ])
        provider = PgFindingsProvider(env["maker"])
        got = await provider(ids["run"])
        assert len(got) == 1
        assert got[0]["severity"] == "Medium"


# ── attach_findings (unit-уровень) ──


class TestAttachFindings:
    async def test_append_and_total(self, env):
        ids = await _seed_plan_with_run(env["maker"], findings=[
            {"severity": "low", "title": "old"}])
        total = await attach_findings(env["maker"], ids["run"], [
            {"severity": "CRITICAL", "title": "new"}])
        assert total == 2
        provider = PgFindingsProvider(env["maker"])
        got = await provider(ids["run"])
        assert [f["severity"] for f in got] == ["Low", "Critical"]

    async def test_bad_severity_rejected(self, env):
        ids = await _seed_plan_with_run(env["maker"])
        with pytest.raises(ValueError, match="severity"):
            await attach_findings(env["maker"], ids["run"], [
                {"severity": "wat", "title": "x"}])

    async def test_missing_severity_rejected(self, env):
        ids = await _seed_plan_with_run(env["maker"])
        with pytest.raises(ValueError, match="severity"):
            await attach_findings(env["maker"], ids["run"], [
                {"title": "no severity"}])

    async def test_missing_run_lookup_error(self, env):
        with pytest.raises(LookupError):
            await attach_findings(env["maker"], "run-ghost", [
                {"severity": "high", "title": "x"}])

    async def test_empty_payload_rejected(self, env):
        ids = await _seed_plan_with_run(env["maker"])
        with pytest.raises(ValueError, match="empty"):
            await attach_findings(env["maker"], ids["run"], [])


# ── Gate hook в finalize_run ──


class TestFinalizeGateBridge:
    async def test_critical_finding_blocks_passed_run(self, env):
        """Все batch'и passed, но Critical finding в runs.findings_refs →
        gate (Critical→block) блокирует прогон: parity RCP COS-055."""
        ids = await _seed_plan_with_run(env["maker"], findings=[
            {"severity": "critical", "title": "SQLi"}])
        await _seed_gate(env["maker"], ids["plan"], {
            "rules": [{"finding_type": "Critical", "action": "block"}]})
        svc = _make_service(env)
        await svc._start_core()
        await svc.finalize_run(ids["run"], all_passed=True)
        run = (await _seeded_run(env, ids["run"]))
        assert run.status == "blocked"

    async def test_medium_finding_passes_high_block_policy(self, env):
        ids = await _seed_plan_with_run(env["maker"], findings=[
            {"severity": "medium", "title": "ok"}])
        await _seed_gate(env["maker"], ids["plan"], {
            "rules": [{"finding_type": "High", "action": "block"}]})
        svc = _make_service(env)
        await svc._start_core()
        await svc.finalize_run(ids["run"], all_passed=True)
        run = await _seeded_run(env, ids["run"])
        assert run.status == "succeeded"

    async def test_no_gates_succeeds_with_findings(self, env):
        ids = await _seed_plan_with_run(env["maker"], findings=[
            {"severity": "critical", "title": "SQLi"}])
        svc = _make_service(env)
        await svc._start_core()
        await svc.finalize_run(ids["run"], all_passed=True)
        run = await _seeded_run(env, ids["run"])
        assert run.status == "succeeded"

    async def test_engine_error_fail_open(self, env):
        """Сломанный sync-factory у engine → fail-open, прогон не блокируется."""
        ids = await _seed_plan_with_run(env["maker"], findings=[
            {"severity": "critical", "title": "SQLi"}])
        await _seed_gate(env["maker"], ids["plan"], {
            "rules": [{"finding_type": "Critical", "action": "block"}]})
        svc = _make_service(env)

        def broken_factory():
            raise RuntimeError("pg down")

        svc.set_gate_bridge(
            _make_engine(broken_factory), PgFindingsProvider(env["maker"]))
        await svc._start_core()
        await svc.finalize_run(ids["run"], all_passed=True)
        run = await _seeded_run(env, ids["run"])
        assert run.status == "succeeded"

    async def test_bridge_disabled_constructor(self, env):
        """gate_bridge=False: findings + блокирующая политика игнорируются."""
        ids = await _seed_plan_with_run(env["maker"], findings=[
            {"severity": "critical", "title": "SQLi"}])
        await _seed_gate(env["maker"], ids["plan"], {
            "rules": [{"finding_type": "Critical", "action": "block"}]})
        svc = _make_service(env, gate_bridge=False)
        await svc._start_core()
        assert svc._gate_engine is None
        await svc.finalize_run(ids["run"], all_passed=True)
        run = await _seeded_run(env, ids["run"])
        assert run.status == "succeeded"

    async def test_degraded_still_failed_over_gate(self, env):
        """Honesty COS-097 сохраняется: degraded → failed, даже когда
        gate-политика заблокировала бы (gate hook не вызывается)."""
        ids = await _seed_plan_with_run(env["maker"], findings=[
            {"severity": "critical", "title": "SQLi"}])
        await _seed_gate(env["maker"], ids["plan"], {
            "rules": [{"finding_type": "Critical", "action": "block"}]})
        svc = _make_service(env)
        await svc._start_core()
        # имитируем sustained-unknown след executor'а (канон COS-097:
        # pop_degraded_reason читает из _degraded_reasons)
        svc._executor._degraded_reasons[ids["run"]] = (
            "woodpecker unreachable: 3 consecutive poll errors")
        await svc.finalize_run(ids["run"], all_passed=True)
        run = await _seeded_run(env, ids["run"])
        assert run.status == "failed"

    # ── SAST-GATE-3: durable решение + терминальная честность ──

    async def test_gate_block_writes_durable_decision_evidence(self, env):
        """SAST-GATE-3: gate block → evidence type=decision с решениями гейтов."""
        ids = await _seed_plan_with_run(env["maker"], findings=[
            {"severity": "critical", "title": "SQLi"}])
        gate_id = await _seed_gate(env["maker"], ids["plan"], {
            "rules": [{"finding_type": "Critical", "action": "block"}]})
        svc = _make_service(env)
        await svc._start_core()
        await svc.finalize_run(ids["run"], all_passed=True)
        run = await _seeded_run(env, ids["run"])
        assert run.status == "blocked"

        async with env["maker"]() as s:
            rows = (await s.execute(
                select(EvidenceLedgerEntry).where(
                    EvidenceLedgerEntry.run_id == ids["run"],
                    EvidenceLedgerEntry.type == "decision")
            )).scalars().all()
        assert len(rows) == 1
        provenance = rows[0].provenance_json
        assert provenance["source"] == "cosmo-gate"
        assert provenance["decisions"] == {gate_id: "block"}

    async def test_missing_sast_report_terminates_run(self, env):
        """SAST-GATE-3: sast-кирпич без маркера отчёта → degraded → failed.

        Отсутствие обязательного evidence не маскируется: alert-след сохранён,
        финализация даёт терминальный failed (не тихий PASS).
        """
        ids = await _seed_plan_with_run(env["maker"])
        batch_id = f"b-sast-{uuid.uuid4().hex[:6]}"
        async with env["maker"]() as s:
            s.add(BatchORM(id=batch_id, plan_id=ids["plan"], type="static_scan",
                           status="passed",
                           bricks_refs=[{"name": "sast-brick", "type": "sast",
                                         "definition": {}}]))
            await s.commit()

        svc = _make_service(env)
        async with env["maker"]() as s:
            batch = await s.get(BatchORM, batch_id)
            await svc._capture_sast_reports(s, ids["run"], batch, {})
        assert svc._executor.degraded_reason(ids["run"])  # хук выставил причину

        async with env["maker"]() as s:
            alerts = (await s.execute(
                select(EvidenceLedgerEntry).where(
                    EvidenceLedgerEntry.run_id == ids["run"],
                    EvidenceLedgerEntry.type == "alert")
            )).scalars().all()
        assert len(alerts) == 1

        await svc.finalize_run(ids["run"], all_passed=True)
        run = await _seeded_run(env, ids["run"])
        assert run.status == "failed"

    async def test_sast_report_auto_ingested_to_findings(self, env, monkeypatch, tmp_path):
        """SAST-GATE-3: валидный отчёт из логов → findings прогона (мост), идемпотентно."""
        import json as _json

        import orchestrator.cosmo.control_plane.sast_capture as sast_capture_mod
        from orchestrator.cosmo.domain.sast_report import emit_sast_report_marker

        monkeypatch.setattr(sast_capture_mod, "SAST_EVIDENCE_BASE_DIR", str(tmp_path))

        report = _json.dumps({"total": 1, "issues": [{
            "key": "AX-1", "rule": "javascript:S2077", "severity": "BLOCKER",
            "component": "cosmo__sast-fixture:src/db.js", "line": 42,
            "message": "SQL injection", "tags": ["cwe-89"],
        }]}).encode("utf-8")
        line = emit_sast_report_marker(report, fmt="ce-issues")

        ids = await _seed_plan_with_run(env["maker"])
        batch_id = f"b-sast-{uuid.uuid4().hex[:6]}"
        async with env["maker"]() as s:
            s.add(BatchORM(id=batch_id, plan_id=ids["plan"], type="static_scan",
                           status="passed",
                           bricks_refs=[{"name": "sast-brick", "type": "sast",
                                         "definition": {}}]))
            await s.commit()

        svc = _make_service(env)
        async with env["maker"]() as s:
            batch = await s.get(BatchORM, batch_id)
            await svc._capture_sast_reports(
                s, ids["run"], batch, {"sonar-report": [line]})

        run = await _seeded_run(env, ids["run"])
        assert len(run.findings_refs) == 1
        finding = run.findings_refs[0]
        assert finding["severity"] == "Critical"  # BLOCKER → канон Critical
        assert finding["file_path"] == "src/db.js"

        # Повторный захват того же отчёта → дедуп, без дублей.
        async with env["maker"]() as s:
            batch = await s.get(BatchORM, batch_id)
            await svc._capture_sast_reports(
                s, ids["run"], batch, {"sonar-report": [line]})
        run = await _seeded_run(env, ids["run"])
        assert len(run.findings_refs) == 1


def _make_engine(sync_factory):
    from orchestrator.cosmo.control_plane.gate_engine import GatePolicyEngine
    return GatePolicyEngine(sync_factory)


async def _seeded_run(env, run_id: str) -> RunORM:
    async with env["maker"]() as s:
        return await s.get(RunORM, run_id)


# ── API ingest (scan-сторона моста) ──


class TestIngestEndpoint:
    async def test_attach_via_api_201(self, pg_client):
        tag = uuid.uuid4().hex[:8]
        run_id, domain_id = f"run-{tag}", f"dom-{tag}"
        plan_id = f"plan-{tag}"
        from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
        engine = create_async_engine(_testpg.TEST_PG_URL, echo=False)
        maker = async_sessionmaker(bind=engine, expire_on_commit=False)
        try:
            async with maker() as s:
                s.add(Domain(id=domain_id, label=f"D {tag}",
                             forge_url="https://git.example.local",
                             forge_token_ref=f"ref/{tag}"))
                s.add(Application(id=f"app-{tag}", domain_id=domain_id,
                                  level=0))
                await s.flush()
                s.add(PipelinePlan(id=plan_id, app_id=f"app-{tag}",
                                   level="app", scope_id=f"sc-{tag}",
                                   compiled_hash=f"h-{tag}"))
                await s.flush()
                s.add(RunORM(id=run_id, plan_id=plan_id, trigger="manual",
                             domain_id=domain_id, status="running"))
                await s.commit()
        finally:
            await engine.dispose()

        res = await pg_client.post(f"/api/v1/runs/{run_id}/findings", json={
            "findings": [
                {"severity": "critical", "title": "RCE",
                 "cwe_ids": ["CWE-78"], "rule_id": "SAST-1"},
                {"severity": "low", "title": "info leak"},
            ]})
        assert res.status_code == 201, res.text
        body = res.json()
        assert body["attached"] == 2
        assert body["total"] == 2

        # persisted + normalized (unit-check через прямой engine)
        from sqlalchemy.ext.asyncio import create_async_engine as _cae
        e2 = _cae(_testpg.TEST_PG_URL, echo=False)
        try:
            m2 = async_sessionmaker(bind=e2, expire_on_commit=False)
            async with m2() as s:
                run = await s.get(RunORM, run_id)
                sevs = [f["severity"] for f in run.findings_refs]
                assert sevs == ["Critical", "Low"]
        finally:
            await e2.dispose()

    async def test_invalid_severity_422(self, pg_client):
        tag = uuid.uuid4().hex[:8]
        run_id, domain_id = f"run-{tag}", f"dom-{tag}"
        plan_id = f"plan-{tag}"
        from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
        engine = create_async_engine(_testpg.TEST_PG_URL, echo=False)
        maker = async_sessionmaker(bind=engine, expire_on_commit=False)
        try:
            async with maker() as s:
                s.add(Domain(id=domain_id, label=f"D {tag}",
                             forge_url="https://git.example.local",
                             forge_token_ref=f"ref/{tag}"))
                s.add(Application(id=f"app-{tag}", domain_id=domain_id,
                                  level=0))
                await s.flush()
                s.add(PipelinePlan(id=plan_id, app_id=f"app-{tag}",
                                   level="app", scope_id=f"sc-{tag}",
                                   compiled_hash=f"h-{tag}"))
                await s.flush()
                s.add(RunORM(id=run_id, plan_id=plan_id, trigger="manual",
                             domain_id=domain_id, status="running"))
                await s.commit()
        finally:
            await engine.dispose()

        res = await pg_client.post(f"/api/v1/runs/{run_id}/findings", json={
            "findings": [{"severity": "catastrophic", "title": "x"}]})
        assert res.status_code == 422
        # ничего не прицепилось
        from sqlalchemy.ext.asyncio import create_async_engine as _cae
        e2 = _cae(_testpg.TEST_PG_URL, echo=False)
        try:
            m2 = async_sessionmaker(bind=e2, expire_on_commit=False)
            async with m2() as s:
                run = await s.get(RunORM, run_id)
                assert run.findings_refs == []
        finally:
            await e2.dispose()

    async def test_ghost_run_404(self, pg_client):
        res = await pg_client.post("/api/v1/runs/run-ghost-404/findings",
                                   json={"findings": [
                                       {"severity": "high", "title": "x"}]})
        assert res.status_code == 404
