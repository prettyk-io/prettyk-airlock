# -*- coding: utf-8 -*-
"""COS-101: MinIO auto-provisioning подписывает запросы SigV4.

Дефект: startup.py создавал httpx-клиент с auth=(access_key, secret_key) —
HTTP Basic auth. MinIO отклоняет Basic для S3 API ("Please use
AWS4-HMAC-SHA256") — каждый запрос provisioning'а падал с 400/403 на живом
стенде. Фикс: каждый запрос подписывается s3_sigv4_headers (канон COS-093).

Проверяем через httpx.MockTransport: заголовки AWS4-HMAC-SHA256 присутствуют,
Basic-авторизации нет, HEAD/PUT идут по нужным путям.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_repo = Path(__file__).resolve().parents[3]
_orch = Path(__file__).resolve().parents[2]
for p in (str(_repo), str(_orch)):
    if p not in sys.path:
        sys.path.insert(0, p)

pytestmark = pytest.mark.asyncio


@pytest.fixture()
def minio_env(monkeypatch):
    monkeypatch.setenv("PK_MINIO_URL", "http://cosmo-minio:9000")
    monkeypatch.setenv("PK_MINIO_ACCESS_KEY", "cosmo")
    monkeypatch.setenv("PK_MINIO_SECRET_KEY", "cosmo-minio-dev")


class _Capture:
    """Записывает (method, path, headers) каждого запроса и отвечает по сценарию."""

    def __init__(self, existing: set[str]):
        self.existing = existing
        self.calls: list[tuple[str, str, dict]] = []

    def handler(self, request: "httpx.Request") -> "httpx.Response":
        import httpx
        self.calls.append((request.method, request.url.path, dict(request.headers)))
        if request.method == "HEAD":
            status = 200 if request.url.path.lstrip("/") in self.existing else 404
        elif request.method == "PUT":
            status = 201
        else:
            status = 400
        return httpx.Response(status, request=request)


async def test_provision_signs_sigv4_and_creates_missing(minio_env):
    from orchestrator.cosmo.api import startup

    cap = _Capture(existing={"cosmo-evidence"})  # остальные два отсутствуют
    await startup.provision_minio_buckets(transport=httpx_Mock(cap.handler))

    methods = [(m, p) for m, p, _ in cap.calls]
    # существующий — HEAD; отсутствующие — HEAD (404) затем PUT
    assert ("HEAD", "/cosmo-evidence") in methods
    assert ("PUT", "/cosmo-artifacts") in methods
    assert ("PUT", "/cosmo-builds") in methods
    assert ("PUT", "/cosmo-evidence") not in methods

    for _m, _p, headers in cap.calls:
        auth = headers.get("authorization", "")
        assert auth.startswith("AWS4-HMAC-SHA256 "), auth
        assert "AWS4-HMAC-SHA256 Credential=cosmo/" in auth
        assert "SignedHeaders=host;x-amz-content-sha256;x-amz-date" in auth
        assert "basic" not in auth.lower()
        assert headers.get("x-amz-date", "").endswith("Z")
        assert headers.get("x-amz-content-sha256", "")


async def test_provision_without_url_is_noop(monkeypatch):
    """PK_MINIO_URL не задан → provisioning выходит раньше создания клиента."""
    from orchestrator.cosmo.api import startup

    monkeypatch.delenv("PK_MINIO_URL", raising=False)
    # sentinel-transport: если код до него дойдёт, httpx упадёт на типе —
    # честный маркер «клиент не создавался».
    await startup.provision_minio_buckets(transport=_SentinelTransport())


class _SentinelTransport:
    """Не является httpx.AsyncBaseTransport: использование — мгновенная ошибка."""

    def __getattr__(self, name):
        raise AssertionError("transport must never be used without PK_MINIO_URL")


def httpx_Mock(handler):
    import httpx
    return httpx.MockTransport(handler)
