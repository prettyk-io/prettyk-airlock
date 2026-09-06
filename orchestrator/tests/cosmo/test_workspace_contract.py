# -*- coding: utf-8 -*-
"""COS-104: Contract tests - workspace API (bootstrap / tree / file).

E2E cycle: bootstrap -> tree -> blob with CAS head_sha.
Negatives: 401/403/404/400, empty repo.
"""
from __future__ import annotations

import hashlib
from unittest.mock import patch

import pytest
import pytest_asyncio
from fastapi import status as http_status

# ---- fixtures ----

@pytest_asyncio.fixture
async def app_with_binding(pg_client, loop_safe_engine_reset):
    """Create domain + app with repo binding via ORM."""
    import uuid
    from orchestrator.cosmo.db.session import get_sessionmaker
    from orchestrator.cosmo.db.models import (
        Domain as DomainModel,
        Application as ApplicationModel,
        RepositoryBinding as RepoBindingModel,
    )

    sm = get_sessionmaker()
    async with sm() as db:
        db.add(DomainModel(
            id="dom-ws-test", label="WS Test Domain",
            forge_type="gitea", forge_url="http://gitea:3000",
            forge_token_ref="VAULT/dev-token",
        ))
        await db.flush()
        db.add(ApplicationModel(id="app-ws-test", domain_id="dom-ws-test", level=1))
        await db.flush()
        db.add(RepoBindingModel(
            id=f"rb-{uuid.uuid4().hex[:12]}",
            app_id="app-ws-test", forge_id="gitea",
            repo_path="testorg/ws-repo", default_branch="main",
        ))
        await db.commit()
    return pg_client

@pytest_asyncio.fixture
async def anon_client(pg_client, loop_safe_engine_reset):
    from orchestrator.cosmo.api.deps import get_current_principal
    from orchestrator.cosmo.api.main import app
    saved = app.dependency_overrides.get(get_current_principal)
    app.dependency_overrides.pop(get_current_principal, None)
    try:
        yield pg_client
    finally:
        if saved is not None:
            app.dependency_overrides[get_current_principal] = saved

# ---- mock forge adapters ----

def _te(path, typ, sha, size):
    from orchestrator.cosmo.adapters.forge_gitea import GiteaTreeEntry
    return GiteaTreeEntry(path=path, type=typ, sha=sha, size=size)

def _info(owner, name, branch):
    from orchestrator.cosmo.adapters.forge_gitea import GiteaRepoInfo
    return GiteaRepoInfo(
        id=1, owner=owner, name=name, full_name=f"{owner}/{name}",
        default_branch=branch, clone_url=f"http://gitea:3000/{owner}/{name}.git",
        ssh_url="",
    )

def _head(sha, msg="feat: contract test fixture"):
    from orchestrator.cosmo.adapters.forge_gitea import GiteaCommit
    return GiteaCommit(sha=sha, message=msg, author="dev", timestamp="2026-09-05T12:00:00Z")

HEAD_SHA = "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0"

def _mc(key: str) -> str:
    """Helper: mock content without escape corruption in source."""
    return {
        "test-repo-readme": "# Test Repo\nWorkspace contract test fixture.\n",
        "src-main": "def main():\n    print('contract test')\n",
        "src-utils": "def add(a, b):\n    return a + b\n",
        "cosmo-pipeline": "version: '2.0'\npipeline:\n  name: Test\n",
    }[key]

MOCK_BLOBS = {
    "README.md": _mc("test-repo-readme"),
    "src/main.py": _mc("src-main"),
    "src/utils.py": _mc("src-utils"),
    ".cosmo/pipeline.yaml": _mc("cosmo-pipeline"),
}

