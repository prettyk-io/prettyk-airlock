# -*- coding: utf-8 -*-
"""COS-156: крипто-верификация JWT вместо формат-чека (PK — боевой identity).

Назначение: заменить base64-парсинг payload-сегмента (COS-085) честной
проверкой **подписи** и claim-контракта. «Формат ``ey…``» больше не является
достаточным признаком аутентификации — только крипто-подпись.

Источник ключей (в порядке приоритета):
  1. ``COSMO_JWT_JWKS_URL`` — JWKS endpoint (``{"keys":[{kty, kid, alg, …}]}``);
  2. ``COSMO_JWT_PUBLIC_KEY`` — статичный публичный ключ SPKI-PEM (RSA или EC,
     несколько ключей допускается конкатенацией);
  3. платформенный OpenBao ``secret/cosmo/jwt-keys`` (best-effort, kv-v2):
     ``{"jwks_url"|"public_key", "issuers", "audience", "algorithms"}``;
  4. ``COSMO_JWT_DEV_PUBLIC_KEY`` — **dev-контур** (только когда
     ``COSMO_ENV=test``): реальный RS256-ключ для CI/ручного прогона suite gate
     без внешнего issuer. НЕ боевой ключ — документирован как dev.

Fail-closed: если ни один источник ключей не сконфигурирован → верификация
отказывает (результат 401 на уровне deps), НЕ дефолтный success.

Claim-проверки (после подписи):
  - ``exp`` (если есть) — не истёкший;
  - ``nbf`` (если есть) — не «ещё не валиден»;
  - ``iss`` — если сконфигурирован allowlist (``COSMO_JWT_ISSUERS``), токен с
    иным ``iss`` отклоняется;
  - ``aud`` — если сконфигурирован (``COSMO_JWT_AUDIENCE``), проверяется
    на вхождение (claim-``aud`` может быть строкой или списком).

Алгоритмы: RS256 всегда, ES256 опционально (закрытый список, ``none``/HS* —
запрещены). Подпись — ``cryptography`` (без внешней JWT-библиотеки).
"""
from __future__ import annotations

import base64
import json
import logging
import os
import time
import threading
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

import requests

logger = logging.getLogger("cosmo.security.jwt")


# ── Env-канон ────────────────────────────────────────────────────────────

JWKS_URL_ENV = "COSMO_JWT_JWKS_URL"
PUBLIC_KEY_ENV = "COSMO_JWT_PUBLIC_KEY"
DEV_PUBLIC_KEY_ENV = "COSMO_JWT_DEV_PUBLIC_KEY"
ISSUERS_ENV = "COSMO_JWT_ISSUERS"
AUDIENCE_ENV = "COSMO_JWT_AUDIENCE"
ALGORITHMS_ENV = "COSMO_JWT_ALGORITHMS"
COSMO_ENV_ENV = "COSMO_ENV"

VAULT_JWT_SECRET = "jwt-keys"

DEFAULT_ALGORITHMS = ("RS256", "ES256")

#: JWKS-кэш: TTL в секундах (не дёргаем endpoint на каждый запрос).
_JWKS_CACHE_TTL = 300.0


class JwtVerificationError(ValueError):
    """Не удалось верифицировать JWT (подпись/claims/ключи).

    Безопасно маппится в 401 на уровне ``deps.get_current_principal``.
    """


@dataclass(frozen=True)
class JwtConfig:
    """Конфигурация верификации — immutable снапшот env (+vault)."""

    jwks_url: str = ""
    public_keys: tuple[str, ...] = ()
    issuers: tuple[str, ...] = ()
    audience: str = ""
    algorithms: tuple[str, ...] = DEFAULT_ALGORITHMS

    @property
    def has_key_source(self) -> bool:
        return bool(self.jwks_url or self.public_keys)


# ── Кэш JWKS ─────────────────────────────────────────────────────────────

_jwks_cache_lock = threading.Lock()
_jwks_cache: dict[str, tuple[float, dict[str, Any]]] = {}


def reset_jwt_key_cache() -> None:
    """Сбросить JWKS-кэш (для тестов)."""
    with _jwks_cache_lock:
        _jwks_cache.clear()


