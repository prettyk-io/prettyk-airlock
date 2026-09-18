# -*- coding: utf-8 -*-
"""COS-118: Workspace pipeline discovery — DTO unit + route mock.

Запуск:  pytest .../test_workspace_pipelines.py -q
"""
from __future__ import annotations

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
    WorkspacePipelineSummary,
    WorkspacePipelineListResponse,
)

SHA = "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6a7b8c9d0"


# ── Fake forge adapter ──────────────────────────────────────────────────────

class FakeForge:
    """In-memory forge: tree entries + file content for pipeline discovery."""

    def __init__(self, files: dict[str, str] | None = None):
        # path → content (all text)
        self._files = files or {}
        self.tree_error: Optional[Exception] = None
        self.read_error: Optional[Exception] = None

    def get_tree(self, owner: str, repo: str, ref: str = "",
                 recursive: bool = True) -> list:
        if self.tree_error:
            raise self.tree_error
        from orchestrator.cosmo.adapters.forge_gitea import GiteaTreeEntry
        entries = []
        for path, content in self._files.items():
            entries.append(GiteaTreeEntry(
                path=path, type="blob", sha=f"sha-{path}", size=len(content),
            ))
        return entries

    def get_commit(self, owner: str, repo: str, ref: str = ""):
        import requests as _r
        return type("Commit", (), {
            "sha": SHA, "message": "feat",
            "author": "max", "timestamp": "2026-09-06T00:00:00Z",
        })()

    def read_file(self, owner: str, repo: str, path: str, ref: str = "") -> tuple[str, str]:
        if self.read_error:
            raise self.read_error
        if path in self._files:
            return self._files[path], f"sha-{path}"
        raise LookupError(f"File {path} not found")


# ── Standard fake files: one root .woodpecker.yml + one in .woodpecker/ dir ──

def _standard_files() -> dict[str, str]:
    return {
        ".woodpecker.yml": (
            "pipeline:\n"
            "  build:\n"
            "    image: python:3\n"
            "    commands:\n"
            "      - pip install -r requirements.txt\n"
            "  test:\n"
            "    image: python:3\n"
            "    commands:\n"
            "      - pytest\n"
        ),
        ".woodpecker/deploy.yml": (
            "pipeline:\n"
            "  deploy:\n"
            "    image: alpine\n"
            "    commands:\n"
            "      - echo deployed\n"
        ),
        ".woodpecker/lint.yml": (
            "pipeline:\n"
            "  lint:\n"
            "    image: node\n"
            "    commands:\n"
            "      - npm run lint\n"
        ),
        "README.md": "# My Project\n",
        "src/main.py": "print('hello')\n",
    }


# ── DTO unit ────────────────────────────────────────────────────────────────

class TestPipelineSummaryDto:
    def test_minimal(self):
        p = WorkspacePipelineSummary(
            name="build", path=".woodpecker.yml", format="yaml",
        )
        assert p.name == "build"
        assert p.step_names == []

    def test_with_steps(self):
        p = WorkspacePipelineSummary(
            name="ci", path=".woodpecker.yml", format="yaml",
            is_default=True,
            step_names=["build", "test", "deploy"],
        )
        assert p.step_names == ["build", "test", "deploy"]
        assert p.is_default is True

    def test_camel_case_dump(self):
        p = WorkspacePipelineSummary(
            name="ci", path=".woodpecker.yml", format="yaml",
            is_default=True, step_names=["a"],
        )
        d = p.model_dump(by_alias=True)
        assert "isDefault" in d and d["isDefault"] is True
        assert "stepNames" in d
        assert "defaultPipeline" not in d  # not on summary

    def test_extra_forbid(self):
        with pytest.raises(ValidationError):
            WorkspacePipelineSummary(
                name="x", path="x", format="yaml", hack=1,
            )