class MockForgeAdapter:
    def __init__(self):
        self._sha = HEAD_SHA
        self._tree = [
            _te("README.md", "blob", self._sha, 42),
            _te("src", "tree", self._sha, 0),
            _te("src/main.py", "blob", self._sha, 128),
            _te("src/utils.py", "blob", self._sha, 256),
            _te(".cosmo", "tree", self._sha, 0),
            _te(".cosmo/pipeline.yaml", "blob", self._sha, 99),
        ]
        self._info = _info("testorg", "ws-repo", "main")
        self._head = _head(self._sha)

    def get_repo_info(self, owner, name):
        return self._info

    def get_commit(self, owner, name, branch):
        return self._head

    def get_tree(self, owner, name, ref="", recursive=True):
        return self._tree

    def read_file(self, owner, name, path, ref=""):
        content = MOCK_BLOBS.get(path)
        if content is None:
            raise LookupError(f"File not found: {path}")
        sha = hashlib.sha256(content.encode()).hexdigest()
        return content, sha

class EmptyForgeAdapter:
    def get_repo_info(self, owner, name):
        return _info("testorg", "ws-repo", "main")

    def get_commit(self, owner, name, branch):
        return _head("e" * 40, msg="init: empty repo")

    def get_tree(self, owner, name, ref="", recursive=True):
        return []

    def read_file(self, owner, name, path, ref=""):
        raise LookupError(f"File not found: {path}")

QUERY = "?repo=testorg/ws-repo&branch=main"
HEAD_Q = f"{QUERY}&head_sha={HEAD_SHA}"
PATCH = "orchestrator.cosmo.api.forge_client.build_adapter"

# ---- tests ----

@pytest.mark.asyncio
class TestWorkspaceBootstrap:

    async def test_bootstrap_ok(self, pg_client, app_with_binding):
        mock = MockForgeAdapter()
        with patch(PATCH, return_value=mock):
            res = await pg_client.get(f"/api/v1/repos/workspace/bootstrap{QUERY}")
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["repo"] == "testorg/ws-repo"
        assert body["branch"] == "main"
        assert body["headSha"] == HEAD_SHA
        assert "read" in body["capabilities"]
        assert body["authorization"] == "allow"

    async def test_bootstrap_401(self, anon_client, app_with_binding):
        res = await anon_client.get(f"/api/v1/repos/workspace/bootstrap{QUERY}")
        assert res.status_code == 401, res.text

    async def test_bootstrap_404(self, pg_client, app_with_binding):
        mock = MockForgeAdapter()
        with patch(PATCH, return_value=mock):
            res = await pg_client.get("/api/v1/repos/workspace/bootstrap?repo=ghost/nope")
        assert res.status_code == 404, res.text

    async def test_bootstrap_400(self, pg_client, app_with_binding):
        mock = MockForgeAdapter()
        with patch(PATCH, return_value=mock):
            res = await pg_client.get("/api/v1/repos/workspace/bootstrap?repo=badrepo")
        assert res.status_code == 400, res.text

@pytest.mark.asyncio
class TestWorkspaceTree:

    async def test_tree_ok(self, pg_client, app_with_binding):
        mock = MockForgeAdapter()
        with patch(PATCH, return_value=mock):
            res = await pg_client.get(f"/api/v1/repos/tree{HEAD_Q}")
        assert res.status_code == 200, res.text
        entries = sorted(res.json()["entries"], key=lambda e: e["path"])
        paths = [e["path"] for e in entries]
        assert "README.md" in paths
        assert "src" in paths
        assert len(entries) == 6

    async def test_tree_empty(self, pg_client, app_with_binding):
        mock = EmptyForgeAdapter()
        empty_sha = "e" * 40
        with patch(PATCH, return_value=mock):
            res = await pg_client.get(f"/api/v1/repos/tree{QUERY}&head_sha={empty_sha}")
        assert res.status_code == 200, res.text
        assert res.json()["entries"] == []

    async def test_tree_409(self, pg_client, app_with_binding):
        mock = MockForgeAdapter()
        wrong_sha = "b" * 40
        with patch(PATCH, return_value=mock):
            res = await pg_client.get(f"/api/v1/repos/tree{QUERY}&head_sha={wrong_sha}")
        assert res.status_code == 409, res.text

    async def test_tree_401(self, anon_client, app_with_binding):
        mock = MockForgeAdapter()
        with patch(PATCH, return_value=mock):
            res = await anon_client.get(f"/api/v1/repos/tree{HEAD_Q}")
        assert res.status_code == 401, res.text

    async def test_tree_404(self, pg_client, app_with_binding):
        mock = MockForgeAdapter()
        with patch(PATCH, return_value=mock):
            res = await pg_client.get(f"/api/v1/repos/tree?repo=ghost/nope&branch=x&head_sha={HEAD_SHA}")
        assert res.status_code == 404, res.text