def _fetch_jwks(url: str, timeout: float = 10.0) -> dict[str, Any]:
    """Скачать JWKS. Кэшируется по URL с TTL; ошибки честно всплывают."""
    now = time.time()
    with _jwks_cache_lock:
        hit = _jwks_cache.get(url)
        if hit and (now - hit[0]) < _JWKS_CACHE_TTL:
            return hit[1]
    try:
        r = requests.get(url, timeout=timeout)
    except requests.RequestException as exc:
        raise JwtVerificationError(f"JWKS fetch failed for {url}: {exc}") from exc
    if r.status_code != 200:
        raise JwtVerificationError(f"JWKS endpoint {url} returned HTTP {r.status_code}")
    try:
        doc = r.json()
    except ValueError as exc:
        raise JwtVerificationError(f"JWKS endpoint {url} returned non-JSON: {exc}") from exc
    if not isinstance(doc, dict) or not isinstance(doc.get("keys"), list):
        raise JwtVerificationError(f"JWKS endpoint {url} has invalid structure")
    with _jwks_cache_lock:
        _jwks_cache[url] = (now, doc)
    return doc


# ── Конфигурация ─────────────────────────────────────────────────────────

def _split_csv(raw: str) -> tuple[str, ...]:
    return tuple(p.strip() for p in (raw or "").split(",") if p.strip())


def load_jwt_config(
    env: dict[str, str] | None = None,
    *,
    vault_reader: Optional[Callable[[str], dict[str, Any]]] = None,
) -> JwtConfig:
    """Собрать JwtConfig из env (+ best-effort OpenBao fallback).

    Порядок ключей: JWKS URL → static public key → OpenBao → dev-public-key
    (dev-ключ учитывается только при ``COSMO_ENV=test``). OpenBao трогаем
    только вне test-контура (в test ключи задаются env/dev-ключом явно).
    """
    env = env if env is not None else dict(os.environ)

    jwks_url = env.get(JWKS_URL_ENV, "").strip()
    public_key = env.get(PUBLIC_KEY_ENV, "").strip()
    dev_pub = env.get(DEV_PUBLIC_KEY_ENV, "").strip()

    issuers = _split_csv(env.get(ISSUERS_ENV, ""))
    audience = env.get(AUDIENCE_ENV, "").strip()
    algorithms = _split_csv(env.get(ALGORITHMS_ENV, "")) or DEFAULT_ALGORITHMS

    # OpenBao fallback (только если env-источники пусты; vault — prod-контур).
    if not jwks_url and not public_key and env.get(COSMO_ENV_ENV, "").strip() != "test":
        vault_cfg: dict[str, Any] = {}
        if vault_reader is not None:
            try:
                vault_cfg = vault_reader(VAULT_JWT_SECRET) or {}
            except Exception as exc:  # noqa: BLE001 — best-effort
                logger.warning("OpenBao jwt-keys read failed (best-effort): %s", exc)
        if isinstance(vault_cfg, dict):
            jwks_url = str(vault_cfg.get("jwks_url") or "").strip()
            if not public_key:
                pk = vault_cfg.get("public_key")
                if isinstance(pk, str):
                    public_key = pk.strip()
                elif isinstance(pk, list):
                    public_key = "\n".join(str(k).strip() for k in pk if str(k).strip())
            if not issuers:
                iss_v = vault_cfg.get("issuers")
                if isinstance(iss_v, list):
                    issuers = tuple(str(i).strip() for i in iss_v if str(i).strip())
                elif isinstance(iss_v, str) and iss_v.strip():
                    issuers = _split_csv(iss_v)
            if not audience:
                audience = str(vault_cfg.get("audience") or "").strip()
            if not algorithms:
                alg_v = vault_cfg.get("algorithms")
                if isinstance(alg_v, list):
                    algorithms = tuple(str(a).strip() for a in alg_v if str(a).strip())

    # Dev-ключ — только dev-контур, и только если боевых источников нет.
    if not jwks_url and not public_key and env.get(COSMO_ENV_ENV, "").strip() == "test":
        if dev_pub:
            public_key = dev_pub
            logger.warning(
                "JWT verification using COSMO_JWT_DEV_PUBLIC_KEY (dev contour only)"
            )

    keys: tuple[str, ...] = ()
    if public_key:
        keys = tuple(_iter_pem_blocks(public_key))

    return JwtConfig(
        jwks_url=jwks_url,
        public_keys=keys,
        issuers=issuers,
        audience=audience,
        algorithms=algorithms,
    )


def _iter_pem_blocks(pem_text: str) -> list[str]:
    """Разбить (возможно конкатенированную) PEM-строку на отдельные блоки."""
    blocks: list[str] = []
    cur: list[str] = []
    for line in pem_text.splitlines():
        if line.strip():
            cur.append(line)
        if line.strip().startswith("-----END"):
            blocks.append("\n".join(cur) + "\n")
            cur = []
    # Неполный блок — пробуем целиком (single key без хвостового переноса).
    if cur and not blocks:
        blocks.append("\n".join(cur))
    return [b for b in blocks if "-----BEGIN" in b]


