"""PostgreSQL-only async database session for Cosmoport 2.0."""
from __future__ import annotations

import os
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Declarative base for all Cosmo ORM models."""
    pass


DATABASE_URL = os.getenv(
    "COSMO_DATABASE_URL",
    "postgresql+asyncpg://cosmo:cosmo@localhost:5432/cosmo",
)

_engine: AsyncEngine | None = None
_SessionLocal: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    """Return the async engine (singleton, lazy-init)."""
    global _engine
    if _engine is None:
        _engine = create_async_engine(
        DATABASE_URL,
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

    Replaces `+asyncpg` driver with `+psychopg2` so Alembic can connect.
    """
    return DATABASE_URL.replace("+asyncpg", "+psycopg2")


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
    global _engine, _SessionLocal
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _SessionLocal = None


# ── Synchronous session (для тестов и миграций) ──

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

_sync_engine = None
_SyncSessionLocal = None


def get_sync_engine():
    global _sync_engine
    if _sync_engine is None:
        _sync_engine = create_engine(get_sync_url(), echo=False)
    return _sync_engine


def get_sync_session() -> Session:
    global _SyncSessionLocal
    if _SyncSessionLocal is None:
        _SyncSessionLocal = sessionmaker(bind=get_sync_engine(), autoflush=False, autocommit=False)
    return _SyncSessionLocal()