@pytest.mark.asyncio
class TestWorkspaceBlob:

    BLOB_Q = f"/api/v1/repos/file{HEAD_Q}&path=README.md"

    async def test_blob_ok(self, pg_client, app_with_binding):
        mock = MockForgeAdapter()
        with patch(PATCH, return_value=mock):
            res = await pg_client.get(self.BLOB_Q)
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["path"] == "README.md"
        assert "contract test fixture" in body["content"]
        assert body["encoding"] == "utf-8"
        assert len(body["baseBlobSha"]) >= 7

    async def test_blob_400_traversal(self, pg_client, app_with_binding):
        mock = MockForgeAdapter()
        with patch(PATCH, return_value=mock):
            res = await pg_client.get(f"/api/v1/repos/file{HEAD_Q}&path=../etc/passwd")
        assert res.status_code == 400, res.text

    async def test_blob_404(self, pg_client, app_with_binding):
        mock = MockForgeAdapter()
        with patch(PATCH, return_value=mock):
            res = await pg_client.get(f"/api/v1/repos/file{HEAD_Q}&path=missing.txt")
        assert res.status_code == 404, res.text

    async def test_blob_401(self, anon_client, app_with_binding):
        mock = MockForgeAdapter()
        with patch(PATCH, return_value=mock):
            res = await anon_client.get(self.BLOB_Q)
        assert res.status_code == 401, res.text

@pytest.mark.asyncio
class TestWorkspaceEndToEnd:

    async def test_e2e_cycle(self, pg_client, app_with_binding):
        mock = MockForgeAdapter()
        with patch(PATCH, return_value=mock):
            boot_res = await pg_client.get(f"/api/v1/repos/workspace/bootstrap{QUERY}")
            assert boot_res.status_code == 200
            sha = boot_res.json()["headSha"]
            tree_res = await pg_client.get(f"/api/v1/repos/tree{QUERY}&head_sha={sha}")
            assert tree_res.status_code == 200
            assert len(tree_res.json()["entries"]) == 6
            blob_res = await pg_client.get(f"/api/v1/repos/file{QUERY}&head_sha={sha}&path=src/main.py")
            assert blob_res.status_code == 200
            body = blob_res.json()
            assert body["path"] == "src/main.py"
            assert "def main()" in body["content"]
            assert len(body["baseBlobSha"]) >= 7

    async def test_e2e_409_after_head_move(self, pg_client, app_with_binding):
        mock = MockForgeAdapter()
        with patch(PATCH, return_value=mock):
            boot_res = await pg_client.get(f"/api/v1/repos/workspace/bootstrap{QUERY}")
            assert boot_res.status_code == 200
            sha = boot_res.json()["headSha"]
            tree_res = await pg_client.get(f"/api/v1/repos/tree{QUERY}&head_sha={sha}")
            assert tree_res.status_code == 200
            old_sha = mock._head.sha
            mock._head = _head("f" * 40, msg="feat: new head")
            tree_res2 = await pg_client.get(f"/api/v1/repos/tree{QUERY}&head_sha={old_sha}")
            assert tree_res2.status_code == 409, tree_res2.text