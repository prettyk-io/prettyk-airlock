"""Cosmoport 2.0 — Health & Readiness endpoints.

/live   — процесс жив (всегда 200 если FastAPI отвечает).
/ready  — K8s readiness-семантика: 200 только когда ядро способно
          обслуживать трафик. Hard-dep PostgreSQL недоступен → 503 +
          честный компонент-мап в теле. Soft-деградации (Valkey → SSE
          in-memory fallback COS-088, anchor → unknown_anchor на verify)
          НЕ роняют readiness — видны в теле.
/health — расширенная диагностика без раскрытия credentials.
"""
from __future__ import annotations

import asyncio
import logging
import os
import platform
import time
from typing import Optional

from fastapi import APIRouter
from fastapi.responses import JSONResponse
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
    """GET /ready — компонент-мап готовности.

    database/cache: "connected" | "unavailable";
    anchor:         "connected" | "disabled" | "unavailable".
    """
    status: str                  # "ok" | "degraded" | "not_ready"
    database: str                # hard-dep: 503 при "unavailable"
    cache: str                   # soft: SSE in-memory fallback
    anchor: str = "disabled"     # soft: evidence anchor sink (COS-087)


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


def _probe_anchor() -> DependencyStatus:
    """Проверить evidence anchor sink (COS-087/093): file | s3 backend.

    Soft-зависимость: недоступность НЕ роняет readiness — verify-сторона
    честно скажет unknown_anchor. Сами данные не трогаем (append-only!):
    file-режим проверяет доступность директории/файла; s3-режим — доступность
    бакета (HEAD, без записи).

    Статус: disabled (backend не сконфигурирован) | healthy | unhealthy.
    Не раскрывает путь к sink и креды.
    """
    try:
        from orchestrator.cosmo.ledger import evidence_anchor

        if evidence_anchor.backend() == "s3":
            cfg = evidence_anchor.s3_config()
            if cfg is None:
                return DependencyStatus(name="anchor", status="disabled")
            t0 = time.monotonic()
            try:
                import httpx
                # MinIO Basic auth не принимает — SigV4 (COS-093)
                sig = evidence_anchor.s3_sigv4_headers(
                    "HEAD", httpx.URL(cfg["endpoint"]).host + (
                        f":{httpx.URL(cfg['endpoint']).port}"
                        if httpx.URL(cfg["endpoint"]).port else ""
                    ),
                    f"/{cfg['bucket']}", None,
                    cfg["access_key"], cfg["secret_key"], cfg["region"],
                )
                with httpx.Client(
                    base_url=cfg["endpoint"],
                    timeout=httpx.Timeout(5.0),
                ) as client:
                    r = client.head(f"/{cfg['bucket']}", headers=sig)
            except Exception:
                return DependencyStatus(
                    name="anchor", status="unhealthy",
                    latency_ms=round((time.monotonic() - t0) * 1000, 1),
                    error="anchor object-store unreachable",
                )
            # 403 = бакет существует, но list-права нет — ok для anchor-проб
            if r.status_code in (200, 403):
                return DependencyStatus(
                    name="anchor", status="healthy",
                    latency_ms=round((time.monotonic() - t0) * 1000, 1),
                )
            return DependencyStatus(
                name="anchor", status="unhealthy",
                latency_ms=round((time.monotonic() - t0) * 1000, 1),
                error=f"anchor bucket check failed (HTTP {r.status_code})",
            )

        path = evidence_anchor.sink_path()
        if not path:
            return DependencyStatus(name="anchor", status="disabled")
        t0 = time.monotonic()
        parent = os.path.dirname(path) or "."
        if not os.path.isdir(parent):
            return DependencyStatus(
                name="anchor", status="unhealthy",
                latency_ms=round((time.monotonic() - t0) * 1000, 1),
                error="sink directory missing",
            )
        if not os.access(parent, os.W_OK):
            return DependencyStatus(
                name="anchor", status="unhealthy",
                latency_ms=round((time.monotonic() - t0) * 1000, 1),
                error="sink directory not writable",
            )
        if os.path.exists(path) and not os.access(path, os.R_OK):
            return DependencyStatus(
                name="anchor", status="unhealthy",
                latency_ms=round((time.monotonic() - t0) * 1000, 1),
                error="sink not readable",
            )
        return DependencyStatus(
            name="anchor", status="healthy",
            latency_ms=round((time.monotonic() - t0) * 1000, 1),
        )
    except Exception as exc:
        return DependencyStatus(
            name="anchor", status="unhealthy",
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
async def ready() -> object:
    """Готовность принимать трафик (K8s readiness-семантика).

    200: ядро способно обслуживать запросы (PostgreSQL жив). Мягкие
         деградации (Valkey → SSE in-memory fallback, anchor sink) видны
         в теле как status="degraded", но НЕ выводят инстанс из ротации.
    503: недоступен hard-dep PostgreSQL + честный компонент-мап в теле,
         чтобы Caddy/upstream вывел инстанс из ротации.
    """
    pg, vk = await asyncio.gather(
        _probe_postgres(timeout=2.0),
        _probe_valkey(timeout=2.0),
        return_exceptions=True,
    )
    anchor = _probe_anchor()

    db_status = "connected" if isinstance(pg, DependencyStatus) and pg.status == "healthy" else "unavailable"
    cache_status = "connected" if isinstance(vk, DependencyStatus) and vk.status == "healthy" else "unavailable"
    anchor_token = {
        "healthy": "connected",
        "disabled": "disabled",
    }.get(anchor.status, "unavailable")

    if db_status == "unavailable":
        # Hard-dep упал: 503 с честным компонент-мапом (не HTTPException,
        # чтобы тело не заворачивалось в {"detail": ...}).
        return JSONResponse(
            status_code=503,
            content=ReadyResponse(
                status="not_ready",
                database=db_status,
                cache=cache_status,
                anchor=anchor_token,
            ).model_dump(),
        )

    soft_ok = cache_status == "connected" and anchor_token in ("connected", "disabled")
    return ReadyResponse(
        status="ok" if soft_ok else "degraded",
        database=db_status,
        cache=cache_status,
        anchor=anchor_token,
    )


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