# -*- coding: utf-8 -*-
"""COS-116: Workspace commits history & timeline — unit + route tests.

Запуск:  pytest .../test_workspace_commits.py -q
"""
from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

import pytest
from httpx import AsyncClient
from pydantic import ValidationError

_orch = Path(__file__).resolve().parents[1]
if str(_orch) not in sys.path:
    sys.path.insert(0, str(_orch))

from orchestrator.cosmo.domain.workspace import (
    WorkspaceCommitSummary,
    WorkspaceCommitListResponse,
)

SHA1 = "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6a7b8c9d0"
SHA2 = "b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6a7b8c9d0a1"
SHA3 = "c3d4e5f6a7b8c9d0e1f2a3b4c5d6a7b8c9d0a1b2"
SHA4 = "d4e5f6a7b8c9d0e1f2a3b4c5d6a7b8c9d0a1b2c3"


def _make_commit(sha: str, message: str, parents: list[str] | None = None) -> dict:
    return {
        "sha": sha,
        "short_sha": sha[:8],
        "message": message,
        "author_name": "Dev",
        "author_email": "dev@org.local",
        "committed_at": "2026-09-06T12:00:00+03:00",
        "parent_shas": parents or [],
    }


ALL_COMMITS = [
    _make_commit(SHA1, "feat: add login", []),
    _make_commit(SHA2, "fix: typo in readme", [SHA1]),
    _make_commit(SHA3, "chore: update deps", [SHA2]),
    _make_commit(SHA4, "docs: changelog", [SHA3]),
]


# ── Fake Gitea adapter for commits ──────────────────────────────────────

class FakeCommitAdapter:
    def __init__(self, commits: list[dict] | None = None):
        self._commits = commits or list(ALL_COMMITS)
        self.last_params: dict | None = None

    def list_commits(
        self,
        owner: str,
        repo: str,
        branch: str | None = None,
        path: str | None = None,
        limit: int = 30,
        page: int = 1,
    ) -> list[dict]:
        self.last_params = dict(owner=owner, repo=repo, branch=branch, path=path, limit=limit, page=page)
        # Имитация пагинации: срез коммитов по (page-1)*limit .. page*limit
        start = (page - 1) * limit
        end = start + limit
        page_commits = self._commits[start:end]
        # Применяем фильтр по пути если передан
        if path:
            page_commits = [c for c in page_commits if path in c["message"]]
        return page_commits


# ── Seed helper ─────────────────────────────────────────────────────────

async def _seed_app(pg_client: AsyncClient, repo: str = "org/app"):
    dom = f"dom-{uuid.uuid4().hex[:8]}"
    aid = f"app-{uuid.uuid4().hex[:8]}"
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


# ── DTO unit tests ─────────────────────────────────────────────────────

class TestCommitDto:
    def test_commit_summary_minimal(self):
        c = WorkspaceCommitSummary(
            sha=SHA1, short_sha=SHA1[:8], message="init",
            author_name="Dev", author_email="dev@o.l",
            committed_at="2026-09-06T12:00:00Z",
        )
        assert c.sha == SHA1
        assert c.short_sha == SHA1[:8]
        assert c.parent_shas == []

    def test_commit_summary_camel_case(self):
        payload = {
            "sha": SHA1,
            "shortSha": SHA1[:8],
            "message": "init",
            "authorName": "Dev",
            "authorEmail": "dev@o.l",
            "committedAt": "2026-09-06T12:00:00Z",
            "parentShas": [SHA2],
        }
        c = WorkspaceCommitSummary.model_validate_json(json.dumps(payload))
        assert c.author_name == "Dev"
        assert c.author_email == "dev@o.l"
        assert c.parent_shas == [SHA2]

    def test_commit_summary_extra_forbidden(self):
        with pytest.raises(ValidationError):
            WorkspaceCommitSummary(
                sha=SHA1, short_sha=SHA1[:8], message="x",
                author_name="D", author_email="d@o",
                committed_at="t", hack=1,
            )

    def test_commit_list_response_dump(self):
        r = WorkspaceCommitListResponse(
            commits=[
                WorkspaceCommitSummary(
                    sha=SHA1, short_sha=SHA1[:8], message="init",
                    author_name="Dev", author_email="dev@o.l",
                    committed_at="t",
                ),
            ],
            total=1, has_more=False,
        )
        d = json.loads(r.model_dump_json(by_alias=True))
        assert d["total"] == 1
        assert d["hasMore"] is False
        assert len(d["commits"]) == 1
        assert d["commits"][0]["shortSha"] == SHA1[:8]

    def test_commit_list_has_more_true(self):
        r = WorkspaceCommitListResponse(commits=[], total=0, has_more=True)
        d = json.loads(r.model_dump_json(by_alias=True))
        assert d["hasMore"] is True

    def test_commit_summary_parent_shas_default(self):
        c = WorkspaceCommitSummary(
            sha=SHA1, short_sha=SHA1[:8], message="M",
            author_name="A", author_email="a@b", committed_at="t",
        )
        assert c.parent_shas == []


