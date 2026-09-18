# -*- coding: utf-8 -*-
"""COS-107: Workspace commit — unit (DTO + CAS route mock), live opt-in.

Запуск:  pytest .../test_workspace_commit.py -q
Live:     $env:COSMO_LIVE_COMMIT = "1"; pytest .../test_workspace_commit.py -v
"""
from __future__ import annotations

import base64
import json
import os
import sys
import uuid
from pathlib import Path
from typing import Optional

import pytest
from httpx import AsyncClient
from pydantic import ValidationError

_orch = Path(__file__).resolve().parents[1]
if str(_orch) not in sys.path:
    sys.path.insert(0, str(_orch))

from orchestrator.cosmo.domain.workspace import (
    WorkspaceContentsFileChange,
    WorkspaceContentsCommitRequest,
    WorkspaceContentsCommitResponse,
    WorkspaceContractError,
    validate_head_sha,
    validate_tree_path,
)

LIVE_GATE = "COSMO_LIVE_COMMIT"
SHA = "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6a7b8c9d0"


# ── DTO unit ────────────────────────────────────────────────────────────

class TestCommitDto:
    def test_request_minimal_single_file(self):
        r = WorkspaceContentsCommitRequest(
            repo="org/app", branch="main", message="feat: add x",
            changes=[WorkspaceContentsFileChange(path="src/x.py", content="print(1)")],
        )
        assert r.repo == "org/app"
        assert r.changes[0].action == "upsert"

    def test_request_full_camel_case(self):
        payload = {
            "repo": "org/app", "branch": "main", "message": "fix",
            "changes": [
                {"path": "x.py", "content": "hi", "baseBlobSha": SHA, "action": "upsert"},
                {"path": "old.py", "content": "", "action": "delete"},
            ],
            "expectedHeadSha": SHA,
        }
        r = WorkspaceContentsCommitRequest.model_validate_json(json.dumps(payload))
        assert r.expected_head_sha == SHA
        assert r.changes[0].base_blob_sha == SHA
        assert r.changes[1].action == "delete"

    def test_request_extra_forbidden(self):
        with pytest.raises(ValidationError):
            WorkspaceContentsCommitRequest(
                repo="org/app", branch="main", message="x",
                changes=[WorkspaceContentsFileChange(path="x.py", content="y")],
                hack=1,
            )

    def test_empty_changes_rejected(self):
        with pytest.raises(ValidationError):
            WorkspaceContentsCommitRequest(
                repo="org/app", branch="main", message="x",
                changes=[],
            )

    def test_empty_message_rejected(self):
        with pytest.raises(ValidationError):
            WorkspaceContentsCommitRequest(
                repo="org/app", branch="main", message="",
                changes=[WorkspaceContentsFileChange(path="x.py", content="y")],
            )

    def test_traversal_in_change_path_rejected(self):
        with pytest.raises(ValidationError):
            WorkspaceContentsCommitRequest(
                repo="org/app", branch="main", message="x",
                changes=[WorkspaceContentsFileChange(path="../secrets.yaml", content="evil")],
            )

    def test_response_dump_alias(self):
        r = WorkspaceContentsCommitResponse(
            commit_sha=SHA, branch="main", tree_sha=SHA,
        )
        d = json.loads(r.model_dump_json(by_alias=True))
        assert d == {"commitSha": SHA, "branch": "main", "treeSha": SHA}

    def test_file_change_base_blob_sha_camel_alias(self):
        """base_blob_sha принимается и как snake, и как camel (baseBlobSha)."""
        r = WorkspaceContentsCommitRequest.model_validate_json(json.dumps({
            "repo": "org/app", "branch": "main", "message": "x",
            "changes": [{"path": "f.py", "content": "y", "baseBlobSha": SHA}],
        }))
        assert r.changes[0].base_blob_sha == SHA


# ── Route tests (mock adapter) ─────────────────────────────────────────

