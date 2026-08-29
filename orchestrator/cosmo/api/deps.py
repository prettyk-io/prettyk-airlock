"""Cosmoport 2.0 — FastAPI shared dependencies.

Provides async database session per request.
"""
from __future__ import annotations

from collections.abc import AsyncGenerator
from sqlalchemy.ext.asyncio import AsyncSession
from orchestrator.cosmo.db.session import get_sessionmaker


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Yield an async SQLAlchemy session per request."""
    session_factory = get_sessionmaker()
    async with session_factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
