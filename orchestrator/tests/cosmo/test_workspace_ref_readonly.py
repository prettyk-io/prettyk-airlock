# -*- coding: utf-8 -*-
"""COS-177: Workspace ref-readonly — tree/file по произвольному commit (FR-004 §7).

Покрытие acceptance COS-177:
  - после движения ветки чтение по ref=<старый commit> → 200 (snapshot);
    по head_sha=<старый commit> → 409 (CAS-путь не сломан);
  - несуществующий ref → 404, битый формат → 400, не 5xx;
  - ref+head_sha: приоритет у ref (нет ложного 409);
  - файл на ref: sha/baseBlobSha — blob sha коммита (не головы);
  - write-путь (draft/commit/files/branches) ref не принимает
    (read-only by construction);
  - Gitea-квирк: 500 "object does not exist" на неизвестный ref →
    LookupError (404), не 502; настоящие 500 не глотаются;
  - контракт: ref-параметр в docs json == yaml == live app.openapi().

Fake ForgeAdapter monkeypatch'ит forge_client.build_adapter — живой Gitea
не нужен. Live-smoke — opt-in (COSMO_LIVE_GITEA=1, класс в конце модуля):
сценарий «ветка уехала» на живом стенде Gitea (:3100) + ПУ (:8100).
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest
import yaml

_orch = Path(__file__).resolve().parents[1]
if str(_orch) not in sys.path:
    sys.path.insert(0, str(_orch))

from httpx import AsyncClient

from orchestrator.cosmo.api.main import app

OLD_SHA = "1" * 40
NEW_SHA = "2" * 40
OLD_BLOB = "3" * 40
NEW_BLOB = "4" * 40
REPO = "acme/refapi"
DOMAIN_ID = "ws177-dom"
APP_ID = "ws177-app"


# ── Fake ForgeAdapter (пер-коммитные snapshot'ы) ──────────────────────

class FakeTreeEntry:
    def __init__(self, path: str, type_: str):
        self.path = path
        self.type = type_
        self.sha = OLD_SHA
        self.size = 10


class FakeRefAdapter:
    """In-memory Gitea: sha → (files, tree); head = последний snapshot."""

    def __init__(self) -> None:
        self.refs: dict[str, dict] = {}
        self.head = ""

    def add_snapshot(self, sha: str, files: dict, tree: list | None = None) -> None:
        self.refs[sha] = {
            "files": files,
            "tree": tree or [FakeTreeEntry(p, "blob") for p in files],
        }
        self.head = sha

    # ── GiteaForgeAdapter API ──
    def get_commit(self, owner: str, name: str, ref: str = ""):
        return type("Commit", (), {
            "sha": self.head, "message": "feat", "author": "max",
            "timestamp": "2026-09-25T00:00:00Z",
        })()

    def get_tree(self, owner: str, name: str, ref: str = "", recursive: bool = True):
        snap = self.refs.get(ref) or self.refs[self.head]
        return snap["tree"]

    def read_file(self, owner: str, name: str, path: str, ref: str = ""):
        snap = self.refs.get(ref) or self.refs[self.head]
        if path not in snap["files"]:
            raise LookupError(f"File {path} not found in {owner}/{name} (ref={ref})")
        return snap["files"][path]

    def resolve_ref(self, owner: str, name: str, ref: str) -> str:
        for sha in self.refs:
            if sha.startswith(ref.lower()):
                return sha
        raise LookupError(f"Ref {ref!r} not found in {owner}/{name}")

    def get_tree_by_sha(self, owner: str, name: str, sha: str, recursive: bool = True):
        if sha not in self.refs:
            raise LookupError(f"Tree {sha} not found in {owner}/{name}")
        return self.refs[sha]["tree"]


def _two_revisions(adapter: FakeRefAdapter) -> None:
    """Ветка уехала: A (v1) → B (v2, +src/new.py); head = B."""
    adapter.add_snapshot(OLD_SHA, {
        "README.md": ("# v1", OLD_BLOB),
        "src/app.py": ("print('v1')", "5" * 40),
    }, tree=[
        FakeTreeEntry("README.md", "blob"),
        FakeTreeEntry("src", "tree"),
        FakeTreeEntry("src/app.py", "blob"),
    ])
    adapter.add_snapshot(NEW_SHA, {
        "README.md": ("# v2", NEW_BLOB),
        "src/app.py": ("print('v2')", "6" * 40),
        "src/new.py": ("# new", "7" * 40),
    }, tree=[
        FakeTreeEntry("README.md", "blob"),
        FakeTreeEntry("src", "tree"),
        FakeTreeEntry("src/app.py", "blob"),
        FakeTreeEntry("src/new.py", "blob"),
    ])


@pytest.fixture()
def fake_adapter(monkeypatch):
    from orchestrator.cosmo.api import forge_client

    adapter = FakeRefAdapter()
    _two_revisions(adapter)
    monkeypatch.setattr(forge_client, "build_adapter", lambda: adapter)
    return adapter


async def _seed(pg_client: AsyncClient) -> None:
    await pg_client.post("/api/v1/domains", json={
        "id": DOMAIN_ID, "label": "Ref readonly domain",
        "forge_binding": {"forge_type": "gitea", "url": "http://gitea",
                          "token_ref": "vault:ws177"},
    })
    res = await pg_client.post("/api/v1/apps", json={
        "id": APP_ID, "domain_id": DOMAIN_ID, "level": 1,
        "repo_binding": {"forge_id": "gitea", "repo_path": REPO},
    })
    assert res.status_code in (200, 201), res.text


# ── Tree: ref-режим ───────────────────────────────────────────────────

@pytest.mark.asyncio
class TestTreeRefMode:

    async def test_ref_old_commit_snapshot_after_branch_moved(
            self, pg_client: AsyncClient, fake_adapter):
        """Acceptance #1: ветка уехала, но ref=<старый commit> → 200 snapshot."""
        await _seed(pg_client)
        res = await pg_client.get(f"/api/v1/repos/tree?repo={REPO}&ref={OLD_SHA}")
        assert res.status_code == 200, res.text
        paths = {e["path"] for e in res.json()["entries"]}
        assert paths == {"README.md", "src", "src/app.py"}  # snapshot A, не голова
        assert "src/new.py" not in paths

    async def test_ref_wins_over_head_sha_no_false_409(
            self, pg_client: AsyncClient, fake_adapter):
        """ref+head_sha: ref приоритетен; устаревший head_sha не даёт 409."""
        await _seed(pg_client)
        res = await pg_client.get(
            f"/api/v1/repos/tree?repo={REPO}&ref={OLD_SHA}"
            f"&branch=main&head_sha={NEW_SHA}")
        assert res.status_code == 200, res.text
        assert "src/new.py" not in {e["path"] for e in res.json()["entries"]}

    async def test_ref_prefix_resolves(self, pg_client: AsyncClient, fake_adapter):
        await _seed(pg_client)
        res = await pg_client.get(f"/api/v1/repos/tree?repo={REPO}&ref={OLD_SHA[:7]}")
        assert res.status_code == 200, res.text
        assert {e["path"] for e in res.json()["entries"]} == {
            "README.md", "src", "src/app.py"}

    async def test_ref_nonexistent_404_not_5xx(
            self, pg_client: AsyncClient, fake_adapter):
        await _seed(pg_client)
        res = await pg_client.get(f"/api/v1/repos/tree?repo={REPO}&ref={'f' * 40}")
        assert res.status_code == 404, res.text

    @pytest.mark.parametrize("bad", ["zzz", "not-a-sha", "123456", "a" * 65])
    async def test_ref_malformed_400(
            self, pg_client: AsyncClient, fake_adapter, bad):
        await _seed(pg_client)
        res = await pg_client.get(f"/api/v1/repos/tree?repo={REPO}&ref={bad}")
        assert res.status_code == 400, res.text
        assert "ref" in res.json()["detail"]

    async def test_no_ref_requires_branch_and_head_sha(
            self, pg_client: AsyncClient, fake_adapter):
        """CAS-путь без ref: пара branch+head_sha обязательна → 400."""
        await _seed(pg_client)
        res = await pg_client.get(f"/api/v1/repos/tree?repo={REPO}")
        assert res.status_code == 400, res.text
        res2 = await pg_client.get(f"/api/v1/repos/tree?repo={REPO}&branch=main")
        assert res2.status_code == 400, res2.text

    async def test_cas_regression_stale_409_fresh_200(
            self, pg_client: AsyncClient, fake_adapter):
        """CAS-путь не регрессирует: устаревший head_sha → 409, свежий → 200."""
        await _seed(pg_client)
        stale = await pg_client.get(
            f"/api/v1/repos/tree?repo={REPO}&branch=main&head_sha={OLD_SHA}")
        assert stale.status_code == 409, stale.text
        fresh = await pg_client.get(
            f"/api/v1/repos/tree?repo={REPO}&branch=main&head_sha={NEW_SHA}")
        assert fresh.status_code == 200, fresh.text
        assert "src/new.py" in {e["path"] for e in fresh.json()["entries"]}


