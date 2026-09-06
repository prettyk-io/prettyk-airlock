# -*- coding: utf-8 -*-
"""COS-108: API-layer фабрика WoodpeckerAdapter (аналог forge_client).

Единая точка создания адаптера для workspace-роутов: env-конфигурация
(COSMO_WOODPECKER_URL / COSMO_WOODPECKER_TOKEN), нормализация ошибок
Woodpecker в HTTP-семантику.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

import requests
from fastapi import HTTPException, status

from orchestrator.cosmo.adapters.execution_woodpecker import WoodpeckerAdapter

logger = logging.getLogger("cosmo.woodpecker")

DEFAULT_WP_URL = "http://woodpecker:8000"


class WoodpeckerNotConfigured(RuntimeError):
    """Woodpecker недоступен (нет URL/token)."""


def build_woodpecker() -> WoodpeckerAdapter:
    """Собрать WoodpeckerAdapter из env. Без COSMO_WOODPECKER_URL — дефолт."""
    base = (os.getenv("COSMO_WOODPECKER_URL", "")
            or os.getenv("PK_WOODPECKER_URL", "")
            or DEFAULT_WP_URL)
    token = os.getenv("COSMO_WOODPECKER_TOKEN", "")
    return WoodpeckerAdapter(base_url=base, token=token)


def woodpecker_http_error(exc: Exception, what: str) -> HTTPException:
    """Нормализация ошибки Woodpecker → честный HTTP-ответ."""
    if isinstance(exc, PermissionError):
        logger.warning("Woodpecker auth rejected for %s: %s", what, exc)
        return HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Woodpecker rejected submit for {what}; check COSMO_WOODPECKER_TOKEN",
        )
    if isinstance(exc, LookupError):
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        )
    if isinstance(exc, requests.HTTPError):
        code = exc.response.status_code if exc.response is not None else 0
        logger.warning("Woodpecker HTTP error for %s: %d", what, code)
        return HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Woodpecker unavailable for {what} (HTTP {code})",
        )
    if isinstance(exc, (requests.ConnectionError, requests.Timeout)):
        logger.warning("Woodpecker unreachable for %s: %s", what, exc)
        return HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Woodpecker unreachable for {what}",
        )
    logger.exception("Unexpected Woodpecker error for %s", what)
    return HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail=f"Woodpecker error for {what}: {type(exc).__name__}",
    )