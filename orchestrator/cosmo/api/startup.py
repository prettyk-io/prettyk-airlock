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
"""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

import httpx

logger = logging.getLogger("cosmo.startup")

_REQUIRED_BUCKETS = [
    "cosmo-evidence",
    "cosmo-artifacts",
    "cosmo-builds",
]


async def _minio_client() -> httpx.AsyncClient | None:
    """Создать HTTP-клиент для MinIO S3 API.

    Возвращает None если переменные не заданы.
    """
    endpoint = os.getenv("PK_MINIO_URL", "").strip().rstrip("/")
    access_key = os.getenv("PK_MINIO_ACCESS_KEY", "cosmo")
    secret_key = os.getenv("PK_MINIO_SECRET_KEY", "cosmo-minio-dev")

    if not endpoint:
        logger.warning("PK_MINIO_URL not set — skipping MinIO bucket provisioning")
        return None

    return httpx.AsyncClient(
        base_url=endpoint,
        auth=(access_key, secret_key),
        timeout=httpx.Timeout(10.0),
    )


async def _bucket_exists(client: httpx.AsyncClient, bucket: str) -> bool:
    """Проверить существует ли бакет."""
    try:
        r = await client.head(f"/{bucket}")
        return r.status_code in (200, 403)  # 403 = exists but no list permission (ok for our use)
    except httpx.HTTPError:
        return False


async def _create_bucket(client: httpx.AsyncClient, bucket: str) -> bool:
    """Создать бакет. True если создан или уже существует."""
    try:
        r = await client.put(f"/{bucket}")
        if r.status_code in (200, 201, 409):
            logger.info("MinIO bucket '%s' ready", bucket)
            return True
        logger.error("MinIO: unexpected status %d creating bucket '%s': %s", r.status_code, bucket, r.text)
        return False
    except httpx.HTTPError as exc:
        logger.error("MinIO: failed to create bucket '%s': %s", bucket, exc)
        return False


async def provision_minio_buckets() -> None:
    """Проверить и создать все обязательные бакеты.

    Вызывается при старте API. Не роняет приложение при ошибке.
    """
    client = await _minio_client()
    if client is None:
        return

    try:
        for bucket in _REQUIRED_BUCKETS:
            if await _bucket_exists(client, bucket):
                logger.debug("MinIO bucket '%s' already exists", bucket)
                continue
            await _create_bucket(client, bucket)
    finally:
        await client.aclose()


@asynccontextmanager
async def lifespan(app):
    """FastAPI lifespan: Alembic миграции + MinIO bucket provisioning."""
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

    yield

    logger.info("Cosmo API shutting down")