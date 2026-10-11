# -*- coding: utf-8 -*-
"""COS-105: Vault adapter — unit (mock), integration (dev root token),
и opt-in live (против платформенного prettyk-openbao :8200).
"""
from __future__ import annotations

import os
import json as _json

import pytest

from orchestrator.cosmo.infra.vault import (
    DEFAULT_VAULT_ADDR,
    VaultAuthError,
    VaultClient,
    VaultError,
    VaultLookupError,
    VaultNotConfigured,
    VaultUnavailableError,
)

ROOT_TOKEN_DEFAULT = "cosmo-bao-root-dev"

# Quirk: OpenBao 2.2.2 игнорирует VAULT_DEV_ROOT_TOKEN_ID —
# реальный рут-токен ловится из логов контейнера (платформенный prettyk-openbao,
# COS-173; раньше — per-product cosmo-openbao).
def _live_root_token() -> str:
    """Рут-токен OpenBao в dev-режиме (из логов или env)."""
    explicit = os.getenv("COSMO_LIVE_BAO_ROOT_TOKEN", "").strip()
    if explicit:
        return explicit
    try:
        import subprocess
        out = subprocess.run(
            ["docker", "logs", "prettyk-openbao"],
            capture_output=True, text=True, timeout=5,
        )
        for line in out.stdout.split("\n"):
            if "Root Token:" in line:
                token = line.split("Root Token:", 1)[1].strip()
                if token:
                    return token
    except Exception:
        pass
    return ROOT_TOKEN_DEFAULT  # fallback на compose-дефолт (может работать в новых версиях)
LIVE_GATE = "COSMO_LIVE_BAO"


@pytest.fixture(autouse=True)
def _clean_vault_env(monkeypatch):
    """Снять Vault-энвы, чтобы тесты не подхватывали стенд случайно."""
    for env in ("VAULT_ADDR", "VAULT_APPROLE_ROLE_ID", "VAULT_APPROLE_SECRET_ID",
                "VAULT_DEV_ROOT_TOKEN_ID", "COSMO_ENV"):
        monkeypatch.delenv(env, raising=False)


# ── Dev mode tests ─────────────────────────────────────────────────────

class TestDevMode:
    def test_dev_token_auth_ok(self, monkeypatch):
        monkeypatch.setenv("COSMO_ENV", "test")
        monkeypatch.setenv("VAULT_DEV_ROOT_TOKEN_ID", "dev-root-123")
        c = VaultClient()
        c.authenticate()
        assert c._token == "dev-root-123"

    def test_dev_token_empty_rejected(self, monkeypatch):
        monkeypatch.setenv("COSMO_ENV", "test")
        monkeypatch.setenv("VAULT_DEV_ROOT_TOKEN_ID", "")
        c = VaultClient()
        with pytest.raises(VaultAuthError, match="empty"):
            c.authenticate()

    def test_not_configured_without_approle_or_test(self):
        """Нет AppRole, нет COSMO_ENV=test → VaultNotConfigured."""
        c = VaultClient()
        with pytest.raises(VaultNotConfigured, match="required"):
            c.authenticate()

    def test_lazy_reauth_on_read_after_token_reset(self, monkeypatch):
        """COS-178: сброшенный токен → read сам поднимает сессию (lazy-auth)."""
        monkeypatch.setenv("COSMO_ENV", "test")
        monkeypatch.setenv("VAULT_DEV_ROOT_TOKEN_ID", "dev-root-123")
        c = VaultClient()
        c.authenticate()
        c._token = None  # симуляция сброса (напр. vault ожил после старта API)

        class MS:
            def get(self, url, headers=None, timeout=None):
                assert headers["X-Vault-Token"] == "dev-root-123"
                return MockResponse({"data": {"data": {"ok": "yes"}}})
            def post(self, *a, **kw):
                return MockResponse({})

        c._session = MS()
        data = c.read_secret("any")
        assert data["ok"] == "yes"
        assert c._token == "dev-root-123"  # сессия восстановлена

    def test_default_addr_localhost(self):
        c = VaultClient()
        assert c.addr == DEFAULT_VAULT_ADDR

    def test_custom_addr_from_env(self, monkeypatch):
        monkeypatch.setenv("VAULT_ADDR", "https://vault.prod:8200")
        c = VaultClient()
        assert c.addr == "https://vault.prod:8200"


# ── AppRole mock tests ─────────────────────────────────────────────────