# ── Route tests ─────────────────────────────────────────────────────────

class TestCommitsRoute:
    @pytest.fixture(autouse=True)
    def _mock_adapter(self, monkeypatch):
        from orchestrator.cosmo.api import forge_client as fc
        self._adapter = FakeCommitAdapter()
        monkeypatch.setattr(fc, "build_adapter", lambda: self._adapter)

    @pytest.mark.asyncio
    async def test_list_commits_200(self, pg_client: AsyncClient):
        meta = await _seed_app(pg_client)
        res = await pg_client.get(
            "/api/v1/repos/workspace/commits",
            params={"repo": meta["repo"]},
            headers={"X-Cosmo-Domain": meta["domain"]},
        )
        assert res.status_code == 200, res.text
        data = res.json()
        assert data["total"] == 4
        assert data["hasMore"] is False
        commits = data["commits"]
        assert len(commits) == 4
        assert commits[0]["sha"] == SHA1
        assert commits[0]["shortSha"] == SHA1[:8]
        assert commits[0]["authorName"] == "Dev"
        assert commits[0]["parentShas"] == []

    @pytest.mark.asyncio
    async def test_list_commits_pagination(self, pg_client: AsyncClient):
        meta = await _seed_app(pg_client)
        res = await pg_client.get(
            "/api/v1/repos/workspace/commits",
            params={"repo": meta["repo"], "limit": 2, "offset": 2},
            headers={"X-Cosmo-Domain": meta["domain"]},
        )
        assert res.status_code == 200, res.text
        data = res.json()
        assert data["total"] == 2  # SHA3, SHA4
        assert data["hasMore"] is True  # full page → can't know if more
        commits = data["commits"]
        assert commits[0]["sha"] == SHA3
        assert commits[1]["sha"] == SHA4

    @pytest.mark.asyncio
    async def test_list_commits_has_more(self, pg_client: AsyncClient):
        meta = await _seed_app(pg_client)
        res = await pg_client.get(
            "/api/v1/repos/workspace/commits",
            params={"repo": meta["repo"], "limit": 2, "offset": 0},
            headers={"X-Cosmo-Domain": meta["domain"]},
        )
        assert res.status_code == 200, res.text
        data = res.json()
        assert len(data["commits"]) == 2
        assert data["hasMore"] is True  # limit=2 но всего 4 → есть ещё

    @pytest.mark.asyncio
    async def test_list_commits_with_branch(self, pg_client: AsyncClient):
        meta = await _seed_app(pg_client)
        res = await pg_client.get(
            "/api/v1/repos/workspace/commits",
            params={"repo": meta["repo"], "branch": "feat/x"},
            headers={"X-Cosmo-Domain": meta["domain"]},
        )
        assert res.status_code == 200, res.text
        assert self._adapter.last_params["branch"] == "feat/x"

    @pytest.mark.asyncio
    async def test_list_commits_with_path(self, pg_client: AsyncClient):
        meta = await _seed_app(pg_client)
        res = await pg_client.get(
            "/api/v1/repos/workspace/commits",
            params={"repo": meta["repo"], "path": "src/main.py"},
            headers={"X-Cosmo-Domain": meta["domain"]},
        )
        assert res.status_code == 200, res.text
        assert self._adapter.last_params["path"] == "src/main.py"

    @pytest.mark.asyncio
    async def test_list_commits_limit_default_30(self, pg_client: AsyncClient):
        meta = await _seed_app(pg_client)
        res = await pg_client.get(
            "/api/v1/repos/workspace/commits",
            params={"repo": meta["repo"]},
            headers={"X-Cosmo-Domain": meta["domain"]},
        )
        assert res.status_code == 200
        assert self._adapter.last_params["limit"] == 30

    @pytest.mark.asyncio
    async def test_list_commits_limit_capped_100(self, pg_client: AsyncClient):
        meta = await _seed_app(pg_client)
        res = await pg_client.get(
            "/api/v1/repos/workspace/commits",
            params={"repo": meta["repo"], "limit": 200},
            headers={"X-Cosmo-Domain": meta["domain"]},
        )
        # FastAPI отвергает >100 (Query(le=100)) → 422
        assert res.status_code == 422, res.text

    @pytest.mark.asyncio
    async def test_list_commits_ghost_404(self, pg_client: AsyncClient):
        res = await pg_client.get(
            "/api/v1/repos/workspace/commits",
            params={"repo": "ghost/no-repo"},
            headers={"X-Cosmo-Domain": "dom-00000000"},
        )
        assert res.status_code == 404