# -*- coding: utf-8 -*-
"""COS-110: Workspace drafts & 3-way diff — unit + integration tests.

Запуск:  pytest .../test_workspace_draft.py -q
Live:    $env:COSMO_LIVE_DRAFT="1"; pytest .../test_workspace_draft.py -v
"""
from __future__ import annotations

import json
import os
import sys
import uuid
from pathlib import Path
from unittest import mock

import pytest
from httpx import AsyncClient
from pydantic import ValidationError

_orch = Path(__file__).resolve().parents[1]
if str(_orch) not in sys.path:
    sys.path.insert(0, str(_orch))

from orchestrator.cosmo.domain.workspace import (
    WorkspaceContractError,
    WorkspaceDiffResponse,
    WorkspaceDraftResponse,
    WorkspaceDraftUpsertRequest,
    validate_head_sha,
    validate_tree_path,
)

LIVE_GATE = "COSMO_LIVE_DRAFT"
SHA = "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6a7b8c9d0"
SHA2 = "b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6a7b8c9d0a1"


# ── Mock store (in-memory dict — doubles valkey_drafts) ────────────────

class InMemoryDraftStore:
    """In-memory double для valkey_drafts."""
    def __init__(self):
        self._store: dict[str, dict] = {}

    def _key(self, domain, user_id, owner, repo, branch, path):
        return f"cosmo:draft:{domain}:{user_id}:{owner}:{repo}:{branch}:{path}"

    def save_draft(self, domain, user_id, owner, repo, branch, path,
                   content, base_blob_sha):
        k = self._key(domain, user_id, owner, repo, branch, path)
        data = {"content": content, "base_blob_sha": base_blob_sha,
                "updated_at": "2026-09-05T12:00:00+00:00"}
        self._store[k] = data
        return data

    def load_draft(self, domain, user_id, owner, repo, branch, path):
        k = self._key(domain, user_id, owner, repo, branch, path)
        return self._store.get(k)

    def delete_draft(self, domain, user_id, owner, repo, branch, path):
        k = self._key(domain, user_id, owner, repo, branch, path)
        if k in self._store:
            del self._store[k]
            return True
        return False


# ── Fake Gitea adapter (same pattern as test_workspace_commit.py) ──────

class FakeAdapter:
    def __init__(self, file_content_map: dict | None = None, head_sha: str = SHA):
        self.file_content_map = file_content_map or {}
        self._blob_map: dict[str, str] = {}  # ref → content
        self._head_sha = head_sha

    def get_commit(self, owner: str, repo: str, ref: str):
        class C:
            pass
        c = C()
        c.sha = self._head_sha
        return c

    def read_file(self, owner: str, repo: str, path: str, ref: str = ""):
        # Сначала ищем в blob_map (точный ref)
        if ref and ref in self._blob_map:
            content = self._blob_map[ref]
            return content, ref

        # Затем в file_content_map (любой ref → текущий head)
        if path not in self.file_content_map:
            raise LookupError(f"File {path} not found")
        content = self.file_content_map[path]
        sha = self.file_content_map.get(f"{path}__sha", SHA)
        return content, sha


# ── Seed helper (reused from test_workspace_commit.py) ─────────────────

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

class TestDraftDto:
    """Unit-тесты Pydantic DTO (валидация, camelCase, extra=forbid)."""

    def test_upsert_minimal(self):
        r = WorkspaceDraftUpsertRequest(
            repo="org/app", branch="main", path="src/x.py",
            content="print(1)",
        )
        assert r.repo == "org/app"
        assert r.base_blob_sha is None

    def test_upsert_full_camel_case(self):
        payload = {
            "repo": "org/app", "branch": "main", "path": "src/x.py",
            "content": "hello", "baseBlobSha": SHA,
        }
        r = WorkspaceDraftUpsertRequest.model_validate_json(json.dumps(payload))
        assert r.base_blob_sha == SHA
        assert r.path == "src/x.py"

    def test_upsert_extra_forbidden(self):
        with pytest.raises(ValidationError):
            WorkspaceDraftUpsertRequest(
                repo="org/app", branch="main", path="x.py",
                content="y", hack=1,
            )

    def test_traversal_rejected(self):
        with pytest.raises(ValidationError):
            WorkspaceDraftUpsertRequest(
                repo="org/app", branch="main", path="../secret",
                content="evil",
            )

    def test_response_dump_alias(self):
        r = WorkspaceDraftResponse(
            path="x.py", content="hi", base_blob_sha=SHA,
            updated_at="2026-09-05T12:00:00Z",
        )
        d = json.loads(r.model_dump_json(by_alias=True))
        assert d == {
            "path": "x.py", "content": "hi",
            "baseBlobSha": SHA, "updatedAt": "2026-09-05T12:00:00Z",
        }

    def test_diff_response_alias(self):
        r = WorkspaceDiffResponse(
            path="x.py", base_content="base", draft_content="draft",
            head_content="head", has_conflict=True,
            additions=5, deletions=2,
        )
        d = json.loads(r.model_dump_json(by_alias=True))
        assert d["hasConflict"] is True
        assert d["baseContent"] == "base"
        assert d["draftContent"] == "draft"
        assert d["headContent"] == "head"
        assert d["additions"] == 5
        assert d["deletions"] == 2

    def test_diff_response_no_conflict_by_default(self):
        r = WorkspaceDiffResponse(
            path="x.py",
            base_content=None, draft_content=None, head_content=None,
            has_conflict=False,
        )
        assert r.has_conflict is False
        assert r.additions == 0

    def test_empty_path_rejected(self):
        with pytest.raises(ValidationError):
            WorkspaceDraftUpsertRequest(
                repo="org/app", branch="main", path="",
                content="y",
            )


