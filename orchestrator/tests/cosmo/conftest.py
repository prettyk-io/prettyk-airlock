# -*- coding: utf-8 -*-
"""Cosmoport 2.0 — Shared test fixtures (PostgreSQL-only, no sqlite).

Provides pg_client: async httpx client with real PG session, auto-skip if PG down.
Each test gets its own engine — no global engine race.

Usage:
  async def test_something(pg_client: AsyncClient):
      r = await pg_client.get("/api/v1/domains")
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

_orch = Path(__file__).resolve().parents[1]
if str(_orch) not in sys.path:
    sys.path.insert(0, str(_orch))

from orchestrator.cosmo.api.main import app
from orchestrator.cosmo.api.deps import get_db
from orchestrator.cosmo.db.models import Base as CosmoBase  # noqa: F811

_PG_URL = "postgresql+asyncpg://cosmo:cosmo@localhost:5432/cosmo"

# ══════════════════════════════════════════════════════════════════
# PG availability skip
# ══════════════════════════════════════════════════════════════════

def _pg_available() -> bool:
    engine = create_async_engine(_PG_URL, echo=False)
    async def _check():
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
            await conn.commit()
    try:
        asyncio.run(_check())
        asyncio.run(engine.dispose())
        return True
    except Exception:
        return False

_pg_needed = pytest.mark.skipif(not _pg_available(), reason="PG :5432 unreachable")

# ══════════════════════════════════════════════════════════════════
# PG client fixture (function-scoped, fresh engine per test)
# ══════════════════════════════════════════════════════════════════

@pytest_asyncio.fixture(scope="function")
async def pg_client():
    """Per-test PG + httpx client. Own engine, clean tables, no global state."""
    engine = create_async_engine(_PG_URL, echo=False)

    # Ensure tables exist (no-op if already created)
    async with engine.begin() as conn:
        await conn.run_sync(CosmoBase.metadata.create_all)

    # Clean all tables: nullify circular FKs → TRUNCATE CASCADE
    async with engine.begin() as conn:
        # Nullify circular FK columns so TRUNCATE works
        await conn.exec_driver_sql("UPDATE apps SET pipeline_plan_id = NULL")
        await conn.exec_driver_sql("UPDATE runs SET batch_id = NULL")
        # TRUNCATE with CASCADE handles all FK chains automatically
        sorted_names = [t.name for t in CosmoBase.metadata.sorted_tables]
        for tbl in reversed(sorted_names):
            await conn.exec_driver_sql(f"TRUNCATE TABLE {tbl} CASCADE")
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

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()
    await engine.dispose()