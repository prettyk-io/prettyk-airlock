# -*- coding: utf-8 -*-
"""COS-132: Workspace full repository security scan & SARIF export.

DTO + scan_tree + SARIF 2.1.0 serializer + route mock.

Запуск:  pytest .../test_workspace_gate_scan.py -q
"""
from __future__ import annotations

import json
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

from orchestrator.cosmo.adapters.forge_gitea import GiteaTreeEntry
from orchestrator.cosmo.api.deps import get_current_principal
from orchestrator.cosmo.api.main import app
from orchestrator.cosmo.domain.gate_verdict import (
    MAX_SCAN_BLOB_BYTES,
    SARIF_SCHEMA,
    SARIF_VERSION,
    Violation,
    compute_verdict,
    scan_tree,
    to_sarif,
)
from orchestrator.cosmo.domain.rbac import CBRRole, PrincipalContext
from orchestrator.cosmo.domain.workspace import (
    WorkspaceGateScanRequest,
    WorkspaceGateScanResponse,
)

SHA_COMMIT = "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6a7b8c9d0"
REPO = "scan-owner/scan-repo"

AWS_KEY = "AKIAIOSFODNN7EXAMPLE"
JWT = ("eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
       "eyJzdWIiOiIxMjM0NTY3ODkwIn0."
       "dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U")
PRIVATE_KEY = "-----BEGIN RSA PRIVATE KEY-----\nMIIEpA...\n-----END RSA PRIVATE KEY-----"


def _entry(path: str, sha: str = "s", size: int | None = None, kind: str = "blob"):
    return GiteaTreeEntry(path=path, type=kind, sha=sha, size=size)


# ══════════════════════════════════════════════════════════════════
# DTO tests
# ══════════════════════════════════════════════════════════════════

class TestScanRequestDto:
    def test_defaults(self):
        r = WorkspaceGateScanRequest(repo="o/n")
        assert r.ref is None
        assert r.max_files == 1000
        assert r.export_format == "json"

    def test_camel_case_json(self):
        r = WorkspaceGateScanRequest.model_validate_json(json.dumps({
            "repo": "o/n", "ref": "feature",
            "maxFiles": 42, "exportFormat": "sarif",
        }))
        assert r.max_files == 42
        assert r.export_format == "sarif"
        assert r.ref == "feature"

    def test_dump_aliases(self):
        d = WorkspaceGateScanRequest(repo="o/n").model_dump(by_alias=True)
        assert d["maxFiles"] == 1000
        assert d["exportFormat"] == "json"

    def test_empty_ref_normalized_none(self):
        assert WorkspaceGateScanRequest(repo="o/n", ref="").ref is None

    def test_bad_repo(self):
        with pytest.raises(ValidationError):
            WorkspaceGateScanRequest(repo="../etc")

    def test_bad_ref(self):
        with pytest.raises(ValidationError):
            WorkspaceGateScanRequest(repo="o/n", ref="../bad")

    def test_max_files_zero(self):
        with pytest.raises(ValidationError):
            WorkspaceGateScanRequest(repo="o/n", max_files=0)

    def test_max_files_over_limit(self):
        with pytest.raises(ValidationError):
            WorkspaceGateScanRequest(repo="o/n", max_files=1001)

    def test_export_format_literal(self):
        with pytest.raises(ValidationError):
            WorkspaceGateScanRequest(repo="o/n", export_format="xml")

    def test_extra_forbid(self):
        with pytest.raises(ValidationError):
            WorkspaceGateScanRequest(repo="o/n", hack=1)


class TestScanResponseDto:
    def test_camel_case_dump(self):
        r = WorkspaceGateScanResponse(
            scanned_files=10, clean_files=8, block_violations=1,
            warn_violations=2, verdict="BLOCK", duration_ms=7,
            violations=[],
        )
        d = json.loads(r.model_dump_json(by_alias=True))
        assert d["scannedFiles"] == 10
        assert d["cleanFiles"] == 8
        assert d["blockViolations"] == 1
        assert d["warnViolations"] == 2
        assert d["durationMs"] == 7
        assert d["verdict"] == "BLOCK"

    def test_extra_forbid(self):
        with pytest.raises(ValidationError):
            WorkspaceGateScanResponse(
                scanned_files=0, clean_files=0, block_violations=0,
                warn_violations=0, verdict="PASS", duration_ms=0, hack=1,
            )


# ══════════════════════════════════════════════════════════════════
# scan_tree tests
# ══════════════════════════════════════════════════════════════════

def _loader_from(files: dict[str, bytes | str]):
    def _load(entry):
        val = files.get(entry.path)
        if val is None:
            return None
        return val.encode("utf-8") if isinstance(val, str) else val
    return _load


