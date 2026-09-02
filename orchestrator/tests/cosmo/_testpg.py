# -*- coding: utf-8 -*-
"""COS-073: isolated test PostgreSQL contract.

Contract: tests NEVER touch the dev-stand database (host :5432, db `cosmo`).
Every PG engine / connection inside tests resolves through this module:

- URL:  env ``COSMO_TEST_DATABASE_URL`` wins, default
        ``postgresql+asyncpg://cosmo:cosmo@127.0.0.1:5433/cosmo_test``
        (127.0.0.1, not localhost: ``localhost`` may resolve to ::1 which
        is intercepted by the WSL relay — proven in COS-064)
- Stand-up:  ``docker compose -f services/docker-compose.test-pg.yml up -d``
- Guard: any URL resolving to dev-stand port 5432 (explicit or implicit)
  is refused at import time — hard failure, not a skip.

Import as ``import _testpg`` (pytest puts this dir on sys.path).
"""
from __future__ import annotations

import asyncio
import os
import uuid
from urllib.parse import urlsplit

DEV_STAND_PORT = 5432
TEST_PG_DEFAULT_PORT = 5433  # 5432 is the dev-stand cosmo-postgres — forbidden

_DEFAULT_URL = "postgresql+asyncpg://cosmo:cosmo@127.0.0.1:5433/cosmo_test"
TEST_PG_URL = os.getenv("COSMO_TEST_DATABASE_URL", _DEFAULT_URL)

# ── COS-076: opt-in per-session test DB (pytest-xdist / parallel processes) ──
# COSMO_TEST_SESSION_DB=1 → при импорте модуля создаётся уникальная БД
# cosmo_test_s<hex> на том же инстансе, TEST_PG_URL переключается на неё,
# atexit дропает её при завершении процесса. Каждый параллельный процесс
# получает СВОЮ схему+данные — wipe/pg_client одного процесса больше не
# роняет тесты другого (FK/data-гонки общего cosmo_test). Опция безопасна
# по умолчанию: без флага поведение прежнее (общий cosmo_test).
if os.getenv("COSMO_TEST_SESSION_DB", "").strip().lower() in ("1", "true", "yes"):
    import atexit

    import psycopg2

    _sp = urlsplit(TEST_PG_URL)
    _SESSION_DB = f"cosmo_test_s{uuid.uuid4().hex[:8]}"
    _admin_conn = psycopg2.connect(
        f"host={_sp.hostname} port={_sp.port} dbname=postgres "
        f"user={_sp.username} password={_sp.password}",
        connect_timeout=3,
    )
    try:
        _admin_conn.autocommit = True
        _admin_conn.cursor().execute(f'CREATE DATABASE "{_SESSION_DB}"')
    finally:
        _admin_conn.close()

    TEST_PG_URL = (
        f"postgresql+asyncpg://{_sp.username}:{_sp.password}"
        f"@{_sp.hostname}:{_sp.port}/{_SESSION_DB}"
    )

    def _drop_session_db() -> None:
        try:
            conn = psycopg2.connect(
                f"host={_sp.hostname} port={_sp.port} dbname=postgres "
                f"user={_sp.username} password={_sp.password}",
                connect_timeout=3,
            )
            try:
                conn.autocommit = True
                cur = conn.cursor()
                cur.execute(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = %s AND pid <> pg_backend_pid()",
                    (_SESSION_DB,),
                )
                cur.execute(f'DROP DATABASE IF EXISTS "{_SESSION_DB}"')
            finally:
                conn.close()
        except Exception:
            pass  # atexit-janitor не маскирует код выхода процесса

    atexit.register(_drop_session_db)


def scratch_name(prefix: str) -> str:
    """COS-078: unique per-run scratch DB name.

    Fixed scratch names (cosmo_mig_recon и т.п.) ловили каталожную гонку
    pg_type_typname_nsp_index при параллельных pytest на стенде — два
    процесса CREATE TABLE с одним именем в одной scratch-БД. Уникальный
    суффикс per-run разводит конкурирующие прогоны по разным БД.
    """
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def refuse_dev_stand(url: str) -> str:
    """Return the url if it does NOT point at the dev-stand PG, else raise.

    The dev stand is identified by host port 5432 (explicit or implicit —
    a URL without a port defaults to 5432 for postgres and is refused too).
    """
    parsed = urlsplit(url)
    port = parsed.port if parsed.port is not None else DEV_STAND_PORT
    if port == DEV_STAND_PORT:
        raise RuntimeError(
            "COS-073 contract violated: test URL points at the dev-stand "
            f"port {DEV_STAND_PORT}: {url!r}\n"
            "Tests must use the isolated test PG: "
            "docker compose -f services/docker-compose.test-pg.yml up -d "
            "(host :5433, db cosmo_test) or set COSMO_TEST_DATABASE_URL."
        )
    return url


refuse_dev_stand(TEST_PG_URL)


def asyncpg_dsn(url: str = TEST_PG_URL) -> str:
    """asyncpg accepts the plain ``postgresql://`` scheme (no +asyncpg)."""
    return url.replace("postgresql+asyncpg://", "postgresql://", 1)


def psycopg2_url(dbname: str | None = None, url: str = TEST_PG_URL) -> str:
    """Sync-driver URL against the test PG instance (or a scratch db on it)."""
    parsed = urlsplit(url)
    name = dbname or parsed.path.lstrip("/")
    return (
        f"postgresql+psycopg2://{parsed.username}:{parsed.password}"
        f"@{parsed.hostname}:{parsed.port}/{name}"
    )


def admin_dsn(dbname: str = "postgres", url: str = TEST_PG_URL) -> str:
    """psycopg2 keyword DSN for admin ops (CREATE/DROP DATABASE)."""
    parsed = urlsplit(url)
    return (
        f"host={parsed.hostname} port={parsed.port} dbname={dbname} "
        f"user={parsed.username} password={parsed.password}"
    )


def pg_available(timeout: float = 3.0) -> bool:
    """True when the isolated test PG answers on its port."""
    try:
        conn = asyncio.new_event_loop()
        try:
            c = conn.run_until_complete(
                _connect_asyncpg(asyncpg_dsn(), timeout)
            )
            conn.run_until_complete(c.close())
            return True
        finally:
            conn.close()
    except Exception:
        return False


async def _connect_asyncpg(dsn: str, timeout: float):
    import asyncpg

    return await asyncpg.connect(dsn, timeout=timeout)
