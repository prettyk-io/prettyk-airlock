# -*- coding: utf-8 -*-
"""COS-157: issuer — выдача RS256 JWT + JWKS (боевой identity).

Назначение: вторая половина боевой auth-линии. ``security/jwt_verifier``
(COS-156) уже проверяет подпись; здесь — **выпускающая** сторона: мятёж
подписанных токенов и JWKS-эндпоинт для verifier'а.

Ключевое:
- приватный signing-ключ читается ТОЛЬКО из OpenBao ``secret/cosmo/jwt-keys``
  (``rsa_private``) через AppRole ``cosmo-app`` (``VaultClient`` COS-105) —
  НЕ из кода / ``.env`` / git;
- публичный ключ (``rsa_public``) — для JWKS (RFC 7517, ``n``/``e``);
- ``kid`` стабильно выводится из SPKI публичного ключа (SHA-256), если не
  задан явно в секрете — чтобы verifier однозначно резолвил ключ по ``kid``;
- подпись — RS256 (``PKCS1v15`` + ``SHA256``), ровно тот же алгоконтракт, что
  принимает ``jwt_verifier``.

Форма ``secret/cosmo/jwt-keys`` (канон, см. research COS-157):
    {
      "rsa_private": "<PKCS#8 PEM>",
      "rsa_public":  "<SPKI PEM>",
      "issuers": ["cosmoport"],
      "audience": "cosmo-api",
      "kid": "",            # опционально
      "ttl_seconds": 3600   # опционально
    }
"""
from __future__ import annotations

import base64
import hashlib
import json
import time
from dataclasses import dataclass
from typing import Any, Callable, Optional

JWT_KEYS_SECRET = "jwt-keys"
DEFAULT_ISSUER = "cosmoport"
DEFAULT_TTL_SECONDS = 3600


class IssuerConfigError(RuntimeError):
    """Не удалось загрузить signing-конфигурацию (нет ключа / нет vault).

    Маппится в явную ошибку (не дефолт-success) на уровне auth-роута.
    """


@dataclass(frozen=True)
class IssuerConfig:
    """Immutable снапшот signing-конфигурации из ``secret/cosmo/jwt-keys``."""

    private_key_pem: str
    public_key_pem: str
    kid: str
    issuer: str = DEFAULT_ISSUER
    audience: str = ""
    ttl_seconds: int = DEFAULT_TTL_SECONDS

    @classmethod
    def load(cls, reader: Optional[Callable[[str], dict[str, Any]]] = None) -> "IssuerConfig":
        """Собрать IssuerConfig через ``reader("jwt-keys")`` (AppRole-read)."""
        data = (reader or default_reader)(JWT_KEYS_SECRET) or {}
        if not isinstance(data, dict):
            data = {}
        private = str(data.get("rsa_private") or "").strip()
        public = str(data.get("rsa_public") or "").strip()
        if not private or not public:
            raise IssuerConfigError(
                f"secret/cosmo/{JWT_KEYS_SECRET} lacks rsa_private/rsa_public "
                f"(issuer keypair not bootstrapped)"
            )

        kid = str(data.get("kid") or "").strip() or derive_kid(public)

        issuers = data.get("issuers")
        if isinstance(issuers, list) and issuers:
            issuer = str(issuers[0]).strip()
        else:
            issuer = str(data.get("issuer") or DEFAULT_ISSUER).strip()

        audience = str(data.get("audience") or "").strip()
        try:
            ttl = int(data.get("ttl_seconds") or DEFAULT_TTL_SECONDS)
        except (TypeError, ValueError):
            ttl = DEFAULT_TTL_SECONDS

        return cls(
            private_key_pem=private,
            public_key_pem=public,
            kid=kid,
            issuer=issuer,
            audience=audience,
            ttl_seconds=max(1, ttl),
        )


# ── Ключи ────────────────────────────────────────────────────────────────

