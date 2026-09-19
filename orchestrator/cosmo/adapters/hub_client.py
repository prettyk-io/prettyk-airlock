# -*- coding: utf-8 -*-
"""COS-139: Contract B — HTTP-клиент к PrettyK Hub (QGFCS evaluation).

Отправка конверта оценки релиза в PrettyK Hub. Контракт транспорта:

  - адрес по умолчанию ``http://localhost:8000/api/v1/evaluations``,
    переопределяется через ``COSMO_HUB_URL`` (принимается и корень хаба,
    и полный путь — см. :func:`evaluations_url`);
  - таймаут 10с (``timeout``);
  - bounded retry с экспоненциальным backoff ТОЛЬКО для транспортных сбоев,
    таймаутов, ``429`` и ``5xx``;
  - ``4xx`` (кроме ``429``) — немедленный отказ без повторов: контрактный
    отказ хаба повторять бессмысленно и опасно;
  - таймаут/сбой НЕ превращается в PASS — вызывающая сторона получает
    :class:`HubDispatchError` (honest UNKNOWN/BLOCKED).

Сеть в тестах подменяется ``httpx.MockTransport`` (transport seam), без
реального сокета.
"""
from __future__ import annotations

import asyncio
import os
from typing import Any, Optional

import httpx

#: Полный URL эндпоинта оценок по умолчанию.
DEFAULT_HUB_URL = "http://localhost:8000/api/v1/evaluations"

#: Env-переменная адреса PrettyK Hub.
HUB_URL_ENV = "COSMO_HUB_URL"

#: Таймаут одного запроса, сек.
DEFAULT_TIMEOUT_SECONDS = 10.0

#: Максимум попыток (первая + повторы).
DEFAULT_MAX_ATTEMPTS = 3

#: База экспоненциального backoff, сек (0 — без ожидания).
DEFAULT_BACKOFF_BASE = 0.5

#: Путь эндпоинта оценок относительно корня хаба.
_EVALUATIONS_PATH = "/api/v1/evaluations"


def evaluations_url(raw: str) -> str:
    """Нормализовать адрес хаба в полный URL эндпоинта оценок.

    Принимает корень хаба (``http://hub:8000``), префикс API
    (``http://hub:8000/api/v1``) или уже полный путь
    (``.../api/v1/evaluations``).
    """
    base = (raw or "").strip().rstrip("/")
    if not base:
        base = DEFAULT_HUB_URL.rstrip("/")
    if base.endswith("/evaluations"):
        return base
    if base.endswith("/api/v1"):
        return f"{base}/evaluations"
    return f"{base}{_EVALUATIONS_PATH}"


class HubDispatchError(RuntimeError):
    """Сбой отправки оценки в Hub (транспорт/таймаут/отказ хаба)."""

    def __init__(
        self,
        message: str,
        *,
        status_code: Optional[int] = None,
        attempts: int = 1,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.attempts = attempts
        self.retryable = retryable


class HubEvaluationClient:
    """Тонкий async HTTP-клиент к PrettyK Hub для Contract B."""

    def __init__(
        self,
        base_url: str | None = None,
        *,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
        backoff_base: float = DEFAULT_BACKOFF_BASE,
        transport: httpx.AsyncBaseTransport | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._url = evaluations_url(
            base_url or os.getenv(HUB_URL_ENV, "") or DEFAULT_HUB_URL,
        )
        self._timeout = timeout
        self._max_attempts = max(1, int(max_attempts))
        self._backoff_base = max(0.0, float(backoff_base))
        self._transport = transport
        self._client = client

    @property
    def url(self) -> str:
        """Полный URL эндпоинта оценок (для логов/диагностики)."""
        return self._url

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            kwargs: dict[str, Any] = {"timeout": self._timeout}
            if self._transport is not None:
                kwargs["transport"] = self._transport
            self._client = httpx.AsyncClient(**kwargs)
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def dispatch(self, payload: dict[str, Any]) -> dict[str, Any]:
        """POST конверта Contract B; возвращает JSON-ответ хаба.

        Raises:
            HubDispatchError: транспортный сбой/таймаут (после повторов),
                либо отказ хаба (``4xx``/``5xx``).
        """
        client = await self._get_client()
        last_error: str = "unknown transport failure"
        last_status: Optional[int] = None

        for attempt in range(1, self._max_attempts + 1):
            try:
                response = await client.post(self._url, json=payload)
            except httpx.RequestError as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                last_status = None
                if attempt < self._max_attempts:
                    await self._backoff(attempt)
                    continue
                raise HubDispatchError(
                    f"Hub unreachable after {attempt} attempt(s): {last_error}",
                    attempts=attempt, retryable=True,
                ) from exc

            if response.status_code == 429 or response.status_code >= 500:
                last_status = response.status_code
                last_error = f"Hub returned {response.status_code}"
                if attempt < self._max_attempts:
                    await self._backoff(attempt)
                    continue
                raise HubDispatchError(
                    f"Hub failed after {attempt} attempt(s): {last_error}",
                    status_code=last_status, attempts=attempt, retryable=True,
                )

            if response.status_code >= 400:
                raise HubDispatchError(
                    f"Hub rejected evaluation with {response.status_code}: "
                    f"{_short(response.text)}",
                    status_code=response.status_code, attempts=attempt,
                    retryable=False,
                )

            try:
                data = response.json()
            except ValueError as exc:
                raise HubDispatchError(
                    f"Hub returned non-JSON response ({response.status_code})",
                    status_code=response.status_code, attempts=attempt,
                    retryable=False,
                ) from exc
            if not isinstance(data, dict):
                raise HubDispatchError(
                    "Hub returned unexpected JSON shape (not an object)",
                    status_code=response.status_code, attempts=attempt,
                    retryable=False,
                )
            return data

        # Недостижимо: цикл либо возвращает, либо бросает.
        raise HubDispatchError(
            f"Hub dispatch exhausted attempts: {last_error}",
            status_code=last_status, attempts=self._max_attempts, retryable=True,
        )

    async def _backoff(self, attempt: int) -> None:
        if self._backoff_base <= 0:
            return
        await asyncio.sleep(self._backoff_base * (2 ** (attempt - 1)))


def _short(text: str, limit: int = 200) -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else f"{text[:limit]}..."


__all__ = [
    "DEFAULT_BACKOFF_BASE",
    "DEFAULT_HUB_URL",
    "DEFAULT_MAX_ATTEMPTS",
    "DEFAULT_TIMEOUT_SECONDS",
    "HUB_URL_ENV",
    "HubDispatchError",
    "HubEvaluationClient",
    "evaluations_url",
]