# ── File: ref-режим ───────────────────────────────────────────────────

@pytest.mark.asyncio
class TestFileRefMode:

    async def test_file_ref_snapshot_content_and_blob_sha(
            self, pg_client: AsyncClient, fake_adapter):
        """Acceptance #5: sha/baseBlobSha — blob коммита, не головы."""
        await _seed(pg_client)
        res = await pg_client.get(
            f"/api/v1/repos/file?repo={REPO}&ref={OLD_SHA}&path=README.md")
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["content"] == "# v1"
        assert body["sha"] == OLD_BLOB
        assert body["baseBlobSha"] == OLD_BLOB
        # голова отдала бы другой blob — доказываем, что это snapshot
        head_res = await pg_client.get(
            f"/api/v1/repos/file?repo={REPO}&branch=main&head_sha={NEW_SHA}"
            f"&path=README.md")
        assert head_res.status_code == 200, head_res.text
        assert head_res.json()["sha"] == NEW_BLOB

    async def test_file_ref_prefix_and_missing_path(
            self, pg_client: AsyncClient, fake_adapter):
        await _seed(pg_client)
        ok = await pg_client.get(
            f"/api/v1/repos/file?repo={REPO}&ref={OLD_SHA[:8]}&path=src%2Fapp.py")
        assert ok.status_code == 200, ok.text
        assert ok.json()["content"] == "print('v1')"
        # в snapshot A файла src/new.py ещё нет — честный 404, не голова
        missing = await pg_client.get(
            f"/api/v1/repos/file?repo={REPO}&ref={OLD_SHA}&path=src%2Fnew.py")
        assert missing.status_code == 404, missing.text

    async def test_file_ref_nonexistent_and_malformed(
            self, pg_client: AsyncClient, fake_adapter):
        await _seed(pg_client)
        gone = await pg_client.get(
            f"/api/v1/repos/file?repo={REPO}&ref={'f' * 40}&path=README.md")
        assert gone.status_code == 404, gone.text
        bad = await pg_client.get(
            f"/api/v1/repos/file?repo={REPO}&ref=zzz&path=README.md")
        assert bad.status_code == 400, bad.text

    async def test_file_ref_wins_over_stale_head_sha(
            self, pg_client: AsyncClient, fake_adapter):
        await _seed(pg_client)
        res = await pg_client.get(
            f"/api/v1/repos/file?repo={REPO}&ref={OLD_SHA}"
            f"&branch=main&head_sha={NEW_SHA}&path=README.md")
        assert res.status_code == 200, res.text
        assert res.json()["content"] == "# v1"