# ── Декодирование / базовая валидация ────────────────────────────────────

def _b64url_decode(seg: str) -> bytes:
    padded = seg + "=" * (-len(seg) % 4)
    try:
        return base64.urlsafe_b64decode(padded)
    except Exception as exc:  # noqa: BLE001
        raise JwtVerificationError("token segment is not valid base64url") from exc


def _decode_json(seg_b64: str) -> dict[str, Any]:
    raw = _b64url_decode(seg_b64)
    try:
        obj = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise JwtVerificationError("token segment is not valid JSON") from exc
    if not isinstance(obj, dict):
        raise JwtVerificationError("token segment is not a JSON object")
    return obj


def _split_token(token: str) -> tuple[str, str, str]:
    if not isinstance(token, str) or not token.strip():
        raise JwtVerificationError("token is missing or not a string")
    parts = token.split(".")
    if len(parts) != 3 or not all(parts):
        raise JwtVerificationError("token is not a JWS (header.payload.signature)")
    return parts[0], parts[1], parts[2]


# ── Ключи ────────────────────────────────────────────────────────────────

def _load_spki_pem(pem: str):
    from cryptography.hazmat.primitives import serialization

    data = pem.encode("utf-8")
    try:
        return serialization.load_pem_public_key(data)
    except Exception as exc:  # noqa: BLE001
        raise JwtVerificationError("configured public key is not valid SPKI PEM") from exc


def _pubkey_from_jwk(jwk: dict[str, Any]):
    """Собрать cryptography-ключ из JWK (RSA: n/e; EC: crv/x/y)."""
    from cryptography.hazmat.primitives.asymmetric import ec, rsa

    kty = jwk.get("kty")
    if kty == "RSA":
        n_b64 = jwk.get("n")
        e_b64 = jwk.get("e")
        if not n_b64 or not e_b64:
            raise JwtVerificationError("RSA JWK missing n/e")
        n = int.from_bytes(_b64url_decode(n_b64), "big")
        e = int.from_bytes(_b64url_decode(e_b64), "big")
        return rsa.RSAPublicNumbers(e, n).public_key()
    if kty == "EC":
        crv = jwk.get("crv")
        x_b64 = jwk.get("x")
        y_b64 = jwk.get("y")
        if crv != "P-256" or not x_b64 or not y_b64:
            raise JwtVerificationError("EC JWK must be P-256 with x/y")
        curve = ec.SECP256R1()
        x = int.from_bytes(_b64url_decode(x_b64), "big")
        y = int.from_bytes(_b64url_decode(y_b64), "big")
        return ec.EllipticCurvePublicNumbers(x, y, curve).public_key()
    raise JwtVerificationError(f"unsupported JWK kty={kty!r}")


def _alg_for_key(key) -> str:
    from cryptography.hazmat.primitives.asymmetric import ec, rsa

    if isinstance(key, rsa.RSAPublicKey):
        return "RS256"
    if isinstance(key, ec.EllipticCurvePublicKey):
        return "ES256"
    raise JwtVerificationError("unsupported public key type")


def _resolve_verification_key(
    header: dict[str, Any],
    cfg: JwtConfig,
    *,
    jwks_fetcher: Optional[Callable[[str], dict[str, Any]]] = None,
):
    """Выбрать/собрать публичный ключ под подпись токена.

    Fail-closed: нет источника ключей → ошибка. ``kid``/``alg`` учитываются
    для JWKS; для статичных PEM-ключей выбираем ключ совпадающего типа.
    """
    if not cfg.has_key_source:
        raise JwtVerificationError(
            "JWT verification keys are not configured "
            "(set COSMO_JWT_JWKS_URL / COSMO_JWT_PUBLIC_KEY "
            "/ COSMO_JWT_DEV_PUBLIC_KEY in test)"
        )

    alg = str(header.get("alg") or "")
    if alg not in cfg.algorithms:
        raise JwtVerificationError(f"token alg {alg!r} not in allowed {list(cfg.algorithms)}")

    if cfg.jwks_url:
        fetch = jwks_fetcher or _fetch_jwks
        doc = fetch(cfg.jwks_url)
        keys = doc.get("keys") or []
        kid = header.get("kid")
        for jwk in keys:
            jwk_alg = jwk.get("alg")
            if jwk_alg and jwk_alg != alg:
                continue
            if kid and jwk.get("kid") != kid:
                continue
            candidate = _pubkey_from_jwk(jwk)
            if _alg_for_key(candidate) != alg:
                continue
            return candidate
        raise JwtVerificationError("no matching key in JWKS for token")

    # Статичные ключи
    for pem in cfg.public_keys:
        candidate = _load_spki_pem(pem)
        if _alg_for_key(candidate) == alg:
            return candidate
    raise JwtVerificationError(
        f"no configured public key supports token alg {alg!r}"
    )


