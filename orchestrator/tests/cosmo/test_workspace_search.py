# -*- coding: utf-8 -*-
"""COS-114: Workspace search — DTO unit + route mock.

Запуск:  pytest .../test_workspace_search.py -q
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Optional

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
    WorkspaceSearchMatch,
    WorkspaceSearchResponse,
)

SHA = "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6a7b8c9d0"


# ── Fake forge adapter ──────────────────────────────────────────────────────

class FakeForge:
    """In-memory forge: tree entries + file content for search tests."""

    def __init__(self):
        # Map path → (content, sha)
        self._files: dict[str, tuple[str, str]] = {
            "src/main.py": ("import os\nimport sys\n\n# Main entry point\n"
                            "def main():\n    print('hello world')\n",
                            "sha-main"),
            "src/utils.py": ("def helper():\n    return 'hello world'\n"
                             "def other():\n    pass\n",
                             "sha-utils"),
            "tests/test_main.py": ("def test_main():\n    assert True\n\n"
                                   "def test_helper():\n    assert True\n",
                                   "sha-test"),
            "README.md": ("# My Project\n\nHello World demo project.\n",
                          "sha-readme"),
            "logo.png": ("\x89PNG\r\n\x1a\n", "sha-logo"),
        }
        self._call_count = 0
        self.tree_error: Optional[Exception] = None
        self.read_error: Optional[Exception] = None

    def get_tree(self, owner: str, repo: str, ref: str = "",
                 recursive: bool = True) -> list:
        if self.tree_error:
            raise self.tree_error
        from orchestrator.cosmo.adapters.forge_gitea import GiteaTreeEntry
        entries = []
        for path, (content, sha) in self._files.items():
            entry_type = "blob"
            entries.append(GiteaTreeEntry(
                path=path, type=entry_type, sha=sha, size=len(content),
            ))
        return entries

    def get_commit(self, owner: str, repo: str, ref: str = ""):
        import requests as _r
        return type("Commit", (), {
            "sha": SHA, "message": "feat",
            "author": "max", "timestamp": "2026-09-05T00:00:00Z",
        })()

    def read_file(self, owner: str, repo: str, path: str, ref: str = "") -> tuple[str, str]:
        if self.read_error:
            raise self.read_error
        if path in self._files:
            content, sha = self._files[path]
            # Simulate binary rejection for known binary extensions
            if path.lower().endswith((".png", ".jpg", ".exe")):
                raise ValueError(f"Binary file: {path}")
            self._call_count += 1
            return content, sha
        raise LookupError(f"File {path} not found")


# ── DTO unit ────────────────────────────────────────────────────────────────

class TestSearchMatchDto:
    def test_minimal(self):
        m = WorkspaceSearchMatch(
            path="src/main.py", line_number=5, line_content="print('hello')",
            match_start=6, match_end=11,
        )
        assert m.path == "src/main.py"
        assert m.line_number == 5

    def test_camel_case_dump(self):
        m = WorkspaceSearchMatch(
            path="a.py", line_number=1, line_content="x",
            match_start=0, match_end=1,
        )
        d = m.model_dump(by_alias=True)
        assert "lineNumber" in d and d["lineNumber"] == 1
        assert "matchStart" in d
        assert "matchEnd" in d

    def test_extra_forbid(self):
        with pytest.raises(ValidationError):
            WorkspaceSearchMatch(
                path="a.py", line_number=1, line_content="x",
                match_start=0, match_end=1, hack=1,
            )


class TestSearchResponseDto:
    def test_valid(self):
        r = WorkspaceSearchResponse(
            query="hello",
            matches=[],
            total_matches=0,
            scanned_files=0,
        )
        assert r.query == "hello"
        assert r.total_matches == 0
        assert r.has_more is False

    def test_with_matches(self):
        r = WorkspaceSearchResponse(
            query="hello",
            matches=[
                WorkspaceSearchMatch(
                    path="a.py", line_number=1, line_content="hello",
                    match_start=0, match_end=5,
                ),
            ],
            total_matches=1,
            scanned_files=1,
            has_more=False,
        )
        assert r.total_matches == 1

    def test_camel_case_dump(self):
        r = WorkspaceSearchResponse(
            query="test", matches=[], total_matches=5,
            scanned_files=3, has_more=True,
        )
        d = r.model_dump(by_alias=True)
        assert "totalMatches" in d and d["totalMatches"] == 5
        assert "scannedFiles" in d
        assert "hasMore" in d and d["hasMore"] is True

    def test_extra_forbid(self):
        with pytest.raises(ValidationError):
            WorkspaceSearchResponse(
                query="x", matches=[], total_matches=0,
                scanned_files=0, hack=1,
            )


# ── Route tests ─────────────────────────────────────────────────────────────

_SEARCH_BASE = "/api/v1/repos/workspace/search"


class TestSearchRoute:
    """Route-тесты поиска: mock forge, реальный pg_client."""

    @pytest.fixture(autouse=True)
    def _mocks(self, monkeypatch):
        self._forge = FakeForge()
        import orchestrator.cosmo.api.routes.workspace as _ws
        monkeypatch.setattr(_ws, "build_adapter", lambda: self._forge)

        async def _principal() -> PrincipalContext:
            return PrincipalContext(
                user_id="ws-search-tester",
                roles=[CBRRole.SERVICE_ADMIN],
                domain_id="ws-search-dom", zone="zr",
                is_authenticated=True, is_system_admin=False,
            )
        app.dependency_overrides[get_current_principal] = _principal

    @pytest_asyncio.fixture(autouse=True)
    async def _seed_db(self, pg_client: AsyncClient):
        """Seed domain + app + repo_binding."""
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
                "VALUES ('ws-search-dom', 'ws-search-test', 'gitea', "
                "'http://gitea:3000', 't', '{}'::jsonb, 50, 100, 8, now()) "
                "ON CONFLICT (id) DO NOTHING"
            ))
            await conn.execute(text(
                "INSERT INTO apps (id, domain_id, level) "
                "VALUES ('ws-search-app', 'ws-search-dom', 0) "
                "ON CONFLICT (id) DO NOTHING"
            ))
            await conn.execute(text(
                "INSERT INTO repo_bindings (id, app_id, forge_id, repo_path, "
                "default_branch) "
                "VALUES ('ws-search-bind', 'ws-search-app', 'gitea-1', "
                "'ws-owner/ws-repo', 'main') "
                "ON CONFLICT (id) DO NOTHING"
            ))
        await engine.dispose()

    # ── Happy paths ──

    async def test_search_finds_hello(self, pg_client: AsyncClient):
        res = await pg_client.get(
            f"{_SEARCH_BASE}?repo=ws-owner/ws-repo&q=hello")
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["totalMatches"] >= 2  # in main.py and README.md and utils.py
        assert body["scannedFiles"] >= 3   # 3 text files (logo.png skipped)
        assert body["hasMore"] is False

        # All matches should have the right structure
        for m in body["matches"]:
            assert "path" in m
            assert "lineNumber" in m
            assert "lineContent" in m
            assert "matchStart" in m
            assert "matchEnd" in m

    async def test_search_case_sensitive(self, pg_client: AsyncClient):
        # "Hello" capital H — only in README.md
        res = await pg_client.get(
            f"{_SEARCH_BASE}?repo=ws-owner/ws-repo&q=Hello&caseSensitive=true")
        assert res.status_code == 200
        body = res.json()
        # README.md has "Hello World"
        has_readme = any("README" in m["path"] for m in body["matches"])
        assert has_readme, f"Expected match in README.md, got: {body['matches']}"

    async def test_search_regex(self, pg_client: AsyncClient):
        res = await pg_client.get(_SEARCH_BASE, params={
            "repo": "ws-owner/ws-repo",
            "q": r"def\s+\w+",
            "isRegex": "true",
        })
        assert res.status_code == 200, res.text
        body = res.json()
        # Should find def main, def helper, def other, def test_main, def test_helper
        assert body["totalMatches"] >= 3

    async def test_search_path_prefix(self, pg_client: AsyncClient):
        res = await pg_client.get(
            f"{_SEARCH_BASE}?repo=ws-owner/ws-repo&q=def&path_prefix=tests/")
        assert res.status_code == 200
        body = res.json()
        # Only in tests/test_main.py
        for m in body["matches"]:
            assert m["path"].startswith("tests/")

    async def test_search_no_matches(self, pg_client: AsyncClient):
        res = await pg_client.get(
            f"{_SEARCH_BASE}?repo=ws-owner/ws-repo&q=xyznonexistent")
        assert res.status_code == 200
        body = res.json()
        assert body["totalMatches"] == 0
        assert body["matches"] == []

    async def test_search_limit(self, pg_client: AsyncClient):
        res = await pg_client.get(
            f"{_SEARCH_BASE}?repo=ws-owner/ws-repo&q=def&limit=2")
        assert res.status_code == 200
        body = res.json()
        assert len(body["matches"]) <= 2
        if body["totalMatches"] > 2:
            assert body["hasMore"] is True

    async def test_search_binary_skipped(self, pg_client: AsyncClient):
        """Binary files (logo.png) should be silently skipped."""
        res = await pg_client.get(
            f"{_SEARCH_BASE}?repo=ws-owner/ws-repo&q=PNG")
        assert res.status_code == 200
        body = res.json()
        # No match from logo.png (it's binary — even if FakeForge has it as text,
        # the _BINARY_EXTENSIONS heuristic filters it)
        png_matches = [m for m in body["matches"] if "png" in m["path"].lower()]
        assert png_matches == [], f"Binary file matched: {png_matches}"

    # ── Auth / ghost ──

    async def test_search_unknown_repo_404(self, pg_client: AsyncClient):
        res = await pg_client.get(
            f"{_SEARCH_BASE}?repo=ghost/unknown&q=hello")
        assert res.status_code == 404

    async def test_search_anonymous_401(self, pg_client: AsyncClient):
        app.dependency_overrides.pop(get_current_principal, None)
        try:
            res = await pg_client.get(
                f"{_SEARCH_BASE}?repo=ws-owner/ws-repo&q=hello")
            assert res.status_code == 401
        finally:
            pass

    # ── Validation ──

    async def test_search_bad_repo_422(self, pg_client: AsyncClient):
        res = await pg_client.get(
            f"{_SEARCH_BASE}?repo=../bad&q=hello")
        assert res.status_code in (400, 422)  # _validate_or_400 returns 400

    async def test_search_short_query_422(self, pg_client: AsyncClient):
        res = await pg_client.get(
            f"{_SEARCH_BASE}?repo=ws-owner/ws-repo&q=x")
        assert res.status_code == 422

    async def test_search_invalid_regex_400(self, pg_client: AsyncClient):
        res = await pg_client.get(
            f"{_SEARCH_BASE}?repo=ws-owner/ws-repo&q=[unclosed&isRegex=true")
        assert res.status_code == 400

    # ── Forge errors ──

    async def test_search_tree_error_502(self, pg_client: AsyncClient):
        import requests as _r
        self._forge.tree_error = _r.ConnectionError("down")
        res = await pg_client.get(
            f"{_SEARCH_BASE}?repo=ws-owner/ws-repo&q=hello")
        assert res.status_code in (502, 503)