class TestAppRoleAuth:
    def _mock_approle(self, monkeypatch, status=200, resp=None):
        resp = resp or {
            "auth": {
                "client_token": "s.approle-token-abc",
                "lease_duration": 3600,
            }
        }

        class MockResp:
            status_code = status
            _json = resp
            def json(self):
                return self._json
            def raise_for_status(self):
                if self.status_code >= 400:
                    import requests
                    raise requests.HTTPError(f"HTTP {self.status_code}",
                                             response=self)
                return self

        class MockSession:
            def __init__(self):
                self.last_json = None
            def post(self, url, json=None, timeout=None, headers=None):
                self.last_json = json
                if resp and "error" in resp:
                    return type("_R", (), {"status_code": status, "json": lambda: resp, "raise_for_status": lambda: None if status < 400 else (_ for _ in ()).throw(Exception())})()
                return MockResp()

        return MockSession()

    def test_approle_login_success(self, monkeypatch):
        monkeypatch.setenv("VAULT_APPROLE_ROLE_ID", "rid-cosmo-app")
        monkeypatch.setenv("VAULT_APPROLE_SECRET_ID", "sid-secret")
        c = VaultClient()
        c._session = self._mock_approle(monkeypatch)
        c.authenticate()
        assert c._token == "s.approle-token-abc"

    def test_approle_login_401_rejected(self, monkeypatch):
        monkeypatch.setenv("VAULT_APPROLE_ROLE_ID", "rid-bad")
        monkeypatch.setenv("VAULT_APPROLE_SECRET_ID", "sid-bad")
        c = VaultClient()

        class Bad:
            status_code = 401
            def json(self):
                return {"errors": ["bad credentials"]}
            def raise_for_status(self):
                import requests
                raise requests.HTTPError("401 Unauthorized", response=self)

        class BadSession:
            def post(self, *a, **kw):
                return Bad()

        c._session = BadSession()
        with pytest.raises(VaultAuthError, match="AppRole login failed"):
            c.authenticate()

    def test_approle_login_empty_token_in_response(self, monkeypatch):
        monkeypatch.setenv("VAULT_APPROLE_ROLE_ID", "rid-x")
        monkeypatch.setenv("VAULT_APPROLE_SECRET_ID", "sid-x")
        c = VaultClient()

        class EmptyAuth:
            status_code = 200
            def json(self):
                return {"auth": {}}
            def raise_for_status(self):
                return self

        class ES:
            def post(self, *a, **kw):
                return EmptyAuth()

        c._session = ES()
        with pytest.raises(VaultAuthError, match="empty client_token"):
            c.authenticate()

    def test_dev_mode_wins_over_approle(self, monkeypatch):
        """COSMO_ENV=test игнорирует AppRole-энвы."""
        monkeypatch.setenv("COSMO_ENV", "test")
        monkeypatch.setenv("VAULT_DEV_ROOT_TOKEN_ID", "rt")
        monkeypatch.setenv("VAULT_APPROLE_ROLE_ID", "rid")
        monkeypatch.setenv("VAULT_APPROLE_SECRET_ID", "sid")
        c = VaultClient()
        c.authenticate()
        assert c._token == "rt"  # dev token, НЕ approle

    def test_approle_login_sealed_503_raises_unavailable(self, monkeypatch):
        """COS-178: sealed vault на AppRole login → VaultUnavailableError (не VaultAuthError)."""
        monkeypatch.setenv("VAULT_APPROLE_ROLE_ID", "rid-x")
        monkeypatch.setenv("VAULT_APPROLE_SECRET_ID", "sid-x")
        c = VaultClient()

        class Sealed:
            status_code = 503
            def json(self):
                return {"errors": ["Vault is sealed"]}
            def raise_for_status(self):
                import requests
                raise requests.HTTPError("503 sealed", response=self)

        class SealedSession:
            def post(self, *a, **kw):
                return Sealed()

        c._session = SealedSession()
        with pytest.raises(VaultUnavailableError, match="sealed"):
            c.authenticate()


# ── KV secret I/O mock tests ───────────────────────────────────────────

class MockResponse:
    status_code = 200
    _json: dict
    def __init__(self, data: dict, status=200):
        self._json = data
        self.status_code = status
    def json(self):
        return self._json
    def raise_for_status(self):
        if self.status_code >= 400:
            import requests
            raise requests.HTTPError(f"HTTP {self.status_code}", response=self)