# ── Верификация подписи ──────────────────────────────────────────────────

def _verify_signature(
    signing_input: bytes,
    signature: bytes,
    key,
    alg: str,
) -> None:
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec, padding

    try:
        if alg == "RS256":
            key.verify(
                signature, signing_input, padding.PKCS1v15(), hashes.SHA256(),
            )
        elif alg == "ES256":
            from cryptography.hazmat.primitives.asymmetric import utils

            # JWT ES256: raw R||S → DER для cryptography.
            der_sig = utils.encode_dss_signature(
                int.from_bytes(signature[:32], "big"),
                int.from_bytes(signature[32:], "big"),
            )
            key.verify(der_sig, signing_input, ec.ECDSA(hashes.SHA256()))
        else:  # pragma: no cover — alg уже закрыт resolve-шагом
            raise JwtVerificationError(f"unsupported alg {alg!r}")
    except (InvalidSignature, ValueError) as exc:
        raise JwtVerificationError("JWT signature verification failed") from exc


# ── Claim-валидация ──────────────────────────────────────────────────────

def _validate_claims(claims: dict[str, Any], cfg: JwtConfig, now: float) -> None:
    exp = claims.get("exp")
    if exp is not None:
        if not isinstance(exp, (int, float)) or now >= float(exp):
            raise JwtVerificationError("JWT is expired (exp)")

    nbf = claims.get("nbf")
    if nbf is not None:
        if not isinstance(nbf, (int, float)) or now < float(nbf):
            raise JwtVerificationError("JWT is not yet valid (nbf)")

    if cfg.issuers:
        iss = claims.get("iss")
        if not isinstance(iss, str) or iss not in cfg.issuers:
            raise JwtVerificationError("JWT issuer not in allowlist")

    if cfg.audience:
        aud = claims.get("aud")
        if isinstance(aud, list):
            ok = cfg.audience in aud
        else:
            ok = aud == cfg.audience
        if not ok:
            raise JwtVerificationError("JWT audience does not match")


# ── Основной entrypoint ──────────────────────────────────────────────────

def verify_jwt(
    token: str,
    *,
    env: dict[str, str] | None = None,
    now: Optional[float] = None,
    jwks_fetcher: Optional[Callable[[str], dict[str, Any]]] = None,
    vault_reader: Optional[Callable[[str], dict[str, Any]]] = None,
) -> dict[str, Any]:
    """Верифицировать JWT: подпись + claims. Возвращает claims (verified).

    Raises:
        JwtVerificationError: любое нарушение (подпись/alg/claims/нет ключей).
    """
    if vault_reader is None:
        vault_reader = default_vault_reader
    cfg = load_jwt_config(env, vault_reader=vault_reader)
    header_b64, payload_b64, sig_b64 = _split_token(token)

    header = _decode_json(header_b64)
    claims = _decode_json(payload_b64)
    signature = _b64url_decode(sig_b64)

    alg = str(header.get("alg") or "")
    if alg == "none":
        raise JwtVerificationError("alg=none tokens are not accepted")
    if alg.startswith("HS"):
        raise JwtVerificationError(f"HMAC alg {alg!r} not accepted (asymmetric only)")

    key = _resolve_verification_key(header, cfg, jwks_fetcher=jwks_fetcher)
    _verify_signature(
        (header_b64 + "." + payload_b64).encode("ascii"), signature, key, alg,
    )
    _validate_claims(claims, cfg, now if now is not None else time.time())
    return claims


def default_vault_reader(name: str) -> dict[str, Any]:
    """Best-effort чтение ``secret/cosmo/jwt-keys`` через VaultClient (COS-105).

    Броски исключений — признак «vault не доступен/сконфигурирован»; вызывающий
    код (load_jwt_config) обрабатывает их как best-effort.
    """
    from orchestrator.cosmo.infra.vault import VaultClient

    client = VaultClient()
    client.authenticate()
    return client.read_secret(name)