# ── Read-only by construction ─────────────────────────────────────────

class TestWritePathIsCasOnly:
    """ref не протекает в write-контракты (read-only by construction)."""

    def test_write_dtos_have_no_ref_field(self):
        from orchestrator.cosmo.domain.workspace import (
            WorkspaceCommitRequest,
            WorkspaceContentsCommitRequest,
            WorkspaceCreateBranchRequest,
            WorkspaceDraftUpsertRequest,
            WorkspaceFileCreateRequest,
            WorkspaceFileDeleteRequest,
            WorkspaceFileMoveRequest,
        )
        for dto in (
            WorkspaceCommitRequest,
            WorkspaceContentsCommitRequest,
            WorkspaceCreateBranchRequest,
            WorkspaceDraftUpsertRequest,
            WorkspaceFileCreateRequest,
            WorkspaceFileDeleteRequest,
            WorkspaceFileMoveRequest,
        ):
            assert "ref" not in dto.model_fields, dto.__name__


# ── Adapter: Gitea-квирк неизвестного ref ─────────────────────────────

class TestResolveRefGiteaQuirk:
    """Gitea 1.22.6: /commits?sha=<unknown> → 500 'object does not exist'.

    Контракт COS-177: несуществующий ref → 404, не 502. Адаптер
    нормализует квирк в LookupError, настоящие 500 — не глотает.
    """

    @staticmethod
    def _adapter():
        from orchestrator.cosmo.adapters.forge_gitea import GiteaForgeAdapter
        return GiteaForgeAdapter(base_url="http://gitea.local")

    @staticmethod
    def _http_error(status: int, body: str):
        import requests
        resp = requests.Response()
        resp.status_code = status
        resp.encoding = "utf-8"
        resp._content = body.encode("utf-8")
        return requests.HTTPError(f"HTTP {status}", response=resp)

    def test_missing_ref_500_normalized_to_lookup(self, monkeypatch):
        ad = self._adapter()
        err = self._http_error(
            500, '{"message":"object does not exist [id: ffff, rel_path: ]"}')

        def _raise(*a, **k):
            raise err

        monkeypatch.setattr(ad, "list_commits_history", _raise)
        with pytest.raises(LookupError):
            ad.resolve_ref("acme", "api", "f" * 40)

    def test_genuine_500_not_swallowed(self, monkeypatch):
        import requests

        ad = self._adapter()
        err = self._http_error(500, '{"message":"database is locked"}')

        def _raise(*a, **k):
            raise err

        monkeypatch.setattr(ad, "list_commits_history", _raise)
        with pytest.raises(requests.HTTPError):
            ad.resolve_ref("acme", "api", "f" * 40)


