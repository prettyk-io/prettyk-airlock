# -*- coding: utf-8 -*-
"""COS-157: тесты auth-роутов (login + JWKS) с подменённым Vault.

Vault подменяется через ``app.dependency_overrides[deps.get_vault]`` — роут
сам читает ``secret/cosmo/auth`` и ``secret/cosmo/jwt-keys`` из фейка.
"""
from __future__ import annotations

import asyncio

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from httpx import ASGITransport, AsyncClient

from orchestrator.cosmo.infra.vault import VaultLookupError
from orchestrator.cosmo.security.credentials import hash_password
from orchestrator.cosmo.security.jwt_verifier import verify_jwt

AUTH_EMAIL = "admin@kits.bank.corp"
AUTH_PASSWORD = "battle-password"


class FakeVault:
    def __init__(self, secrets: dict[str, dict]):
        self.secrets = secrets

    def read_secret(self, name: str) -> dict:
        if name not in self.secrets:
            raise VaultLookupError(f"secret/cosmo/{name} not found")
        return self.secrets[name]


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


def _seeded_vault():
    priv, pub = _keypair()
    return (
        FakeVault(
            {
                "auth": {
                    "email": AUTH_EMAIL,
                    "password_hash": hash_password(AUTH_PASSWORD, iterations=1000),
                    "sub": "admin",
                    "roles": ["admin_sec"],
                    "is_admin": True,
                },
                "jwt-keys": {
                    "rsa_private": priv,
                    "rsa_public": pub,
                    "issuers": ["cosmoport"],
                    "audience": "cosmo-api",
                },
            }
        ),
        pub,
    )


@pytest.fixture
def client():
    from orchestrator.cosmo.api import deps
    from orchestrator.cosmo.api.main import app

    fake, pub = _seeded_vault()
    app.dependency_overrides[deps.get_vault] = lambda: fake
    transport = ASGITransport(app=app)
    yield AsyncClient(transport=transport, base_url="http://test"), pub
    app.dependency_overrides.clear()


# ── Login ────────────────────────────────────────────────────────────────

def test_login_returns_signed_token(client):
    c, pub = client
    r = asyncio.run(c.post(
        "/api/v1/auth/login",
        json={"email": AUTH_EMAIL, "password": AUTH_PASSWORD},
    ))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == 3600
    assert body["user"]["sub"] == "admin"
    assert body["user"]["is_admin"] is True

    # токен реально верифицируется публичным ключом (сквозной, не декор)
    claims = verify_jwt(
        body["access_token"],
        env={
            "COSMO_JWT_PUBLIC_KEY": pub,
            "COSMO_JWT_ISSUERS": "cosmoport",
            "COSMO_JWT_AUDIENCE": "cosmo-api",
        },
    )
    assert claims["sub"] == "admin"
    assert claims["roles"] == ["admin_sec"]


def test_login_wrong_password_401(client):
    c, _ = client
    r = asyncio.run(c.post(
        "/api/v1/auth/login",
        json={"email": AUTH_EMAIL, "password": "wrong"},
    ))
    assert r.status_code == 401


def test_login_wrong_email_401(client):
    c, _ = client
    r = asyncio.run(c.post(
        "/api/v1/auth/login",
        json={"email": "intruder@kits.bank.corp", "password": AUTH_PASSWORD},
    ))
    assert r.status_code == 401


def test_login_missing_auth_secret_503(client):
    from orchestrator.cosmo.api import deps
    from orchestrator.cosmo.api.main import app

    fake_v = _seeded_vault()[0]
    fake_v.secrets.pop("auth")
    app.dependency_overrides[deps.get_vault] = lambda: fake_v
    c = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    r = asyncio.run(c.post(
        "/api/v1/auth/login", json={"email": AUTH_EMAIL, "password": AUTH_PASSWORD}
    ))
    assert r.status_code == 503


def test_login_missing_jwt_keys_503(client):
    from orchestrator.cosmo.api import deps
    from orchestrator.cosmo.api.main import app

    fake_v = _seeded_vault()[0]
    fake_v.secrets.pop("jwt-keys")
    app.dependency_overrides[deps.get_vault] = lambda: fake_v
    c = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    r = asyncio.run(c.post(
        "/api/v1/auth/login", json={"email": AUTH_EMAIL, "password": AUTH_PASSWORD}
    ))
    assert r.status_code == 503


# ── JWKS ─────────────────────────────────────────────────────────────────

def test_jwks_endpoint(client):
    c, _ = client
    r = asyncio.run(c.get("/.well-known/jwks.json"))
    assert r.status_code == 200, r.text
    keys = r.json()["keys"]
    assert len(keys) == 1
    assert keys[0]["kty"] == "RSA"
    assert keys[0]["alg"] == "RS256"
    assert "n" in keys[0] and "e" in keys[0]