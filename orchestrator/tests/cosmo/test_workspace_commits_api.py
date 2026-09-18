# -*- coding: utf-8 -*-
"""COS-124: Atomic multi-file commit — unit (DTO) + route (mock adapter).

Запуск:  pytest .../test_workspace_commits_api.py -q
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

from orchestrator.cosmo.adapters.forge_gitea import GiteaConflictError
from orchestrator.cosmo.domain.workspace import (
    WorkspaceCommitRequest,
    WorkspaceCommitResponse,
    WorkspaceFileChange,
)

SHA = "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6a7b8c9d0"
SHA2 = "b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6a7b8c9d0a1"

_PRIVATE_KEY = "-----BEGIN RSA PRIVATE KEY-----\nMIIEabc123\n-----END RSA PRIVATE KEY-----"
_JWT = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJkZXYifQ.abcdefghijklmnopqrstuv"

_API = "/api/v1/repos/workspace/commits"


# ── DTO unit ─────────────────────────────────────────────────────────────

class TestAtomicCommitDto:
    def test_request_minimal_create(self):
        r = WorkspaceCommitRequest(
            repo="org/app", branch="main", message="feat: add",
            file_changes=[
                WorkspaceFileChange(path="src/x.py", content="print(1)", action="create"),
            ],
        )
        assert r.repo == "org/app"
        assert r.file_changes[0].action == "create"
        assert r.author_name is None and r.author_email is None

    def test_request_full_camel_case(self):
        payload = {
            "repo": "org/app", "branch": "main", "message": "refactor",
            "authorName": "Dev", "authorEmail": "dev@org.local",
            "fileChanges": [
                {"path": "a.py", "content": "a", "action": "create"},
                {"path": "b.py", "content": "b2", "action": "update"},
                {"path": "c.py", "action": "delete"},
            ],
        }
        r = WorkspaceCommitRequest.model_validate_json(json.dumps(payload))
        assert r.author_name == "Dev"
        assert r.author_email == "dev@org.local"
        assert [c.action for c in r.file_changes] == ["create", "update", "delete"]
        assert r.file_changes[2].content is None

    def test_extra_forbidden(self):
        with pytest.raises(ValidationError):
            WorkspaceCommitRequest(
                repo="org/app", branch="main", message="x",
                file_changes=[
                    WorkspaceFileChange(path="x.py", content="y", action="create"),
                ],
                hack=1,
            )

    def test_empty_file_changes_rejected(self):
        with pytest.raises(ValidationError):
            WorkspaceCommitRequest(
                repo="org/app", branch="main", message="x", file_changes=[],
            )

    def test_empty_message_rejected(self):
        with pytest.raises(ValidationError):
            WorkspaceCommitRequest(
                repo="org/app", branch="main", message="",
                file_changes=[
                    WorkspaceFileChange(path="x.py", content="y", action="create"),
                ],
            )

    def test_message_too_long_rejected(self):
        with pytest.raises(ValidationError):
            WorkspaceCommitRequest(
                repo="org/app", branch="main", message="m" * 501,
                file_changes=[
                    WorkspaceFileChange(path="x.py", content="y", action="create"),
                ],
            )

    def test_traversal_path_rejected(self):
        with pytest.raises(ValidationError):
            WorkspaceFileChange(path="../secrets.yaml", content="evil", action="create")

    def test_absolute_path_rejected(self):
        with pytest.raises(ValidationError):
            WorkspaceFileChange(path="/etc/passwd", content="x", action="create")

    def test_content_required_for_create(self):
        with pytest.raises(ValidationError):
            WorkspaceFileChange(path="x.py", action="create")

    def test_content_required_for_update(self):
        with pytest.raises(ValidationError):
            WorkspaceFileChange(path="x.py", action="update")

    def test_delete_with_content_rejected(self):
        with pytest.raises(ValidationError):
            WorkspaceFileChange(path="x.py", content="oops", action="delete")

    def test_delete_without_content_ok(self):
        fc = WorkspaceFileChange(path="x.py", action="delete")
        assert fc.content is None

    def test_empty_content_allowed_for_create(self):
        fc = WorkspaceFileChange(path="empty.txt", content="", action="create")
        assert fc.content == ""

    def test_invalid_action_rejected(self):
        with pytest.raises(ValidationError):
            WorkspaceFileChange(path="x.py", content="y", action="upsert")

    def test_response_dump_alias(self):
        r = WorkspaceCommitResponse(
            sha=SHA, html_url="http://g/c",
            authored_at="2026-09-18T10:00:00Z", files_changed=3,
        )
        d = json.loads(r.model_dump_json(by_alias=True))
        assert d["sha"] == SHA
        assert d["htmlUrl"] == "http://g/c"
        assert d["filesChanged"] == 3
        assert d["authoredAt"].startswith("2026-09-18")

    def test_response_sha_validated(self):
        with pytest.raises(ValidationError):
            WorkspaceCommitResponse(
                sha="zz", html_url="u",
                authored_at="2026-09-18T10:00:00Z", files_changed=1,
            )

    def test_author_fields_optional(self):
        r = WorkspaceCommitRequest(
            repo="o/r", branch="main", message="m",
            file_changes=[
                WorkspaceFileChange(path="x.py", content="y", action="update"),
            ],
        )
        assert r.author_name is None and r.author_email is None


# ── Route tests (mock adapter) ───────────────────────────────────────────

class FakeAtomicAdapter:
    """Mock Gitea: get_commit / read_file / commit_changes."""

    def __init__(self, file_sha_map: dict | None = None, head_sha: str | None = SHA,
                 fail_commit: Exception | None = None):
        self.file_sha_map = file_sha_map if file_sha_map is not None else {}
        self._head_sha = head_sha
        self._fail_commit = fail_commit
        self.commit_calls: list[dict] = []

    def get_commit(self, owner: str, repo: str, ref: str = ""):
        if self._head_sha is None:
            raise LookupError(f"No commits in {owner}/{repo}")
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

    def commit_changes(self, owner, repo, branch, message, file_changes,
                       author_name=None, author_email=None):
        if self._fail_commit is not None:
            raise self._fail_commit
        self.commit_calls.append({
            "owner": owner, "repo": repo, "branch": branch, "message": message,
            "file_changes": file_changes,
            "author_name": author_name, "author_email": author_email,
        })
        return {
            "sha": "f" * 40,
            "html_url": "http://gitea/org/repo/commit/" + "f" * 40,
            "authored_at": "2026-09-18T10:00:00Z",
            "files_changed": len(file_changes),
        }


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


class TestAtomicCommitRoute:
    @pytest.fixture(autouse=True)
    def _mock_adapter(self, monkeypatch):
        from orchestrator.cosmo.api import forge_client as fc
        self._adapter = FakeAtomicAdapter()
        monkeypatch.setattr(fc, "build_adapter", lambda: self._adapter)

    @pytest.mark.asyncio
    async def test_create_201(self, pg_client: AsyncClient):
        meta = await _seed_app(pg_client, repo="ac-org/ac-create")
        res = await pg_client.post(_API, json={
            "repo": meta["repo"], "branch": "main", "message": "add x",
            "fileChanges": [{"path": "src/x.py", "content": "print(1)", "action": "create"}],
        }, headers={"X-Cosmo-Domain": meta["domain"]})
        assert res.status_code == 201, res.text
        body = res.json()
        assert body["sha"] == "f" * 40
        assert body["htmlUrl"].startswith("http://gitea/")
        assert body["authoredAt"].startswith("2026-09-18")
        assert body["filesChanged"] == 1
        ops = self._adapter.commit_calls[0]["file_changes"]
        assert ops[0]["action"] == "create"
        assert "sha" not in ops[0]

    @pytest.mark.asyncio
    async def test_update_201_with_blob_sha(self, pg_client: AsyncClient):
        meta = await _seed_app(pg_client, repo="ac-org/ac-update")
        self._adapter.file_sha_map["src/x.py"] = SHA
        res = await pg_client.post(_API, json={
            "repo": meta["repo"], "branch": "main", "message": "upd x",
            "fileChanges": [{"path": "src/x.py", "content": "v2", "action": "update"}],
        }, headers={"X-Cosmo-Domain": meta["domain"]})
        assert res.status_code == 201, res.text
        ops = self._adapter.commit_calls[0]["file_changes"]
        assert ops[0]["action"] == "update"
        assert ops[0]["sha"] == SHA
        assert ops[0]["content"] == "v2"

    @pytest.mark.asyncio
    async def test_delete_201_with_blob_sha(self, pg_client: AsyncClient):
        meta = await _seed_app(pg_client, repo="ac-org/ac-delete")
        self._adapter.file_sha_map["old.py"] = SHA
        res = await pg_client.post(_API, json={
            "repo": meta["repo"], "branch": "main", "message": "rm old",
            "fileChanges": [{"path": "old.py", "action": "delete"}],
        }, headers={"X-Cosmo-Domain": meta["domain"]})
        assert res.status_code == 201, res.text
        ops = self._adapter.commit_calls[0]["file_changes"]
        assert ops[0]["action"] == "delete"
        assert ops[0]["sha"] == SHA
        assert ops[0]["content"] is None

    @pytest.mark.asyncio
    async def test_mixed_create_update_delete_201(self, pg_client: AsyncClient):
        meta = await _seed_app(pg_client, repo="ac-org/ac-mixed")
        self._adapter.file_sha_map = {"b.py": SHA, "c.py": SHA2}
        res = await pg_client.post(_API, json={
            "repo": meta["repo"], "branch": "main", "message": "atomic mix",
            "fileChanges": [
                {"path": "a.py", "content": "a", "action": "create"},
                {"path": "b.py", "content": "b2", "action": "update"},
                {"path": "c.py", "action": "delete"},
            ],
        }, headers={"X-Cosmo-Domain": meta["domain"]})
        assert res.status_code == 201, res.text
        assert res.json()["filesChanged"] == 3
        ops = self._adapter.commit_calls[0]["file_changes"]
        assert [o["action"] for o in ops] == ["create", "update", "delete"]
        assert len(self._adapter.commit_calls) == 1  # одна транзакция

    @pytest.mark.asyncio
    async def test_gate_block_422(self, pg_client: AsyncClient):
        res = await pg_client.post(_API, json={
            "repo": "ac-org/ac-gate", "branch": "main", "message": "leak",
            "fileChanges": [
                {"path": "keys.txt", "content": _PRIVATE_KEY, "action": "create"},
            ],
        })
        assert res.status_code == 422, res.text
        detail = res.json()["detail"]
        assert detail["verdict"] == "BLOCK"
        assert len(detail["violations"]) >= 1
        assert detail["violations"][0]["severity"] == "BLOCK"
        # Коммит в forge не полетел.
        assert self._adapter.commit_calls == []

    @pytest.mark.asyncio
    async def test_gate_blocks_forbidden_file_422(self, pg_client: AsyncClient):
        res = await pg_client.post(_API, json={
            "repo": "ac-org/ac-env", "branch": "main", "message": "env",
            "fileChanges": [{"path": ".env", "content": "SAFE=1", "action": "create"}],
        })
        assert res.status_code == 422, res.text
        assert res.json()["detail"]["verdict"] == "BLOCK"

    @pytest.mark.asyncio
    async def test_gate_warn_passes_201(self, pg_client: AsyncClient):
        meta = await _seed_app(pg_client, repo="ac-org/ac-warn")
        res = await pg_client.post(_API, json={
            "repo": meta["repo"], "branch": "main", "message": "warn only",
            "fileChanges": [{"path": "cfg.txt", "content": _JWT, "action": "create"}],
        }, headers={"X-Cosmo-Domain": meta["domain"]})
        assert res.status_code == 201, res.text

    @pytest.mark.asyncio
    async def test_create_conflict_409(self, pg_client: AsyncClient):
        meta = await _seed_app(pg_client, repo="ac-org/ac-cc")
        self._adapter.file_sha_map["x.py"] = SHA  # уже существует
        res = await pg_client.post(_API, json={
            "repo": meta["repo"], "branch": "main", "message": "dup",
            "fileChanges": [{"path": "x.py", "content": "y", "action": "create"}],
        }, headers={"X-Cosmo-Domain": meta["domain"]})
        assert res.status_code == 409, res.text
        assert "create conflict" in res.json()["detail"]
        assert self._adapter.commit_calls == []

    @pytest.mark.asyncio
    async def test_update_missing_409(self, pg_client: AsyncClient):
        meta = await _seed_app(pg_client, repo="ac-org/ac-um")
        res = await pg_client.post(_API, json={
            "repo": meta["repo"], "branch": "main", "message": "upd",
            "fileChanges": [{"path": "gone.py", "content": "v2", "action": "update"}],
        }, headers={"X-Cosmo-Domain": meta["domain"]})
        assert res.status_code == 409, res.text
        assert "does not exist" in res.json()["detail"]

    @pytest.mark.asyncio
    async def test_delete_missing_409(self, pg_client: AsyncClient):
        meta = await _seed_app(pg_client, repo="ac-org/ac-dm")
        res = await pg_client.post(_API, json={
            "repo": meta["repo"], "branch": "main", "message": "rm",
            "fileChanges": [{"path": "gone.py", "action": "delete"}],
        }, headers={"X-Cosmo-Domain": meta["domain"]})
        assert res.status_code == 409, res.text

    @pytest.mark.asyncio
    async def test_adapter_conflict_maps_409(self, pg_client: AsyncClient):
        meta = await _seed_app(pg_client, repo="ac-org/ac-adc")
        self._adapter._fail_commit = GiteaConflictError("ref moved")
        res = await pg_client.post(_API, json={
            "repo": meta["repo"], "branch": "main", "message": "race",
            "fileChanges": [{"path": "n.py", "content": "x", "action": "create"}],
        }, headers={"X-Cosmo-Domain": meta["domain"]})
        assert res.status_code == 409, res.text
        assert "commit conflict" in res.json()["detail"]

    @pytest.mark.asyncio
    async def test_branch_missing_404(self, pg_client: AsyncClient):
        meta = await _seed_app(pg_client, repo="ac-org/ac-nobranch")
        self._adapter._head_sha = None  # get_commit → LookupError
        res = await pg_client.post(_API, json={
            "repo": meta["repo"], "branch": "no-such", "message": "x",
            "fileChanges": [{"path": "x.py", "content": "y", "action": "create"}],
        }, headers={"X-Cosmo-Domain": meta["domain"]})
        assert res.status_code == 404, res.text

    @pytest.mark.asyncio
    async def test_ghost_404(self, pg_client: AsyncClient):
        res = await pg_client.post(_API, json={
            "repo": "ghost/repo", "branch": "main", "message": "x",
            "fileChanges": [{"path": "x.py", "content": "y", "action": "create"}],
        })
        assert res.status_code == 404

    @pytest.mark.asyncio
    async def test_author_forwarded(self, pg_client: AsyncClient):
        meta = await _seed_app(pg_client, repo="ac-org/ac-author")
        res = await pg_client.post(_API, json={
            "repo": meta["repo"], "branch": "main", "message": "authored",
            "authorName": "Dev", "authorEmail": "dev@org.local",
            "fileChanges": [{"path": "x.py", "content": "y", "action": "create"}],
        }, headers={"X-Cosmo-Domain": meta["domain"]})
        assert res.status_code == 201, res.text
        call = self._adapter.commit_calls[0]
        assert call["author_name"] == "Dev"
        assert call["author_email"] == "dev@org.local"

    @pytest.mark.asyncio
    async def test_extra_field_422(self, pg_client: AsyncClient):
        res = await pg_client.post(_API, json={
            "repo": "ac-org/ac-extra", "branch": "main", "message": "x",
            "fileChanges": [{"path": "x.py", "content": "y", "action": "create"}],
            "hack": 1,
        })
        assert res.status_code == 422

    @pytest.mark.asyncio
    async def test_empty_file_changes_422(self, pg_client: AsyncClient):
        res = await pg_client.post(_API, json={
            "repo": "ac-org/ac-empty", "branch": "main", "message": "x",
            "fileChanges": [],
        })
        assert res.status_code == 422

    @pytest.mark.asyncio
    async def test_traversal_repo_400_or_422(self, pg_client: AsyncClient):
        res = await pg_client.post(_API, json={
            "repo": "../bad", "branch": "main", "message": "x",
            "fileChanges": [{"path": "x.py", "content": "y", "action": "create"}],
        })
        assert res.status_code in (400, 422)

    @pytest.mark.asyncio
    async def test_traversal_path_400_or_422(self, pg_client: AsyncClient):
        res = await pg_client.post(_API, json={
            "repo": "ac-org/ac-trav", "branch": "main", "message": "x",
            "fileChanges": [{"path": "../../etc/passwd", "content": "y", "action": "create"}],
        })
        assert res.status_code in (400, 422)