# ── Контракт: ref в docs json == yaml == live ─────────────────────────

_DOCS = Path(__file__).resolve().parents[3] / "docs"


def _docs_specs() -> tuple[dict, dict]:
    with open(_DOCS / "cosmo-openapi.json", encoding="utf-8") as fh:
        spec_json = json.load(fh)
    with open(_DOCS / "cosmo-openapi.yaml", encoding="utf-8") as fh:
        spec_yaml = yaml.safe_load(fh)
    return spec_json, spec_yaml


class TestOpenApiRefContract:
    """Acceptance: OpenAPI содержит ref-параметр; json == yaml == live."""

    def test_ref_param_in_docs_json_and_yaml(self):
        spec_json, spec_yaml = _docs_specs()
        for label, spec in (("json", spec_json), ("yaml", spec_yaml)):
            for path in ("/api/v1/repos/tree", "/api/v1/repos/file"):
                params = {p["name"]: p for p in spec["paths"][path]["get"]["parameters"]}
                assert "ref" in params, f"{label}:{path}"
                assert params["ref"]["in"] == "query", label
                # ref-режим не требует CAS-пары — обе становятся optional
                assert params["branch"].get("required") in (False, None), label
                assert params["head_sha"].get("required") in (False, None), label

    def test_docs_json_equals_docs_yaml(self):
        spec_json, spec_yaml = _docs_specs()
        assert spec_json == spec_yaml

    def test_docs_equal_live_app_schema(self):
        """json == yaml == live: docs-артефакты == app.openapi()."""
        spec_json, _spec_yaml = _docs_specs()
        assert spec_json == app.openapi()


# ══════════════════════════════════════════════════════════════════════
# Live-smoke: сценарий «ветка уехала» (opt-in: COSMO_LIVE_GITEA=1)
# ══════════════════════════════════════════════════════════════════════

_LIVE = os.getenv("COSMO_LIVE_GITEA")
GITEA_URL = os.getenv("PK_GITEA_URL_LIVE", "http://localhost:3100").rstrip("/")
GITEA_USER = os.getenv("PK_GITEA_USER", "cosmo")
GITEA_PASSWORD = os.getenv("COSMO_FORGE_ADMIN_PASSWORD", "cosmo-admin-dev")
API_URL = os.getenv("PK_API_URL_LIVE", "http://localhost:8100").rstrip("/")
LIVE_ORG = "fc-live"


def _gitea(method: str, path: str, **kw):
    import requests
    return requests.request(method, f"{GITEA_URL}/api/v1{path}",
                            auth=(GITEA_USER, GITEA_PASSWORD), timeout=15, **kw)


