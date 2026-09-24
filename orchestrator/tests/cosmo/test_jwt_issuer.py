# -*- coding: utf-8 -*-
"""COS-157: unit-тесты issuer (mint RS256 + JWKS + config)."""
from __future__ import annotations

import json

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from orchestrator.cosmo.security.jwt_issuer import (
    IssuerConfig,
    IssuerConfigError,
    build_jwks,
    derive_kid,
    mint_access_token,
)
from orchestrator.cosmo.security.jwt_verifier import verify_jwt


def _keypair() -> tuple[str, str]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    priv = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode("utf-8")
    pub = key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")
    return priv, pub


def _cfg() -> IssuerConfig:
    priv, pub = _keypair()
    return IssuerConfig(
        private_key_pem=priv,
        public_key_pem=pub,
        kid=derive_kid(pub),
        issuer="cosmoport",
        audience="cosmo-api",
        ttl_seconds=3600,
    )


# ── Mint → JWKS → verify: сквозной unit-прогон ───────────────────────────

def test_mint_jwks_verify_roundtrip():
    """Выпущенный токен проходит verifier COS-156 через JWKS (не unit-mock)."""
    cfg = _cfg()
    token = mint_access_token(
        cfg,
        sub="admin",
        email="admin@kits.bank.corp",
        roles=["admin_sec"],
        scopes=["build:run"],
        is_admin=True,
    )

    jwks = build_jwks(cfg)
    claims = verify_jwt(
        token,
        env={
            "COSMO_JWT_JWKS_URL": "http://cosmo-api/.well-known/jwks.json",
            "COSMO_JWT_ISSUERS": "cosmoport",
            "COSMO_JWT_AUDIENCE": "cosmo-api",
        },
        jwks_fetcher=lambda url: jwks,
    )

    assert claims["sub"] == "admin"
    assert claims["email"] == "admin@kits.bank.corp"
    assert claims["roles"] == ["admin_sec"]
    assert claims["scopes"] == ["build:run"]
    assert claims["is_admin"] is True
    assert claims["iss"] == "cosmoport"
    assert claims["aud"] == "cosmo-api"


def test_mint_verify_static_public_key():
    """Тот же токен проходит verifier и по статичному PEM (COSMO_JWT_PUBLIC_KEY)."""
    cfg = _cfg()
    token = mint_access_token(cfg, sub="u", email="u@kits.bank.corp", roles=["user"])
    claims = verify_jwt(
        token,
        env={
            "COSMO_JWT_PUBLIC_KEY": cfg.public_key_pem,
            "COSMO_JWT_ISSUERS": "cosmoport",
        },
    )
    assert claims["sub"] == "u"
    assert claims["is_admin"] is False


def test_tampered_token_rejected():
    """Подмена подписи → verifier отклоняет (не issuer «прощает»)."""
    cfg = _cfg()
    token = mint_access_token(cfg, sub="u", email="u@kits.bank.corp")
    head, payload, sig = token.rsplit(".", 2)
    forged_sig = ("A" if not sig.endswith("A") else "B") + sig[1:]
    bad = f"{head}.{payload}.{forged_sig}"
    from orchestrator.cosmo.security.jwt_verifier import JwtVerificationError

    with pytest.raises(JwtVerificationError):
        verify_jwt(
            bad,
            env={"COSMO_JWT_PUBLIC_KEY": cfg.public_key_pem},
        )


# ── JWKS структура ───────────────────────────────────────────────────────

def test_jwks_shape():
    """JWKS — RFC 7517: kty/use/alg/kid/n/e."""
    cfg = _cfg()
    jwks = build_jwks(cfg)
    assert list(jwks.keys()) == ["keys"]
    key = jwks["keys"][0]
    assert key["kty"] == "RSA"
    assert key["use"] == "sig"
    assert key["alg"] == "RS256"
    assert key["kid"] == cfg.kid
    # n/e — base64url без padding
    assert "=" not in key["n"]
    assert "=" not in key["e"]


def test_jwks_key_matches_public_numbers():
    """n/e в JWKS совпадают с публичным ключом (roundtrip через cryptography)."""
    cfg = _cfg()
    jwks = build_jwks(cfg)

    from orchestrator.cosmo.security.jwt_verifier import _b64url_decode, _pubkey_from_jwk

    jwk = jwks["keys"][0]
    resolved = _pubkey_from_jwk(jwk)
    n = int.from_bytes(_b64url_decode(jwk["n"]), "big")
    e = int.from_bytes(_b64url_decode(jwk["e"]), "big")
    assert resolved.public_numbers().n == n
    assert resolved.public_numbers().e == e


def test_kid_stable():
    priv, pub = _keypair()
    assert derive_kid(pub) == derive_kid(pub)


# ── Config load ──────────────────────────────────────────────────────────

def test_config_load_requires_keypair():
    with pytest.raises(IssuerConfigError):
        IssuerConfig.load(lambda name: {})

    with pytest.raises(IssuerConfigError):
        IssuerConfig.load(lambda name: {"rsa_private": "p", "rsa_public": ""})


def test_config_load_from_secret():
    priv, pub = _keypair()
    cfg = IssuerConfig.load(
        lambda name: {
            "rsa_private": priv,
            "rsa_public": pub,
            "issuers": ["cosmoport"],
            "audience": "cosmo-api",
        }
    )
    assert cfg.issuer == "cosmoport"
    assert cfg.audience == "cosmo-api"
    assert cfg.kid == derive_kid(pub)