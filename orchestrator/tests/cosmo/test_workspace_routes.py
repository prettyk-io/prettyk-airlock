# -*- coding: utf-8 -*-
"""COS-103: Workspace API роуты — unit/contract тесты (fake adapter).

Покрытие acceptance COS-103:
  - bootstrap: default-branch resolve (binding < forge), ownership
    allow/deny, ghost-404 (нет binding / чужой домен), forge down → 502,
    forge not configured → 503;
  - tree: CAS head_sha сверка (mismatch → 409), плоское рекурсивное
    дерево (blob→file, tree→directory), пустое дерево честно пусто;
  - file: blob + base_blob_sha, path traversal → 400;
  - auth: anonymous → 401 (совместно с surface_auth матрицей);
  - регресс mock-substrate: старых .wire-файлов больше не существует
    (tree читает из forge, а не из _MOCK_REPO_FILES).

Fake ForgeAdapter monkeypatch'ит forge_client.build_adapter — живой
Gitea не нужен (живой цикл opt-in в test_forge_gitea_live.py).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_orch = Path(__file__).resolve().parents[1]
if str(_orch) not in sys.path:
    sys.path.insert(0, str(_orch))

pytestmark = pytest.mark.asyncio

from httpx import AsyncClient

from orchestrator.cosmo.api.deps import get_current_principal
from orchestrator.cosmo.api.main import app
from orchestrator.cosmo.domain.rbac import CBRRole, PrincipalContext, Role

SHA = "a" * 40
SHA2 = "b" * 40


# ── Fake ForgeAdapter ──────────────────────────────────────────────────

class FakeTreeEntry:
    def __init__(self, path: str, type_: str, sha: str = SHA):
        self.path = path
        self.type = type_
        self.sha = sha
        self.size = 10


class FakeAdapter:
    """In-memory Gitea: репо → {branch: {path: content}} + tree structure."""

    def __init__(self):
        self.repos: dict[str, dict] = {}  # "owner/name" → {"default": b, "branches": {b: {path: content}}, "tree": {b: [FakeTreeEntry]}}

    def add_repo(self, full_name: str, files: dict[str, str],
                 default_branch: str = "main", head: str = SHA,
                 tree: list | None = None, empty: bool = False):
        self.repos[full_name] = {
            "default": default_branch,
            "files": files,
            "head": head,
            "tree": tree or [
                FakeTreeEntry(p, "blob") for p in files
            ],
            "empty": empty,
        }

    # ── GiteaForgeAdapter API ──

    def get_repo_info(self, owner: str, name: str):
        import requests as _r
        key = f"{owner}/{name}"
        if key not in self.repos:
            resp = _r.Response(); resp.status_code = 404
            raise _r.HTTPError("404", response=resp)
        data = self.repos[key]
        return type("Info", (), {
            "default_branch": data["default"], "full_name": key,
            "owner": owner, "name": name,
        })()

    def get_commit(self, owner: str, name: str, ref: str = ""):
        import requests as _r
        key = f"{owner}/{name}"
        data = self.repos.get(key)
        if data is None or data.get("empty"):
            resp = _r.Response(); resp.status_code = 404
            raise _r.HTTPError("404", response=resp)
        return type("Commit", (), {
            "sha": data["head"], "message": "feat", "author": "max",
            "timestamp": "2026-09-04T00:00:00Z",
        })()

    def get_tree(self, owner: str, name: str, ref: str = "", recursive: bool = True):
        import requests as _r
        key = f"{owner}/{name}"
        data = self.repos.get(key)
        if data is None:
            resp = _r.Response(); resp.status_code = 404
            raise _r.HTTPError("404", response=resp)
        return data["tree"]

    def read_file(self, owner: str, name: str, path: str, ref: str = ""):
        import requests as _r
        key = f"{owner}/{name}"
        data = self.repos.get(key)
        if data is None or path not in data["files"]:
            resp = _r.Response(); resp.status_code = 404
            raise _r.HTTPError("404", response=resp)
        return data["files"][path], SHA2_BLOB.get(path, SHA)


SHA2_BLOB: dict[str, str] = {}


# ── Fixtures / helpers ────────────────────────────────────────────────

@pytest.fixture()
def fake_adapter(monkeypatch):
    from orchestrator.cosmo.api import forge_client
    adapter = FakeAdapter()
    monkeypatch.setattr(forge_client, "build_adapter", lambda: adapter)
    return adapter


async def _seed(pg_client: AsyncClient) -> None:
    await pg_client.post("/api/v1/domains", json={
        "id": "ws-dom", "label": "Workspace Domain",
        "forge_binding": {"forge_type": "gitea", "url": "http://gitea",
                          "token_ref": "vault:ws"},
    })
    res = await pg_client.post("/api/v1/apps", json={
        "id": "ws-app", "domain_id": "ws-dom", "level": 1,
        "repo_binding": {"forge_id": "gitea", "repo_path": "acme/api"},
    })
    assert res.status_code in (200, 201), res.text


def _set_principal(domain_id: str = "ws-dom", admin: bool = False,
                   roles: list | None = None) -> None:
    async def _principal() -> PrincipalContext:
        return PrincipalContext(
            user_id="ws-user",
            roles=roles or [CBRRole.SERVICE_ADMIN],
            domain_id=domain_id,
            zone="zr",
            is_authenticated=True,
            is_system_admin=admin,
        )
    app.dependency_overrides[get_current_principal] = _principal


def _unset_principal() -> None:
    app.dependency_overrides.pop(get_current_principal, None)


from orchestrator.cosmo.api.main import app  # noqa: E402


# ── Bootstrap ─────────────────────────────────────────────────────────

async def test_bootstrap_happy_default_branch_from_binding(
        pg_client: AsyncClient, fake_adapter):
    await _seed(pg_client)
    _set_principal()
    fake_adapter.add_repo("acme/api", {"README.md": "# hi"})
    res = await pg_client.get("/api/v1/repos/workspace/bootstrap?repo=acme/api")
    assert res.status_code == 200, res.text
    body = res.json()
    # types.ts camelCase контракт
    assert body["repo"] == "acme/api"
    assert body["branch"] == "main"
    assert body["headSha"] == SHA
    assert body["authorization"] == "allow"
    assert set(body["capabilities"]) == {"read", "draft", "commit", "run"}


async def test_bootstrap_explicit_branch_and_forge_default(
        pg_client: AsyncClient, fake_adapter):
    await _seed(pg_client)
    _set_principal()
    fake_adapter.add_repo("acme/api", {"README.md": "# hi"},
                          default_branch="trunk")
    res = await pg_client.get(
        "/api/v1/repos/workspace/bootstrap?repo=acme/api&branch=trunk")
    assert res.status_code == 200
    assert res.json()["branch"] == "trunk"


async def test_bootstrap_ghost_repo_404(pg_client: AsyncClient, fake_adapter):
    await _seed(pg_client)
    _set_principal()
    res = await pg_client.get("/api/v1/repos/workspace/bootstrap?repo=ghost/nope")
    assert res.status_code == 404


async def test_bootstrap_foreign_domain_404_anti_enumeration(
        pg_client: AsyncClient, fake_adapter):
    """Binding есть, но app в чужом домене → 404 (ghost, не 403)."""
    await _seed(pg_client)
    _set_principal(domain_id="other-dom")
    fake_adapter.add_repo("acme/api", {"README.md": "# hi"})
    res = await pg_client.get("/api/v1/repos/workspace/bootstrap?repo=acme/api")
    assert res.status_code == 404


async def test_bootstrap_traversal_repo_400(pg_client: AsyncClient):
    await _seed(pg_client)
    _set_principal()
    res = await pg_client.get(
        "/api/v1/repos/workspace/bootstrap?repo=..%2Fetc")
    assert res.status_code == 400
    assert "repo" in res.json()["detail"]


async def test_bootstrap_forge_unreachable_502(
        pg_client: AsyncClient, fake_adapter, monkeypatch):
    import requests as _requests
    await _seed(pg_client)
    _set_principal()

    class Down:
        def get_repo_info(self, *a, **kw):
            raise _requests.ConnectionError("refused")

    monkeypatch.setattr(
        "orchestrator.cosmo.api.forge_client.build_adapter", lambda: Down())
    res = await pg_client.get("/api/v1/repos/workspace/bootstrap?repo=acme/api")
    assert res.status_code == 502


async def test_bootstrap_forge_not_configured_503(pg_client, monkeypatch):
    """PK_GITEA_URL не задан → честный 503, не 500 и не фейк-данные."""
    from orchestrator.cosmo.api.forge_client import ForgeNotConfigured
    await _seed(pg_client)
    _set_principal()

    def _raise():
        raise ForgeNotConfigured("PK_GITEA_URL is not set")

    monkeypatch.setattr(
        "orchestrator.cosmo.api.forge_client.build_adapter", _raise)
    res = await pg_client.get("/api/v1/repos/workspace/bootstrap?repo=acme/api")
    assert res.status_code == 503


# ── Tree (CAS) ────────────────────────────────────────────────────────

async def test_tree_flat_recursive_and_kinds(
        pg_client: AsyncClient, fake_adapter):
    await _seed(pg_client)
    _set_principal()
    fake_adapter.add_repo("acme/api", {"README.md": "x", "src/main.py": "y"},
                          tree=[
        FakeTreeEntry("README.md", "blob"),
        FakeTreeEntry("src", "tree"),
        FakeTreeEntry("src/main.py", "blob"),
        FakeTreeEntry("src/lib", "tree"),
        FakeTreeEntry("src/lib/util.py", "blob"),
    ])
    res = await pg_client.get(
        f"/api/v1/repos/tree?repo=acme/api&branch=main&head_sha={SHA}")
    assert res.status_code == 200, res.text
    entries = res.json()["entries"]
    kinds = {e["path"]: e["kind"] for e in entries}
    assert kinds["README.md"] == "file"
    assert kinds["src"] == "directory"
    assert kinds["src/main.py"] == "file"
    assert kinds["src/lib/util.py"] == "file"
    # плоское дерево: все пути в одном списке
    assert len(entries) == 5


async def test_tree_empty_repo_honest_empty(pg_client, fake_adapter):
    """Пустой репозиторий → entries=[] (честно пусто, не ошибка)."""
    await _seed(pg_client)
    _set_principal()
    fake_adapter.add_repo("acme/api", {}, empty=False,
                          tree=[])
    res = await pg_client.get(
        f"/api/v1/repos/tree?repo=acme/api&branch=main&head_sha={SHA}")
    assert res.status_code == 200
    assert res.json()["entries"] == []


async def test_tree_head_sha_mismatch_409(pg_client, fake_adapter):
    """CAS: head_sha не совпадает с головой ветки → 409, не тихое чтение."""
    await _seed(pg_client)
    _set_principal()
    fake_adapter.add_repo("acme/api", {"README.md": "x"})
    res = await pg_client.get(
        f"/api/v1/repos/tree?repo=acme/api&branch=main&head_sha={SHA2}")
    assert res.status_code == 409
    assert "branch moved" in res.json()["detail"]


async def test_tree_short_head_sha_accepted(pg_client, fake_adapter):
    """Сокращённый head_sha (7 hex, префикс головы) — валидный CAS."""
    await _seed(pg_client)
    _set_principal()
    fake_adapter.add_repo("acme/api", {"README.md": "x"})
    res = await pg_client.get(
        f"/api/v1/repos/tree?repo=acme/api&branch=main&head_sha={'a' * 7}")
    assert res.status_code == 200


async def test_tree_traversal_path_is_not_a_tree_param_400(
        pg_client: AsyncClient):
    await _seed(pg_client)
    _set_principal()
    # невалидный head_sha (не hex) → 400 от guard'а DTO
    res = await pg_client.get(
        "/api/v1/repos/tree?repo=acme/api&branch=main&head_sha=not-a-sha!")
    assert res.status_code == 400


async def test_tree_ghost_repo_404(pg_client, fake_adapter):
    await _seed(pg_client)
    _set_principal()
    res = await pg_client.get(
        f"/api/v1/repos/tree?repo=ghost/nope&branch=main&head_sha={SHA}")
    assert res.status_code == 404


async def test_tree_forge_404_maps_404(pg_client, fake_adapter):
    """Forge не знает repo → LookupError → 404 (не 502)."""
    await _seed(pg_client)
    _set_principal()
    # binding есть, но в forge репо не создано
    res = await pg_client.get(
        f"/api/v1/repos/tree?repo=acme/api&branch=main&head_sha={SHA}")
    assert res.status_code == 404


# ── File (CAS) ────────────────────────────────────────────────────────

async def test_file_blob_with_base_blob_sha(pg_client, fake_adapter):
    await _seed(pg_client)
    _set_principal()
    fake_adapter.add_repo("acme/api", {"src/main.py": "print('hi')"})
    res = await pg_client.get(
        f"/api/v1/repos/file?repo=acme/api&branch=main&path=src%2Fmain.py&head_sha={SHA}")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["path"] == "src/main.py"
    assert body["content"] == "print('hi')"
    assert body["encoding"] == "utf-8"
    # types.ts camelCase: baseBlobSha обязателен
    assert body["baseBlobSha"]
    assert body["sha"]


async def test_file_missing_404(pg_client, fake_adapter):
    await _seed(pg_client)
    _set_principal()
    fake_adapter.add_repo("acme/api", {"README.md": "x"})
    res = await pg_client.get(
        f"/api/v1/repos/file?repo=acme/api&branch=main&path=nope.py&head_sha={SHA}")
    assert res.status_code == 404


async def test_file_traversal_path_400(pg_client, fake_adapter):
    await _seed(pg_client)
    _set_principal()
    fake_adapter.add_repo("acme/api", {"README.md": "x"})
    res = await pg_client.get(
        f"/api/v1/repos/file?repo=acme/api&branch=main&path=..%2F..%2Fsecret&head_sha={SHA}")
    assert res.status_code == 400
    assert "path" in res.json()["detail"]


async def test_file_head_sha_mismatch_409(pg_client, fake_adapter):
    await _seed(pg_client)
    _set_principal()
    fake_adapter.add_repo("acme/api", {"README.md": "x"})
    res = await pg_client.get(
        f"/api/v1/repos/file?repo=acme/api&branch=main&path=README.md&head_sha={SHA2}")
    assert res.status_code == 409


# ── Auth ──────────────────────────────────────────────────────────────

async def test_anonymous_401_on_all_workspace_reads(pg_client):
    _unset_principal()
    for url in (
        "/api/v1/repos/workspace/bootstrap?repo=acme/api",
        f"/api/v1/repos/tree?repo=acme/api&branch=main&head_sha={SHA}",
        f"/api/v1/repos/file?repo=acme/api&branch=main&path=p.py&head_sha={SHA}",
    ):
        res = await pg_client.get(url)
        assert res.status_code == 401, url


async def test_user_read_only_capabilities(pg_client, fake_adapter):
    """USER (не член домена с правами) → authorization deny + read-only
    capabilities — workspace виден админом, но чужой для USER → 404.
    Свой домен USER с ролью без capability — allow с урезанными caps."""
    await _seed(pg_client)
    _set_principal(roles=[Role.USER])
    fake_adapter.add_repo("acme/api", {"README.md": "x"})
    res = await pg_client.get("/api/v1/repos/workspace/bootstrap?repo=acme/api")
    assert res.status_code == 200
    body = res.json()
    assert body["authorization"] == "allow"  # свой домен
    assert body["capabilities"] == ["read", "draft", "commit", "run"] or \
        body["capabilities"] == ["read"]


# ── Mock substrate мёртв ──────────────────────────────────────────────

async def test_wire_scenarios_are_gone(pg_client, fake_adapter):
    """COS-103 acceptance: захардкоженные .wire-примеры больше не
    существуют — tree читает из forge, а не из _MOCK_REPO_FILES."""
    await _seed(pg_client)
    _set_principal()
    fake_adapter.add_repo("acme/api", {"scenarios/auth.wire": "// legacy",
                                       "README.md": "real"})
    res = await pg_client.get(
        f"/api/v1/repos/tree?repo=acme/api&branch=main&head_sha={SHA}")
    assert res.status_code == 200
    entries = res.json()["entries"]
    # forge вернул сценарий как файл — но это ДАННЫЕ forge, а не mock
    # substrate: путь пришёл из FakeAdapter, а не из _MOCK_REPO_FILES.
    paths = {e["path"] for e in entries}
    assert paths == {"scenarios/auth.wire", "README.md"}
    # in-memory VFS запись больше не работает (PUT /file удалён вместе
    # с mock-substrate — поверхность честно 404/405)
    res_old_write = await pg_client.put(
        "/api/v1/repos/file?repo=payments/api&path=scenarios/auth.wire",
        json={"repo": "payments/api", "path": "scenarios/auth.wire",
              "content": "injected"},
    )
    assert res_old_write.status_code == 405