def _live_login() -> str:
    """Боевой логин через issuer (COS-157/175).

    Dev-минтинг (`_jwt_testkey`) стенд не принимает: identity живёт ТОЛЬКО
    в крипто-верифицированных claims из OpenBao-JWKS.
    """
    import requests

    email = os.getenv("E2E_COSMO_EMAIL", "admin@cosmoport.local")
    password = os.getenv("COSMO_AUTH_ADMIN_PASSWORD", "cosmo-admin-dev")
    r = requests.post(f"{API_URL}/api/v1/auth/login",
                      json={"email": email, "password": password}, timeout=10)
    assert r.status_code == 200, f"live login failed: {r.status_code} {r.text}"
    return r.json()["access_token"]


def _commit_two_revisions(repo_full: str) -> tuple[str, str]:
    """Реальный git push: два коммита A→B (v1 → v2), ветка main = B."""
    import shutil
    import subprocess
    import tempfile

    work = Path(tempfile.mkdtemp(prefix="cos177-"))
    url = (f"http://{GITEA_USER}:{GITEA_PASSWORD}@"
           f"{GITEA_URL.split('//', 1)[1]}/{repo_full}.git")

    def git(*args: str):
        return subprocess.run(["git", "-C", str(work), *args],
                              check=True, capture_output=True, text=True)

    try:
        subprocess.run(["git", "init", str(work)], check=True, capture_output=True)
        git("checkout", "-b", "main")
        (work / "README.md").write_text("# v1\n", encoding="utf-8")
        (work / "src").mkdir()
        (work / "src" / "app.py").write_text("print('v1')\n", encoding="utf-8")
        ident = ["-c", "user.name=cosmo", "-c", "user.email=cosmo@local"]
        git(*ident, "add", "-A")
        git(*ident, "commit", "-m", "feat: v1 (COS-177)")
        old_sha = git("rev-parse", "HEAD").stdout.strip()

        (work / "README.md").write_text("# v2\n", encoding="utf-8")
        (work / "src" / "app.py").write_text("print('v2')\n", encoding="utf-8")
        (work / "src" / "new.py").write_text("# new\n", encoding="utf-8")
        git(*ident, "add", "-A")
        git(*ident, "commit", "-m", "feat: v2 (COS-177)")
        new_sha = git("rev-parse", "HEAD").stdout.strip()

        git("remote", "add", "origin", url)
        git("push", "-u", "origin", "main")
        return old_sha, new_sha
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _wait_commits_visible(repo_full: str, tries: int = 30) -> None:
    """Gitea 1.22 eventual consistency после push — поллим, не спим вслепую."""
    import time

    for _ in range(tries):
        r = _gitea("GET", f"/repos/{repo_full}/commits", params={"limit": 5})
        if r.status_code == 200 and r.json():
            return
        time.sleep(0.5)
    raise AssertionError(f"git push did not land in {tries * 0.5}s: {repo_full}")


@pytest.fixture(scope="class")
def live_ctx():
    import uuid

    import requests

    if not _LIVE:
        pytest.skip("COSMO_LIVE_GITEA not set — live ref smoke skipped")

    tag = "rr" + uuid.uuid4().hex[:8]
    repo_name = f"{tag}-repo"
    repo_full = f"{LIVE_ORG}/{repo_name}"
    domain_id = f"dom-{tag}"
    app_id = f"app-{tag}"

    r = _gitea("POST", "/orgs", json={"username": LIVE_ORG})
    assert r.status_code in (201, 422), r.text
    r = _gitea("POST", f"/orgs/{LIVE_ORG}/repos", json={
        "name": repo_name, "auto_init": False,
        "default_branch": "main", "private": False,
    })
    assert r.status_code == 201, f"repo create failed: {r.text}"

    old_sha, new_sha = _commit_two_revisions(repo_full)
    _wait_commits_visible(repo_full)

    auth = {"Authorization": f"Bearer {_live_login()}"}
    r = requests.post(f"{API_URL}/api/v1/domains", headers=auth, json={
        "id": domain_id, "label": f"COS-177 live {tag}",
        "forge_binding": {"forge_type": "gitea", "url": GITEA_URL,
                          "token_ref": "vault:secret/data/cos177-live"},
    }, timeout=10)
    assert r.status_code in (200, 201), r.text
    r = requests.post(f"{API_URL}/api/v1/apps", headers=auth, json={
        "id": app_id, "domain_id": domain_id, "level": 1,
        "repo_binding": {"forge_id": "gitea", "repo_path": repo_full},
    }, timeout=10)
    assert r.status_code in (200, 201), r.text

    yield {"base": API_URL, "auth": auth, "repo": repo_full,
           "old_sha": old_sha, "new_sha": new_sha}

    _gitea("DELETE", f"/repos/{LIVE_ORG}/{repo_name}")
    requests.delete(f"{API_URL}/api/v1/apps/{app_id}", headers=auth, timeout=10)
    requests.delete(f"{API_URL}/api/v1/domains/{domain_id}", headers=auth, timeout=10)