class TestScanTree:
    def test_clean_text_files(self):
        entries = [_entry("a.py"), _entry("b.md")]
        res = scan_tree(entries, _loader_from({"a.py": "print(1)", "b.md": "# doc"}))
        assert res.scanned_files == 2
        assert res.clean_files == 2
        assert res.skipped_files == 0
        assert res.violations == []

    def test_collects_violations(self):
        res = scan_tree([_entry("x.py")], _loader_from({"x.py": f"k={AWS_KEY}"}))
        assert res.scanned_files == 1
        assert res.clean_files == 0
        assert any(v.rule_id == "aws-key" for v in res.violations)

    def test_mixed_clean_and_dirty(self):
        entries = [_entry("ok.py"), _entry("bad.py")]
        res = scan_tree(entries, _loader_from({
            "ok.py": "print('ok')", "bad.py": PRIVATE_KEY,
        }))
        assert res.scanned_files == 2
        assert res.clean_files == 1
        assert any(v.rule_id == "private-key" for v in res.violations)

    def test_forbidden_file_path(self):
        res = scan_tree([_entry("config/.env")],
                        _loader_from({"config/.env": "A=1"}))
        assert any(v.rule_id == "forbidden-file" for v in res.violations)

    def test_skips_non_blob(self):
        entries = [_entry("src", kind="tree"), _entry("sub", kind="commit")]
        res = scan_tree(entries, _loader_from({}))
        assert res.scanned_files == 0
        assert res.skipped_files == 0

    def test_skips_oversized_by_size(self):
        called = {"n": 0}

        def _load(entry):
            called["n"] += 1
            return b"x"

        res = scan_tree(
            [_entry("big.bin", size=MAX_SCAN_BLOB_BYTES + 1)], _load,
        )
        assert res.scanned_files == 0
        assert res.skipped_files == 1
        assert called["n"] == 0  # не читаем вовсе

    def test_skips_oversized_by_actual(self):
        big = b"a" * (MAX_SCAN_BLOB_BYTES + 1)
        res = scan_tree([_entry("big.txt")], _loader_from({"big.txt": big}))
        assert res.scanned_files == 0
        assert res.skipped_files == 1

    def test_skips_binary(self):
        res = scan_tree([_entry("img.png")],
                        _loader_from({"img.png": b"\x89PNG\x00\x01"}))
        assert res.scanned_files == 0
        assert res.skipped_files == 1

    def test_skips_undecodable(self):
        res = scan_tree([_entry("weird.bin")],
                        _loader_from({"weird.bin": b"\xff\xfe\xfd"}))
        assert res.skipped_files == 1

    def test_loader_none_skipped(self):
        res = scan_tree([_entry("gone.py")], lambda entry: None)
        assert res.skipped_files == 1

    def test_loader_exception_skipped(self):
        def _boom(entry):
            raise RuntimeError("blob read failed")

        res = scan_tree([_entry("x.py")], _boom)
        assert res.skipped_files == 1
        assert res.scanned_files == 0

    def test_loader_returns_str(self):
        res = scan_tree([_entry("s.py")], lambda entry: "print('hi')")
        assert res.scanned_files == 1
        assert res.clean_files == 1

    def test_empty_content_clean(self):
        res = scan_tree([_entry("empty.py")], _loader_from({"empty.py": ""}))
        assert res.scanned_files == 1
        assert res.clean_files == 1

    def test_verdict_from_scan(self):
        res = scan_tree([_entry("k.py")], _loader_from({"k.py": AWS_KEY}))
        assert compute_verdict(res.violations) == "BLOCK"

    def test_empty_tree_pass(self):
        res = scan_tree([], _loader_from({}))
        assert res.scanned_files == 0
        assert compute_verdict(res.violations) == "PASS"


# ══════════════════════════════════════════════════════════════════
# SARIF 2.1.0 serializer tests
# ══════════════════════════════════════════════════════════════════

def _v(rule_id="aws-key", severity="BLOCK", line=3, path="a.py", snippet="snip"):
    return Violation(
        path=path, rule_id=rule_id, severity=severity,
        message=f"msg {rule_id}", line_number=line, snippet=snippet,
    )