class FakeAdapter:
    def __init__(self, file_sha_map: dict | None = None, head_sha: str = SHA):
        self.file_sha_map = file_sha_map or {}
        self._head_sha = head_sha
        self._parent_calls: list = []
        self._commit_calls: list = []

    def get_commit(self, owner: str, repo: str, ref: str):
        class C:
            pass
        c = C()
        c.sha = self._head_sha
        return c

    def read_file(self, owner: str, repo: str, path: str, ref: str = ""):
        sha = self.file_sha_map.get(path)
        if sha is None:
            raise LookupError(f"File {path} not found")
        return "dummy-content", sha

    def create_commit(self, owner, repo, branch, message, changes, parent_sha):
        self._commit_calls.append((changes, parent_sha))
        import hashlib
        class C:
            pass
        c = C()
        c.sha = hashlib.sha1(str(uuid.uuid4()).encode()).hexdigest()
        c.message = message
        c.author = "cosmo"
        c.timestamp = "2026-09-03T12:00:00Z"
        c.tree_sha = hashlib.sha1(("tree" + str(uuid.uuid4())).encode()).hexdigest()
        return c


def _seed_app(pg_client: AsyncClient, repo: str = "org/app"):
    """Создать domain + app + binding через API."""
    import anyio  # noqa

    async def _seed():
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

    return _seed()


