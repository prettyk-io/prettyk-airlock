# -*- coding: utf-8 -*-
"""COS-154: legacy /api/v1/repos/commit & commit-and-run — честный forge-write.

Убирает фейковый ``c-{uuid}`` commit hash: write-path теперь через
``build_adapter().commit_changes`` (bulk Contents API, тот же контур что
COS-124 /workspace/commits). CommitFileItem = {path, content} без action →
маппинг в create/update через CAS-состояние (read_file → blob sha).

Запуск:  pytest .../test_repos_commit_cos154.py -q
"""
from __future__ import annotations

import sys
import uuid
from pathlib import Path

import pytest
from httpx import AsyncClient

_orch = Path(__file__).resolve().parents[1]
if str(_orch) not in sys.path:
    sys.path.insert(0, str(_orch))

from orchestrator.cosmo.adapters.forge_gitea import GiteaConflictError  # noqa: E402

SHA = "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6a7b8c9d0"
REAL_SHA = "f" * 40

_COMMIT = "/api/v1/repos/commit"
_COMMIT_AND_RUN = "/api/v1/repos/commit-and-run"


class FakeAutoActionAdapter:
    """Mock Gitea: get_commit / read_file / commit_changes (auto-action)."""

    def __init__(self, file_sha_map: dict | None = None,
                 fail_commit: Exception | None = None,
                 not_configured: bool = False):
        self.file_sha_map = file_sha_map if file_sha_map is not None else {}
        self._fail_commit = fail_commit
        self._not_configured = not_configured
        self.commit_calls: list[dict] = []

    def read_file(self, owner, repo, path, ref=""):
        sha = self.file_sha_map.get(path)
        if sha is None:
            raise LookupError(f"File {path} not found")
        return "dummy-content", sha

    def commit_changes(self, owner, repo, branch, message, file_changes,
                       author_name=None, author_email=None):
        if self._fail_commit is not None:
            raise self._fail_commit
        self.commit_calls.append({
            "owner": owner, "repo": repo, "branch": branch, "message": message,
            "file_changes": file_changes,
        })
        return {
            "sha": REAL_SHA,
            "html_url": "http://gitea/org/repo/commit/" + REAL_SHA,
            "authored_at": "2026-09-18T10:00:00Z",
            "files_changed": len(file_changes),
        }


async def _seed_app(pg_client: AsyncClient, repo: str = "org/app",
                    dom: str | None = None, app_id: str | None = None):
    dom = dom or f"dom-{uuid.uuid4().hex[:8]}"
    aid = app_id or f"app-{uuid.uuid4().hex[:8]}"
    r = await pg_client.post("/api/v1/domains", json={
        "id": dom, "label": f"Dom {dom[:8]}",
        "forge_binding": {"forge_type": "gitea", "url": "http://gitea",
                          "token_ref": "vault:secret/data/token"},
    })
    assert r.status_code in (200, 201), f"domain POST: {r.text}"
    res = await pg_client.post("/api/v1/apps", json={
        "id": aid, "domain_id": dom, "level": 1,
        "repo_binding": {"forge_id": "gitea", "repo_path": repo},
    })
    assert res.status_code in (200, 201), res.text
    return {"domain": dom, "app": aid, "repo": repo}