class TestSarif:
    def test_version_and_schema(self):
        doc = to_sarif([])
        assert doc["version"] == SARIF_VERSION == "2.1.0"
        assert doc["$schema"] == SARIF_SCHEMA

    def test_runs_tool_driver(self):
        doc = to_sarif([_v()])
        run = doc["runs"][0]
        assert run["tool"]["driver"]["name"]
        assert run["tool"]["driver"]["version"]

    def test_rules_unique(self):
        doc = to_sarif([_v("aws-key"), _v("aws-key"), _v("private-key")])
        ids = [r["id"] for r in doc["runs"][0]["tool"]["driver"]["rules"]]
        assert ids == ["aws-key", "private-key"]

    def test_result_location_region(self):
        res = to_sarif([_v(line=5)])["runs"][0]["results"][0]
        assert res["ruleId"] == "aws-key"
        assert res["level"] == "error"
        loc = res["locations"][0]["physicalLocation"]
        assert loc["artifactLocation"]["uri"] == "a.py"
        assert loc["region"]["startLine"] == 5
        assert loc["region"]["snippet"]["text"] == "snip"

    def test_warn_level_warning(self):
        res = to_sarif([_v("jwt-exposed", "WARN")])["runs"][0]["results"][0]
        assert res["level"] == "warning"

    def test_forbidden_file_line_defaults_one(self):
        res = to_sarif([_v("forbidden-file", "BLOCK", line=0, path=".env")])
        region = res["runs"][0]["results"][0]["locations"][0][
            "physicalLocation"]["region"]
        assert region["startLine"] == 1

    def test_empty_violations(self):
        run = to_sarif([])["runs"][0]
        assert run["results"] == []
        assert run["tool"]["driver"]["rules"] == []

    def test_json_serializable(self):
        doc = to_sarif([_v()])
        assert json.loads(json.dumps(doc))["version"] == "2.1.0"

    def test_information_uri_optional(self):
        doc = to_sarif([_v()], information_uri="https://example.test")
        assert doc["runs"][0]["tool"]["driver"]["informationUri"] == \
            "https://example.test"


# ══════════════════════════════════════════════════════════════════
# Route tests (httpx через реальный PG + mock forge adapter)
# ══════════════════════════════════════════════════════════════════

_SCAN_BASE = "/api/v1/repos/workspace/gate-scan"


class FakeScanAdapter:
    """In-memory forge: refs + дерево + blob-и."""

    def __init__(self, files: dict[str, bytes | str] | None = None):
        self.files = files or {}
        self.refs_called: list[str] = []
        self.error: Exception | None = None

    def resolve_ref(self, owner, repo, ref):
        self.refs_called.append(ref)
        if self.error:
            raise self.error
        if ref not in ("main", "feature", "develop"):
            raise LookupError(f"Ref {ref!r} not found")
        return SHA_COMMIT

    def get_tree_by_sha(self, owner, repo, sha, recursive=True):
        if self.error:
            raise self.error
        entries = []
        for path, content in self.files.items():
            raw = content.encode("utf-8") if isinstance(content, str) else content
            entries.append(GiteaTreeEntry(
                path=path, type="blob", sha=f"blob-{path}", size=len(raw),
            ))
        return entries

    def get_blob(self, owner, repo, blob_sha):
        path = blob_sha[len("blob-"):]
        if path not in self.files:
            raise LookupError(path)
        content = self.files[path]
        return content.encode("utf-8") if isinstance(content, str) else content

    def read_file(self, owner, repo, path, ref=""):
        if path in self.files and isinstance(self.files[path], str):
            return self.files[path], f"blob-{path}"
        raise LookupError(path)