# ── Route integration tests ────────────────────────────────────────────

class TestDraftRoute:
    """Интеграционные тесты PUT/GET/DELETE draft + GET diff с mock'ами."""

    @pytest.fixture(autouse=True)
    def _mock_deps(self, monkeypatch):
        # Mock forge adapter
        from orchestrator.cosmo.api import forge_client as fc
        self._adapter = FakeAdapter()
        monkeypatch.setattr(fc, "build_adapter", lambda: self._adapter)

        # Mock valkey drafts — patch the module functions
        self._store = InMemoryDraftStore()
        import orchestrator.cosmo.infra.valkey_drafts as vd
        monkeypatch.setattr(vd, "save_draft", self._store.save_draft)
        monkeypatch.setattr(vd, "load_draft", self._store.load_draft)
        monkeypatch.setattr(vd, "delete_draft", self._store.delete_draft)
        # Remove ValkeyUnreachableError — never raised in mock tests
        monkeypatch.setattr(vd, "ValkeyUnreachableError", RuntimeError)

    # ── PUT /workspace/draft ──

    @pytest.mark.asyncio
    async def test_upsert_201(self, pg_client: AsyncClient):
        meta = await _seed_app(pg_client)
        res = await pg_client.put("/api/v1/repos/workspace/draft", json={
            "repo": meta["repo"], "branch": "main", "path": "src/x.py",
            "content": "print(1)",
        }, headers={"X-Cosmo-Domain": meta["domain"]})
        assert res.status_code == 201, res.text
        data = res.json()
        assert data["path"] == "src/x.py"
        assert data["content"] == "print(1)"

    @pytest.mark.asyncio
    async def test_upsert_with_base_blob_sha(self, pg_client: AsyncClient):
        meta = await _seed_app(pg_client)
        res = await pg_client.put("/api/v1/repos/workspace/draft", json={
            "repo": meta["repo"], "branch": "main", "path": "src/y.py",
            "content": "hi", "baseBlobSha": SHA,
        }, headers={"X-Cosmo-Domain": meta["domain"]})
        assert res.status_code == 201, res.text
        assert res.json()["baseBlobSha"] == SHA

    @pytest.mark.asyncio
    async def test_upsert_overwrite(self, pg_client: AsyncClient):
        meta = await _seed_app(pg_client)
        body = {"repo": meta["repo"], "branch": "main", "path": "src/z.py",
                "content": "v1"}
        h = {"X-Cosmo-Domain": meta["domain"]}
        r1 = await pg_client.put("/api/v1/repos/workspace/draft", json=body, headers=h)
        assert r1.status_code == 201
        body["content"] = "v2"
        r2 = await pg_client.put("/api/v1/repos/workspace/draft", json=body, headers=h)
        assert r2.status_code == 201
        assert r2.json()["content"] == "v2"

    # ── GET /workspace/draft ──

    @pytest.mark.asyncio
    async def test_get_existing(self, pg_client: AsyncClient):
        meta = await _seed_app(pg_client)
        h = {"X-Cosmo-Domain": meta["domain"]}
        await pg_client.put("/api/v1/repos/workspace/draft", json={
            "repo": meta["repo"], "branch": "main", "path": "src/a.py",
            "content": "aaa",
        }, headers=h)
        res = await pg_client.get(
            "/api/v1/repos/workspace/draft",
            params={"repo": meta["repo"], "branch": "main", "path": "src/a.py"},
            headers=h,
        )
        assert res.status_code == 200, res.text
        assert res.json()["content"] == "aaa"

    @pytest.mark.asyncio
    async def test_get_missing_404(self, pg_client: AsyncClient):
        meta = await _seed_app(pg_client)
        res = await pg_client.get(
            "/api/v1/repos/workspace/draft",
            params={"repo": meta["repo"], "branch": "main", "path": "src/nope.py"},
            headers={"X-Cosmo-Domain": meta["domain"]},
        )
        assert res.status_code == 404, res.text

    @pytest.mark.asyncio
    async def test_get_no_binding_404(self, pg_client: AsyncClient):
        res = await pg_client.get(
            "/api/v1/repos/workspace/draft",
            params={"repo": "ghost/phantom", "branch": "main", "path": "x.py"},
            headers={"X-Cosmo-Domain": "dom-00000000"},
        )
        assert res.status_code == 404

    # ── DELETE /workspace/draft ──

    @pytest.mark.asyncio
    async def test_delete_existing_204(self, pg_client: AsyncClient):
        meta = await _seed_app(pg_client)
        h = {"X-Cosmo-Domain": meta["domain"]}
        await pg_client.put("/api/v1/repos/workspace/draft", json={
            "repo": meta["repo"], "branch": "main", "path": "src/del.py",
            "content": "bye",
        }, headers=h)
        res = await pg_client.delete(
            "/api/v1/repos/workspace/draft",
            params={"repo": meta["repo"], "branch": "main", "path": "src/del.py"},
            headers=h,
        )
        assert res.status_code == 204, res.text

        # Verify deleted
        r2 = await pg_client.get(
            "/api/v1/repos/workspace/draft",
            params={"repo": meta["repo"], "branch": "main", "path": "src/del.py"},
            headers=h,
        )
        assert r2.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_missing_404(self, pg_client: AsyncClient):
        meta = await _seed_app(pg_client)
        res = await pg_client.delete(
            "/api/v1/repos/workspace/draft",
            params={"repo": meta["repo"], "branch": "main", "path": "nope.py"},
            headers={"X-Cosmo-Domain": meta["domain"]},
        )
        assert res.status_code == 404

    # ── GET /workspace/diff ──

    @pytest.mark.asyncio
    async def test_diff_no_draft_returns_empty(self, pg_client: AsyncClient):
        meta = await _seed_app(pg_client)
        res = await pg_client.get(
            "/api/v1/repos/workspace/diff",
            params={"repo": meta["repo"], "branch": "main", "path": "src/none.py"},
            headers={"X-Cosmo-Domain": meta["domain"]},
        )
        assert res.status_code == 200, res.text
        data = res.json()
        assert data["hasConflict"] is False
        assert data["draftContent"] is None

    @pytest.mark.asyncio
    async def test_diff_no_conflict_base_equals_head(self, pg_client: AsyncClient):
        meta = await _seed_app(pg_client)
        h = {"X-Cosmo-Domain": meta["domain"]}
        content = "def foo(): pass\n"
        self._adapter.file_content_map = {
            "src/ok.py": content, "src/ok.py__sha": SHA,
        }
        await pg_client.put("/api/v1/repos/workspace/draft", json={
            "repo": meta["repo"], "branch": "main", "path": "src/ok.py",
            "content": content, "baseBlobSha": SHA,
        }, headers=h)
        res = await pg_client.get(
            "/api/v1/repos/workspace/diff",
            params={"repo": meta["repo"], "branch": "main", "path": "src/ok.py"},
            headers=h,
        )
        assert res.status_code == 200, res.text
        data = res.json()
        assert data["hasConflict"] is False
        assert data["baseContent"] == content
        assert data["draftContent"] == content
        assert data["headContent"] == content

    @pytest.mark.asyncio
    async def test_diff_has_conflict_head_diverged(self, pg_client: AsyncClient):
        meta = await _seed_app(pg_client)
        h = {"X-Cosmo-Domain": meta["domain"]}
        path = "src/div.py"
        base = "old base content\n"
        head = "someone else changed this\n"
        draft = "my draft changes\n"
        # Blob map: SHA → base content (old version того же файла)
        self._adapter._blob_map = {SHA: base}
        # file_content_map → head (что сейчас в ветке)
        self._adapter.file_content_map = {
            path: head, f"{path}__sha": SHA2,
        }
        await pg_client.put("/api/v1/repos/workspace/draft", json={
            "repo": meta["repo"], "branch": "main", "path": path,
            "content": draft, "baseBlobSha": SHA,
        }, headers=h)
        res = await pg_client.get(
            "/api/v1/repos/workspace/diff",
            params={"repo": meta["repo"], "branch": "main", "path": path,
                    "baseBlobSha": SHA},
            headers=h,
        )
        assert res.status_code == 200, res.text
        data = res.json()
        assert data["hasConflict"] is True
        assert data["baseContent"] == base
        assert data["draftContent"] == draft
        assert data["headContent"] == head

    @pytest.mark.asyncio
    async def test_diff_no_binding_404(self, pg_client: AsyncClient):
        res = await pg_client.get(
            "/api/v1/repos/workspace/diff",
            params={"repo": "ghost/phantom", "branch": "main", "path": "x.py"},
            headers={"X-Cosmo-Domain": "dom-00000000"},
        )
        assert res.status_code == 404

    # ── Valkey unavailable → 503 ──

    @pytest.mark.asyncio
    async def test_upsert_valkey_down_503(self, pg_client: AsyncClient, monkeypatch):
        from orchestrator.cosmo.infra import valkey_drafts as vd
        monkeypatch.setattr(vd, "ValkeyUnreachableError",
                            type("ValkeyUnreachableError", (Exception,), {}))
        # Patch save_draft to raise
        monkeypatch.setattr(vd, "save_draft",
                            mock.Mock(side_effect=vd.ValkeyUnreachableError("down")))
        meta = await _seed_app(pg_client)
        res = await pg_client.put("/api/v1/repos/workspace/draft", json={
            "repo": meta["repo"], "branch": "main", "path": "src/x.py",
            "content": "hi",
        }, headers={"X-Cosmo-Domain": meta["domain"]})
        assert res.status_code == 503, res.text

    @pytest.mark.asyncio
    async def test_load_valkey_down_503(self, pg_client: AsyncClient, monkeypatch):
        from orchestrator.cosmo.infra import valkey_drafts as vd
        monkeypatch.setattr(vd, "ValkeyUnreachableError",
                            type("ValkeyUnreachableError", (Exception,), {}))
        monkeypatch.setattr(vd, "load_draft",
                            mock.Mock(side_effect=vd.ValkeyUnreachableError("down")))
        meta = await _seed_app(pg_client)
        res = await pg_client.get(
            "/api/v1/repos/workspace/draft",
            params={"repo": meta["repo"], "branch": "main", "path": "src/x.py"},
            headers={"X-Cosmo-Domain": meta["domain"]},
        )
        assert res.status_code == 503, res.text

    # ── Traversal guard on GET/DELETE ──

    @pytest.mark.asyncio
    async def test_get_traversal_rejected_400(self, pg_client: AsyncClient):
        meta = await _seed_app(pg_client)
        res = await pg_client.get(
            "/api/v1/repos/workspace/draft",
            params={"repo": meta["repo"], "branch": "main", "path": "../secret"},
            headers={"X-Cosmo-Domain": meta["domain"]},
        )
        assert res.status_code == 400, res.text


