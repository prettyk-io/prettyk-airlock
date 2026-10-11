# -*- coding: utf-8 -*-
"""COS-105: OpenBao / HashiCorp Vault — AppRole-адаптер (платформенный).

Режимы:
  1. **Production (AppRole):** VAULT_APPROLE_ROLE_ID + VAULT_APPROLE_SECRET_ID
     → POST /v1/auth/approle/login → client_token с policy ``secret/cosmo/*``.
  2. **Dev (COSMO_ENV=test):** root token из VAULT_DEV_ROOT_TOKEN_ID
     (dev-стенд OpenBao, compose — full access для тестов и локальной
     разработки).

Пути — kv-v2 (``secret/cosmo/…``): ``read_secret`` достаёт ``data.data``,
``write_secret`` пишет ``{"data": …}``.

Сессия не кэширует токен вечно: при 403 (expired token) — re-auth + retry
(идемпотентно для read, аккуратно для write).
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any, Optional

import requests
from requests.adapters import HTTPAdapter, Retry

logger = logging.getLogger("cosmo.vault")

# ── Env канон ──────────────────────────────────────────────────────────

VAULT_ADDR_ENV = "VAULT_ADDR"
DEFAULT_VAULT_ADDR = "http://localhost:8200"

APPROLE_ROLE_ID_ENV = "VAULT_APPROLE_ROLE_ID"
APPROLE_SECRET_ID_ENV = "VAULT_APPROLE_SECRET_ID"
DEV_ROOT_TOKEN_ENV = "VAULT_DEV_ROOT_TOKEN_ID"

COSMO_ENV_ENV = "COSMO_ENV"
SECRET_ENGINE_PREFIX = "secret"  # kv-v2 mount point
COSMO_SECRET_NS = "cosmo"  # под-space в kv-v2

# ── Ошибки ─────────────────────────────────────────────────────────────


class VaultError(RuntimeError):
    """Базовая ошибка Vault-адаптера."""


class VaultAuthError(VaultError):
    """Не удалось аутентифицироваться (bad role/secret, vault down)."""


class VaultLookupError(VaultError):
    """Секрет не найден (404)."""


class VaultNotConfigured(VaultError):
    """Vault не сконфигурирован (COSMO_ENV != test и нет AppRole-энв)."""


class VaultUnavailableError(VaultError):
    """COS-178: Vault недоступен или запечатан (sealed).

    Surface (login/JWKS/…) обязана отдать честный 503, не 500:
    sealed — это неготовность платформы, а не ошибка запроса.
    """


# ── Клиент ─────────────────────────────────────────────────────────────


@dataclass
class VaultClient:
    """AppRole Vault-клиент с автоматической сессией и retry на транзиентах.

    Использование:
        client = VaultClient()
        client.authenticate()
        data = client.read_secret("myapp/db")
        client.write_secret("myapp/db", {"password": "new"})
    """

    addr: str = ""
    _token: Optional[str] = None
    _session: requests.Session | None = None

    def __post_init__(self) -> None:
        if not self.addr:
            self.addr = os.getenv(VAULT_ADDR_ENV, DEFAULT_VAULT_ADDR).rstrip("/")
        self._session = self._make_session()

    @staticmethod
    def _make_session() -> requests.Session:
        s = requests.Session()
        retries = Retry(
            total=3,
            backoff_factor=0.3,
            status_forcelist=[500, 502, 503, 504],
            allowed_methods=frozenset({"GET", "POST"}),
        )
        s.mount("http://", HTTPAdapter(max_retries=retries))
        s.mount("https://", HTTPAdapter(max_retries=retries))
        s.headers.update({"User-Agent": "cosmo-vault/1.0 (COS-105)"})
        return s

    # ── Auth ─────────────────────────────────────────────────────────

    def authenticate(self) -> None:
        """Аутентификация: dev root token или AppRole login.

        COSMO_ENV=test → использует VAULT_DEV_ROOT_TOKEN_ID напрямую.
        Иначе → AppRole login (VAULT_APPROLE_ROLE_ID / …_SECRET_ID).
        """
        if os.getenv(COSMO_ENV_ENV) == "test":
            token = os.getenv(DEV_ROOT_TOKEN_ENV, "").strip()
            if not token:
                raise VaultAuthError(
                    f"{DEV_ROOT_TOKEN_ENV} is empty in test mode "
                    f"({COSMO_ENV_ENV}=test)"
                )
            self._token = token
            logger.info("Vault authenticated via dev root token (%s)", COSMO_ENV_ENV)
            return

        role_id = os.getenv(APPROLE_ROLE_ID_ENV, "").strip()
        secret_id = os.getenv(APPROLE_SECRET_ID_ENV, "").strip()
        if not role_id or not secret_id:
            raise VaultNotConfigured(
                f"{APPROLE_ROLE_ID_ENV} and {APPROLE_SECRET_ID_ENV} "
                f"required (set {COSMO_ENV_ENV}=test for dev mode)"
            )

        try:
            r = self._session.post(
                f"{self.addr}/v1/auth/approle/login",
                json={"role_id": role_id, "secret_id": secret_id},
                timeout=15,
            )
            r.raise_for_status()
        except requests.HTTPError as exc:
            # COS-178: sealed/unavailable vault отвечает 503 — это не «плохие
            # креды», а неготовность платформы; surface отдаст честный 503.
            if getattr(exc, "response", None) is not None and exc.response.status_code == 503:
                raise VaultUnavailableError(
                    f"Vault sealed or unavailable at {self.addr} (HTTP 503)"
                ) from exc
            raise VaultAuthError(
                f"AppRole login failed for role {role_id[:8]}… "
                f"at {self.addr}: {exc}"
            ) from exc
        except requests.RequestException as exc:
            raise VaultAuthError(
                f"AppRole login failed for role {role_id[:8]}… "
                f"at {self.addr}: {exc}"
            ) from exc

        self._token = r.json().get("auth", {}).get("client_token", "")
        if not self._token:
            raise VaultAuthError("AppRole login returned empty client_token")
        logger.info(
            "Vault AppRole login OK (role %s…, ttl=%s)",
            role_id[:8],
            r.json().get("auth", {}).get("lease_duration", "?"),
        )

    @property
    def _headers(self) -> dict[str, str]:
        if not self._token:
            raise VaultAuthError("not authenticated — call authenticate() first")
        return {"X-Vault-Token": self._token}

    def _ensure_token(self) -> None:
        """COS-178: lazy-auth — если токен не выставлен (vault был недоступен
        на старте API и ожил позже), аутентифицироваться здесь и сейчас."""
        if not self._token:
            self.authenticate()

    @staticmethod
    def _check_response(r: requests.Response, what: str) -> None:
        """COS-178: 503 (sealed/unavailable) → VaultUnavailableError, прочее → VaultError."""
        if r.status_code == 503:
            raise VaultUnavailableError(f"{what}: vault sealed or unavailable (HTTP 503)")
        try:
            r.raise_for_status()
        except requests.HTTPError as exc:
            raise VaultError(f"{what} failed: HTTP {r.status_code}") from exc

    # ── Secret I/O ────────────────────────────────────────────────────

    def _secret_path(self, name: str) -> str:
        """kv-v2 data path: secret/data/cosmo/<name>."""
        return f"{SECRET_ENGINE_PREFIX}/data/{COSMO_SECRET_NS}/{name}"

    def read_secret(self, name: str) -> dict[str, Any]:
        """Читает kv-v2 секрет secret/cosmo/<name>.

        Returns:
            dict с полями секрета (data.data из ответа Vault).

        Raises:
            VaultLookupError — секрет не найден (404).
            VaultAuthError — токен истёк и повторная аутентификация
                не удалась.
            VaultError — другие ошибки.
        """
        path = self._secret_path(name)
        self._ensure_token()  # COS-178: lazy-auth (vault мог ожить после старта API)
        try:
            r = self._session.get(f"{self.addr}/v1/{path}", headers=self._headers, timeout=15)
        except requests.RequestException as exc:
            raise VaultError(f"Vault read {path} failed: {exc}") from exc

        if r.status_code == 404:
            raise VaultLookupError(f"Secret {SECRET_ENGINE_PREFIX}/{COSMO_SECRET_NS}/{name} not found")
        if r.status_code in (401, 403):
            # Токен истёк — честная попытка re-auth + retry (один раз)
            logger.warning("Vault token expired, re-authenticating…")
            try:
                self.authenticate()
                r = self._session.get(f"{self.addr}/v1/{path}", headers=self._headers, timeout=15)
            except VaultUnavailableError:
                raise
            except Exception as exc2:
                raise VaultAuthError(f"Vault re-auth failed after 401: {exc2}") from exc2

        self._check_response(r, f"Vault read {path}")
        data = r.json().get("data", {}).get("data", {})
        return data

    def write_secret(self, name: str, data: dict[str, Any]) -> None:
        """Пишет kv-v2 секрет secret/cosmo/<name>."""
        path = self._secret_path(name)
        self._ensure_token()  # COS-178: lazy-auth
        try:
            r = self._session.post(
                f"{self.addr}/v1/{path}",
                headers=self._headers,
                json={"data": data},
                timeout=15,
            )
        except requests.RequestException as exc:
            raise VaultError(f"Vault write {path} failed: {exc}") from exc

        if r.status_code in (401, 403):
            logger.warning("Vault token expired on write, re-authenticating…")
            self.authenticate()
            r = self._session.post(
                f"{self.addr}/v1/{path}", headers=self._headers, json={"data": data}, timeout=15,
            )

        self._check_response(r, f"Vault write {path}")
        logger.info("Vault secret %s written", name)

    # ── Health ────────────────────────────────────────────────────────

    def health(self) -> dict[str, Any]:
        """GET /v1/sys/health — статус кластера (без аутентификации)."""
        r = self._session.get(f"{self.addr}/v1/sys/health", timeout=10)
        r.raise_for_status()
        return r.json()  # {"initialized": bool, "sealed": bool, ...}

    def close(self) -> None:
        if self._session:
            self._session.close()
            self._session = None