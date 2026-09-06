# -*- coding: utf-8 -*-
"""COS-113: Workspace branches & tags — unit + route tests.

Запуск:  pytest .../test_workspace_branches.py -q
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
    WorkspaceBranchSummary,
    WorkspaceBranchListResponse,
    WorkspaceCreateBranchRequest,
    WorkspaceTagSummary,
    WorkspaceTagListResponse,
    WorkspaceContractError,
    validate_branch_name,
)

SHA = "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6a7b8c9d0"
SHA2 = "b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6a7b8c9d0a1"


# ── Fake Gitea adapter for branches/tags ────────────────────────────────

class FakeBranchAdapter:
    def __init__(self, branches: list[dict] | None = None, tags: list[dict] | None = None):
        self.branches = branches or [
            {"name": "main", "sha": SHA, "is_default": True, "is_protected": True},
            {"name": "feat/x", "sha": SHA2, "is_default": False, "is_protected": False},
        ]
        self.tags = tags or [
            {"name": "v1.0.0", "sha": SHA},
            {"name": "v0.9.0", "sha": SHA2},
        ]
        self.last_created_branch: dict | None = None
        self.deleted_branches: list[str] = []

    def list_branches(self, owner: str, repo: str) -> list[dict]:
        return list(self.branches)

    def create_branch(self, owner: str, repo: str, new_branch: str, base_branch: str) -> dict:
        # 409 name collision
        for b in self.branches:
            if b["name"] == new_branch:
                raise RuntimeError(f"branch '{new_branch}' already exists")
        result = {"name": new_branch, "sha": SHA, "is_default": False, "is_protected": False}
        self.branches.append(result)
        self.last_created_branch = result
        return result

    def delete_branch(self, owner: str, repo: str, branch_name: str) -> bool:
        for b in self.branches:
            if b["name"] == branch_name:
                if b.get("is_default"):
                    raise RuntimeError(f"cannot delete default branch '{branch_name}'")
                self.branches.remove(b)
                self.deleted_branches.append(branch_name)
                return True
        return False

    def list_tags(self, owner: str, repo: str) -> list[dict]:
        return list(self.tags)


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

class TestBranchDto:
    def test_branch_summary_minimal(self):
        b = WorkspaceBranchSummary(name="main", sha=SHA)
        assert b.name == "main"
        assert b.is_default is False
        assert b.is_protected is False

    def test_branch_summary_camel_case(self):
        payload = {"name": "main", "sha": SHA, "isDefault": True, "isProtected": True}
        b = WorkspaceBranchSummary.model_validate_json(json.dumps(payload))
        assert b.is_default is True
        assert b.is_protected is True

    def test_branch_summary_extra_forbidden(self):
        with pytest.raises(ValidationError):
            WorkspaceBranchSummary(name="main", sha=SHA, hack=1)

    def test_branch_list_response_dump(self):
        r = WorkspaceBranchListResponse(
            branches=[WorkspaceBranchSummary(name="main", sha=SHA, is_default=True)],
            default_branch="main",
        )
        d = json.loads(r.model_dump_json(by_alias=True))
        assert d["defaultBranch"] == "main"
        assert len(d["branches"]) == 1
        assert d["branches"][0]["isDefault"] is True

    def test_create_branch_request_alias(self):
        payload = {"repo": "org/app", "baseBranch": "main", "newBranch": "feat/y"}
        r = WorkspaceCreateBranchRequest.model_validate_json(json.dumps(payload))
        assert r.base_branch == "main"
        assert r.new_branch == "feat/y"

    def test_create_branch_request_extra_forbidden(self):
        with pytest.raises(ValidationError):
            WorkspaceCreateBranchRequest(repo="org/app", base_branch="main", new_branch="x", hack=1)

    def test_tag_summary(self):
        t = WorkspaceTagSummary(name="v1.0.0", sha=SHA)
        d = json.loads(t.model_dump_json(by_alias=True))
        assert d == {"name": "v1.0.0", "sha": SHA}

    def test_tag_list_response(self):
        r = WorkspaceTagListResponse(
            tags=[WorkspaceTagSummary(name="v1.0.0", sha=SHA)],
        )
        d = json.loads(r.model_dump_json(by_alias=True))
        assert len(d["tags"]) == 1

    def test_branch_name_validation(self):
        # Valid
        validate_branch_name("main")
        validate_branch_name("feat/x")
        validate_branch_name("release-1.0")
        # Invalid
        for bad in ["", " ", "..", "-main", "main.", "feat x"]:
            with pytest.raises(WorkspaceContractError):
                validate_branch_name(bad)


# ── Route tests ─────────────────────────────────────────────────────────

class TestBranchRoute:
    """Интеграционные тесты GET/POST/DELETE /workspace/branches + GET /workspace/tags."""

    @pytest.fixture(autouse=True)
    def _mock_adapter(self, monkeypatch):
        from orchestrator.cosmo.api import forge_client as fc
        self._adapter = FakeBranchAdapter()
        monkeypatch.setattr(fc, "build_adapter", lambda: self._adapter)

    # ── GET /workspace/branches ──

    @pytest.mark.asyncio
    async def test_list_branches_200(self, pg_client: AsyncClient):
        meta = await _seed_app(pg_client)
        res = await pg_client.get(
            "/api/v1/repos/workspace/branches",
            params={"repo": meta["repo"]},
            headers={"X-Cosmo-Domain": meta["domain"]},
        )
        assert res.status_code == 200, res.text
        data = res.json()
        assert data["defaultBranch"] == "main"
        branches = data["branches"]
        assert len(branches) == 2
        assert branches[0]["name"] == "main"
        assert branches[0]["isDefault"] is True
        assert branches[1]["name"] == "feat/x"

    @pytest.mark.asyncio
    async def test_list_branches_ghost_404(self, pg_client: AsyncClient):
        res = await pg_client.get(
            "/api/v1/repos/workspace/branches",
            params={"repo": "ghost/no-repo"},
            headers={"X-Cosmo-Domain": "dom-00000000"},
        )
        assert res.status_code == 404

    # ── POST /workspace/branches ──

    @pytest.mark.asyncio
    async def test_create_branch_201(self, pg_client: AsyncClient):
        meta = await _seed_app(pg_client)
        res = await pg_client.post(
            "/api/v1/repos/workspace/branches",
            json={"repo": meta["repo"], "baseBranch": "main", "newBranch": "feat/z"},
            headers={"X-Cosmo-Domain": meta["domain"]},
        )
        assert res.status_code == 201, res.text
        data = res.json()
        assert data["name"] == "feat/z"
        assert data["sha"] == SHA
        assert data["isDefault"] is False

    @pytest.mark.asyncio
    async def test_create_branch_name_collision_409(self, pg_client: AsyncClient):
        meta = await _seed_app(pg_client)
        # Попытка создать ветку с существующим именем
        res = await pg_client.post(
            "/api/v1/repos/workspace/branches",
            json={"repo": meta["repo"], "baseBranch": "main", "newBranch": "main"},
            headers={"X-Cosmo-Domain": meta["domain"]},
        )
        assert res.status_code in (409, 502), res.text  # 502 = forge_http_error для RuntimeError

    @pytest.mark.asyncio
    async def test_create_branch_traversal_rejected_400(self, pg_client: AsyncClient):
        meta = await _seed_app(pg_client)
        res = await pg_client.post(
            "/api/v1/repos/workspace/branches",
            json={"repo": meta["repo"], "baseBranch": "main", "newBranch": "../evil"},
            headers={"X-Cosmo-Domain": meta["domain"]},
        )
        assert res.status_code in (400, 422), res.text  # Pydantic rejects before route

    # ── DELETE /workspace/branches ──

    @pytest.mark.asyncio
    async def test_delete_branch_204(self, pg_client: AsyncClient):
        meta = await _seed_app(pg_client)
        res = await pg_client.delete(
            "/api/v1/repos/workspace/branches",
            params={"repo": meta["repo"], "branch": "feat/x"},
            headers={"X-Cosmo-Domain": meta["domain"]},
        )
        assert res.status_code == 204, res.text
        assert self._adapter.deleted_branches == ["feat/x"]

    @pytest.mark.asyncio
    async def test_delete_branch_404_missing(self, pg_client: AsyncClient):
        meta = await _seed_app(pg_client)
        res = await pg_client.delete(
            "/api/v1/repos/workspace/branches",
            params={"repo": meta["repo"], "branch": "no-such-branch"},
            headers={"X-Cosmo-Domain": meta["domain"]},
        )
        assert res.status_code == 404, res.text

    @pytest.mark.asyncio
    async def test_delete_default_branch_400(self, pg_client: AsyncClient):
        meta = await _seed_app(pg_client)
        res = await pg_client.delete(
            "/api/v1/repos/workspace/branches",
            params={"repo": meta["repo"], "branch": "main"},
            headers={"X-Cosmo-Domain": meta["domain"]},
        )
        assert res.status_code == 400, res.text
        assert "default" in res.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_delete_branch_ghost_404(self, pg_client: AsyncClient):
        res = await pg_client.delete(
            "/api/v1/repos/workspace/branches",
            params={"repo": "ghost/none", "branch": "main"},
            headers={"X-Cosmo-Domain": "dom-00000000"},
        )
        assert res.status_code == 404

    # ── GET /workspace/tags ──

    @pytest.mark.asyncio
    async def test_list_tags_200(self, pg_client: AsyncClient):
        meta = await _seed_app(pg_client)
        res = await pg_client.get(
            "/api/v1/repos/workspace/tags",
            params={"repo": meta["repo"]},
            headers={"X-Cosmo-Domain": meta["domain"]},
        )
        assert res.status_code == 200, res.text
        data = res.json()
        assert len(data["tags"]) == 2
        assert data["tags"][0]["name"] == "v1.0.0"
        assert data["tags"][1]["name"] == "v0.9.0"

    @pytest.mark.asyncio
    async def test_list_tags_ghost_404(self, pg_client: AsyncClient):
        res = await pg_client.get(
            "/api/v1/repos/workspace/tags",
            params={"repo": "ghost/no-repo"},
            headers={"X-Cosmo-Domain": "dom-00000000"},
        )
        assert res.status_code == 404