class TestGateScanRoute:
    @pytest.fixture(autouse=True)
    def _mocks(self, monkeypatch):
        self._forge = FakeScanAdapter({
            "src/app.py": "print('hello')\n",
            "README.md": "# docs\n",
        })
        import orchestrator.cosmo.api.routes.workspace as _ws
        monkeypatch.setattr(_ws, "build_adapter", lambda: self._forge)

        async def _principal() -> PrincipalContext:
            return PrincipalContext(
                user_id="scan-tester",
                roles=[CBRRole.SERVICE_ADMIN],
                domain_id="scan-dom", zone="zr",
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
                "VALUES ('scan-dom', 'scan-test', 'gitea', "
                "'http://gitea:3000', 't', '{}'::jsonb, 50, 100, 8, now()) "
                "ON CONFLICT (id) DO NOTHING"
            ))
            await conn.execute(text(
                "INSERT INTO apps (id, domain_id, level) "
                "VALUES ('scan-app', 'scan-dom', 0) "
                "ON CONFLICT (id) DO NOTHING"
            ))
            await conn.execute(text(
                "INSERT INTO repo_bindings (id, app_id, forge_id, repo_path, "
                "default_branch) "
                "VALUES ('scan-bind', 'scan-app', 'gitea-1', "
                "'scan-owner/scan-repo', 'main') "
                "ON CONFLICT (id) DO NOTHING"
            ))
        await engine.dispose()

    async def _post(self, pg_client: AsyncClient, **body):
        body.setdefault("repo", REPO)
        return await pg_client.post(_SCAN_BASE, json=body)

    # ── Verdicts ──

    async def test_pass_200(self, pg_client: AsyncClient):
        res = await self._post(pg_client)
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["verdict"] == "PASS"
        assert body["scannedFiles"] == 2
        assert body["cleanFiles"] == 2
        assert body["blockViolations"] == 0
        assert body["warnViolations"] == 0
        assert body["violations"] == []
        assert isinstance(body["durationMs"], int)

    async def test_block_200(self, pg_client: AsyncClient):
        self._forge.files = {"secret.py": PRIVATE_KEY}
        res = await self._post(pg_client)
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["verdict"] == "BLOCK"
        assert body["blockViolations"] >= 1
        assert any(v["ruleId"] == "private-key" for v in body["violations"])
        assert body["violations"][0]["lineNumber"] >= 1

    async def test_warn_200(self, pg_client: AsyncClient):
        self._forge.files = {"api.http": f"Authorization: Bearer {JWT}\n"}
        res = await self._post(pg_client)
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["verdict"] == "WARN"
        assert body["warnViolations"] >= 1
        assert body["blockViolations"] == 0

    async def test_binary_skipped(self, pg_client: AsyncClient):
        self._forge.files = {
            "logo.png": b"\x89PNG\x00\x01\x02",
            "app.py": "print(1)\n",
        }
        res = await self._post(pg_client)
        assert res.status_code == 200
        body = res.json()
        assert body["scannedFiles"] == 1  # бинарник не сканировался

    # ── SARIF export ──

    async def test_sarif_media_type(self, pg_client: AsyncClient):
        self._forge.files = {"secret.py": AWS_KEY}
        res = await self._post(pg_client, exportFormat="sarif")
        assert res.status_code == 200, res.text
        assert res.headers["content-type"].startswith("application/sarif+json")
        doc = res.json()
        assert doc["version"] == "2.1.0"
        assert doc["runs"][0]["tool"]["driver"]["rules"]
        assert doc["runs"][0]["results"]
        assert doc["runs"][0]["properties"]["verdict"] == "BLOCK"

    async def test_sarif_clean_empty_results(self, pg_client: AsyncClient):
        res = await self._post(pg_client, exportFormat="sarif")
        assert res.status_code == 200
        doc = res.json()
        assert doc["runs"][0]["results"] == []
        assert doc["runs"][0]["properties"]["verdict"] == "PASS"

    # ── Ref resolution ──

    async def test_default_ref_from_binding(self, pg_client: AsyncClient):
        res = await self._post(pg_client)
        assert res.status_code == 200
        assert self._forge.refs_called == ["main"]

    async def test_explicit_ref(self, pg_client: AsyncClient):
        res = await self._post(pg_client, ref="feature")
        assert res.status_code == 200
        assert self._forge.refs_called == ["feature"]

    async def test_unknown_ref_404(self, pg_client: AsyncClient):
        res = await self._post(pg_client, ref="ghost")
        assert res.status_code == 404

    # ── Limits / validation / ghost / auth ──

    async def test_too_many_files_413(self, pg_client: AsyncClient):
        self._forge.files = {"a.py": "x", "b.py": "y"}
        res = await self._post(pg_client, maxFiles=1)
        assert res.status_code == 413, res.text

    async def test_max_files_over_1000_422(self, pg_client: AsyncClient):
        res = await self._post(pg_client, maxFiles=1001)
        assert res.status_code == 422

    async def test_invalid_export_format_422(self, pg_client: AsyncClient):
        res = await self._post(pg_client, exportFormat="xml")
        assert res.status_code == 422

    async def test_bad_repo_400(self, pg_client: AsyncClient):
        res = await self._post(pg_client, repo="../bad")
        assert res.status_code in (400, 422)

    async def test_bad_ref_400(self, pg_client: AsyncClient):
        res = await self._post(pg_client, ref="../bad")
        assert res.status_code in (400, 422)

    async def test_unknown_repo_404(self, pg_client: AsyncClient):
        res = await self._post(pg_client, repo="ghost/nope")
        assert res.status_code == 404

    async def test_anonymous_401(self, pg_client: AsyncClient):
        app.dependency_overrides.pop(get_current_principal, None)
        try:
            res = await self._post(pg_client)
            assert res.status_code == 401
        finally:
            pass

    async def test_forge_unreachable_502(self, pg_client: AsyncClient):
        import requests as _r
        self._forge.error = _r.ConnectionError("down")
        res = await self._post(pg_client)
        assert res.status_code in (502, 503)
