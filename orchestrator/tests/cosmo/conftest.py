# -*- coding: utf-8 -*-
"""Cosmoport 2.0 — Shared test fixtures (PostgreSQL-only, no sqlite).

COS-073 contract: tests NEVER touch the dev-stand database (host :5432).
All PG access resolves through _testpg (isolated test PG, host :5433,
db cosmo_test). Stand it up with:

  docker compose -f services/docker-compose.test-pg.yml up -d

Provides pg_client: async httpx client with real PG session, auto-skip if
the test PG is down. Each test gets its own engine — no global engine race.

Usage:
  async def test_something(pg_client: AsyncClient):
      r = await pg_client.get("/api/v1/domains")
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

# COS-073: resolve the test PG URL FIRST — importing _testpg enforces the
# guard (refuses any URL pointing at the dev-stand port 5432) and then we
# FORCE COSMO_DATABASE_URL to the test PG so product modules (session.py,
# migration verifier) bind to the isolated instance in the test process.
# Forced, not setdefault: a COSMO_DATABASE_URL from the outer environment
# (e.g. a gate run against the live stand) must never leak into tests.
import _testpg  # noqa: E402  (test dir is on sys.path)

_PG_URL = _testpg.TEST_PG_URL
_testpg.refuse_dev_stand(_PG_URL)
os.environ["COSMO_DATABASE_URL"] = _PG_URL
os.environ.setdefault("COSMO_ENV", "test")

_orch = Path(__file__).resolve().parents[1]
if str(_orch) not in sys.path:
    sys.path.insert(0, str(_orch))

from orchestrator.cosmo.api.main import app
from orchestrator.cosmo.api.deps import get_db, get_current_principal, require_capability
from orchestrator.cosmo.api.domain_guard import require_domain
from orchestrator.cosmo.db.models import Base as CosmoBase  # noqa: F811
from orchestrator.cosmo.domain.rbac import PrincipalContext, Role

# ══════════════════════════════════════════════════════════════════
# PG availability skip
# ══════════════════════════════════════════════════════════════════

def _pg_available() -> bool:
    return _testpg.pg_available()

_pg_needed = pytest.mark.skipif(
    not _pg_available(),
    reason="test PG unreachable — docker compose -f services/docker-compose.test-pg.yml up -d",
)

# ══════════════════════════════════════════════════════════════════
# COS-075: loop-safe engine reset (per-test loop rebinds the GLOBAL engine)
# ══════════════════════════════════════════════════════════════════

@pytest_asyncio.fixture(scope="function")
async def loop_safe_engine_reset():
    """Reset the GLOBAL async engine/sessionmaker for the CURRENT event loop.

    Product code paths (integration._emit, sse.py get_sessionmaker) use the
    module-level singleton in db.session. The singleton is bound to the loop
    that first created it; each pytest-asyncio test gets a fresh loop, so a
    singleton created by an earlier test dies with that loop — and _emit
    silently swallows the resulting 'Event loop is closed' (outbox stays
    empty). COS-072 acceptance exposed this as isolated-vs-combined
    divergence; COS-075 makes every notification PG fixture reset the
    singleton at setup so it rebinds to the live loop. Notification fixtures
    request this fixture BEFORE creating their own per-test engines.
    """
    from orchestrator.cosmo.db.session import dispose_engine

    await dispose_engine()
    yield

# ══════════════════════════════════════════════════════════════════
# PG client fixture (function-scoped, fresh engine per test)
# ══════════════════════════════════════════════════════════════════

@pytest_asyncio.fixture(scope="function")
async def pg_client():
    """Per-test PG + httpx client. Own engine, clean tables, no global state.

    COS-073: wipes happen ONLY on the isolated test PG (:5433/cosmo_test).
    Teardown после yield повторяет wipe: тестовые данные не переживают
    ни тест, ни сессию — параллельные worker'ы не ловят cross-run
    contamination (и всё это внутри тестового инстанса, dev-стенд не
    получает ни одного DELETE).
    """

    async def _wipe(conn):
        """COS-151: canonical topological wipe (see _wipe_order).

        Nullify circular FKs → ordered DELETE child-before-parent for EVERY
        table with a FK onto runs/releases/apps/deployments. Раньше releases
        удалялись раньше cosmo_deployments, а scan_*/LR-дети
        (scan_findings/scan_evidence/scan_results, release_batches,
        application_teams, application_kits_tags) в порядке отсутствовали —
        первый же FK-violation ронял транзакцию, и строки переживали очистку
        между тестами (фантомы/конфликты). Данные тестов не переживают ни
        тест, ни сессию."""
        from _wipe_order import CIRCULAR_NULLIFY, DELETE_ORDER

        for stmt in CIRCULAR_NULLIFY:
            await conn.exec_driver_sql(stmt)
        for tbl in DELETE_ORDER:
            await conn.exec_driver_sql(f'DELETE FROM "{tbl}"')

    engine = create_async_engine(_PG_URL, echo=False)

    # Ensure tables exist (no-op if already created). COS-081: + gate trail
    # (отдельный GateTrailBase вне frozen alembic-цепочки).
    async with engine.begin() as conn:
        # COS-076: pg_advisory_xact_lock сериализует bootstrap схемы между
        # параллельными pytest-процессами на одном cosmo_test — check-then-
        # create в create_all не атомарен, без лока две сессии ловят
        # каталожную гонку pg_type_typname_nsp_index.
        await conn.execute(text("SELECT pg_advisory_xact_lock(7241965813)"))
        await conn.run_sync(CosmoBase.metadata.create_all)
        from orchestrator.cosmo.db.models_gate_trail import GateTrailBase
        await conn.run_sync(GateTrailBase.metadata.create_all)
        from orchestrator.cosmo.db.models_transfer import TransferRegistryBase
        await conn.run_sync(TransferRegistryBase.metadata.create_all)
        # COS-097/COS-108: execution handles + workspace runs
        from orchestrator.cosmo.db.models_execution import ExecutionBase
        await conn.run_sync(ExecutionBase.metadata.create_all)
        # COS-133: cosmo_workspace_runs predates the rerun-link column and
        # create_all does not ALTER existing tables — heal stale test DBs.
        await conn.exec_driver_sql(
            "ALTER TABLE cosmo_workspace_runs "
            "ADD COLUMN IF NOT EXISTS original_run_id VARCHAR(64)"
        )

    # Clean all tables before the test
    async with engine.begin() as conn:
        await _wipe(conn)
        await conn.commit()

    session_maker = async_sessionmaker(engine, expire_on_commit=False)

    async def _override_get_db():
        async with session_maker() as session:
            try:
                yield session
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db] = _override_get_db

    # COS-032: Override get_current_principal with admin for tests
    async def _get_admin_principal() -> PrincipalContext:
        return PrincipalContext(
            user_id="test-admin", roles=[Role.ADMIN_SEC],
            domain_id="test", zone="zr", is_system_admin=True,
        )
    app.dependency_overrides[get_current_principal] = _get_admin_principal

    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac
    finally:
        app.dependency_overrides.clear()
        # Teardown: тестовые данные (включая домены 'test'/'alpha') не
        # остаются в тестовом PG после последнего теста сессии.
        try:
            async with engine.begin() as conn:
                await _wipe(conn)
                await conn.commit()
        except Exception:
            pass  # teardown не маскирует результат теста, но и не шумит
        await engine.dispose()