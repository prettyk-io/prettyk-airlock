"""COS-114: tests for VaultSecretRef validator and PlaintextLeakGuard."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI, Body
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field, field_validator

_orch = Path(__file__).resolve().parents[1]
if str(_orch) not in sys.path:
    sys.path.insert(0, str(_orch))

from orchestrator.cosmo.api.middleware import PlaintextLeakGuardMiddleware
from orchestrator.cosmo.domain.vault_ref import (
    _looks_like_token,
    scan_for_leaks,
    validate_secret_reference,
    PLAINTEXT_PATTERNS_CI,
)


# ── Test models ───────────────────────────────────────────────────────

class TestModel(BaseModel):
    name: str
    token_ref: str = Field(...)

    _validate_token = field_validator("token_ref")(validate_secret_reference)


class TestBody(BaseModel):
    data: TestModel


# ── Test app ───────────────────────────────────────────────────────────

@pytest.fixture
def client():
    app = FastAPI()

    @app.post("/test")
    async def test_endpoint(body: TestBody | None = None):
        if body is None:
            return {"status": "ignored"}
        return {"status": "ok", "name": body.data.name}

    app.add_middleware(PlaintextLeakGuardMiddleware)

    return TestClient(app)


# ══════════════════════════════════════════════════════════════════════════
# Vault Secret Reference Validator
# ══════════════════════════════════════════════════════════════════════════

class TestVaultRefValidator:

    def test_valid_vault_secret_reference(self):
        result = validate_secret_reference("vault:secret/cosmo/database")
        assert result == "vault:secret/cosmo/database"

    def test_valid_vault_kv2_reference(self):
        result = validate_secret_reference("vault:kv-v2/cosmo/data/db")
        assert result == "vault:kv-v2/cosmo/data/db"

    def test_valid_vault_forge_reference(self):
        result = validate_secret_reference("vault:secret/cosmo/forge/gitea")
        assert result == "vault:secret/cosmo/forge/gitea"

    def test_reject_raw_token_jwt(self):
        with pytest.raises(Exception):
            validate_secret_reference(
                "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOnRydWV9.signature"
            )

    def test_reject_raw_sonarqube_token(self):
        with pytest.raises(Exception):
            validate_secret_reference("squ_752b04a6a1d45a6c29a3b6fe291a3b12d5dddba9")

    def test_reject_raw_github_token(self):
        with pytest.raises(Exception):
            validate_secret_reference("ghp_1234567890abcdef1234567890abcdef12345678")

    def test_reject_empty_string(self):
        with pytest.raises(Exception):
            validate_secret_reference("")

    def test_reject_unknown_vault_path(self):
        with pytest.raises(Exception):
            validate_secret_reference("vault:secret/hacker/evil")

    def test_allow_url(self):
        result = validate_secret_reference("http://gitea:3000")
        assert result == "http://gitea:3000"


# ══════════════════════════════════════════════════════════════════════════
# Token detection heuristics
# ══════════════════════════════════════════════════════════════════════════

class TestTokenDetection:

    def test_jwt_looks_like_token(self):
        assert _looks_like_token("eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOnRydWV9.signature")

    def test_sonarqube_token(self):
        assert _looks_like_token("squ_752b04a6a1d45a6c29a3b6fe291a3b12d5dddba9")

    def test_github_pat(self):
        assert _looks_like_token("ghp_1234567890abcdef1234567890abcdef12345678")

    def test_random_string_is_token(self):
        assert _looks_like_token("XyZ8aBcDeFgHiJkLmNoPqRsTuVw12345678")

    def test_short_string_not_token(self):
        assert not _looks_like_token("short")

    def test_url_not_token(self):
        assert not _looks_like_token("http://gitea:3000")


# ══════════════════════════════════════════════════════════════════════════
# Plaintext leak scanner
# ══════════════════════════════════════════════════════════════════════════

class TestLeakScanner:

    def test_scan_hardcoded_password(self):
        content = 'password = "supersecret"\nother = "ok"'
        leaks = scan_for_leaks("test.py", content)
        assert len(leaks) >= 1

    def test_scan_dsn_in_config(self):
        content = 'postgresql://admin:secretpass@localhost:5432/db'
        leaks = scan_for_leaks("config.yml", content)
        assert len(leaks) >= 1

    def test_scan_clean_file(self):
        content = 'domain = "test"\nforge_url = "http://gitea:3000"\n'
        leaks = scan_for_leaks("clean.py", content)
        assert len(leaks) == 0

    def test_scan_env_var_skip(self):
        content = 'COSMO_PG_PASSWORD = "${COSMO_PG_PASSWORD:-cosmo}"'
        leaks = scan_for_leaks(".env", content)
        assert len(leaks) == 0


# ══════════════════════════════════════════════════════════════════════════
# PlaintextLeakGuard Middleware
# ══════════════════════════════════════════════════════════════════════════

class TestLeakGuardMiddleware:

    def test_allows_clean_request(self, client: TestClient):
        # Nest vault ref in data.token_ref — test both paths (scan + field_names)
        r = client.post("/test", json={"data": {"name": "clean", "token_ref": "vault:secret/cosmo/forge/gitea"}})
        assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"

    def test_blocks_jwt_in_request(self, client: TestClient):
        jwt = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOnRydWV9.signature"
        r = client.post("/test", json={"data": {"name": "test", "token_ref": jwt}})
        assert r.status_code == 422
        data = r.json()
        assert "Plaintext secrets detected" in data["detail"]

    def test_blocks_password_in_request(self, client: TestClient):
        r = client.post("/test", json={"password": "secret123"})
        assert r.status_code == 422

    def test_allows_health_endpoint(self, client: TestClient):
        r = client.get("/live")
        assert r.status_code not in (422,)

    def test_allows_get_request(self, client: TestClient):
        r = client.get("/api/v1/domains")
        assert r.status_code not in (422,)

    def test_allows_url_in_token_ref(self, client: TestClient):
        r = client.post("/test", json={"data": {"name": "test", "token_ref": "http://gitea:3000"}})
        assert r.status_code == 200