def _load_private_key(pem: str):
    from cryptography.hazmat.primitives import serialization

    return serialization.load_pem_private_key(pem.encode("utf-8"), password=None)


def derive_kid(public_key_pem: str, length: int = 16) -> str:
    """Стабильный ``kid``: SHA-256(SPKI-der)[:length] → base64url."""
    from cryptography.hazmat.primitives import serialization

    key = serialization.load_pem_public_key(public_key_pem.encode("utf-8"))
    der = key.public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return base64.urlsafe_b64encode(hashlib.sha256(der).digest()[:length]).decode().rstrip("=")


def _rsa_public_numbers(public_key_pem: str) -> tuple[int, int]:
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives import serialization

    key = serialization.load_pem_public_key(public_key_pem.encode("utf-8"))
    if not isinstance(key, rsa.RSAPublicKey):
        raise IssuerConfigError("jwt-keys.rsa_public is not an RSA public key")
    nums = key.public_numbers()
    return nums.n, nums.e


# ── base64url (RFC 7515) ─────────────────────────────────────────────────

def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64url_int(value: int) -> str:
    return _b64url(value.to_bytes((value.bit_length() + 7) // 8 or 1, "big"))


# ── Mint ─────────────────────────────────────────────────────────────────

def mint_access_token(
    cfg: IssuerConfig,
    *,
    sub: str,
    email: str,
    roles: Optional[list[str]] = None,
    scopes: Optional[list[str]] = None,
    is_admin: bool = False,
    now: Optional[float] = None,
    ttl: Optional[int] = None,
) -> str:
    """Выпустить подписанный RS256 access-токен.

    Claims: ``sub``/``email``/``roles``/``scopes``/``is_admin`` (identity) +
    ``iss``/``iat``/``nbf``/``exp`` и опционально ``aud`` — ровно тот контракт,
    который читает ``deps.get_current_principal`` из верифицированных claims.
    """
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding

    now = int(now if now is not None else time.time())
    ttl = ttl if ttl is not None else cfg.ttl_seconds

    claims: dict[str, Any] = {
        "sub": sub,
        "email": email,
        "iss": cfg.issuer,
        "iat": now,
        "nbf": now,
        "exp": now + ttl,
        "is_admin": bool(is_admin),
    }
    if roles:
        claims["roles"] = [str(r) for r in roles]
    if scopes:
        claims["scopes"] = [str(s) for s in scopes]
    if cfg.audience:
        claims["aud"] = cfg.audience

    header = {"alg": "RS256", "typ": "JWT", "kid": cfg.kid}
    header_b64 = _b64url(json.dumps(header, separators=(",", ":")).encode("utf-8"))
    payload_b64 = _b64url(json.dumps(claims, separators=(",", ":")).encode("utf-8"))
    signing_input = f"{header_b64}.{payload_b64}".encode("ascii")

    key = _load_private_key(cfg.private_key_pem)
    signature = key.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
    return f"{header_b64}.{payload_b64}.{_b64url(signature)}"


# ── JWKS (RFC 7517) ──────────────────────────────────────────────────────

def build_jwks(cfg: IssuerConfig) -> dict[str, Any]:
    """Собрать JWKS из ``rsa_public`` (ключ, понятный verifier COS-156)."""
    n, e = _rsa_public_numbers(cfg.public_key_pem)
    return {
        "keys": [
            {
                "kty": "RSA",
                "use": "sig",
                "alg": "RS256",
                "kid": cfg.kid,
                "n": _b64url_int(n),
                "e": _b64url_int(e),
            }
        ]
    }


# ── Чтение из OpenBao ────────────────────────────────────────────────────

def default_reader(name: str) -> dict[str, Any]:
    """Best-effort чтение ``secret/cosmo/<name>`` через VaultClient (COS-105).

    Бросок — признак «vault недоступен/не сконфигурирован».
    """
    from orchestrator.cosmo.infra.vault import VaultClient

    client = VaultClient()
    client.authenticate()
    return client.read_secret(name)