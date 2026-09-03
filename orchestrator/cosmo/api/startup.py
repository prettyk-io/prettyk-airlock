"""Cosmoport 2.0 — Startup: MinIO bucket auto-provisioning.

Вызывается при старте FastAPI (lifespan). Создаёт обязательные бакеты
если их ещё нет. Не блокирует старт при недоступности MinIO — пишет warning.

Бакеты:
  cosmo-evidence   — скриншоты, логи, трассировка, видео
  cosmo-artifacts  — SARIF, ГОСТ-Акты, отчёты, документы
  cosmo-builds     — build outputs, package artifacts

Требует переменные окружения:
  PK_MINIO_URL        — http://minio:9000 (или http://cosmo-minio:9000 в compose)
  PK_MINIO_ACCESS_KEY — access key (default: cosmo)
  PK_MINIO_SECRET_KEY — secret key (default: cosmo-minio-dev)

COS-101: запросы к S3 API подписываются SigV4 (s3_sigv4_headers, канон
COS-093) — MinIO отклоняет HTTP Basic auth ("Please use AWS4-HMAC-SHA256").
Раньше клиент создавался с auth=(access_key, secret_key) — каждый запрос
авто-provisioning'а падал с 400 на живом MinIO.
"""
from __future__ import annotations

import logging
import os
import urllib.parse
from contextlib import asynccontextmanager

import httpx

logger = logging.getLogger("cosmo.startup")

_REQUIRED_BUCKETS = [
    "cosmo-evidence",
    "cosmo-artifacts",
    "cosmo-builds",
]


def _minio_conf() -> tuple[str, str, str] | None:
    """(endpoint, access_key, secret_key) или None, если URL не задан."""
    endpoint = os.getenv("PK_MINIO_URL", "").strip().rstrip("/")
    if not endpoint:
        logger.warning("PK_MINIO_URL not set — skipping MinIO bucket provisioning")
        return None
    access_key = os.getenv("PK_MINIO_ACCESS_KEY", "cosmo")
    secret_key = os.getenv("PK_MINIO_SECRET_KEY", "cosmo-minio-dev")
    return endpoint, access_key, secret_key


def _sig_headers(
    endpoint: str, method: str, path: str,
    access_key: str, secret_key: str, content: bytes | None = None,
) -> dict[str, str]:
    """SigV4-заголовки для S3-запроса (канон COS-093, переиспользование)."""
    from orchestrator.cosmo.ledger.evidence_anchor import s3_sigv4_headers
    host = urllib.parse.urlsplit(endpoint).netloc
    return s3_sigv4_headers(
        method, host, path, None, access_key, secret_key, content=content)


async def _bucket_exists(
    client: httpx.AsyncClient, endpoint: str,
    access_key: str, secret_key: str, bucket: str,
) -> bool:
    """Проверить существует ли бакет (HEAD, SigV4)."""
    path = f"/{bucket}"
    try:
        r = await client.head(
            path, headers=_sig_headers(endpoint, "HEAD", path,
                                       access_key, secret_key))
        return r.status_code in (200, 403)  # 403 = exists but no list permission (ok for our use)
    except httpx.HTTPError:
        return False


async def _create_bucket(
    client: httpx.AsyncClient, endpoint: str,
    access_key: str, secret_key: str, bucket: str,
) -> bool:
    """Создать бакет (PUT, SigV4). True если создан или уже существует."""
    path = f"/{bucket}"
    try:
        r = await client.put(
            path, headers=_sig_headers(endpoint, "PUT", path,
                                       access_key, secret_key))
        if r.status_code in (200, 201, 409):
            logger.info("MinIO bucket '%s' ready", bucket)
            return True
        logger.error("MinIO: unexpected status %d creating bucket '%s': %s", r.status_code, bucket, r.text)
        return False
    except httpx.HTTPError as exc:
        logger.error("MinIO: failed to create bucket '%s': %s", bucket, exc)
        return False


async def provision_minio_buckets(transport: httpx.AsyncBaseTransport | None = None) -> None:
    """Проверить и создать все обязательные бакеты.

    Вызывается при старте API. Не роняет приложение при ошибке.
    transport — точка внедрения MockTransport в тестах.
    """
    conf = _minio_conf()
    if conf is None:
        return
    endpoint, access_key, secret_key = conf

    client = httpx.AsyncClient(
        base_url=endpoint,
        timeout=httpx.Timeout(10.0),
        transport=transport,
    )

    try:
        for bucket in _REQUIRED_BUCKETS:
            if await _bucket_exists(client, endpoint, access_key, secret_key, bucket):
                logger.debug("MinIO bucket '%s' already exists", bucket)
                continue
            await _create_bucket(client, endpoint, access_key, secret_key, bucket)
    finally:
        await client.aclose()


@asynccontextmanager
async def lifespan(app):
    """FastAPI lifespan: Alembic миграции + MinIO bucket provisioning + outbox worker."""
    logger.info("Cosmo API starting — provisioning MinIO buckets...")
    await provision_minio_buckets()

    # Alembic migrations are handled by entrypoint.sh before uvicorn starts.
    # If running without entrypoint (dev), run them here.
    auto_migrate = os.getenv("COSMO_AUTO_MIGRATE", "").strip().lower()
    if auto_migrate in ("1", "true", "yes"):
        logger.info("Running Alembic migrations from lifespan...")
        from alembic.config import Config
        from alembic import command
        alembic_cfg = Config("alembic.ini")
        command.upgrade(alembic_cfg, "head")

    # COS-081: gate decision trail — таблица на отдельном GateTrailBase вне
    # замороженной alembic-цепочки; создаётся idempotent create_all при старте
    # (миграции выше её не создают, chain править запрещено).
    try:
        from sqlalchemy.ext.asyncio import create_async_engine as _cae
        from orchestrator.cosmo.db.session import resolve_database_url
        from orchestrator.cosmo.db.models_gate_trail import GateTrailBase
        _boot_engine = _cae(resolve_database_url(), echo=False)
        async with _boot_engine.begin() as _conn:
            await _conn.run_sync(GateTrailBase.metadata.create_all)
        await _boot_engine.dispose()
    except Exception as exc:  # bootstrap не роняет старт, но факт фиксирует
        logger.warning("Gate trail bootstrap skipped: %s", exc)

    # ── Notification Delivery Hardening: background outbox worker ──
    # Доставка уведомлений без ручного POST /process. Endpoint остаётся.
    outbox_worker = None
    from orchestrator.cosmo.notifications.worker import OutboxWorker, worker_enabled

    if worker_enabled():
        outbox_worker = OutboxWorker()
        outbox_worker.start()
        app.state.outbox_worker = outbox_worker
    else:
        logger.info("Outbox worker disabled via COSMO_OUTBOX_WORKER_ENABLED")

    # ── COS-097: живой Woodpecker execution-контур (opt-in) ──
    # BatchExecutor + poll loop + honest degraded + evidence из реального
    # прогона. Выключен по умолчанию: unit-сеты и стенды без Woodpecker
    # не меняют поведение.
    exec_service = None
    from orchestrator.cosmo.control_plane.execution_service import (
        ExecutionService,
        execution_enabled,
    )

    if execution_enabled():
        from orchestrator.cosmo.db.session import get_sessionmaker
        exec_service = ExecutionService(get_sessionmaker())
        await exec_service.start()
        app.state.execution_service = exec_service
    else:
        logger.info("Execution service disabled via COSMO_EXECUTOR_ENABLED")

    yield

    if exec_service is not None:
        await exec_service.stop()
    if outbox_worker is not None:
        await outbox_worker.stop()
    logger.info("Cosmo API shutting down")