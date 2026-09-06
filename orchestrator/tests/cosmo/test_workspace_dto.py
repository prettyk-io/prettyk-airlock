# -*- coding: utf-8 -*-
"""COS-102: Workspace DTO — валидность, ригидность, traversal, camelCase.

Контракт-зеркало prettyk-ide src/workspace/types.ts:
  - JSON-ключи camelCase (headSha / baseBlobSha) — model_dump(by_alias=True);
  - model_validate_json принимает TS-пейлоады напрямую;
  - extra="forbid" — драйф контракта ловится на границе, не тишиной;
  - head_sha обязателен для CAS-ready операций (tree/blob);
  - path traversal (../, abs, backslash, NUL, drive) — reject в Pydantic.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from orchestrator.cosmo.domain.workspace import (
    TreeEntry,
    WorkspaceAuthorization,
    WorkspaceBlobRequest,
    WorkspaceBlobResponse,
    WorkspaceBootstrapRequest,
    WorkspaceBootstrapResponse,
    WorkspaceContractError,
    WorkspaceTreeRequest,
    WorkspaceTreeResponse,
    validate_branch,
    validate_head_sha,
    validate_repo,
    validate_tree_path,
)

SHA = "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6a7b8c9d0"  # 40 hex


# ── Bootstrap ──────────────────────────────────────────────────────────

class TestBootstrap:
    def test_request_minimal_repo_only(self):
        r = WorkspaceBootstrapRequest(repo="org/app")
        assert r.repo == "org/app"
        assert r.branch == ""  # пусто → default branch (резолвит COS-103)

    def test_request_full(self):
        r = WorkspaceBootstrapRequest.model_validate_json(
            json.dumps({"repo": "org/app", "branch": "main"}))
        assert r.branch == "main"

    def test_request_extra_forbidden(self):
        with pytest.raises(ValidationError):
            WorkspaceBootstrapRequest(repo="org/app", branch="main", hack=1)

    def test_response_from_ts_shaped_json(self):
        """TS-пейлоад (headSha camelCase) валидируется напрямую."""
        payload = {
            "repo": "org/app",
            "branch": "main",
            "headSha": SHA,
            "capabilities": ["read", "draft", "commit"],
            "authorization": "allow",
        }
        r = WorkspaceBootstrapResponse.model_validate_json(json.dumps(payload))
        assert r.head_sha == SHA
        assert r.capabilities == ["read", "draft", "commit"]
        assert r.authorization == "allow"

    def test_response_dump_aliases_match_ts_keys(self):
        r = WorkspaceBootstrapResponse(
            repo="org/app", branch="main", head_sha=SHA,
            capabilities=["read"], authorization="deny")
        keys = set(json.loads(r.model_dump_json(by_alias=True)).keys())
        assert keys == {"repo", "branch", "headSha", "capabilities", "authorization"}

    def test_response_bad_capability_rejected(self):
        with pytest.raises(ValidationError):
            WorkspaceBootstrapResponse(
                repo="org/app", branch="main", head_sha=SHA,
                capabilities=["admin"], authorization="allow")

    def test_response_bad_authorization_rejected(self):
        with pytest.raises(ValidationError):
            WorkspaceBootstrapResponse(
                repo="org/app", branch="main", head_sha=SHA,
                capabilities=[], authorization="maybe")

    def test_response_head_sha_required_valid(self):
        with pytest.raises(ValidationError):
            WorkspaceBootstrapResponse(
                repo="org/app", branch="main", head_sha="not-a-sha",
                capabilities=[], authorization="allow")


# ── Tree ───────────────────────────────────────────────────────────────

class TestTree:
    def test_request_camel_and_snake_both_accepted(self):
        a = WorkspaceTreeRequest.model_validate_json(
            json.dumps({"repo": "org/app", "branch": "main", "headSha": SHA}))
        b = WorkspaceTreeRequest(
            repo="org/app", branch="main", head_sha=SHA)
        assert a.head_sha == b.head_sha == SHA

    def test_request_head_sha_missing_rejected(self):
        """CAS: без head_sha операция не адресуемая — 422 на границе."""
        with pytest.raises(ValidationError):
            WorkspaceTreeRequest.model_validate_json(
                json.dumps({"repo": "org/app", "branch": "main"}))

    def test_request_extra_forbidden(self):
        with pytest.raises(ValidationError):
            WorkspaceTreeRequest(
                repo="org/app", branch="main", head_sha=SHA, path="src")

    def test_response_entries(self):
        r = WorkspaceTreeResponse.model_validate_json(json.dumps({
            "entries": [
                {"path": "src/main.py", "kind": "file", "status": "M"},
                {"path": "src", "kind": "directory"},
                {"path": "README.md", "kind": "file", "status": None},
            ]}))
        assert r.entries[0].status == "M"
        assert r.entries[1].status is None
        assert r.entries[2].kind == "file"

    def test_response_entry_bad_kind_rejected(self):
        with pytest.raises(ValidationError):
            TreeEntry(path="x", kind="symlink")

    def test_response_entry_bad_status_rejected(self):
        with pytest.raises(ValidationError):
            TreeEntry(path="x", kind="file", status="A")  # TS: только M|U|D

    def test_response_entry_empty_path_rejected(self):
        with pytest.raises(ValidationError):
            TreeEntry(path="", kind="file")


# ── Blob ───────────────────────────────────────────────────────────────

class TestBlob:
    def test_request_happy(self):
        r = WorkspaceBlobRequest.model_validate_json(json.dumps({
            "repo": "org/app", "branch": "main",
            "path": "src/cosmo/main.py", "headSha": SHA}))
        assert r.path == "src/cosmo/main.py"
        assert r.head_sha == SHA

    def test_request_path_required(self):
        with pytest.raises(ValidationError):
            WorkspaceBlobRequest(
                repo="org/app", branch="main", path="", head_sha=SHA)

    def test_response_happy_with_base_blob_sha(self):
        r = WorkspaceBlobResponse.model_validate_json(json.dumps({
            "path": "src/x.py", "content": "print(1)", "sha": SHA,
            "encoding": "utf-8", "baseBlobSha": SHA}))
        assert r.base_blob_sha == SHA
        assert r.encoding == "utf-8"

    def test_response_base_blob_sha_required(self):
        """CAS: без базы черновик не строится — DTO не даёт забыть."""
        with pytest.raises(ValidationError):
            WorkspaceBlobResponse(
                path="src/x.py", content="x", sha=SHA, encoding="utf-8")

    def test_response_encoding_literal_utf8_only(self):
        with pytest.raises(ValidationError):
            WorkspaceBlobResponse(
                path="src/x.py", content="x", sha=SHA,
                encoding="base64", base_blob_sha=SHA)

    def test_response_dump_alias_base_blob_sha(self):
        r = WorkspaceBlobResponse(
            path="src/x.py", content="x", sha=SHA,
            base_blob_sha=SHA)
        d = json.loads(r.model_dump_json(by_alias=True))
        assert "baseBlobSha" in d and "base_blob_sha" not in d
        assert d["path"] == "src/x.py"  # ключи без underscore остаются как есть


# ── Path traversal guard ───────────────────────────────────────────────

class TestTraversalGuard:
    @pytest.mark.parametrize("bad", [
        "../etc/passwd",
        "a/../../b",
        "..",
        ".",
        "a/../b",
        "/absolute/path",
        "a//b",
        "a/",
        "a\\b",
        "C:/windows/system32",
        "C:\\x",
        "src\x00null",
        " src/main.py",
        "src/main.py ",
        "src/./x",
    ])
    def test_tree_path_rejections(self, bad):
        with pytest.raises(WorkspaceContractError):
            validate_tree_path(bad)

    @pytest.mark.parametrize("good", [
        "src/main.py",
        "src/cosmo/deep/nested/file.yaml",
        ".cosmo/pipeline.yaml",
        "README.md",
        "a.b.c/d-e/f_g.h",
    ])
    def test_tree_path_acceptances(self, good):
        assert validate_tree_path(good) == good

    @pytest.mark.parametrize("bad", [
        "../up",
        "org/repo/extra",
        "/abs",
        "org/",
        "org/..",
        "or g/app",
        "org\\app",
        "org/repo ",
        "-org/app",
    ])
    def test_repo_rejections(self, bad):
        with pytest.raises(WorkspaceContractError):
            validate_repo(bad)

    @pytest.mark.parametrize("good", ["org/app", "cosmo-port/web.ide"])
    def test_repo_acceptances(self, good):
        assert validate_repo(good) == good

    @pytest.mark.parametrize("bad", [
        "../main",
        "-flag-injection",
        "feature//x",
        "main/",
        "a b",
        "branch\\x",
        "main..history",
    ])
    def test_branch_rejections(self, bad):
        with pytest.raises(WorkspaceContractError):
            validate_branch(bad)

    @pytest.mark.parametrize("good", [
        "main",
        "feature/cos-102-dto",
        "release/v1.2.3",
    ])
    def test_branch_acceptances(self, good):
        assert validate_branch(good) == good

    @pytest.mark.parametrize("bad", [
        "", "short", "g1b2c3d",  # 7 chars, но 'g' не hex
        "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6a7b8c9d0e1f2a3b4c5d6a7b8c9d0x",  # 65
        SHA + " ", "A1B2C3D!!",
    ])
    def test_head_sha_rejections(self, bad):
        with pytest.raises(WorkspaceContractError):
            validate_head_sha(bad)

    @pytest.mark.parametrize("good", [
        "a1b2c3d",                       # сокращённый sha
        SHA,                             # полный sha1
        "A1B2C3D4E5F6A7B8C9D0E1F2A3B4C5D6A7B8C9D0",  # uppercase
    ])
    def test_head_sha_acceptances(self, good):
        assert validate_head_sha(good) == good

    def test_guard_blocks_traversal_before_adapter(self):
        """Traversal в blob-запросе не проходит Pydantic — до адаптера не дойдёт."""
        with pytest.raises(ValidationError):
            WorkspaceBlobRequest.model_validate_json(json.dumps({
                "repo": "org/app", "branch": "main",
                "path": "../secrets.yaml", "headSha": SHA}))


# ── Контракт types.ts (round-trip) ─────────────────────────────────────

class TestTypesTsContract:
    TS_FILE = Path(r"D:\prettyk-ide\src\workspace\types.ts")

    def test_types_ts_exists(self):
        if not self.TS_FILE.is_file():
            pytest.skip("prettyk-ide checkout недоступен на этой машине")
        assert self.TS_FILE.is_file()

    def test_ts_literals_mirror(self):
        """Capability / kind / status / authorization литералы совпадают с TS."""
        if not self.TS_FILE.is_file():
            pytest.skip("prettyk-ide checkout недоступен на этой машине")
        ts = self.TS_FILE.read_text(encoding="utf-8")
        for lit in ["'read' | 'draft' | 'commit' | 'run'",
                    "'file' | 'directory'",
                    "'M' | 'U' | 'D'",
                    "'allow' | 'deny'"]:
            assert lit in ts, f"types.ts дрейф: не найдено {lit}"

    def test_full_cycle_ts_shaped(self):
        """IDE-пейлоад → DTO → by_alias dump → снова DTO: без потерь."""
        original = {
            "repo": "org/app", "branch": "feat/x", "headSha": SHA,
            "capabilities": ["read", "commit"], "authorization": "allow",
        }
        dto = WorkspaceBootstrapResponse.model_validate_json(json.dumps(original))
        round_trip = json.loads(dto.model_dump_json(by_alias=True))
        assert round_trip == original