class TestPipelineListResponseDto:
    def test_valid(self):
        r = WorkspacePipelineListResponse(
            pipelines=[], default_pipeline=None,
        )
        assert r.pipelines == []
        assert r.default_pipeline is None

    def test_with_pipelines(self):
        r = WorkspacePipelineListResponse(
            pipelines=[
                WorkspacePipelineSummary(
                    name="build", path=".woodpecker.yml", format="yaml",
                    is_default=True, step_names=["build"],
                ),
            ],
            default_pipeline="build",
        )
        assert r.default_pipeline == "build"

    def test_camel_case_dump(self):
        r = WorkspacePipelineListResponse(
            pipelines=[], default_pipeline="ci",
        )
        d = r.model_dump(by_alias=True)
        assert "defaultPipeline" in d and d["defaultPipeline"] == "ci"

    def test_extra_forbid(self):
        with pytest.raises(ValidationError):
            WorkspacePipelineListResponse(
                pipelines=[], default_pipeline=None, hack=1,
            )


# ── Route tests ─────────────────────────────────────────────────────────────

_PIPE_BASE = "/api/v1/repos/workspace/pipelines"


class TestPipelinesRoute:
    """Route-тесты обнаружения пайплайнов: mock forge, реальный pg_client."""

    @pytest.fixture(autouse=True)
    def _mocks(self, monkeypatch):
        self._forge = FakeForge(files=_standard_files())
        import orchestrator.cosmo.api.routes.workspace as _ws
        monkeypatch.setattr(_ws, "build_adapter", lambda: self._forge)

        async def _principal() -> PrincipalContext:
            return PrincipalContext(
                user_id="ws-pipe-tester",
                roles=[CBRRole.SERVICE_ADMIN],
                domain_id="ws-pipe-dom", zone="zr",
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
                "VALUES ('ws-pipe-dom', 'ws-pipe-test', 'gitea', "
                "'http://gitea:3000', 't', '{}'::jsonb, 50, 100, 8, now()) "
                "ON CONFLICT (id) DO NOTHING"
            ))
            await conn.execute(text(
                "INSERT INTO apps (id, domain_id, level) "
                "VALUES ('ws-pipe-app', 'ws-pipe-dom', 0) "
                "ON CONFLICT (id) DO NOTHING"
            ))
            await conn.execute(text(
                "INSERT INTO repo_bindings (id, app_id, forge_id, repo_path, "
                "default_branch) "
                "VALUES ('ws-pipe-bind', 'ws-pipe-app', 'gitea-1', "
                "'ws-owner/ws-repo', 'main') "
                "ON CONFLICT (id) DO NOTHING"
            ))
        await engine.dispose()

    # ── Happy paths ──

    async def test_discovers_pipelines(self, pg_client: AsyncClient):
        res = await pg_client.get(
            f"{_PIPE_BASE}?repo=ws-owner/ws-repo")
        assert res.status_code == 200, res.text
        body = res.json()
        assert len(body["pipelines"]) == 3  # .woodpecker.yml + 2 in .woodpecker/
        names = {p["name"] for p in body["pipelines"]}
        assert ".woodpecker" in names
        assert "deploy" in names
        assert "lint" in names

    async def test_first_is_default(self, pg_client: AsyncClient):
        res = await pg_client.get(
            f"{_PIPE_BASE}?repo=ws-owner/ws-repo")
        assert res.status_code == 200
        body = res.json()
        assert body["defaultPipeline"] == body["pipelines"][0]["name"]
        assert body["pipelines"][0]["isDefault"] is True

    async def test_extracts_step_names(self, pg_client: AsyncClient):
        res = await pg_client.get(
            f"{_PIPE_BASE}?repo=ws-owner/ws-repo")
        assert res.status_code == 200
        body = res.json()

        # Find .woodpecker.yml (has build + test)
        wp = [p for p in body["pipelines"] if p["name"] == ".woodpecker"]
        assert len(wp) == 1
        assert "build" in wp[0]["stepNames"]
        assert "test" in wp[0]["stepNames"]

        # deploy.yml has one step
        dp = [p for p in body["pipelines"] if p["name"] == "deploy"]
        assert len(dp) == 1
        assert "deploy" in dp[0]["stepNames"]

    async def test_empty_repo_no_pipelines(self, pg_client: AsyncClient):
        """Репо без файлов пайплайнов — пустой список."""
        self._forge._files = {"README.md": "# empty\n"}
        res = await pg_client.get(
            f"{_PIPE_BASE}?repo=ws-owner/ws-repo")
        assert res.status_code == 200
        body = res.json()
        assert body["pipelines"] == []
        assert body["defaultPipeline"] is None

    async def test_broken_yaml_invalid_format(self, pg_client: AsyncClient):
        """Невалидный YAML → format=invalid, steps=[], не 500."""
        self._forge._files = {
            ".woodpecker.yml": "pipeline:\n  build:\n    - !!!bad yaml!!!\n",
        }
        res = await pg_client.get(
            f"{_PIPE_BASE}?repo=ws-owner/ws-repo")
        assert res.status_code == 200
        body = res.json()
        assert len(body["pipelines"]) >= 1
        broken = body["pipelines"][0]
        assert broken["format"] == "invalid"
        assert broken["stepNames"] == []

    async def test_yaml_no_steps(self, pg_client: AsyncClient):
        """YAML без ключа pipeline/steps — всё равно valid, steps=[]."""
        self._forge._files = {
            ".woodpecker.yml": "when:\n  branch: main\n",
        }
        res = await pg_client.get(
            f"{_PIPE_BASE}?repo=ws-owner/ws-repo")
        assert res.status_code == 200
        body = res.json()
        assert len(body["pipelines"]) == 1
        assert body["pipelines"][0]["format"] == "yaml"
        assert body["pipelines"][0]["stepNames"] == []

    async def test_only_woodpecker_dir(self, pg_client: AsyncClient):
        """Только .woodpecker/*.yml без корневого файла."""
        self._forge._files = {
            ".woodpecker/build.yml": "pipeline:\n  build:\n    image: python\n",
            ".woodpecker/test.yml": "pipeline:\n  test:\n    image: python\n",
            "README.md": "# doc\n",
        }
        res = await pg_client.get(
            f"{_PIPE_BASE}?repo=ws-owner/ws-repo")
        assert res.status_code == 200
        body = res.json()
        names = {p["name"] for p in body["pipelines"]}
        assert names == {"build", "test"}

    async def test_pipeline_yaml_root_file(self, pg_client: AsyncClient):
        """Сканирование .pipeline.yaml корневого файла."""
        self._forge._files = {
            ".pipeline.yaml": "pipeline:\n  ci:\n    image: python\n",
        }
        res = await pg_client.get(
            f"{_PIPE_BASE}?repo=ws-owner/ws-repo")
        assert res.status_code == 200
        body = res.json()
        names = {p["name"] for p in body["pipelines"]}
        assert ".pipeline" in names

    async def test_yaml_file_in_woodpecker_dir(self, pg_client: AsyncClient):
        """Файлы без .yml/.yaml в .woodpecker/ игнорируются."""
        self._forge._files = {
            ".woodpecker/README.md": "# docs\n",
            ".woodpecker/config.json": "{}",
            ".woodpecker/ci.yml": "pipeline:\n  ci:\n    image: python\n",
        }
        res = await pg_client.get(
            f"{_PIPE_BASE}?repo=ws-owner/ws-repo")
        assert res.status_code == 200
        body = res.json()
        names = {p["name"] for p in body["pipelines"]}
        assert names == {"ci"}  # only .yml, not .md or .json

    # ── Auth / ghost ──

    async def test_unknown_repo_404(self, pg_client: AsyncClient):
        res = await pg_client.get(
            f"{_PIPE_BASE}?repo=ghost/unknown")
        assert res.status_code == 404

    async def test_anonymous_401(self, pg_client: AsyncClient):
        app.dependency_overrides.pop(get_current_principal, None)
        try:
            res = await pg_client.get(
                f"{_PIPE_BASE}?repo=ws-owner/ws-repo")
            assert res.status_code == 401
        finally:
            pass

    # ── Validation ──

    async def test_bad_repo_400(self, pg_client: AsyncClient):
        res = await pg_client.get(
            f"{_PIPE_BASE}?repo=../bad")
        assert res.status_code in (400, 422)

    # ── Forge errors ──

    async def test_tree_error_503(self, pg_client: AsyncClient):
        import requests as _r
        self._forge.tree_error = _r.ConnectionError("down")
        res = await pg_client.get(
            f"{_PIPE_BASE}?repo=ws-owner/ws-repo")
        assert res.status_code in (502, 503)