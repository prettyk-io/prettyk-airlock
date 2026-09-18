# -*- coding: utf-8 -*-
"""COS-120: Workspace file actions — unit + route tests.

Запуск:  pytest .../test_workspace_files.py -q
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
    WorkspaceFileCreateRequest,
    WorkspaceFileDeleteRequest,
    WorkspaceFileMoveRequest,
    WorkspaceFileActionResponse,
)

SHA = "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6a7b8c9d0"


# ── Fake Gitea adapter ─────────────────────────────────────────────────

class FakeFileAdapter:
    def __init__(self):
        self._files: dict[str, str] = {"README.md": "existing content"}
        self.last_calls: list[dict] = []

    def create_file(
        self, owner: str, repo: str, path: str, content: str,
        branch: str, message: str, is_base64: bool = False,
    ) -> dict:
        self.last_calls.append({"method": "create", "path": path, "branch": branch})
        if path in self._files:
            raise RuntimeError(f"file '{path}' already exists")
        self._files[path] = content
        return {"commit_sha": SHA, "path": path, "status": "created"}

    def delete_file(
        self, owner: str, repo: str, path: str,
        branch: str, message: str,
    ) -> dict:
        self.last_calls.append({"method": "delete", "path": path, "branch": branch})
        if path not in self._files:
            raise RuntimeError(f"file '{path}' not found")
        del self._files[path]
        return {"commit_sha": SHA, "path": path, "status": "deleted"}

    def move_file(
        self, owner: str, repo: str, src: str, dst: str,
        branch: str, message: str,
    ) -> dict:
        self.last_calls.append({"method": "move", "src": src, "dst": dst, "branch": branch})
        if src not in self._files:
            raise RuntimeError(f"source '{src}' not found")
        if dst in self._files:
            raise RuntimeError(f"target '{dst}' already exists")
        self._files[dst] = self._files.pop(src)
        return {"commit_sha": SHA, "path": dst, "status": "moved"}

    def add_file(self, path: str, content: str = "dummy"):
        self._files[path] = content


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

class TestFileCreateDto:
    def test_minimal(self):
        r = WorkspaceFileCreateRequest(
            repo="org/app", path="src/main.py", content="hello",
        )
        assert r.base_branch == ""
        assert r.is_base64 is False
        assert r.message == "Create file via Web IDE"

    def test_camel_case(self):
        payload = json.dumps({
            "repo": "org/app", "path": "f.py", "content": "x",
            "baseBranch": "main", "isBase64": True, "message": "msg",
        })
        r = WorkspaceFileCreateRequest.model_validate_json(payload)
        assert r.base_branch == "main"
        assert r.is_base64 is True
        assert r.message == "msg"

    def test_extra_forbidden(self):
        with pytest.raises(ValidationError):
            WorkspaceFileCreateRequest(repo="org/app", path="f.py", content="x", hack=1)

    def test_path_traversal_rejected(self):
        for bad in ["../evil", "/etc/passwd", "foo\\bar"]:
            with pytest.raises(ValidationError):
                WorkspaceFileCreateRequest(repo="org/app", path=bad, content="x")


class TestFileDeleteDto:
    def test_minimal(self):
        r = WorkspaceFileDeleteRequest(repo="org/app", path="f.py")
        assert r.branch == ""
        assert r.last_commit_sha is None
        assert r.message == "Delete file via Web IDE"

    def test_camel_case(self):
        payload = json.dumps({
            "repo": "org/app", "path": "f.py",
            "branch": "dev", "lastCommitSha": SHA, "message": "gone",
        })
        r = WorkspaceFileDeleteRequest.model_validate_json(payload)
        assert r.branch == "dev"
        assert r.last_commit_sha == SHA
        assert r.message == "gone"

    def test_extra_forbidden(self):
        with pytest.raises(ValidationError):
            WorkspaceFileDeleteRequest(repo="org/app", path="f.py", hack=1)


class TestFileMoveDto:
    def test_minimal(self):
        r = WorkspaceFileMoveRequest(
            repo="org/app", source_path="a.py", target_path="b.py",
        )
        assert r.branch == ""
        assert r.message == "Move file via Web IDE"

    def test_camel_case(self):
        payload = json.dumps({
            "repo": "org/app", "sourcePath": "a.py", "targetPath": "b.py",
            "branch": "dev", "message": "rename",
        })
        r = WorkspaceFileMoveRequest.model_validate_json(payload)
        assert r.source_path == "a.py"
        assert r.target_path == "b.py"

    def test_traversal_source(self):
        with pytest.raises(ValidationError):
            WorkspaceFileMoveRequest(repo="org/app", source_path="../etc", target_path="b.py")

    def test_traversal_target(self):
        with pytest.raises(ValidationError):
            WorkspaceFileMoveRequest(repo="org/app", source_path="a.py", target_path="/etc/hosts")


class TestFileActionResponse:
    def test_dump(self):
        r = WorkspaceFileActionResponse(commit_sha=SHA, path="f.py", status="created")
        d = json.loads(r.model_dump_json(by_alias=True))
        assert d["commitSha"] == SHA
        assert d["path"] == "f.py"
        assert d["status"] == "created"

    def test_extra_forbidden(self):
        with pytest.raises(ValidationError):
            WorkspaceFileActionResponse(commit_sha=SHA, path="f.py", status="created", hack=1)


# ── Route tests ─────────────────────────────────────────────────────────

class TestFileRoutes:
    @pytest.fixture(autouse=True)
    def _mock_adapter(self, monkeypatch):
        from orchestrator.cosmo.api import forge_client as fc
        self._adapter = FakeFileAdapter()
        monkeypatch.setattr(fc, "build_adapter", lambda: self._adapter)

    # ── POST /workspace/files ──

    @pytest.mark.asyncio
    async def test_create_file_201(self, pg_client: AsyncClient):
        meta = await _seed_app(pg_client)
        res = await pg_client.post(
            "/api/v1/repos/workspace/files",
            json={
                "repo": meta["repo"], "path": "new.py",
                "content": "print(1)", "baseBranch": "main",
                "message": "add new.py",
            },
            headers={"X-Cosmo-Domain": meta["domain"]},
        )
        assert res.status_code == 201, res.text
        data = res.json()
        assert data["path"] == "new.py"
        assert data["status"] == "created"
        assert data["commitSha"] == SHA

    @pytest.mark.asyncio
    async def test_create_file_conflict_409(self, pg_client: AsyncClient):
        meta = await _seed_app(pg_client)
        # Сначала создаём
        self._adapter.add_file("dup.py")
        # Пытаемся создать с тем же именем
        res = await pg_client.post(
            "/api/v1/repos/workspace/files",
            json={
                "repo": meta["repo"], "path": "dup.py",
                "content": "x", "baseBranch": "main",
            },
            headers={"X-Cosmo-Domain": meta["domain"]},
        )
        assert res.status_code in (409, 502), res.text  # RuntimeError → forge_http_error → 502

    @pytest.mark.asyncio
    async def test_create_file_traversal_400(self, pg_client: AsyncClient):
        meta = await _seed_app(pg_client)
        res = await pg_client.post(
            "/api/v1/repos/workspace/files",
            json={
                "repo": meta["repo"], "path": "../etc/passwd",
                "content": "x",
            },
            headers={"X-Cosmo-Domain": meta["domain"]},
        )
        assert res.status_code == 422, res.text  # Pydantic validation

    @pytest.mark.asyncio
    async def test_create_file_ghost_404(self, pg_client: AsyncClient):
        res = await pg_client.post(
            "/api/v1/repos/workspace/files",
            json={"repo": "ghost/none", "path": "f.py", "content": "x"},
            headers={"X-Cosmo-Domain": "dom-00000000"},
        )
        assert res.status_code == 404

    # ── DELETE /workspace/files ──

    @pytest.mark.asyncio
    async def test_delete_file_200(self, pg_client: AsyncClient):
        meta = await _seed_app(pg_client)
        self._adapter.add_file("old.py")
        res = await pg_client.request(
            "DELETE",
            "/api/v1/repos/workspace/files",
            json={
                "repo": meta["repo"], "path": "old.py",
                "branch": "main", "message": "remove old.py",
            },
            headers={"X-Cosmo-Domain": meta["domain"]},
        )
        assert res.status_code == 200, res.text
        data = res.json()
        assert data["path"] == "old.py"
        assert data["status"] == "deleted"

    @pytest.mark.asyncio
    async def test_delete_file_404_missing(self, pg_client: AsyncClient):
        meta = await _seed_app(pg_client)
        res = await pg_client.request(
            "DELETE",
            "/api/v1/repos/workspace/files",
            json={"repo": meta["repo"], "path": "nonexistent.py"},
            headers={"X-Cosmo-Domain": meta["domain"]},
        )
        assert res.status_code in (404, 502), res.text

    @pytest.mark.asyncio
    async def test_delete_file_ghost_404(self, pg_client: AsyncClient):
        res = await pg_client.request(
            "DELETE",
            "/api/v1/repos/workspace/files",
            json={"repo": "ghost/none", "path": "f.py"},
            headers={"X-Cosmo-Domain": "dom-00000000"},
        )
        assert res.status_code == 404

    # ── POST /workspace/files/move ──

    @pytest.mark.asyncio
    async def test_move_file_200(self, pg_client: AsyncClient):
        meta = await _seed_app(pg_client)
        self._adapter.add_file("old_name.py")
        res = await pg_client.post(
            "/api/v1/repos/workspace/files/move",
            json={
                "repo": meta["repo"], "sourcePath": "old_name.py",
                "targetPath": "new_name.py", "branch": "main",
                "message": "rename",
            },
            headers={"X-Cosmo-Domain": meta["domain"]},
        )
        assert res.status_code == 200, res.text
        data = res.json()
        assert data["path"] == "new_name.py"
        assert data["status"] == "moved"

    @pytest.mark.asyncio
    async def test_move_file_source_404(self, pg_client: AsyncClient):
        meta = await _seed_app(pg_client)
        res = await pg_client.post(
            "/api/v1/repos/workspace/files/move",
            json={
                "repo": meta["repo"], "sourcePath": "no_such.py",
                "targetPath": "dest.py",
            },
            headers={"X-Cosmo-Domain": meta["domain"]},
        )
        assert res.status_code in (404, 502), res.text

    @pytest.mark.asyncio
    async def test_move_file_target_conflict_409(self, pg_client: AsyncClient):
        meta = await _seed_app(pg_client)
        self._adapter.add_file("src.py")
        self._adapter.add_file("dst.py")
        res = await pg_client.post(
            "/api/v1/repos/workspace/files/move",
            json={
                "repo": meta["repo"], "sourcePath": "src.py",
                "targetPath": "dst.py",
            },
            headers={"X-Cosmo-Domain": meta["domain"]},
        )
        assert res.status_code in (409, 502), res.text

    @pytest.mark.asyncio
    async def test_move_file_ghost_404(self, pg_client: AsyncClient):
        res = await pg_client.post(
            "/api/v1/repos/workspace/files/move",
            json={
                "repo": "ghost/none", "sourcePath": "a.py",
                "targetPath": "b.py",
            },
            headers={"X-Cosmo-Domain": "dom-00000000"},
        )
        assert res.status_code == 404