class TestKvSecretIO:
    def test_read_ok(self, monkeypatch):
        monkeypatch.setenv("COSMO_ENV", "test")
        monkeypatch.setenv("VAULT_DEV_ROOT_TOKEN_ID", "rt")
        c = VaultClient()
        c.authenticate()

        class MockSess:
            def get(self, url, headers=None, timeout=None):
                return MockResponse({"data": {"data": {"user": "cosmo", "pass": "s3cret"}}})
            def post(self, *a, **kw):
                return MockResponse({})
        c._session = MockSess()
        data = c.read_secret("db-creds")
        assert data["user"] == "cosmo"
        assert data["pass"] == "s3cret"

    def test_read_404_raises_lookup(self, monkeypatch):
        monkeypatch.setenv("COSMO_ENV", "test")
        monkeypatch.setenv("VAULT_DEV_ROOT_TOKEN_ID", "rt")
        c = VaultClient()
        c.authenticate()

        class MS404:
            def get(self, url, headers=None, timeout=None):
                return MockResponse({}, status=404)
            def post(self, *a, **kw):
                return MockResponse({})
        c._session = MS404()
        with pytest.raises(VaultLookupError, match="not found"):
            c.read_secret("nonexistent")

    def test_read_sealed_503_raises_unavailable(self, monkeypatch):
        """COS-178: sealed vault (503) → VaultUnavailableError (surface отдаст 503, не 500)."""
        monkeypatch.setenv("COSMO_ENV", "test")
        monkeypatch.setenv("VAULT_DEV_ROOT_TOKEN_ID", "rt")
        c = VaultClient()
        c.authenticate()

        class MS503:
            def get(self, url, headers=None, timeout=None):
                return MockResponse({"errors": ["Vault is sealed"]}, status=503)
            def post(self, *a, **kw):
                return MockResponse({})
        c._session = MS503()
        with pytest.raises(VaultUnavailableError, match="sealed"):
            c.read_secret("any")

    def test_write_secret(self, monkeypatch):
        monkeypatch.setenv("COSMO_ENV", "test")
        monkeypatch.setenv("VAULT_DEV_ROOT_TOKEN_ID", "rt")
        c = VaultClient()
        c.authenticate()

        posted = {}

        class MSW:
            def post(self, url, headers=None, json=None, timeout=None):
                posted["url"] = url
                posted["body"] = json
                return MockResponse({})
            def get(self, *a, **kw):
                return MockResponse({})

        c._session = MSW()
        c.write_secret("api-tokens", {"github": "ghp_xxx"})
        assert "cosmo/api-tokens" in posted["url"]
        assert posted["body"]["data"]["github"] == "ghp_xxx"

    def test_403_triggers_reauth_on_read(self, monkeypatch):
        """Токен истёк → re-auth → retry → success."""
        monkeypatch.setenv("COSMO_ENV", "test")
        monkeypatch.setenv("VAULT_DEV_ROOT_TOKEN_ID", "rt")
        c = VaultClient()
        c.authenticate()
        call_count = [0]

        class ReAuthSession:
            def get(self, url, headers=None, timeout=None):
                call_count[0] += 1
                if call_count[0] == 1:
                    return MockResponse({}, status=403)
                return MockResponse({"data": {"data": {"ok": "yes"}}})
            def post(self, *a, **kw):
                return MockResponse({})

        c._session = ReAuthSession()
        data = c.read_secret("any")
        assert call_count[0] == 2
        assert data["ok"] == "yes"

    def test_path_is_kv_v2(self, monkeypatch):
        monkeypatch.setenv("COSMO_ENV", "test")
        monkeypatch.setenv("VAULT_DEV_ROOT_TOKEN_ID", "rt")
        c = VaultClient()
        c.authenticate()
        path = c._secret_path("myapp/db")
        assert path == "secret/data/cosmo/myapp/db"


# ── Health test ─────────────────────────────────────────────────────────

class TestHealth:
    def test_health_mock(self, monkeypatch):
        monkeypatch.setenv("COSMO_ENV", "test")
        monkeypatch.setenv("VAULT_DEV_ROOT_TOKEN_ID", "rt")
        c = VaultClient()
        c.authenticate()

        class H:
            def get(self, url, headers=None, timeout=None):
                return MockResponse({"initialized": True, "sealed": False, "version": "2.2.2"})
            def post(self, *a, **kw):
                return MockResponse({})
        c._session = H()
        h = c.health()
        assert h["sealed"] is False
        assert h["version"] == "2.2.2"


# ── Integration: live OpenBao (opt-in gate) ────────────────────────────

@pytest.mark.skipif(not os.getenv(LIVE_GATE), reason=f"{LIVE_GATE} not set")
class TestLiveOpenBao:
    """Живой тест против prettyk-openbao :8200 (dev mode, рут-токен из логов)."""

    @staticmethod
    def _root_token() -> str:
        return _live_root_token()

    def test_dev_root_auth_health(self):
        c = VaultClient(os.getenv("VAULT_ADDR", "http://localhost:8200"))
        c._token = self._root_token()
        h = c.health()
        assert h["initialized"] is True
        assert h["sealed"] is False

    def test_kv_write_read_roundtrip(self):
        c = VaultClient(os.getenv("VAULT_ADDR", "http://localhost:8200"))
        c._token = self._root_token()
        import uuid
        name = f"cos105-test-{uuid.uuid4().hex[:8]}"
        c.write_secret(name, {"alpha": "bravo", "charlie": "delta"})
        data = c.read_secret(name)
        assert data["alpha"] == "bravo"
        assert data["charlie"] == "delta"

    def test_kv_lookup_404(self):
        c = VaultClient(os.getenv("VAULT_ADDR", "http://localhost:8200"))
        c._token = self._root_token()
        with pytest.raises(VaultLookupError, match="not found"):
            c.read_secret("nonexistent-cos105-" + ("x" * 32))

    def test_bad_token_health_still_works(self):
        """Health endpoint НЕ требует аутентификации."""
        c = VaultClient(os.getenv("VAULT_ADDR", "http://localhost:8200"))
        c._token = "not-a-real-token"
        h = c.health()
        assert h["initialized"] is True