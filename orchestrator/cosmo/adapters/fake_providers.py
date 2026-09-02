# -*- coding: utf-8 -*-
"""
COS-052: Reusable provider test fixtures — без реальных внешних сервисов.

Fake-провайдеры соблюдают контракт честности:
  - unsupported capability → OpResult.unsupported / UNSUPPORTED, не fake success;
  - ошибки возвращаются как ошибки (категория TRANSIENT/TERMINAL сохраняется);
  - digest сохраняются как вернул «сервер», без подмены.

FakeSferaTransport — scriptable transport seam для SferaProviderAdapter:
  очередь ответов на (method, url-префикс) + проверка вызовов.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, Optional

from orchestrator.cosmo.adapters.provider_capability import (
    CapabilityReport,
    CapabilityStatus,
    OpResult,
    OpStatus,
    ProviderCapability as PC,
)
from orchestrator.cosmo.adapters.provider_capability import CapabilityProvider


def sha256_of(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


# ── Generic fake provider ───────────────────────────────────────────────────

class FakeCapabilityProvider(CapabilityProvider):
    """Скриптуемый fake: задаётся матрицей + таблицей результатов операций.

    Используется как общий базовый fake для Git/Harbor/Nexus/MinIO fixtures.
    """

    def __init__(self, provider_id: str, matrix: CapabilityReport) -> None:
        self._provider_id = provider_id
        self._matrix = matrix
        self._results: dict[str, OpResult | Exception] = {}
        self.calls: list[tuple[str, Any]] = []

    # -- Scripting --

    def script(self, capability: PC, result: OpResult | Exception) -> None:
        self._results[capability.value] = result

    def _make(self, capability: PC, **kwargs: Any) -> OpResult:
        self.calls.append((capability.value, kwargs))
        scripted = self._results.get(capability.value)
        if isinstance(scripted, Exception):
            raise scripted
        if scripted is not None:
            return scripted
        return OpResult.unsupported(capability, self._provider_id,
                                    "fake has no script for this capability")

    # -- Contract --

    @property
    def provider_id(self) -> str:
        return self._provider_id

    def capability_report(self) -> CapabilityReport:
        return self._matrix

    async def op_health(self) -> OpResult:
        return self._make(PC.HEALTH)

    async def op_push(self, ref: str, data: bytes, *,
                      media_type: str = "application/octet-stream") -> OpResult:
        return self._make(PC.RAW_PUSH, ref=ref, size=len(data))

    async def op_pull(self, ref: str) -> OpResult:
        return self._make(PC.RAW_PULL, ref=ref)

    async def op_exists(self, ref: str, digest: Optional[str] = None) -> OpResult:
        return self._make(PC.EXISTS, ref=ref, digest=digest)


# ── Fake Sfera transport ────────────────────────────────────────────────────

@dataclass
class _ScriptedResponse:
    status_code: int
    headers: dict[str, str] = field(default_factory=dict)
    body: bytes = b""
    json: Optional[Any] = None


class FakeSferaTransport:
    """Scriptable in-memory transport для SferaProviderAdapter (без сети).

    Регистрация ответов:
        transport.expect("PUT", ".../raw/repo/path", _ScriptedResponse(201, ...))
    Регистрация сетевых сбоев:
        transport.fail_on("GET", ".../v2/")   → TransportFailure при вызове
    Записывает все вызовы: transport.calls → список {method, url, headers, data}.
    Непроскриптированный URL → 503 (честный transient, не молчаливый success).
    """

    def __init__(self) -> None:
        self._routes: list[tuple[str, str, _ScriptedResponse]] = []
        self._fail_routes: list[tuple[str, str]] = []
        self.calls: list[dict[str, Any]] = []

    def expect(self, method: str, url_prefix: str, response: _ScriptedResponse) -> None:
        self._routes.append((method.upper(), url_prefix, response))

    def fail_on(self, method: str, url_prefix: str) -> None:
        """Все вызовы (method, prefix) → TransportFailure (сеть недоступна)."""
        self._fail_routes.append((method.upper(), url_prefix))

    async def __call__(self, method: str, url: str, headers: dict[str, Any],
                       data: Optional[bytes]) -> _ScriptedResponse:
        from orchestrator.cosmo.adapters.sfera_provider import TransportFailure
        self.calls.append({"method": method, "url": url,
                           "headers": headers, "data": data})
        for m, prefix in self._fail_routes:
            if m == method.upper() and url.startswith(prefix):
                raise TransportFailure(f"fake network failure on {method} {prefix}")
        for m, prefix, resp in self._routes:
            if m == method.upper() and url.startswith(prefix):
                return _ScriptedResponse(status_code=resp.status_code,
                                         headers=dict(resp.headers),
                                         body=resp.body, json=resp.json)
        return _ScriptedResponse(status_code=503, body=b"fake: no route")