# ── Live opt-in tests ──────────────────────────────────────────────────

class TestLiveDraft:
    """Live-тесты против реального Valkey + Gitea (skip по умолчанию)."""

    @pytest.mark.skipif(LIVE_GATE not in os.environ, reason=f"set {LIVE_GATE}=1")
    @pytest.mark.asyncio
    async def test_save_load_delete_cycle(self, pg_client: AsyncClient):
        meta = await _seed_app(pg_client, repo="fc-live/draft-test-1")
        h = {"X-Cosmo-Domain": meta["domain"]}
        path = f"smoke-{uuid.uuid4().hex[:6]}.py"

        # Save
        r = await pg_client.put("/api/v1/repos/workspace/draft", json={
            "repo": meta["repo"], "branch": "main", "path": path,
            "content": "live test",
        }, headers=h)
        assert r.status_code == 201, r.text

        # Load
        r = await pg_client.get(
            "/api/v1/repos/workspace/draft",
            params={"repo": meta["repo"], "branch": "main", "path": path},
            headers=h,
        )
        assert r.status_code == 200, r.text
        assert r.json()["content"] == "live test"

        # Delete
        r = await pg_client.delete(
            "/api/v1/repos/workspace/draft",
            params={"repo": meta["repo"], "branch": "main", "path": path},
            headers=h,
        )
        assert r.status_code == 204

        # Verify deleted
        r = await pg_client.get(
            "/api/v1/repos/workspace/draft",
            params={"repo": meta["repo"], "branch": "main", "path": path},
            headers=h,
        )
        assert r.status_code == 404

    @pytest.mark.skipif(LIVE_GATE not in os.environ, reason=f"set {LIVE_GATE}=1")
    @pytest.mark.asyncio
    async def test_diff_against_live_gitea(self, pg_client: AsyncClient):
        meta = await _seed_app(pg_client, repo="fc-live/draft-test-2")
        h = {"X-Cosmo-Domain": meta["domain"]}
        path = f"smoke-{uuid.uuid4().hex[:6]}.txt"

        # Save draft
        await pg_client.put("/api/v1/repos/workspace/draft", json={
            "repo": meta["repo"], "branch": "main", "path": path,
            "content": "draft content",
        }, headers=h)

        # Diff (file likely doesn't exist in gitea — still 200, head_content None)
        r = await pg_client.get(
            "/api/v1/repos/workspace/diff",
            params={"repo": meta["repo"], "branch": "main", "path": path},
            headers=h,
        )
        assert r.status_code == 200
        assert r.json()["draftContent"] == "draft content"