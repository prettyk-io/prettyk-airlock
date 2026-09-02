"""PostgreSQL-only async database session for Cosmoport 2.0.

COS-078: canonical DB-URL resolution contract (single documented order,
applied identically in session.py / alembic env.py / migration_verifier.py):

  1. Explicit programmatic target — an alembic Config marked with
     ``attributes["cosmo_url_explicit"] = True`` (in-process migration
     verifier pointing at a scratch DB). Env is NOT consulted — protects
     in-process cycles from a conftest-set env (the COS-073 conftest-hack
     replacement).
  2. ``COSMO_DATABASE_URL`` env var — explicit operator/test override.
     It WINS over the default and is LOUD-logged (once per distinct value)
     by :func:`env_override_url` so DB-target drift is always visible.
  3. Canonical default — ``DEFAULT_DATABASE_URL`` (dev stand) or the ini
     placeholder, whichever the caller owns.

Lazy everywhere: the URL is resolved on every call, never captured at
import time. Import-time capture was the root cause of the COS-072/075
split-brain (modules imported before conftest set the env kept targeting
the dev stand).
"""
from __future__ import annotations

import logging
import os

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Declarative base for all Cosmo ORM models."""
    pass


#: Canonical default: the dev-stand PostgreSQL (cosmo-postgres container).
DEFAULT_DATABASE_URL = "postgresql+asyncpg://cosmo:cosmo@localhost:5432/cosmo"

_logger = logging.getLogger("cosmo.db.config")
_logged_overrides: set[str] = set()


def env_override_url() -> str | None:
    """COS-078: explicit ``COSMO_DATABASE_URL`` override, loud-logged.

    Returns the env URL when set, else ``None``. The override is logged
    once per distinct value (warning level) — DB-target drift must be
    visible in logs, not discovered in test failures.
    """
    env_url = os.getenv("COSMO_DATABASE_URL")
    if env_url and env_url not in _logged_overrides:
        _logger.warning(
            "COS-078 DB-URL override in effect: COSMO_DATABASE_URL=%s "
            "(canonical default would be %s)", env_url, DEFAULT_DATABASE_URL,
        )
        _logged_overrides.add(env_url)
    return env_url


def resolve_database_url(default: str | None = None) -> str:
    """Resolve the runtime DB URL: env override (loud) → ``default`` → canonical."""
    return env_override_url() or default or DEFAULT_DATABASE_URL


_engine: AsyncEngine | None = None
_engine_url: str | None = None
_SessionLocal: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    """Return the async engine (singleton, lazy-init, lazy URL).

    The engine is rebuilt if the resolved URL changed since the previous
    call (env override applied mid-process). The stale engine is dropped
    without an awaitable dispose — acceptable for the test-only path that
    mutates the env after engines exist.
    """
    global _engine, _engine_url, _SessionLocal
    url = resolve_database_url()
    if _engine is None or _engine_url != url:
        _engine = create_async_engine(
            url,
            echo=False,
            pool_size=10,
            max_overflow=20,
            pool_pre_ping=True,       # COS-052: валидация соединения перед checkout
            pool_recycle=1800,        # COS-052: пересоздание соединений каждые 30 мин
            connect_args={
                "timeout": 10,            # таймаут подключения
                "command_timeout": 30,    # таймаут выполнения запроса
                "server_settings": {
                    "application_name": "cosmoport2",
                    "jit": "off",
                },
            },
        )
        _engine_url = url
        _SessionLocal = None
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    """Return the async session factory (singleton, lazy-init)."""
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = async_sessionmaker(get_engine(), expire_on_commit=False)
    return _SessionLocal


async def get_session() -> AsyncSession:
    """Create a new async session (caller must close)."""
    return get_sessionmaker()()


def get_sync_url() -> str:
    """Return a synchronous PostgreSQL URL for Alembic migrations.

    Resolves through the COS-078 contract (env override loud-logged) and
    replaces the ``+asyncpg`` driver with ``+psycopg2`` so Alembic and the
    sync engine can connect.
    """
    return resolve_database_url().replace("+asyncpg", "+psycopg2")


async def create_all() -> None:
    """Create all tables (dev bootstrap without Alembic)."""
    from orchestrator.cosmo.db.models import Base as CosmoBase  # noqa: F811
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(CosmoBase.metadata.create_all)


async def drop_all() -> None:
    """Drop all tables (dev reset, NEVER in production)."""
    from orchestrator.cosmo.db.models import Base as CosmoBase
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(CosmoBase.metadata.drop_all)


async def dispose_engine() -> None:
    """Dispose the async engine and reset singletons (useful in tests)."""
    global _engine, _engine_url, _SessionLocal
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _engine_url = None
    _SessionLocal = None


# ── Synchronous session (для тестов и миграций) ──

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

_sync_engine = None
_sync_engine_url: str | None = None
_SyncSessionLocal = None


def get_sync_engine():
    global _sync_engine, _sync_engine_url, _SyncSessionLocal
    url = get_sync_url()
    if _sync_engine is None or _sync_engine_url != url:
        _sync_engine = create_engine(url, echo=False)
        _sync_engine_url = url
        _SyncSessionLocal = None
    return _sync_engine


def get_sync_session() -> Session:
    global _SyncSessionLocal
    if _SyncSessionLocal is None:
        _SyncSessionLocal = sessionmaker(bind=get_sync_engine(), autoflush=False, autocommit=False)
    return _SyncSessionLocal()
