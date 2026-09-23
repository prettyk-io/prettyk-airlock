# -*- coding: utf-8 -*-
"""COS-156: крипто-верификация JWT (security.jwt_verifier) — unit-матрица.

Проверяет честную проверку подписи + claim-контракт вместо формат-чека:
  - валидный RS256 → claims;
  - forged signature → 401 (JwtVerificationError);
  - expired (exp) / not-yet-valid (nbf) → отказ;
  - iss не в allowlist → отказ;
  - aud не совпадает → отказ;
  - alg=none / HS256 → отказ;
  - unsigned/opaque/garbage → отказ;
  - fail-closed: ключи не сконфигурированы → отказ (не дефолтный success);
  - dev-ключ COSMO_JWT_DEV_PUBLIC_KEY работает только при COSMO_ENV=test.

Внешние issuer/JWKS не требуются: ключ из ``_jwt_testkey`` (тестовая фикстура).
"""
from __future__ import annotations

import time

import pytest

from _jwt_testkey import (
    TEST_PUBLIC_KEY_PEM,
    mint_alg_none,
    mint_rs256,
    tamper_signature,
)

from orchestrator.cosmo.security.jwt_verifier import (
    JwtVerificationError,
    load_jwt_config,
    verify_jwt,
)

# env, при котором static public key подхватывается (COSMO_ENV неважен для
# COSMO_JWT_PUBLIC_KEY — это боевой источник, не dev).
_BASE_ENV = {"COSMO_JWT_PUBLIC_KEY": TEST_PUBLIC_KEY_PEM}


def _verify(token: str, env: dict | None = None, **kw) -> dict:
    return verify_jwt(token, env=env if env is not None else dict(_BASE_ENV), **kw)


# ── подпись ────────────────────────────────────────────────────────────


def test_valid_rs256_returns_claims():
    claims = {"sub": "luna", "roles": ["user"]}
    token = mint_rs256(claims)
    out = _verify(token)
    assert out["sub"] == "luna"
    assert out["roles"] == ["user"]


def test_forged_signature_rejected():
    token = tamper_signature(mint_rs256({"sub": "x"}))
    with pytest.raises(JwtVerificationError):
        _verify(token)


def test_signed_with_other_key_rejected():
    from cryptography.hazmat.primitives.asymmetric import rsa

    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    from cryptography.hazmat.primitives import serialization

    other_pem = other.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    token = mint_rs256({"sub": "x"}, private_key_pem=other_pem)
    with pytest.raises(JwtVerificationError):
        _verify(token)


def test_alg_none_rejected():
    token = mint_alg_none({"sub": "x", "roles": ["admin_sec"], "is_admin": True})
    with pytest.raises(JwtVerificationError):
        _verify(token)


def test_hs256_rejected():
    import base64
    import json

    def b64(d: bytes) -> str:
        return base64.urlsafe_b64encode(d).decode().rstrip("=")

    hdr = b64(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    payload = b64(json.dumps({"sub": "x"}).encode())
    token = f"{hdr}.{payload}.c2ln"
    with pytest.raises(JwtVerificationError):
        _verify(token)


# ── claims ─────────────────────────────────────────────────────────────


def test_expired_rejected():
    claims = {"sub": "x", "exp": int(time.time()) - 10}
    with pytest.raises(JwtVerificationError):
        _verify(mint_rs256(claims))


def test_nbf_future_rejected():
    claims = {"sub": "x", "nbf": int(time.time()) + 60}
    with pytest.raises(JwtVerificationError):
        _verify(mint_rs256(claims))


def test_exp_and_nbf_within_window_accepted():
    now = int(time.time())
    claims = {"sub": "x", "exp": now + 60, "nbf": now - 60}
    assert _verify(mint_rs256(claims))["sub"] == "x"


def test_iss_not_in_allowlist_rejected():
    env = dict(_BASE_ENV, COSMO_JWT_ISSUERS="https://issuer.internal")
    token = mint_rs256({"sub": "x", "iss": "https://evil.example"})
    with pytest.raises(JwtVerificationError):
        _verify(token, env=env)


def test_iss_in_allowlist_accepted():
    env = dict(_BASE_ENV, COSMO_JWT_ISSUERS="https://issuer.internal")
    token = mint_rs256({"sub": "x", "iss": "https://issuer.internal"})
    assert _verify(token, env=env)["iss"] == "https://issuer.internal"


def test_aud_mismatch_rejected():
    env = dict(_BASE_ENV, COSMO_JWT_AUDIENCE="cosmo-api")
    with pytest.raises(JwtVerificationError):
        _verify(mint_rs256({"sub": "x", "aud": "other"}), env=env)


def test_aud_match_accepted():
    env = dict(_BASE_ENV, COSMO_JWT_AUDIENCE="cosmo-api")
    token = mint_rs256({"sub": "x", "aud": "cosmo-api"})
    assert _verify(token, env=env)["aud"] == "cosmo-api"


# ── формат / fail-closed ───────────────────────────────────────────────


@pytest.mark.parametrize("bad", ["", "not-a-jwt", "a.b", "a.b.c.d", None])
def test_malformed_rejected(bad):
    with pytest.raises(JwtVerificationError):
        verify_jwt(bad, env=dict(_BASE_ENV))


def test_fail_closed_no_key_source():
    with pytest.raises(JwtVerificationError):
        verify_jwt(mint_rs256({"sub": "x"}), env={})


def test_fail_closed_no_key_source_opaque():
    with pytest.raises(JwtVerificationError):
        verify_jwt("garbage.sig.x", env={})


# ── конфигурация / dev-ключ ────────────────────────────────────────────


def test_dev_key_only_in_test_env():
    env = {"COSMO_ENV": "test", "COSMO_JWT_DEV_PUBLIC_KEY": TEST_PUBLIC_KEY_PEM}
    cfg = load_jwt_config(env)
    assert cfg.has_key_source is True
    assert _verify(mint_rs256({"sub": "x"}), env=env)["sub"] == "x"


def test_dev_key_ignored_outside_test_env():
    env = {"COSMO_ENV": "prod", "COSMO_JWT_DEV_PUBLIC_KEY": TEST_PUBLIC_KEY_PEM}
    cfg = load_jwt_config(env)
    assert cfg.has_key_source is False
    with pytest.raises(JwtVerificationError):
        _verify(mint_rs256({"sub": "x"}), env=env)


def test_algorithms_allowlist_enforced():
    env = dict(_BASE_ENV, COSMO_JWT_ALGORITHMS="ES256")
    with pytest.raises(JwtVerificationError):
        _verify(mint_rs256({"sub": "x"}), env=env)