@pytest.mark.skipif(not _LIVE, reason="COSMO_LIVE_GITEA not set — live ref smoke skipped")
class TestLiveRefReadonly:
    """Живой стенд Gitea + ПУ: ветка уехала → ref читается, head_sha — 409."""

    def _get(self, live_ctx, path: str, params: dict):
        import requests

        r = requests.get(f"{live_ctx['base']}{path}", headers=live_ctx["auth"],
                         params=params, timeout=15)
        assert r.headers.get("content-type", "").startswith("application/json"), r.text
        return r

    def test_tree_ref_old_commit_after_branch_moved(self, live_ctx):
        r = self._get(live_ctx, "/api/v1/repos/tree",
                      {"repo": live_ctx["repo"], "ref": live_ctx["old_sha"]})
        assert r.status_code == 200, r.text
        paths = {e["path"] for e in r.json()["entries"]}
        assert "src/app.py" in paths
        assert "src/new.py" not in paths  # snapshot v1, не голова

    def test_tree_cas_stale_409_fresh_200(self, live_ctx):
        stale = self._get(live_ctx, "/api/v1/repos/tree", {
            "repo": live_ctx["repo"], "branch": "main",
            "head_sha": live_ctx["old_sha"]})
        assert stale.status_code == 409, stale.text
        fresh = self._get(live_ctx, "/api/v1/repos/tree", {
            "repo": live_ctx["repo"], "branch": "main",
            "head_sha": live_ctx["new_sha"]})
        assert fresh.status_code == 200, fresh.text
        assert "src/new.py" in {e["path"] for e in fresh.json()["entries"]}

    def test_tree_ref_prefix_resolves_live(self, live_ctx):
        r = self._get(live_ctx, "/api/v1/repos/tree",
                      {"repo": live_ctx["repo"], "ref": live_ctx["old_sha"][:10]})
        assert r.status_code == 200, r.text
        assert "src/new.py" not in {e["path"] for e in r.json()["entries"]}

    def test_file_ref_content_and_blob_differs_from_head(self, live_ctx):
        old = self._get(live_ctx, "/api/v1/repos/file", {
            "repo": live_ctx["repo"], "ref": live_ctx["old_sha"], "path": "README.md"})
        assert old.status_code == 200, old.text
        assert old.json()["content"] == "# v1\n"
        new = self._get(live_ctx, "/api/v1/repos/file", {
            "repo": live_ctx["repo"], "ref": live_ctx["new_sha"], "path": "README.md"})
        assert new.status_code == 200, new.text
        assert new.json()["content"] == "# v2\n"
        assert old.json()["sha"] != new.json()["sha"]

    def test_file_ref_wins_over_stale_head_sha(self, live_ctx):
        r = self._get(live_ctx, "/api/v1/repos/file", {
            "repo": live_ctx["repo"], "ref": live_ctx["old_sha"],
            "branch": "main", "head_sha": live_ctx["new_sha"], "path": "README.md"})
        assert r.status_code == 200, r.text
        assert r.json()["content"] == "# v1\n"

    def test_ref_nonexistent_404_not_5xx(self, live_ctx):
        r = self._get(live_ctx, "/api/v1/repos/tree",
                      {"repo": live_ctx["repo"], "ref": "f" * 40})
        assert r.status_code == 404, r.text

    def test_ref_malformed_400(self, live_ctx):
        r = self._get(live_ctx, "/api/v1/repos/tree",
                      {"repo": live_ctx["repo"], "ref": "not-a-sha"})
        assert r.status_code == 400, r.text
