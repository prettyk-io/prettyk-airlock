# -*- coding: utf-8 -*-
"""COS-125: Workspace Compare (tree snapshot diff) — DTO + helpers + route.

Запуск:  pytest .../test_workspace_compare.py -q
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import AsyncClient
from pydantic import ValidationError

_orch = Path(__file__).resolve().parents[1]
if str(_orch) not in sys.path:
    sys.path.insert(0, str(_orch))

pytestmark = pytest.mark.asyncio

from orchestrator.cosmo.adapters.forge_gitea import (
    GiteaCompareLimitError,
    GiteaCompareResult,
    GiteaForgeAdapter,
    GiteaTreeEntry,
    _MAX_COMPARE_BLOB_BYTES,
    _classify_snapshots,
    _decode_text,
    _is_binary_bytes,
    _unified_patch,
)
from orchestrator.cosmo.api.deps import get_current_principal
from orchestrator.cosmo.api.main import app
from orchestrator.cosmo.domain.rbac import CBRRole, PrincipalContext
from orchestrator.cosmo.domain.workspace import (
    WorkspaceCompareFile,
    WorkspaceCompareResponse,
)

SHA_BASE = "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6a7b8c9d0"
SHA_HEAD = "b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6a7b8c9d0a1"
SHA_BLOB_1 = "c3d4e5f6a7b8c9d0e1f2a3b4c5d6a7b8c9d0a1b2"
SHA_BLOB_2 = "d4e5f6a7b8c9d0e1f2a3b4c5d6a7b8c9d0a1b2c3"


def _entry(path: str, sha: str, size: int | None = None, kind: str = "blob") -> GiteaTreeEntry:
    return GiteaTreeEntry(path=path, type=kind, sha=sha, size=size)


# ══════════════════════════════════════════════════════════════════
# DTO unit tests
# ══════════════════════════════════════════════════════════════════

class TestCompareFileDto:
    def test_minimal_added(self):
        f = WorkspaceCompareFile(path="src/a.py", status="added")
        assert f.path == "src/a.py"
        assert f.status == "added"
        assert f.old_path is None
        assert f.additions == 0 and f.deletions == 0
        assert f.patch is None
        assert f.is_binary is False
        assert f.truncated is False

    def test_camel_case_aliases(self):
        f = WorkspaceCompareFile(
            path="a.py", old_path="old.py", status="renamed",
            is_binary=True, truncated=True,
        )
        d = f.model_dump(by_alias=True)
        assert d["oldPath"] == "old.py"
        assert d["isBinary"] is True
        assert d["truncated"] is True

    def test_validate_camel_json(self):
        payload = {
            "path": "a.py", "oldPath": "b.py", "status": "renamed",
            "additions": 2, "deletions": 1, "patch": "@@", "isBinary": False,
        }
        f = WorkspaceCompareFile.model_validate_json(json.dumps(payload))
        assert f.old_path == "b.py"
        assert f.additions == 2

    def test_invalid_status(self):
        with pytest.raises(ValidationError):
            WorkspaceCompareFile(path="a.py", status="exploded")

    def test_extra_forbid(self):
        with pytest.raises(ValidationError):
            WorkspaceCompareFile(path="a.py", status="added", hack=1)

    def test_path_traversal_rejected(self):
        with pytest.raises(ValidationError):
            WorkspaceCompareFile(path="../../etc/passwd", status="added")


class TestCompareResponseDto:
    def test_dump_camel_case(self):
        r = WorkspaceCompareResponse(
            base=SHA_BASE, head=SHA_HEAD,
            files=[WorkspaceCompareFile(path="a.py", status="modified",
                                        additions=1, deletions=1, patch="p")],
            total_additions=1, total_deletions=1, files_changed=1,
        )
        d = json.loads(r.model_dump_json(by_alias=True))
        assert d["base"] == SHA_BASE and d["head"] == SHA_HEAD
        assert d["totalAdditions"] == 1
        assert d["totalDeletions"] == 1
        assert d["filesChanged"] == 1
        assert d["files"][0]["isBinary"] is False

    def test_empty_files(self):
        r = WorkspaceCompareResponse(
            base=SHA_BASE, head=SHA_HEAD, files=[],
            total_additions=0, total_deletions=0, files_changed=0,
        )
        assert r.files == []
        assert r.files_changed == 0

    def test_extra_forbid(self):
        with pytest.raises(ValidationError):
            WorkspaceCompareResponse(
                base=SHA_BASE, head=SHA_HEAD, files=[],
                total_additions=0, total_deletions=0, files_changed=0, hack=1,
            )


# ══════════════════════════════════════════════════════════════════
# Pure helper tests
# ══════════════════════════════════════════════════════════════════

class TestBinaryHelpers:
    def test_text_not_binary(self):
        assert _is_binary_bytes(b"hello\nworld\n") is False

    def test_nul_is_binary(self):
        assert _is_binary_bytes(b"PNG\x00\x01\x02") is True

    def test_decode_utf8(self):
        assert _decode_text("привет".encode("utf-8")) == "привет"

    def test_decode_binary_none(self):
        assert _decode_text(b"\x00\x01\x02") is None

    def test_decode_invalid_utf8_none(self):
        assert _decode_text(b"\xff\xfe\xfd") is None


class TestClassifySnapshots:
    def test_added(self):
        base = {}
        head = {"new.py": _entry("new.py", SHA_BLOB_1)}
        changes = _classify_snapshots(base, head)
        assert len(changes) == 1
        assert changes[0].status == "added"
        assert changes[0].path == "new.py"
        assert changes[0].head_sha == SHA_BLOB_1

    def test_deleted(self):
        base = {"gone.py": _entry("gone.py", SHA_BLOB_1)}
        changes = _classify_snapshots(base, {})
        assert len(changes) == 1
        assert changes[0].status == "deleted"
        assert changes[0].base_sha == SHA_BLOB_1

    def test_modified(self):
        base = {"a.py": _entry("a.py", SHA_BLOB_1)}
        head = {"a.py": _entry("a.py", SHA_BLOB_2)}
        changes = _classify_snapshots(base, head)
        assert changes[0].status == "modified"
        assert changes[0].base_sha == SHA_BLOB_1
        assert changes[0].head_sha == SHA_BLOB_2

    def test_unchanged_excluded(self):
        base = {"a.py": _entry("a.py", SHA_BLOB_1)}
        head = {"a.py": _entry("a.py", SHA_BLOB_1)}
        assert _classify_snapshots(base, head) == []

    def test_rename_by_equal_sha(self):
        base = {"old.py": _entry("old.py", SHA_BLOB_1)}
        head = {"new.py": _entry("new.py", SHA_BLOB_1)}
        changes = _classify_snapshots(base, head)
        assert len(changes) == 1
        assert changes[0].status == "renamed"
        assert changes[0].path == "new.py"
        assert changes[0].old_path == "old.py"

    def test_delete_plus_add_different_sha(self):
        base = {"old.py": _entry("old.py", SHA_BLOB_1)}
        head = {"new.py": _entry("new.py", SHA_BLOB_2)}
        statuses = {c.status for c in _classify_snapshots(base, head)}
        assert statuses == {"deleted", "added"}

    def test_sorted_by_path(self):
        base = {"b.py": _entry("b.py", SHA_BLOB_1)}
        head = {"a.py": _entry("a.py", SHA_BLOB_2),
                "c.py": _entry("c.py", SHA_BLOB_1)}
        paths = [c.path for c in _classify_snapshots(base, head)]
        assert paths == sorted(paths)


class TestUnifiedPatch:
    def test_modified_counts(self):
        patch, adds, dels = _unified_patch("a\nb\n", "a\nc\n", "f.txt")
        assert adds == 1 and dels == 1
        assert "--- a/f.txt" in patch
        assert "+++ b/f.txt" in patch
        assert "+c" in patch and "-b" in patch

    def test_added_file(self):
        patch, adds, dels = _unified_patch("", "x\ny\n", "new.txt")
        assert adds == 2 and dels == 0
        assert "+++ b/new.txt" in patch

    def test_rename_labels_old_path(self):
        patch, adds, dels = _unified_patch("a\n", "b\n", "new.py", old_path="old.py")
        assert "--- a/old.py" in patch
        assert "+++ b/new.py" in patch
        assert adds == 1 and dels == 1

    def test_no_diff_none(self):
        patch, adds, dels = _unified_patch("", "", "empty.txt")
        assert patch is None
        assert adds == 0 and dels == 0


# ══════════════════════════════════════════════════════════════════
# Adapter compare_refs tests (real adapter, HTTP boundary mocked)
# ══════════════════════════════════════════════════════════════════

def _adapter(monkeypatch, base_map, head_map, blobs=None, refs=None):
    refs = refs or {"main": SHA_BASE, "feature": SHA_HEAD}
    ad = GiteaForgeAdapter(base_url="http://forge.local")
    monkeypatch.setattr(ad, "resolve_ref",
                        lambda owner, repo, ref: refs[ref])
    trees = {
        SHA_BASE: list(base_map.values()),
        SHA_HEAD: list(head_map.values()),
    }
    monkeypatch.setattr(ad, "get_tree_by_sha",
                        lambda owner, repo, sha, recursive=True: trees[sha])
    blobs = blobs or {}
    monkeypatch.setattr(ad, "get_blob",
                        lambda owner, repo, sha: blobs[sha])
    return ad


class TestCompareRefs:
    def test_added_text(self, monkeypatch):
        head = {"new.py": _entry("new.py", SHA_BLOB_1)}
        ad = _adapter(monkeypatch, {}, head, blobs={SHA_BLOB_1: b"line1\nline2\n"})
        res = ad.compare_refs("o", "r", "main", "feature")
        assert res.base_sha == SHA_BASE and res.head_sha == SHA_HEAD
        assert len(res.files) == 1
        f = res.files[0]
        assert f.status == "added"
        assert f.additions == 2 and f.deletions == 0
        assert "+line1" in f.patch
        assert f.is_binary is False

    def test_modified_text(self, monkeypatch):
        base = {"a.py": _entry("a.py", SHA_BLOB_1)}
        head = {"a.py": _entry("a.py", SHA_BLOB_2)}
        ad = _adapter(monkeypatch, base, head,
                      blobs={SHA_BLOB_1: b"a\nb\n", SHA_BLOB_2: b"a\nc\n"})
        f = ad.compare_refs("o", "r", "main", "feature").files[0]
        assert f.status == "modified"
        assert f.additions == 1 and f.deletions == 1
        assert f.old_path is None

    def test_deleted_text(self, monkeypatch):
        base = {"gone.py": _entry("gone.py", SHA_BLOB_1)}
        ad = _adapter(monkeypatch, base, {}, blobs={SHA_BLOB_1: b"bye\n"})
        f = ad.compare_refs("o", "r", "main", "feature").files[0]
        assert f.status == "deleted"
        assert f.deletions == 1 and f.additions == 0

    def test_renamed_no_blob_read(self, monkeypatch):
        base = {"old.py": _entry("old.py", SHA_BLOB_1)}
        head = {"new.py": _entry("new.py", SHA_BLOB_1)}

        def _boom(owner, repo, sha):
            raise AssertionError("blob must not be read for rename")

        ad = _adapter(monkeypatch, base, head)
        monkeypatch.setattr(ad, "get_blob", _boom)
        f = ad.compare_refs("o", "r", "main", "feature").files[0]
        assert f.status == "renamed"
        assert f.old_path == "old.py"
        assert f.patch is None

    def test_binary_file(self, monkeypatch):
        head = {"img.png": _entry("img.png", SHA_BLOB_1)}
        ad = _adapter(monkeypatch, {}, head, blobs={SHA_BLOB_1: b"\x89PNG\x00\x01"})
        f = ad.compare_refs("o", "r", "main", "feature").files[0]
        assert f.is_binary is True
        assert f.patch is None
        assert f.additions == 0 and f.deletions == 0

    def test_truncated_by_tree_size(self, monkeypatch):
        head = {"big.txt": _entry("big.txt", SHA_BLOB_1,
                                  size=_MAX_COMPARE_BLOB_BYTES + 1)}

        def _boom(owner, repo, sha):
            raise AssertionError("oversized blob must not be fetched")

        ad = _adapter(monkeypatch, {}, head)
        monkeypatch.setattr(ad, "get_blob", _boom)
        f = ad.compare_refs("o", "r", "main", "feature").files[0]
        assert f.truncated is True
        assert f.patch is None

    def test_limit_exceeded(self, monkeypatch):
        head = {f"f{i}.py": _entry(f"f{i}.py", SHA_BLOB_1) for i in range(501)}
        ad = _adapter(monkeypatch, {}, head)
        with pytest.raises(GiteaCompareLimitError):
            ad.compare_refs("o", "r", "main", "feature")

    def test_empty_compare(self, monkeypatch):
        ad = _adapter(monkeypatch, {}, {})
        res = ad.compare_refs("o", "r", "main", "feature")
        assert res.files == []

    def test_blob_fetch_failure_marks_no_patch(self, monkeypatch):
        head = {"x.py": _entry("x.py", SHA_BLOB_1)}
        ad = _adapter(monkeypatch, {}, head)

        def _gone(owner, repo, sha):
            raise LookupError("gone")

        def _read_gone(owner, repo, path, ref=""):
            raise LookupError("gone")

        monkeypatch.setattr(ad, "get_blob", _gone)
        monkeypatch.setattr(ad, "read_file", _read_gone)
        f = ad.compare_refs("o", "r", "main", "feature").files[0]
        assert f.patch is None
        assert f.is_binary is False
        assert f.truncated is False

    def test_blob_fallback_to_read_file(self, monkeypatch):
        head = {"x.py": _entry("x.py", SHA_BLOB_1)}
        ad = _adapter(monkeypatch, {}, head)

        def _gone(owner, repo, sha):
            raise LookupError("gone")

        monkeypatch.setattr(ad, "get_blob", _gone)
        monkeypatch.setattr(ad, "read_file",
                            lambda owner, repo, path, ref="": ("hi\n", "s"))
        f = ad.compare_refs("o", "r", "main", "feature").files[0]
        assert f.status == "added"
        assert "+hi" in f.patch
        assert f.additions == 1


class TestResolveRef:
    def test_uses_branch_kwarg(self, monkeypatch):
        ad = GiteaForgeAdapter(base_url="http://forge.local")
        seen: dict = {}

        def _list(owner, repo, branch=None, path=None, limit=30, page=1):
            seen.update(branch=branch, limit=limit)
            return [{"sha": SHA_BASE}]

        monkeypatch.setattr(ad, "list_commits_history", _list)
        assert ad.resolve_ref("o", "r", "main") == SHA_BASE
        assert seen == {"branch": "main", "limit": 1}

    def test_unknown_ref_lookup_error(self, monkeypatch):
        ad = GiteaForgeAdapter(base_url="http://forge.local")
        monkeypatch.setattr(ad, "list_commits_history",
                            lambda *a, **k: [])
        with pytest.raises(LookupError):
            ad.resolve_ref("o", "r", "ghost-branch")

    def test_empty_ref_value_error(self):
        ad = GiteaForgeAdapter(base_url="http://forge.local")
        with pytest.raises(ValueError):
            ad.resolve_ref("o", "r", "")


# ══════════════════════════════════════════════════════════════════
# Route tests (httpx через реальный PG + mock forge adapter)
# ══════════════════════════════════════════════════════════════════

_CMP_BASE = "/api/v1/repos/workspace/compare"
_REPO = "cmp-owner/cmp-repo"


class FakeCompareAdapter:
    """Фейковый адаптер: отдаёт заранее заданный GiteaCompareResult."""

    def __init__(self):
        self.result = GiteaCompareResult(
            base_sha=SHA_BASE, head_sha=SHA_HEAD,
            files=[GiteaCompareFileStub()],
        )
        self.error: Exception | None = None
        self.last: tuple | None = None

    def compare_refs(self, owner, repo, base, head):
        self.last = (owner, repo, base, head)
        if self.error:
            raise self.error
        return self.result


class GiteaCompareFileStub:
    path = "src/app.py"
    status = "modified"
    old_path = None
    additions = 3
    deletions = 1
    patch = "--- a/src/app.py\n+++ b/src/app.py\n@@ -1 +1 @@\n-old\n+new\n"
    is_binary = False
    truncated = False


class TestCompareRoute:
    @pytest.fixture(autouse=True)
    def _mocks(self, monkeypatch):
        self._forge = FakeCompareAdapter()
        import orchestrator.cosmo.api.routes.workspace as _ws
        monkeypatch.setattr(_ws, "build_adapter", lambda: self._forge)

        async def _principal() -> PrincipalContext:
            return PrincipalContext(
                user_id="cmp-tester",
                roles=[CBRRole.SERVICE_ADMIN],
                domain_id="cmp-dom", zone="zr",
                is_authenticated=True, is_system_admin=False,
            )
        app.dependency_overrides[get_current_principal] = _principal

    @pytest_asyncio.fixture(autouse=True)
    async def _seed_db(self, pg_client: AsyncClient):
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
                "VALUES ('cmp-dom', 'cmp-test', 'gitea', "
                "'http://gitea:3000', 't', '{}'::jsonb, 50, 100, 8, now()) "
                "ON CONFLICT (id) DO NOTHING"
            ))
            await conn.execute(text(
                "INSERT INTO apps (id, domain_id, level) "
                "VALUES ('cmp-app', 'cmp-dom', 0) "
                "ON CONFLICT (id) DO NOTHING"
            ))
            await conn.execute(text(
                "INSERT INTO repo_bindings (id, app_id, forge_id, repo_path, "
                "default_branch) "
                "VALUES ('cmp-bind', 'cmp-app', 'gitea-1', "
                "'cmp-owner/cmp-repo', 'main') "
                "ON CONFLICT (id) DO NOTHING"
            ))
        await engine.dispose()

    async def _get(self, pg_client: AsyncClient, **params):
        return await pg_client.get(_CMP_BASE, params=params)

    # ── Happy path ──

    async def test_compare_200(self, pg_client: AsyncClient):
        res = await self._get(pg_client, repo=_REPO, base="main", head="feature")
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["base"] == SHA_BASE
        assert body["head"] == SHA_HEAD
        assert body["filesChanged"] == 1
        assert body["totalAdditions"] == 3
        assert body["totalDeletions"] == 1
        f = body["files"][0]
        assert f["path"] == "src/app.py"
        assert f["status"] == "modified"
        assert f["isBinary"] is False
        assert f["oldPath"] is None
        assert self._forge.last == ("cmp-owner", "cmp-repo", "main", "feature")

    async def test_compare_empty_files(self, pg_client: AsyncClient):
        self._forge.result = GiteaCompareResult(
            base_sha=SHA_BASE, head_sha=SHA_HEAD, files=[])
        res = await self._get(pg_client, repo=_REPO, base="main", head="feature")
        assert res.status_code == 200
        body = res.json()
        assert body["files"] == []
        assert body["filesChanged"] == 0
        assert body["totalAdditions"] == 0

    # ── Validation / conflict ──

    async def test_base_equals_head_400(self, pg_client: AsyncClient):
        res = await self._get(pg_client, repo=_REPO, base="main", head="main")
        assert res.status_code == 400, res.text

    async def test_missing_ref_422(self, pg_client: AsyncClient):
        res = await self._get(pg_client, repo=_REPO, base="main")
        assert res.status_code == 422

    async def test_bad_ref_400(self, pg_client: AsyncClient):
        res = await self._get(pg_client, repo=_REPO, base="../bad", head="feature")
        assert res.status_code == 400

    async def test_bad_repo_400(self, pg_client: AsyncClient):
        res = await self._get(pg_client, repo="../bad", base="main", head="feature")
        assert res.status_code in (400, 422)

    # ── Ghost / auth ──

    async def test_unknown_repo_404(self, pg_client: AsyncClient):
        res = await self._get(pg_client, repo="ghost/nope",
                              base="main", head="feature")
        assert res.status_code == 404

    async def test_anonymous_401(self, pg_client: AsyncClient):
        app.dependency_overrides.pop(get_current_principal, None)
        try:
            res = await self._get(pg_client, repo=_REPO,
                                  base="main", head="feature")
            assert res.status_code == 401
        finally:
            pass

    # ── Forge errors ──

    async def test_unknown_ref_404(self, pg_client: AsyncClient):
        self._forge.error = LookupError("Ref 'ghost' not found")
        res = await self._get(pg_client, repo=_REPO, base="main", head="ghost")
        assert res.status_code == 404

    async def test_limit_413(self, pg_client: AsyncClient):
        self._forge.error = GiteaCompareLimitError("touches 501 files")
        res = await self._get(pg_client, repo=_REPO, base="main", head="feature")
        assert res.status_code == 413

    async def test_forge_unreachable_502(self, pg_client: AsyncClient):
        import requests as _r
        self._forge.error = _r.ConnectionError("down")
        res = await self._get(pg_client, repo=_REPO, base="main", head="feature")
        assert res.status_code in (502, 503)
