# -*- coding: utf-8 -*-
"""COS-181 + COS-185: Typed 409 WORKSPACE_CONFLICT — expected_head_sha / base_blob_sha.

Покрытие acceptance COS-181:
  - устаревший expected_head_sha → 409 WORKSPACE_CONFLICT с expected_sha/
    actual_sha, ДО любых чтений/записей файлов;
  - актуальный expected_head_sha (полный или >=7-hex префикс) → успех;
  - без поля — прежнее поведение: precondition не применяется, per-file CAS
    конфликты остаются typed 409 (kind exists|missing + conflicting paths);
  - forge-conflict (GiteaConflictError) → typed 409 kind=concurrent со свежим
    actual_sha;
  - контракт: expectedHeadSha в live OpenAPI-схеме запроса.

Покрытие COS-185 (per-file base_blob_sha):
  - конфликт exists/missing несёт expected_sha = переданную файловую базу;
  - без базы — прежнее поведение (expected_sha=null, совместимость);
  - база не ломает успешный путь; битый формат → 422; head-уровень приоритетен.

Живой Gitea не нужен: адаптер мокается (конвенция COS-124).
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

from orchestrator.cosmo.adapters.forge_gitea import GiteaConflictError  # noqa: E402
from orchestrator.cosmo.api.main import app  # noqa: E402
from orchestrator.cosmo.domain.workspace import (  # noqa: E402
    WorkspaceCommitRequest,
    WorkspaceFileChange,
)

SHA = "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6a7b8c9d0"
SHA2 = "b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6a7b8c9d0a1"
_API = "/api/v1/repos/workspace/commits"


# ── DTO ──────────────────────────────────────────────────────────────────

class TestExpectedHeadShaDto:
    def test_camel_case_alias(self):
        r = WorkspaceCommitRequest.model_validate_json(json.dumps({
            "repo": "org/app", "branch": "main", "message": "m",
            "expectedHeadSha": SHA,
            "fileChanges": [{"path": "x.py", "content": "y", "action": "create"}],
        }))
        assert r.expected_head_sha == SHA

    def test_default_none(self):
        r = WorkspaceCommitRequest(
            repo="org/app", branch="main", message="m",
            file_changes=[
                WorkspaceFileChange(path="x.py", content="y", action="create"),
            ],
        )
        assert r.expected_head_sha is None

    def test_empty_string_becomes_none(self):
        r = WorkspaceCommitRequest(
            repo="org/app", branch="main", message="m",
            expected_head_sha="",
            file_changes=[
                WorkspaceFileChange(path="x.py", content="y", action="create"),
            ],
        )
        assert r.expected_head_sha is None

    def test_malformed_rejected(self):
        with pytest.raises(ValidationError):
            WorkspaceCommitRequest(
                repo="org/app", branch="main", message="m",
                expected_head_sha="zz",
                file_changes=[
                    WorkspaceFileChange(path="x.py", content="y", action="create"),
                ],
            )

    def test_extra_forbidden_still(self):
        with pytest.raises(ValidationError):
            WorkspaceCommitRequest(
                repo="org/app", branch="main", message="m",
                file_changes=[
                    WorkspaceFileChange(path="x.py", content="y", action="create"),
                ],
                hack=1,
            )


# ── Route (mock adapter) ─────────────────────────────────────────────────

class FakeConflictAdapter:
    """Mock Gitea: get_commit / read_file / commit_changes + трекинг вызовов."""

    def __init__(self, head_sha: str | None = SHA,
                 file_sha_map: dict | None = None,
                 fail_commit: Exception | None = None):
        self._head_sha = head_sha
        self.file_sha_map = file_sha_map if file_sha_map is not None else {}
        self._fail_commit = fail_commit
        self.head_calls: list[str] = []
        self.read_calls: list[tuple[str, str]] = []
        self.commit_calls: list[dict] = []

    def get_commit(self, owner: str, repo: str, ref: str = ""):
        self.head_calls.append(ref)
        if self._head_sha is None:
            raise LookupError(f"No commits in {owner}/{repo}")
        c = type("C", (), {})()
        c.sha = self._head_sha
        return c

    def read_file(self, owner: str, repo: str, path: str, ref: str = ""):
        self.read_calls.append((path, ref))
        sha = self.file_sha_map.get(path)
        if sha is None:
            raise LookupError(f"File {path} not found")
        return "dummy-content", sha

    def commit_changes(self, owner, repo, branch, message, file_changes,
                       author_name=None, author_email=None):
        self.commit_calls.append({
            "owner": owner, "repo": repo, "branch": branch,
            "file_changes": file_changes,
        })
        if self._fail_commit is not None:
            raise self._fail_commit
        return {
            "sha": "f" * 40,
            "html_url": "http://gitea/org/repo/commit/" + "f" * 40,
            "authored_at": "2026-09-25T10:00:00Z",
            "files_changed": len(file_changes),
        }


async def _seed_app(pg_client: AsyncClient, repo: str) -> dict:
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


def _create_body(repo: str, **extra) -> dict:
    body = {
        "repo": repo, "branch": "main", "message": "cos181",
        "fileChanges": [{"path": "src/x.py", "content": "print(1)", "action": "create"}],
    }
    body.update(extra)
    return body


class TestExpectedHeadShaPrecondition:
    @pytest.fixture(autouse=True)
    def _mock_adapter(self, monkeypatch):
        from orchestrator.cosmo.api import forge_client as fc
        self._adapter = FakeConflictAdapter()
        monkeypatch.setattr(fc, "build_adapter", lambda: self._adapter)

    @pytest.mark.asyncio
    async def test_stale_head_typed_409_before_any_file_work(self, pg_client: AsyncClient):
        meta = await _seed_app(pg_client, "c181-org/stale")
        res = await pg_client.post(
            _API,
            json=_create_body(meta["repo"], expectedHeadSha=SHA2),
            headers={"X-Cosmo-Domain": meta["domain"]},
        )
        assert res.status_code == 409, res.text
        err = res.json()["error"]
        assert err["code"] == "WORKSPACE_CONFLICT"
        assert err["details"]["kind"] == "concurrent"
        assert err["details"]["expected_sha"] == SHA2
        assert err["details"]["actual_sha"] == SHA
        assert err["details"]["paths"] == []
        # precondition — до любых чтений/записей файлов
        assert self._adapter.read_calls == []
        assert self._adapter.commit_calls == []

    @pytest.mark.asyncio
    async def test_current_head_success_201(self, pg_client: AsyncClient):
        meta = await _seed_app(pg_client, "c181-org/current")
        res = await pg_client.post(
            _API,
            json=_create_body(meta["repo"], expectedHeadSha=SHA),
            headers={"X-Cosmo-Domain": meta["domain"]},
        )
        assert res.status_code == 201, res.text
        assert len(self._adapter.commit_calls) == 1

    @pytest.mark.asyncio
    async def test_prefix_head_success_201(self, pg_client: AsyncClient):
        meta = await _seed_app(pg_client, "c181-org/prefix")
        res = await pg_client.post(
            _API,
            json=_create_body(meta["repo"], expectedHeadSha=SHA[:12]),
            headers={"X-Cosmo-Domain": meta["domain"]},
        )
        assert res.status_code == 201, res.text

    @pytest.mark.asyncio
    async def test_malformed_head_422(self, pg_client: AsyncClient):
        meta = await _seed_app(pg_client, "c181-org/badsha")
        res = await pg_client.post(
            _API,
            json=_create_body(meta["repo"], expectedHeadSha="zz"),
            headers={"X-Cosmo-Domain": meta["domain"]},
        )
        assert res.status_code == 422, res.text
        assert self._adapter.commit_calls == []


class TestPerFileConflictsRemainTyped:
    """Без expected_head_sha — прежний per-file CAS, но typed 409."""

    @pytest.fixture(autouse=True)
    def _mock_adapter(self, monkeypatch):
        from orchestrator.cosmo.api import forge_client as fc
        self._adapter = FakeConflictAdapter()
        monkeypatch.setattr(fc, "build_adapter", lambda: self._adapter)

    @pytest.mark.asyncio
    async def test_no_field_previous_behavior_success(self, pg_client: AsyncClient):
        meta = await _seed_app(pg_client, "c181-org/nofield")
        res = await pg_client.post(
            _API, json=_create_body(meta["repo"]),
            headers={"X-Cosmo-Domain": meta["domain"]},
        )
        assert res.status_code == 201, res.text
        assert len(self._adapter.commit_calls) == 1

    @pytest.mark.asyncio
    async def test_no_field_create_exists_typed_409(self, pg_client: AsyncClient):
        meta = await _seed_app(pg_client, "c181-org/exists")
        self._adapter.file_sha_map["src/x.py"] = SHA2
        res = await pg_client.post(
            _API, json=_create_body(meta["repo"]),
            headers={"X-Cosmo-Domain": meta["domain"]},
        )
        assert res.status_code == 409, res.text
        err = res.json()["error"]
        assert err["code"] == "WORKSPACE_CONFLICT"
        assert err["details"]["kind"] == "exists"
        assert err["details"]["paths"] == ["src/x.py"]
        assert err["details"]["actual_sha"] == SHA2
        assert self._adapter.commit_calls == []

    @pytest.mark.asyncio
    async def test_no_field_update_missing_typed_409(self, pg_client: AsyncClient):
        meta = await _seed_app(pg_client, "c181-org/missing")
        body = {
            "repo": meta["repo"], "branch": "main", "message": "upd",
            "fileChanges": [{"path": "gone.py", "content": "v2", "action": "update"}],
        }
        res = await pg_client.post(
            _API, json=body, headers={"X-Cosmo-Domain": meta["domain"]},
        )
        assert res.status_code == 409, res.text
        err = res.json()["error"]
        assert err["code"] == "WORKSPACE_CONFLICT"
        assert err["details"]["kind"] == "missing"
        assert err["details"]["paths"] == ["gone.py"]


class TestForgeConflictTyped:
    @pytest.fixture(autouse=True)
    def _mock_adapter(self, monkeypatch):
        from orchestrator.cosmo.api import forge_client as fc
        self._adapter = FakeConflictAdapter(fail_commit=GiteaConflictError("ref moved"))
        monkeypatch.setattr(fc, "build_adapter", lambda: self._adapter)

    @pytest.mark.asyncio
    async def test_forge_conflict_typed_concurrent_with_fresh_actual(
            self, pg_client: AsyncClient):
        meta = await _seed_app(pg_client, "c181-org/forge")
        res = await pg_client.post(
            _API,
            json=_create_body(meta["repo"], expectedHeadSha=SHA),
            headers={"X-Cosmo-Domain": meta["domain"]},
        )
        assert res.status_code == 409, res.text
        err = res.json()["error"]
        assert err["code"] == "WORKSPACE_CONFLICT"
        assert err["details"]["kind"] == "concurrent"
        assert err["details"]["expected_sha"] == SHA
        assert err["details"]["actual_sha"] == SHA  # свежий head (mock)
        assert "commit conflict" in err["message"]


# ── COS-185: per-file base_blob_sha ──────────────────────────────────────

class TestBaseBlobShaDto:
    def test_camel_case_alias(self):
        fc = WorkspaceFileChange.model_validate({
            "path": "x.py", "content": "y", "action": "create", "baseBlobSha": SHA,
        })
        assert fc.base_blob_sha == SHA

    def test_default_none(self):
        fc = WorkspaceFileChange(path="x.py", content="y", action="create")
        assert fc.base_blob_sha is None

    def test_empty_string_becomes_none(self):
        fc = WorkspaceFileChange(
            path="x.py", content="y", action="create", base_blob_sha="",
        )
        assert fc.base_blob_sha is None

    def test_malformed_rejected(self):
        with pytest.raises(ValidationError):
            WorkspaceFileChange(
                path="x.py", content="y", action="create", base_blob_sha="zz",
            )

    def test_allowed_on_delete(self):
        fc = WorkspaceFileChange(path="x.py", action="delete", base_blob_sha=SHA)
        assert fc.base_blob_sha == SHA


class TestPerFileBaseBlobSha:
    """COS-185: файловая база уезжает в expected_sha файлового конфликта."""

    @pytest.fixture(autouse=True)
    def _mock_adapter(self, monkeypatch):
        from orchestrator.cosmo.api import forge_client as fc
        self._adapter = FakeConflictAdapter()
        monkeypatch.setattr(fc, "build_adapter", lambda: self._adapter)

    @pytest.mark.asyncio
    async def test_create_exists_carries_base_as_expected_sha(self, pg_client: AsyncClient):
        meta = await _seed_app(pg_client, "c185-org/exists")
        self._adapter.file_sha_map["src/x.py"] = SHA2  # actual (на ветке)
        base = SHA  # база клиента
        res = await pg_client.post(_API, json={
            "repo": meta["repo"], "branch": "main", "message": "m",
            "fileChanges": [{
                "path": "src/x.py", "content": "y", "action": "create",
                "baseBlobSha": base,
            }],
        }, headers={"X-Cosmo-Domain": meta["domain"]})
        assert res.status_code == 409, res.text
        d = res.json()["error"]["details"]
        assert d["kind"] == "exists"
        assert d["expected_sha"] == base  # COS-185: база, не null
        assert d["actual_sha"] == SHA2
        assert d["paths"] == ["src/x.py"]
        assert self._adapter.commit_calls == []

    @pytest.mark.asyncio
    async def test_update_missing_carries_base_as_expected_sha(self, pg_client: AsyncClient):
        meta = await _seed_app(pg_client, "c185-org/missing")
        base = SHA2
        res = await pg_client.post(_API, json={
            "repo": meta["repo"], "branch": "main", "message": "m",
            "fileChanges": [{
                "path": "gone.py", "content": "v2", "action": "update",
                "baseBlobSha": base,
            }],
        }, headers={"X-Cosmo-Domain": meta["domain"]})
        assert res.status_code == 409, res.text
        d = res.json()["error"]["details"]
        assert d["kind"] == "missing"
        assert d["expected_sha"] == base
        assert d["actual_sha"] is None

    @pytest.mark.asyncio
    async def test_delete_missing_carries_base_as_expected_sha(self, pg_client: AsyncClient):
        meta = await _seed_app(pg_client, "c185-org/delmissing")
        base = SHA
        res = await pg_client.post(_API, json={
            "repo": meta["repo"], "branch": "main", "message": "m",
            "fileChanges": [{
                "path": "gone.py", "action": "delete", "baseBlobSha": base,
            }],
        }, headers={"X-Cosmo-Domain": meta["domain"]})
        assert res.status_code == 409, res.text
        d = res.json()["error"]["details"]
        assert d["kind"] == "missing"
        assert d["expected_sha"] == base

    @pytest.mark.asyncio
    async def test_without_base_expected_sha_null(self, pg_client: AsyncClient):
        """Без базы — прежнее поведение COS-181 (expected_sha=null)."""
        meta = await _seed_app(pg_client, "c185-org/nobase")
        self._adapter.file_sha_map["src/x.py"] = SHA2
        res = await pg_client.post(_API, json=_create_body(meta["repo"]),
                                   headers={"X-Cosmo-Domain": meta["domain"]})
        assert res.status_code == 409, res.text
        d = res.json()["error"]["details"]
        assert d["kind"] == "exists"
        assert d["expected_sha"] is None

    @pytest.mark.asyncio
    async def test_base_accepted_on_success_path(self, pg_client: AsyncClient):
        """Поле не ломает успешный коммит (совместимость)."""
        meta = await _seed_app(pg_client, "c185-org/success")
        res = await pg_client.post(_API, json={
            "repo": meta["repo"], "branch": "main", "message": "m",
            "fileChanges": [{
                "path": "src/x.py", "content": "y", "action": "create",
                "baseBlobSha": SHA,
            }],
        }, headers={"X-Cosmo-Domain": meta["domain"]})
        assert res.status_code == 201, res.text
        assert len(self._adapter.commit_calls) == 1

    @pytest.mark.asyncio
    async def test_malformed_base_422(self, pg_client: AsyncClient):
        meta = await _seed_app(pg_client, "c185-org/badbase")
        res = await pg_client.post(_API, json={
            "repo": meta["repo"], "branch": "main", "message": "m",
            "fileChanges": [{
                "path": "src/x.py", "content": "y", "action": "create",
                "baseBlobSha": "zz",
            }],
        }, headers={"X-Cosmo-Domain": meta["domain"]})
        assert res.status_code == 422, res.text
        assert self._adapter.commit_calls == []

    @pytest.mark.asyncio
    async def test_head_level_conflict_wins_over_file_base(self, pg_client: AsyncClient):
        """expectedHeadSha (branch-level) проверяется до файлов — приоритет."""
        meta = await _seed_app(pg_client, "c185-org/both")
        self._adapter.file_sha_map["src/x.py"] = SHA2
        res = await pg_client.post(_API, json={
            "repo": meta["repo"], "branch": "main", "message": "m",
            "expectedHeadSha": SHA2,  # stale vs head SHA
            "fileChanges": [{
                "path": "src/x.py", "content": "y", "action": "create",
                "baseBlobSha": SHA,
            }],
        }, headers={"X-Cosmo-Domain": meta["domain"]})
        assert res.status_code == 409, res.text
        d = res.json()["error"]["details"]
        assert d["kind"] == "concurrent"
        assert d["expected_sha"] == SHA2
        assert d["actual_sha"] == SHA
        # до любых чтений файлов (precondition COS-181)
        assert self._adapter.read_calls == []


# ── Контракт ─────────────────────────────────────────────────────────────

class TestContract:
    def test_openapi_request_schema_has_expected_head_sha(self):
        spec = app.openapi()
        props = spec["components"]["schemas"]["WorkspaceCommitRequest"]["properties"]
        assert "expectedHeadSha" in props

    def test_openapi_file_change_schema_has_base_blob_sha(self):
        """COS-185: per-file baseBlobSha объявлен в схеме запроса."""
        spec = app.openapi()
        props = spec["components"]["schemas"]["WorkspaceFileChange"]["properties"]
        assert "baseBlobSha" in props

    def test_workspace_conflict_shape_is_transfer_envelope(self):
        """Структура 409: error{code,message,details} — контракт COS-058."""
        from orchestrator.cosmo.api.routes.workspace import _workspace_conflict

        exc = _workspace_conflict(
            kind="concurrent", message="m", expected_sha=SHA, actual_sha=SHA2,
            paths=["a.py"],
        )
        assert exc.status_code == 409
        err = exc.detail["error"]
        assert set(err) == {"code", "message", "details"}
        assert err["code"] == "WORKSPACE_CONFLICT"
        assert err["details"] == {
            "kind": "concurrent", "expected_sha": SHA, "actual_sha": SHA2,
            "paths": ["a.py"],
        }
