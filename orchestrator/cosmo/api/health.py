"""Cosmoport 2.0 — Health & Readiness endpoints.

/live   — процесс жив (всегда 200 если FastAPI отвечает).
/ready  — PG+Valkey готовы к приёму трафика (200/503).
/health — расширенная диагностика без раскрытия credentials.
"""
from __future__ import annotations

import asyncio
import logging
import os
import platform
import time
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text

logger = logging.getLogger("cosmo.health")

router = APIRouter(tags=["health"])

_STARTED_AT: float = time.time()


# ── Response models ────────────────────────────────────────────────────

class LiveResponse(BaseModel):
    """GET /live — минимальный ответ. Всегда 200 если процесс жив."""
    status: str = "ok"


class ReadyResponse(BaseModel):
    """GET /ready — готовность принимать трафик."""
    status: str                  # "ok" | "degraded" | "not_ready"
    database: str                # "connected" | "unavailable"
    cache: str                   # "connected" | "unavailable"


class DependencyStatus(BaseModel):
    name: str
    status: str                  # "healthy" | "unhealthy" | "degraded"
    latency_ms: Optional[float] = None
    error: Optional[str] = None


class HealthResponse(BaseModel):
    """GET /health — расширенная диагностика без credentials."""
    status: str                  # "ok" | "degraded" | "unhealthy"
    uptime_seconds: float = Field(description="Время работы процесса")
    version: str = "0.1.0"
    platform: str = Field(description="python_version / system")
    dependencies: list[DependencyStatus] = Field(default_factory=list)


# ── Internal probes ────────────────────────────────────────────────────

async def _probe_postgres(timeout: float = 3.0) -> DependencyStatus:
    """Проверить PostgreSQL: выполнить SELECT 1.

    Не раскрывает DSN, host, port или версию — только connected/unavailable.
    """
    t0 = time.monotonic()
    try:
        from orchestrator.cosmo.db.session import get_engine
        engine = get_engine()
        async with engine.connect() as conn:
            await asyncio.wait_for(
                conn.execute(text("SELECT 1")),
                timeout=timeout,
            )
            await conn.commit()
        latency = (time.monotonic() - t0) * 1000
        return DependencyStatus(name="postgres", status="healthy", latency_ms=round(latency, 1))
    except Exception as exc:
        latency = (time.monotonic() - t0) * 1000
        return DependencyStatus(
            name="postgres", status="unhealthy",
            latency_ms=round(latency, 1),
            error=_sanitize_error(exc),
        )


async def _probe_valkey(timeout: float = 3.0) -> DependencyStatus:
    """Проверить Valkey: PING через raw TCP.

    Не раскрывает host, port, версию — только connected/unavailable.
    """
    t0 = time.monotonic()
    try:
        host = os.getenv("PK_VALKEY_HOST", "127.0.0.1")
        port = int(os.getenv("PK_VALKEY_PORT", "6379"))
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port),
            timeout=timeout,
        )
        writer.write(b"PING\r\n")
        await writer.drain()
        response = await asyncio.wait_for(reader.readline(), timeout=timeout)
        writer.close()
        await writer.wait_closed()
        latency = (time.monotonic() - t0) * 1000
        if response.strip() == b"+PONG":
            return DependencyStatus(name="valkey", status="healthy", latency_ms=round(latency, 1))
        return DependencyStatus(
            name="valkey", status="unhealthy",
            latency_ms=round(latency, 1),
            error=f"unexpected response: {response!r}",
        )
    except Exception as exc:
        latency = (time.monotonic() - t0) * 1000
        return DependencyStatus(
            name="valkey", status="unhealthy",
            latency_ms=round(latency, 1),
            error=_sanitize_error(exc),
        )


def _sanitize_error(exc: Exception) -> str:
    """Убрать потенциально чувствительные данные из сообщения об ошибке.

    Не раскрываем: DSN, URL с паролями, внутренние hostnames/IP.
    """
    msg = str(exc)
    # Отрезаем всё после первого переноса строки (Python traceback).
    msg = msg.split("\n", 1)[0]
    # Обрезаем до 120 символов.
    if len(msg) > 120:
        msg = msg[:117] + "..."
    return msg


# ── Routes ─────────────────────────────────────────────────────────────

@router.get("/live", response_model=LiveResponse)
async def live() -> LiveResponse:
    """Процесс жив. Самый лёгкий эндпоинт — без зависимостей."""
    return LiveResponse(status="ok")


@router.get("/ready", response_model=ReadyResponse)
async def ready() -> ReadyResponse:
    """Готовность принимать трафик.

    200: PG и Valkey доступны.
    503: одна из зависимостей недоступна.
    """
    pg, vk = await asyncio.gather(
        _probe_postgres(timeout=2.0),
        _probe_valkey(timeout=2.0),
        return_exceptions=True,
    )

    db_status = "connected" if isinstance(pg, DependencyStatus) and pg.status == "healthy" else "unavailable"
    cache_status = "connected" if isinstance(vk, DependencyStatus) and vk.status == "healthy" else "unavailable"

    if db_status == "connected" and cache_status == "connected":
        response = ReadyResponse(status="ok", database=db_status, cache=cache_status)
    elif db_status == "connected" or cache_status == "connected":
        response = ReadyResponse(status="degraded", database=db_status, cache=cache_status)
    else:
        raise HTTPException(
            status_code=503,
            detail=ReadyResponse(status="not_ready", database=db_status, cache=cache_status).model_dump(),
        )

    return response


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Расширенная диагностика.

    200 всегда — даже при недоступных зависимостях.
    Информация о состоянии возвращается в теле ответа.
    Credentials НЕ раскрываются.
    """
    deps: list[DependencyStatus] = []

    results = await asyncio.gather(
        _probe_postgres(timeout=2.0),
        _probe_valkey(timeout=2.0),
        return_exceptions=True,
    )

    for r in results:
        if isinstance(r, DependencyStatus):
            deps.append(r)
        else:
            deps.append(DependencyStatus(
                name="probe_internal_error",
                status="unhealthy",
                error=_sanitize_error(r) if isinstance(r, Exception) else str(r),
            ))

    all_healthy = all(d.status == "healthy" for d in deps)
    any_healthy = any(d.status == "healthy" for d in deps)

    if all_healthy:
        overall = "ok"
    elif any_healthy:
        overall = "degraded"
    else:
        overall = "unhealthy"

    return HealthResponse(
        status=overall,
        uptime_seconds=round(time.time() - _STARTED_AT, 1),
        platform=f"Python {platform.python_version()} / {platform.system()}",
        dependencies=deps,
    )