class TestLegacyCommitCos154:
    @pytest.fixture(autouse=True)
    def _mock_adapter(self, monkeypatch):
        from orchestrator.cosmo.api import forge_client as fc
        self._adapter = FakeAutoActionAdapter()
        monkeypatch.setattr(fc, "build_adapter", lambda: self._adapter)

    @pytest.mark.asyncio
    async def test_commit_returns_real_sha_create(self, pg_client: AsyncClient):
        meta = await _seed_app(pg_client, repo="c154-org/c154-create")
        res = await pg_client.post(_COMMIT, json={
            "repo": meta["repo"], "branch": "main", "message": "add x",
            "files": [{"path": "src/x.py", "content": "print(1)"}],
        }, headers={"X-Cosmo-Domain": meta["domain"]})
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["commit_hash"] == REAL_SHA
        assert body["commit_hash"] != ""  # не фейк
        assert not body["commit_hash"].startswith("c-")
        ops = self._adapter.commit_calls[0]["file_changes"]
        assert ops[0]["action"] == "create"
        assert "sha" not in ops[0]

    @pytest.mark.asyncio
    async def test_commit_update_maps_to_update_with_sha(self, pg_client: AsyncClient):
        meta = await _seed_app(pg_client, repo="c154-org/c154-update")
        self._adapter.file_sha_map["src/x.py"] = SHA
        res = await pg_client.post(_COMMIT, json={
            "repo": meta["repo"], "branch": "main", "message": "upd x",
            "files": [{"path": "src/x.py", "content": "v2"}],
        }, headers={"X-Cosmo-Domain": meta["domain"]})
        assert res.status_code == 200, res.text
        ops = self._adapter.commit_calls[0]["file_changes"]
        assert ops[0]["action"] == "update"
        assert ops[0]["sha"] == SHA

    @pytest.mark.asyncio
    async def test_commit_mixed_create_update(self, pg_client: AsyncClient):
        meta = await _seed_app(pg_client, repo="c154-org/c154-mixed")
        self._adapter.file_sha_map = {"b.py": SHA}
        res = await pg_client.post(_COMMIT, json={
            "repo": meta["repo"], "branch": "main", "message": "mix",
            "files": [
                {"path": "a.py", "content": "a"},
                {"path": "b.py", "content": "b2"},
            ],
        }, headers={"X-Cosmo-Domain": meta["domain"]})
        assert res.status_code == 200, res.text
        ops = self._adapter.commit_calls[0]["file_changes"]
        assert [o["action"] for o in ops] == ["create", "update"]
        assert len(self._adapter.commit_calls) == 1

    @pytest.mark.asyncio
    async def test_commit_empty_files_400(self, pg_client: AsyncClient):
        meta = await _seed_app(pg_client, repo="c154-org/c154-empty")
        res = await pg_client.post(_COMMIT, json={
            "repo": meta["repo"], "branch": "main", "message": "x", "files": [],
        }, headers={"X-Cosmo-Domain": meta["domain"]})
        assert res.status_code == 400, res.text
        assert self._adapter.commit_calls == []

    @pytest.mark.asyncio
    async def test_commit_conflict_maps_409(self, pg_client: AsyncClient):
        meta = await _seed_app(pg_client, repo="c154-org/c154-cc")
        self._adapter._fail_commit = GiteaConflictError("ref moved")
        res = await pg_client.post(_COMMIT, json={
            "repo": meta["repo"], "branch": "main", "message": "race",
            "files": [{"path": "n.py", "content": "x"}],
        }, headers={"X-Cosmo-Domain": meta["domain"]})
        assert res.status_code == 409, res.text

    @pytest.mark.asyncio
    async def test_commit_ghost_404(self, pg_client: AsyncClient):
        res = await pg_client.post(_COMMIT, json={
            "repo": "ghost/repo", "branch": "main", "message": "x",
            "files": [{"path": "x.py", "content": "y"}],
        })
        assert res.status_code == 404

    @pytest.mark.asyncio
    async def test_commit_forge_not_configured_503(self, pg_client: AsyncClient, monkeypatch):
        meta = await _seed_app(pg_client, repo="c154-org/c154-nconf")
        from orchestrator.cosmo.api import forge_client as fc
        from orchestrator.cosmo.api.forge_client import ForgeNotConfigured
        monkeypatch.setattr(fc, "build_adapter",
                            lambda: (_ for _ in ()).throw(ForgeNotConfigured("PK_GITEA_URL is not set")))
        res = await pg_client.post(_COMMIT, json={
            "repo": meta["repo"], "branch": "main", "message": "x",
            "files": [{"path": "x.py", "content": "y"}],
        }, headers={"X-Cosmo-Domain": meta["domain"]})
        assert res.status_code == 503, res.text
        assert "Forge not configured" in res.json()["detail"]


class TestLegacyCommitAndRunCos154:
    @pytest.fixture(autouse=True)
    def _mock_adapter(self, monkeypatch):
        from orchestrator.cosmo.api import forge_client as fc
        self._adapter = FakeAutoActionAdapter()
        monkeypatch.setattr(fc, "build_adapter", lambda: self._adapter)

    @pytest.mark.asyncio
    async def test_commit_and_run_commit_fails_no_run(self, pg_client: AsyncClient):
        """Commit падает → Run НЕ создаётся (ложная атомарность убрана)."""
        meta = await _seed_app(pg_client, repo="c154-org/c154-runfail")
        self._adapter._fail_commit = GiteaConflictError("ref moved")
        res = await pg_client.post(_COMMIT_AND_RUN, json={
            "repo": meta["repo"], "branch": "main", "message": "x",
            "plan_id": "plan-c154", "domain_id": meta["domain"],
            "files": [{"path": "x.py", "content": "y"}],
        }, headers={"X-Cosmo-Domain": meta["domain"]})
        assert res.status_code == 409, res.text
        runs = await pg_client.get("/api/v1/runs?plan_id=plan-c154",
                                   headers={"X-Cosmo-Domain": meta["domain"]})
        assert runs.status_code == 200
        body = runs.json()
        items = body if isinstance(body, list) else (body.get("runs") or body.get("items") or [])
        assert items == []

    @pytest.mark.asyncio
    async def test_commit_and_run_forge_not_configured_no_run(self, pg_client: AsyncClient,
                                                              monkeypatch):
        meta = await _seed_app(pg_client, repo="c154-org/c154-runnconf")
        from orchestrator.cosmo.api import forge_client as fc
        from orchestrator.cosmo.api.forge_client import ForgeNotConfigured
        monkeypatch.setattr(fc, "build_adapter",
                            lambda: (_ for _ in ()).throw(ForgeNotConfigured("no url")))
        res = await pg_client.post(_COMMIT_AND_RUN, json={
            "repo": meta["repo"], "branch": "main", "message": "x",
            "plan_id": "plan-c154b", "domain_id": meta["domain"],
            "files": [{"path": "x.py", "content": "y"}],
        }, headers={"X-Cosmo-Domain": meta["domain"]})
        assert res.status_code == 503, res.text
        runs = await pg_client.get("/api/v1/runs?plan_id=plan-c154b",
                                   headers={"X-Cosmo-Domain": meta["domain"]})
        body = runs.json()
        items = body if isinstance(body, list) else (body.get("runs") or body.get("items") or [])
        assert items == []