class TestCommitRoute:
    """Интеграционные тесты POST /workspace/commit с mock-адаптером."""

    @pytest.fixture(autouse=True)
    def _mock_adapter(self, monkeypatch):
        from orchestrator.cosmo.api import forge_client as fc

        self._adapter = FakeAdapter()
        monkeypatch.setattr(fc, "build_adapter", lambda: self._adapter)

    @pytest.mark.asyncio
    async def test_upsert_single_file_201(self, pg_client: AsyncClient):
        meta = await _seed_app(pg_client, repo="fc-org/fc-live")
        res = await pg_client.post("/api/v1/repos/workspace/commit", json={
            "repo": meta["repo"], "branch": "main", "message": "feat: add x.py",
            "changes": [{"path": "src/x.py", "content": "print(1)"}],
        }, headers={"X-Cosmo-Domain": meta["domain"]})
        assert res.status_code == 201, res.text
        body = res.json()
        assert body["commitSha"]
        assert body["treeSha"]
        assert body["branch"] == "main"
        assert len(self._adapter._commit_calls) == 1

    @pytest.mark.asyncio
    async def test_cas_base_blob_sha_mismatch_409(self, pg_client: AsyncClient):
        meta = await _seed_app(pg_client, repo="fc-org/fc-cas")
        self._adapter.file_sha_map["src/x.py"] = "0" * 40

        res = await pg_client.post("/api/v1/repos/workspace/commit", json={
            "repo": meta["repo"], "branch": "main", "message": "fix",
            "changes": [{"path": "src/x.py", "content": "v2", "baseBlobSha": "1" * 40}],
        }, headers={"X-Cosmo-Domain": meta["domain"]})
        assert res.status_code == 409, res.text
        assert "CAS conflict" in res.json()["detail"]

    @pytest.mark.asyncio
    async def test_cas_file_deleted_while_having_base_sha_409(self, pg_client: AsyncClient):
        """base_blob_sha указан, но файла нет → несоответствие."""
        meta = await _seed_app(pg_client, repo="fc-org/fc-vanished")
        # файла нет в file_sha_map → LookupError → нет current_sha
        # при base_blob_sha != None → 409
        res = await pg_client.post("/api/v1/repos/workspace/commit", json={
            "repo": meta["repo"], "branch": "main", "message": "fix",
            "changes": [{"path": "src/gone.py", "content": "v2", "baseBlobSha": SHA}],
        }, headers={"X-Cosmo-Domain": meta["domain"]})
        assert res.status_code == 409, res.text
        assert "base_blob_sha provided" in res.json()["detail"]

    @pytest.mark.asyncio
    async def test_expected_head_sha_mismatch_409(self, pg_client: AsyncClient):
        meta = await _seed_app(pg_client, repo="fc-org/fc-head")
        self._adapter._head_sha = "a" * 40  # head = aaaaa...

        res = await pg_client.post("/api/v1/repos/workspace/commit", json={
            "repo": meta["repo"], "branch": "main", "message": "fix",
            "changes": [{"path": "x.py", "content": "ok"}],
            "expectedHeadSha": "b" * 40,  # bbbbb... ≠ aaaaa...
        }, headers={"X-Cosmo-Domain": meta["domain"]})
        assert res.status_code == 409, res.text
        assert "expected_head_sha" in res.json()["detail"]

    @pytest.mark.asyncio
    async def test_delete_action_honors_base_tree(self, pg_client: AsyncClient):
        meta = await _seed_app(pg_client, repo="fc-org/fc-delete")
        self._adapter.file_sha_map = {"old.py": SHA}
        res = await pg_client.post("/api/v1/repos/workspace/commit", json={
            "repo": meta["repo"], "branch": "main", "message": "remove old",
            "changes": [{"path": "old.py", "content": "", "action": "delete"}],
        }, headers={"X-Cosmo-Domain": meta["domain"]})
        assert res.status_code == 201, res.text
        assert len(self._adapter._commit_calls[0][0]) == 1

    @pytest.mark.asyncio
    async def test_multifile_upsert_201(self, pg_client: AsyncClient):
        meta = await _seed_app(pg_client, repo="fc-org/fc-multi")
        res = await pg_client.post("/api/v1/repos/workspace/commit", json={
            "repo": meta["repo"], "branch": "main", "message": "multi-add",
            "changes": [
                {"path": "x.py", "content": "print(1)"},
                {"path": "y.py", "content": "print(2)"},
            ],
        }, headers={"X-Cosmo-Domain": meta["domain"]})
        assert res.status_code == 201, res.text
        changes, parent = self._adapter._commit_calls[0]
        assert len(changes) == 2
        assert changes[0]["path"] == "x.py"

    @pytest.mark.asyncio
    async def test_no_binding_404(self, pg_client: AsyncClient):
        """Репо без привязки → ghost 404."""
        res = await pg_client.post("/api/v1/repos/workspace/commit", json={
            "repo": "ghost/repo", "branch": "main", "message": "x",
            "changes": [{"path": "x.py", "content": "y"}],
        })
        assert res.status_code == 404

    @pytest.mark.asyncio
    async def test_cas_match_without_conflict_201(self, pg_client: AsyncClient):
        meta = await _seed_app(pg_client, repo="fc-org/fc-match")
        self._adapter.file_sha_map["src/x.py"] = SHA

        res = await pg_client.post("/api/v1/repos/workspace/commit", json={
            "repo": meta["repo"], "branch": "main", "message": "update",
            "changes": [{"path": "src/x.py", "content": "v2", "baseBlobSha": SHA}],
        }, headers={"X-Cosmo-Domain": meta["domain"]})
        assert res.status_code == 201, res.text


# ── Live commits (opt-in gate) ─────────────────────────────────────────

