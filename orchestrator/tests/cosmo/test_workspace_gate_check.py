# -*- coding: utf-8 -*-
"""COS-123: Pre-flight Quality Gate — DTO unit + verdict engine + route mock.

Запуск:  pytest .../test_workspace_gate_check.py -q
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import AsyncClient
from pydantic import ValidationError

_orch = Path(__file__).resolve().parents[1]
if str(_orch) not in sys.path:
    sys.path.insert(0, str(_orch))

pytestmark = pytest.mark.asyncio

from orchestrator.cosmo.api.deps import get_current_principal
from orchestrator.cosmo.api.main import app
from orchestrator.cosmo.domain.rbac import CBRRole, PrincipalContext
from orchestrator.cosmo.domain.workspace import (
    WorkspaceGateCheckRequest,
    WorkspaceGateFileChange,
    WorkspaceGateVerdictResponse,
    WorkspaceGateViolation,
)
from orchestrator.cosmo.domain.gate_verdict import (
    Violation,
    scan_file,
    compute_verdict,
)


# ══════════════════════════════════════════════════════════════════
# DTO unit tests
# ══════════════════════════════════════════════════════════════════

class TestGateFileChangeDto:
    def test_valid(self):
        fc = WorkspaceGateFileChange(path="src/main.py", content="print('hello')")
        assert fc.path == "src/main.py"
        assert fc.content == "print('hello')"

    def test_extra_forbid(self):
        with pytest.raises(ValidationError):
            WorkspaceGateFileChange(path="x", content="y", hack=1)


class TestGateCheckRequestDto:
    def test_valid(self):
        req = WorkspaceGateCheckRequest(
            repo="owner/name",
            branch="main",
            files=[WorkspaceGateFileChange(path="a.py", content="x")],
        )
        assert req.repo == "owner/name"
        assert len(req.files) == 1

    def test_empty_files_ok(self):
        req = WorkspaceGateCheckRequest(
            repo="owner/name",
            files=[],
        )
        assert req.files == []

    def test_bad_repo_traversal(self):
        with pytest.raises(ValidationError):
            WorkspaceGateCheckRequest(
                repo="../../../etc",
                files=[],
            )

    def test_extra_forbid(self):
        with pytest.raises(ValidationError):
            WorkspaceGateCheckRequest(
                repo="a/b", files=[], hack=1,
            )


class TestGateViolationDto:
    def test_valid(self):
        v = WorkspaceGateViolation(
            path="config.yaml",
            rule_id="private-key",
            severity="BLOCK",
            message="Found private key",
            line_number=5,
            snippet="BEGIN RSA PRIVATE KEY",
        )
        assert v.path == "config.yaml"
        assert v.rule_id == "private-key"
        assert v.line_number == 5

    def test_camel_case_dump(self):
        v = WorkspaceGateViolation(
            path="x", rule_id="r", severity="WARN", message="m",
            line_number=3, snippet="s",
        )
        d = v.model_dump(by_alias=True)
        assert "ruleId" in d and d["ruleId"] == "r"
        assert "lineNumber" in d and d["lineNumber"] == 3

    def test_extra_forbid(self):
        with pytest.raises(ValidationError):
            WorkspaceGateViolation(
                path="x", rule_id="r", severity="BLOCK", message="m",
                hack=1,
            )


class TestGateVerdictResponseDto:
    def test_pass(self):
        r = WorkspaceGateVerdictResponse(
            verdict="PASS", violations=[], summary={"total": 0},
        )
        assert r.verdict == "PASS"

    def test_block(self):
        r = WorkspaceGateVerdictResponse(
            verdict="BLOCK", violations=[], summary={"total": 0, "block": 1},
        )
        assert r.verdict == "BLOCK"

    def test_extra_forbid(self):
        with pytest.raises(ValidationError):
            WorkspaceGateVerdictResponse(
                verdict="PASS", violations=[], summary={}, hack=1,
            )


# ══════════════════════════════════════════════════════════════════
# Verdict engine unit tests (no DB, no HTTP)
# ══════════════════════════════════════════════════════════════════

class TestScanFile:
    """Unit-тесты функций scan_file и compute_verdict."""

    def test_clean_content_no_violations(self):
        violations = scan_file("main.py", "print('hello world')\ndef foo(): pass")
        assert violations == []

    def test_empty_content(self):
        assert scan_file("x.py", "") == []

    # ── BLOCK rules ──

    def test_rsa_private_key(self):
        content = "-----BEGIN RSA PRIVATE KEY-----\nMIIEpAIBAAKCAQEA...\n-----END RSA PRIVATE KEY-----"
        violations = scan_file("cert.pem", content)
        assert len(violations) >= 1
        v = violations[0]
        assert v.rule_id == "private-key"
        assert v.severity == "BLOCK"

    def test_openssh_private_key(self):
        content = "-----BEGIN OPENSSH PRIVATE KEY-----\nb3BlbnNzaC1rZXktdjEAAAAABG5vbmUAAAAEbm9uZQ==\n-----END OPENSSH PRIVATE KEY-----"
        violations = scan_file("id_ed25519", content)
        assert any(v.rule_id == "private-key" and v.severity == "BLOCK" for v in violations)

    def test_aws_access_key(self):
        content = "AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE"
        violations = scan_file(".env", content)
        aws = [v for v in violations if v.rule_id == "aws-key"]
        assert len(aws) >= 1
        assert aws[0].severity == "BLOCK"

    def test_github_token(self):
        content = 'GITHUB_TOKEN=ghp_1a2b3c4d5e6f7g8h9i0j1k2l3m4n5o6p7q8r9s'
        violations = scan_file("ci.yml", content)
        gh = [v for v in violations if v.rule_id == "github-token"]
        assert len(gh) >= 1
        assert gh[0].severity == "BLOCK"

    def test_gitlab_token(self):
        content = "CI_JOB_TOKEN=glpat-abcdefghijklmnopqrstuvwxyz"
        violations = scan_file(".gitlab-ci.yml", content)
        gl = [v for v in violations if v.rule_id == "gitlab-token"]
        assert len(gl) >= 1
        assert gl[0].severity == "BLOCK"

    def test_vault_token(self):
        content = 'VAULT_TOKEN=hvs.CAESIKmz7n9uAbCDEfGhIjKlMnO'
        violations = scan_file("deploy.sh", content)
        vt = [v for v in violations if v.rule_id == "vault-token"]
        assert len(vt) >= 1
        assert vt[0].severity == "BLOCK"

    def test_config_password(self):
        content = "password = hunter2\ndatabase:\n  password: secret123"
        violations = scan_file("config.yaml", content)
        cs = [v for v in violations if v.rule_id == "config-secret"]
        assert len(cs) >= 1
        assert all(v.severity == "BLOCK" for v in cs)

    def test_config_env_var_not_flagged(self):
        """Пароль через переменную окружения не триггерит BLOCK."""
        content = 'password = $DB_PASSWORD\ntoken: ${API_TOKEN}'
        violations = scan_file("config.yaml", content)
        cs = [v for v in violations if v.rule_id == "config-secret"]
        assert len(cs) == 0

    # ── WARN rules ──

    def test_jwt_detected(self):
        content = 'Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U'
        violations = scan_file("request.http", content)
        jwt = [v for v in violations if v.rule_id == "jwt-exposed"]
        assert len(jwt) >= 1
        assert jwt[0].severity == "WARN"

    def test_generic_token_warn(self):
        content = '"api_key": "sk-1234567890abcdef"'
        violations = scan_file("settings.json", content)
        gt = [v for v in violations if v.rule_id == "generic-token"]
        assert len(gt) >= 1
        assert gt[0].severity == "WARN"

    def test_env_content_warn(self):
        content = "DATABASE_URL=postgres://user:pass@localhost/db\nSECRET_KEY=supersecret"
        violations = scan_file("config.py", content)
        ev = [v for v in violations if v.rule_id == "env-content"]
        assert len(ev) >= 1
        assert ev[0].severity == "WARN"

    # ── Forbidden file ──

    def test_forbidden_env_file(self):
        violations = scan_file(".env", "KEY=value")
        ff = [v for v in violations if v.rule_id == "forbidden-file"]
        assert len(ff) == 1
        assert ff[0].severity == "BLOCK"

    def test_forbidden_pem_file(self):
        violations = scan_file("certs/server.pem", "dummy")
        ff = [v for v in violations if v.rule_id == "forbidden-file"]
        assert len(ff) == 1

    def test_forbidden_credentials_json(self):
        violations = scan_file("credentials.json", "{}")
        ff = [v for v in violations if v.rule_id == "forbidden-file"]
        assert len(ff) == 1

    def test_forbidden_key_file(self):
        violations = scan_file("ssh/deploy.key", "dummy")
        ff = [v for v in violations if v.rule_id == "forbidden-file"]
        assert len(ff) == 1

    def test_normal_file_not_forbidden(self):
        violations = scan_file("src/main.py", "print('hello')")
        ff = [v for v in violations if v.rule_id == "forbidden-file"]
        assert len(ff) == 0

    # ── Line numbers and snippets ──

    def test_line_number_correct(self):
        content = "line 1\nline 2\n-----BEGIN RSA PRIVATE KEY-----\nline 4\n"
        violations = scan_file("key.txt", content)
        pk = [v for v in violations if v.rule_id == "private-key"]
        assert len(pk) == 1
        assert pk[0].line_number == 3

    def test_snippet_truncated(self):
        content = "x" * 200 + "-----BEGIN RSA PRIVATE KEY-----" + "y" * 200
        violations = scan_file("x.txt", content)
        assert len(violations) >= 1
        assert len(violations[0].snippet) <= 80


class TestComputeVerdict:
    """Тесты compute_verdict (итоговый агрегат)."""

    def _v(self, severity: str) -> Violation:
        return Violation(
            path="x", rule_id="r", severity=severity,  # type: ignore[arg-type]
            message="m", line_number=1, snippet="s",
        )

    def test_pass_on_empty(self):
        assert compute_verdict([]) == "PASS"

    def test_warn_on_warn_only(self):
        assert compute_verdict([self._v("WARN")]) == "WARN"

    def test_block_on_block_only(self):
        assert compute_verdict([self._v("BLOCK")]) == "BLOCK"

    def test_block_dominates_warn(self):
        assert compute_verdict([self._v("WARN"), self._v("BLOCK")]) == "BLOCK"

    def test_multiple_warn_still_warn(self):
        assert compute_verdict([self._v("WARN"), self._v("WARN")]) == "WARN"


# ══════════════════════════════════════════════════════════════════
# Route tests (httpx через реальный PG, не нужен forge mock)
# ══════════════════════════════════════════════════════════════════

_GATE_BASE = "/api/v1/repos/workspace/gate-check"


class TestGateCheckRoute:
    """Route-тесты: реальный pg_client, без forge (gate-check не звонит в форж)."""

    @pytest.fixture(autouse=True)
    def _mocks(self):
        async def _principal() -> PrincipalContext:
            return PrincipalContext(
                user_id="gate-tester",
                roles=[CBRRole.SERVICE_ADMIN],
                domain_id="gate-dom", zone="zr",
                is_authenticated=True, is_system_admin=False,
            )
        app.dependency_overrides[get_current_principal] = _principal

    @pytest_asyncio.fixture(autouse=True)
    async def _seed_db(self, pg_client: AsyncClient):
        from sqlalchemy.ext.asyncio import create_async_engine
        from sqlalchemy import text

        pg_url = os.getenv("COSMO_DATABASE_URL",
                           "postgresql+asyncpg://cosmo:cosmo@127.0.0.1:5433/cosmo_test")
        engine = create_async_engine(pg_url, echo=False)
        async with engine.begin() as conn:
            await conn.execute(text(
                "INSERT INTO domains (id, label, forge_type, forge_url, "
                "forge_token_ref, rbac_config, quota_max_runs, "
                "quota_max_storage_gb, quota_max_cpu, created_at) "
                "VALUES ('gate-dom', 'gate-test', 'gitea', "
                "'http://gitea:3000', 't', '{}'::jsonb, 50, 100, 8, now()) "
                "ON CONFLICT (id) DO NOTHING"
            ))
            await conn.execute(text(
                "INSERT INTO apps (id, domain_id, level) "
                "VALUES ('gate-app', 'gate-dom', 0) "
                "ON CONFLICT (id) DO NOTHING"
            ))
            await conn.execute(text(
                "INSERT INTO repo_bindings (id, app_id, forge_id, repo_path, "
                "default_branch) "
                "VALUES ('gate-bind', 'gate-app', 'gitea-1', "
                "'gate-owner/gate-repo', 'main') "
                "ON CONFLICT (id) DO NOTHING"
            ))
        await engine.dispose()

    def _body(self, files: list[tuple[str, str]]) -> dict:
        return {
            "repo": "gate-owner/gate-repo",
            "branch": "main",
            "files": [{"path": p, "content": c} for p, c in files],
        }

    # ── Happy paths ──

    async def test_clean_files_pass(self, pg_client: AsyncClient):
        res = await pg_client.post(
            _GATE_BASE,
            json=self._body([("main.py", "print('hello')\ndef foo(): pass")]),
        )
        assert res.status_code == 200
        body = res.json()
        assert body["verdict"] == "PASS"
        assert body["violations"] == []
        assert body["summary"]["total"] == 0

    async def test_empty_files_pass(self, pg_client: AsyncClient):
        res = await pg_client.post(_GATE_BASE, json=self._body([]))
        assert res.status_code == 200
        body = res.json()
        assert body["verdict"] == "PASS"
        assert body["summary"]["total"] == 0

    async def test_private_key_block(self, pg_client: AsyncClient):
        res = await pg_client.post(
            _GATE_BASE,
            json=self._body([(
                "key.pem",
                "-----BEGIN RSA PRIVATE KEY-----\nMIIEpA...\n-----END RSA PRIVATE KEY-----",
            )]),
        )
        assert res.status_code == 200
        body = res.json()
        assert body["verdict"] == "BLOCK"
        assert len(body["violations"]) >= 1
        assert any(v["ruleId"] == "private-key" and v["severity"] == "BLOCK"
                   for v in body["violations"])

    async def test_aws_key_block(self, pg_client: AsyncClient):
        res = await pg_client.post(
            _GATE_BASE,
            json=self._body([(
                "config.sh",
                "export AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE",
            )]),
        )
        assert res.status_code == 200
        body = res.json()
        assert body["verdict"] == "BLOCK"
        assert any(v["ruleId"] == "aws-key" for v in body["violations"])

    async def test_jwt_warn(self, pg_client: AsyncClient):
        res = await pg_client.post(
            _GATE_BASE,
            json=self._body([(
                "api.http",
                "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
                "eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U",
            )]),
        )
        assert res.status_code == 200
        body = res.json()
        assert body["verdict"] == "WARN"
        assert any(v["ruleId"] == "jwt-exposed" for v in body["violations"])

    async def test_multiple_files_aggregate(self, pg_client: AsyncClient):
        """Несколько файлов: чистый + с секретом → BLOCK, violations по обоим."""
        res = await pg_client.post(
            _GATE_BASE,
            json=self._body([
                ("main.py", "print('hello')"),
                ("secrets.yaml", "password = hunter2"),
            ]),
        )
        assert res.status_code == 200
        body = res.json()
        assert body["verdict"] in ("BLOCK", "WARN")
        assert body["summary"]["total"] >= 1
        paths = {v["path"] for v in body["violations"]}
        assert "secrets.yaml" in paths
        assert "main.py" not in paths  # чистый

    async def test_block_dominates_over_warn(self, pg_client: AsyncClient):
        """JWT (WARN) + RSA (BLOCK) → итог BLOCK."""
        res = await pg_client.post(
            _GATE_BASE,
            json=self._body([(
                "mixed.txt",
                "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.xxx\n"
                "-----BEGIN RSA PRIVATE KEY-----\nMIIEpA...\n-----END RSA PRIVATE KEY-----",
            )]),
        )
        assert res.status_code == 200
        body = res.json()
        assert body["verdict"] == "BLOCK"
        severities = {v["severity"] for v in body["violations"]}
        assert "BLOCK" in severities

    async def test_forbidden_file_path_block(self, pg_client: AsyncClient):
        res = await pg_client.post(
            _GATE_BASE,
            json=self._body([(".env", "DATABASE_URL=postgres://...")]),
        )
        assert res.status_code == 200
        body = res.json()
        assert any(v["ruleId"] == "forbidden-file" and v["severity"] == "BLOCK"
                   for v in body["violations"])

    # ── Ghost / auth ──

    async def test_unknown_repo_404(self, pg_client: AsyncClient):
        res = await pg_client.post(
            _GATE_BASE,
            json={
                "repo": "ghost/nonexistent",
                "files": [{"path": "x.py", "content": "pass"}],
            },
        )
        assert res.status_code == 404

    async def test_anonymous_401(self, pg_client: AsyncClient):
        app.dependency_overrides.pop(get_current_principal, None)
        try:
            res = await pg_client.post(
                _GATE_BASE,
                json={
                    "repo": "gate-owner/gate-repo",
                    "files": [],
                },
            )
            assert res.status_code == 401
        finally:
            pass

    # ── Validation ──

    async def test_bad_repo_400(self, pg_client: AsyncClient):
        res = await pg_client.post(
            _GATE_BASE,
            json={
                "repo": "../bad",
                "files": [],
            },
        )
        assert res.status_code in (400, 422)

    async def test_missing_files_422(self, pg_client: AsyncClient):
        res = await pg_client.post(
            _GATE_BASE,
            json={"repo": "gate-owner/gate-repo"},
        )
        assert res.status_code == 422

    # ── Summary accuracy ──

    async def test_summary_counts(self, pg_client: AsyncClient):
        res = await pg_client.post(
            _GATE_BASE,
            json=self._body([(
                "multi.txt",
                "-----BEGIN RSA PRIVATE KEY-----\nkey\n-----END RSA PRIVATE KEY-----\n"
                "password = secret123\n"
                "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
                "eyJzdWIiOiIxMjM0NTY3ODkwIn0."
                "dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U\n"
                "AKIAIOSFODNN7EXAMPLE\n"
                "ghp_1a2b3c4d5e6f7g8h9i0j1k2l3m4n5o6p7q8r9s",
            )]),
        )
        assert res.status_code == 200
        body = res.json()
        s = body["summary"]
        assert s["total"] >= 3  # at least: RSA, password, jwt, aws, github
        assert s["block"] >= 3
        assert s["warn"] >= 1