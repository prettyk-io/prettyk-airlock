# -*- coding: utf-8 -*-
"""COS-096: API-layer резолвер GiteaForgeAdapter + честный маппинг ошибок.

Единая точка создания адаптера для роутов: env-конфигурация
(PK_GITEA_URL / PK_GITEA_TOKEN / PK_GITEA_USER / PK_GITEA_PASSWORD),
нормализация ошибок forge в HTTP-семантику:

  - forge недоступен (ConnError/Timeout/5xx)  → 502 Bad Gateway
  - forge отверг аутентификацию (401/403)     → 502 (честно: forge auth
    rejected; token не светится)
  - missing repo / missing file (LookupError) → 404
  - битый pipeline source (ValueError)        → 400

Ничего не выдумываем: нет env PK_GITEA_URL → forge-поверхность честно
503 "forge not configured".
"""
from __future__ import annotations

import logging
import os
from typing import Optional

import requests
from fastapi import HTTPException, status

from orchestrator.cosmo.adapters.forge_gitea import GiteaForgeAdapter

logger = logging.getLogger("cosmo.forge")

# Внутри compose-сети API видит gitea по сервисному имени; на хосте
# (тесты/smoke) — localhost:3100. Приоритет: env > дефолт по контексту.
DEFAULT_GITEA_URL = "http://cosmo-gitea:3000"

WEBHOOK_SECRET_ENV = "PK_GITEA_WEBHOOK_SECRET"
DEFAULT_WEBHOOK_SECRET = "dev-webhook-secret-change-me"


class ForgeNotConfigured(RuntimeError):
    """Env-конфиг forge не задан — поверхность честно недоступна."""


def forge_base_url() -> Optional[str]:
    return os.getenv("PK_GITEA_URL", "").strip() or None


def webhook_secret() -> str:
    return os.getenv(WEBHOOK_SECRET_ENV, "").strip() or DEFAULT_WEBHOOK_SECRET


def build_adapter() -> GiteaForgeAdapter:
    """Собрать адаптер из env. Без PK_GITEA_URL — ForgeNotConfigured."""
    base = forge_base_url()
    if not base:
        raise ForgeNotConfigured("PK_GITEA_URL is not set")
    return GiteaForgeAdapter(
        base_url=base,
        token=os.getenv("PK_GITEA_TOKEN", "").strip(),
        username=os.getenv("PK_GITEA_USER", "").strip(),
        password=os.getenv("PK_GITEA_PASSWORD", ""),
    )


def forge_http_error(exc: Exception, what: str) -> HTTPException:
    """Нормализация ошибки forge → честный HTTP-ответ + лог.

    Secrets/tokens в детали не попадают; причина называется словами.
    """
    if isinstance(exc, ForgeNotConfigured):
        return HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Forge not configured: {exc}",
        )
    if isinstance(exc, LookupError):
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        )
    if isinstance(exc, ValueError):
        return HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )
    if isinstance(exc, requests.HTTPError):
        code = exc.response.status_code if exc.response is not None else 0
        if code in (401, 403):
            logger.warning("Forge auth rejected for %s: HTTP %d", what, code)
            return HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Forge rejected credentials for {what} (HTTP {code}); "
                       f"check PK_GITEA_TOKEN/USER/PASSWORD",
            )
        if code == 404:
            return HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Not found in forge: {what}",
            )
        logger.warning("Forge HTTP error for %s: HTTP %d", what, code)
        return HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Forge unavailable for {what} (HTTP {code})",
        )
    if isinstance(exc, (requests.ConnectionError, requests.Timeout)):
        logger.warning("Forge unreachable for %s: %s", what, exc)
        return HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Forge unreachable for {what}; verify gitea container is up",
        )
    logger.exception("Unexpected forge error for %s", what)
    return HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail=f"Forge error for {what}: {type(exc).__name__}",
    )