@pytest.mark.skipif(not os.getenv(LIVE_GATE), reason=f"{LIVE_GATE} not set")
class TestLiveCommit:
    """Живой коммит в Gitea :3100 через ПУ :8100."""

    GITEA = os.getenv("PK_GITEA_URL_LIVE", "http://localhost:3100").rstrip("/")
    API = os.getenv("PK_API_URL_LIVE", "http://localhost:8100").rstrip("/")
    TAG = "cl" + uuid.uuid4().hex[:8]
    ORG = "fc-live"
    REPO = f"{TAG}-cmt"
    DOMAIN = f"dom-{TAG}"
    APP = f"app-{TAG}"
    REPO_FULL = f"{ORG}/{REPO}"

    @staticmethod
    def _gitea(method: str, path: str, **kw):
        import requests
        return requests.request(method, f"{TestLiveCommit.GITEA}/api/v1{path}",
                                auth=("cosmo", os.getenv("COSMO_FORGE_ADMIN_PASSWORD", "cosmo-admin-dev")),
                                timeout=15, **kw)

    @staticmethod
    def _api(method: str, path: str, jwt: str, **kw):
        import requests
        return requests.request(method, f"{TestLiveCommit.API}{path}",
                                headers={"Authorization": f"Bearer {jwt}"}, timeout=15, **kw)

    @pytest.fixture(scope="class")
    def live_setup(self):
        import requests

        # jwt mint (COS-085 pattern)
        h = base64.urlsafe_b64encode(
            json.dumps({"alg": "none", "typ": "JWT"}).encode()).rstrip(b"=").decode()
        p = base64.urlsafe_b64encode(
            json.dumps({"sub": "gate-agent", "roles": ["admin_sec"], "is_admin": True}).encode()
        ).rstrip(b"=").decode()
        jwt = f"ey{h}.{p}.sig"

        # repo
        r = self._gitea("POST", "/orgs", json={"username": self.ORG})
        assert r.status_code in (201, 422)
        r = self._gitea("POST", f"/orgs/{self.ORG}/repos", json={
            "name": self.REPO, "auto_init": True, "default_branch": "main",
            "private": False,
        })
        assert r.status_code == 201

        # domain + app + binding
        r = self._api("POST", "/api/v1/domains", jwt, json={
            "id": self.DOMAIN, "label": f"FC Commit {self.TAG}",
            "forge_binding": {"forge_type": "gitea", "url": "http://gitea",
                              "token_ref": "vault:secret/data/token"},
        })
        assert r.status_code in (200, 201)
        r = self._api("POST", "/api/v1/apps", jwt, json={
            "id": self.APP, "domain_id": self.DOMAIN, "level": 1,
            "repo_binding": {"forge_id": "gitea", "repo_path": self.REPO_FULL},
        })
        assert r.status_code in (200, 201)

        yield {"jwt": jwt, "repo": self.REPO_FULL}

        # cleanup
        self._api("DELETE", f"/api/v1/apps/{self.APP}", jwt)
        self._api("DELETE", f"/api/v1/domains/{self.DOMAIN}", jwt)
        self._gitea("DELETE", f"/repos/{self.ORG}/{self.REPO}")

    def test_single_file_upsert_live(self, live_setup):
        r = self._api("POST", "/api/v1/repos/workspace/commit", live_setup["jwt"],
                      json={
                          "repo": live_setup["repo"], "branch": "main",
                          "message": "feat: live commit test (COS-107)",
                          "changes": [{"path": "hello.txt", "content": "live commit works!"}],
                      })
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["commitSha"]
        assert body["treeSha"]

        # верификация: файл читается через API
        r = self._api("GET", f"/api/v1/repos/file?repo={live_setup['repo']}"
                       f"&branch=main&headSha={body['commitSha']}&path=hello.txt",
                       live_setup["jwt"])
        assert r.status_code == 200, r.text
        assert r.json()["content"] == "live commit works!"

    def test_cas_conflict_live(self, live_setup):
        # первый коммит для baseline
        r1 = self._api("POST", "/api/v1/repos/workspace/commit", live_setup["jwt"],
                       json={
                           "repo": live_setup["repo"], "branch": "main",
                           "message": "baseline", "changes": [{"path": "two.py", "content": "v1"}]})
        assert r1.status_code == 201
        r2 = self._api("POST", "/api/v1/repos/workspace/commit", live_setup["jwt"],
                       json={
                           "repo": live_setup["repo"], "branch": "main",
                           "message": "conflict attempt",
                           "changes": [{"path": "two.py", "content": "v2",
                                        "baseBlobSha": "0" * 40}],
                       })
        assert r2.status_code == 409, r2.text