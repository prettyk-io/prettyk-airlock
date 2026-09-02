# -*- coding: utf-8 -*-
"""COS-096: Live Gitea forge cycle — offline tests.

Webhook-приёмник (HMAC), last-push ПУ-поверхность, compile-from-source
(живой source → bricks → compile), честный маппинг ошибок forge.

Всё работает БЕЗ живого Gitea: адаптер monkeypatch'ится фейком,
webhook-подпись считается честным HMAC. Живой цикл — opt-in в
test_forge_gitea_live.py (COSMO_LIVE_GITEA=1).
"""
from __future__ import annotations

import hashlib
import hmac as hmac_mod
import sys
from pathlib import Path

import pytest
from httpx import AsyncClient

_orch = Path(__file__).resolve().parents[1]
if str(_orch) not in sys.path:
    sys.path.insert(0, str(_orch))

WEBHOOK_SECRET = "dev-webhook-secret-change-me"

PIPELINE_YAML = """\
pipeline:
  name: fc-app pipeline
  stages:
    - name: build
      brick: fc-build
    - name: sast
      brick: fc-sast
"""


def _sig(payload: bytes, secret: str = WEBHOOK_SECRET) -> str:
    return hmac_mod.new(secret.encode(), payload, hashlib.sha256).hexdigest()


def _push_payload(repo: str = "fc-dom/fc-app", branch: str = "main") -> bytes:
    import json
    return json.dumps({
        "ref": f"refs/heads/{branch}",
        "after": "deadbeef" * 5,
        "pusher": {"login": "max"},
        "repository": {"full_name": repo},
        "commits": [{"id": "c1", "message": "commit pipeline"}],
    }).encode()


@pytest.fixture(autouse=True)
def _reset_forge_state():
    from orchestrator.cosmo.api import forge_events
    forge_events.reset()
    yield
    forge_events.reset()


@pytest.fixture()
def fake_adapter(monkeypatch):
    from orchestrator.cosmo.api import forge_client

    holder = {"adapter": None}

    def _factory():
        return holder["adapter"]

    monkeypatch.setattr(forge_client, "build_adapter", _factory)
    return holder


class FakeCommit:
    def __init__(self, sha: str, message: str):
        self.sha = sha
        self.message = message
        self.author = "max"
        self.timestamp = "2026-09-03T12:00:00Z"


class FakeAdapter:
    """Подменяет GiteaForgeAdapter в forge_client.build_adapter."""

    def __init__(self, file_content: str = PIPELINE_YAML,
                 commits: list | None = None, raise_on_read: Exception | None = None):
        self.file_content = file_content
        self.commits = commits or [FakeCommit("a" * 40, "feat: last")]
        self.raise_on_read = raise_on_read
        self.ensure_calls: list[tuple] = []

    def read_file(self, owner: str, repo: str, path: str, ref: str = ""):
        if self.raise_on_read is not None:
            raise self.raise_on_read
        return self.file_content, "abc123sha"

    def list_commits(self, owner: str, repo: str, ref: str = "", limit: int = 10):
        return self.commits[:limit]

    def ensure_webhook(self, owner: str, repo: str, webhook_url: str, secret: str):
        self.ensure_calls.append((owner, repo, webhook_url, secret))
        return 777, True


# ── Webhook endpoint ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_webhook_missing_signature_rejected_401(pg_client: AsyncClient):
    res = await pg_client.post("/api/v1/webhooks/gitea", content=_push_payload())
    assert res.status_code == 401
    assert "signature" in res.json()["detail"]


@pytest.mark.asyncio
async def test_webhook_bad_signature_rejected_401(pg_client: AsyncClient):
    res = await pg_client.post(
        "/api/v1/webhooks/gitea",
        content=_push_payload(),
        headers={"X-Gitea-Signature": "0" * 64, "X-Gitea-Event": "push"},
    )
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_webhook_valid_signature_unbound_repo_honest(pg_client: AsyncClient):
    """Push репо без привязки — НЕ тихо: 200 + bound=false + audit."""
    res = await pg_client.post(
        "/api/v1/webhooks/gitea",
        content=_push_payload(repo="nobody/stray"),
        headers={"X-Gitea-Signature": _sig(_push_payload(repo="nobody/stray")),
                 "X-Gitea-Event": "push"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["handled"] is True
    assert body["bound"] is False

    # и это видно в audit (system surface)
    res_audit = await pg_client.get(
        "/api/v1/audit?action=webhook_unbound_push&limit=5")
    assert res_audit.status_code == 200
    events = res_audit.json()
    assert any(e["resource_id"] == "nobody/stray" for e in events)


@pytest.mark.asyncio
async def test_webhook_bound_push_cached(pg_client: AsyncClient):
    """Привязанное репо: push → кэш last-push + audit commit_push."""
    await _seed_forge_app(pg_client)
    payload = _push_payload(repo="fc-org/fc-repo", branch="main")
    res = await pg_client.post(
        "/api/v1/webhooks/gitea",
        content=payload,
        headers={"X-Gitea-Signature": _sig(payload), "X-Gitea-Event": "push"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["bound"] is True
    assert body["branch"] == "main"

    from orchestrator.cosmo.api import forge_events
    cached = forge_events.last_push("fc-org/fc-repo")
    assert cached is not None
    assert cached["pusher"] == "max"
    assert cached["head_sha"].startswith("deadbeef")

    res_audit = await pg_client.get(
        "/api/v1/audit?action=commit_push&resource_type=repo&limit=10")
    assert any(
        e["resource_id"] == "fc-org/fc-repo" and e["user_id"] == "forge:gitea:max"
        for e in res_audit.json()
    )


@pytest.mark.asyncio
async def test_webhook_non_push_event_ignored(pg_client: AsyncClient):
    payload = b'{"zen": "Keep it logically awesome."}'
    res = await pg_client.post(
        "/api/v1/webhooks/gitea",
        content=payload,
        headers={"X-Gitea-Signature": _sig(payload), "X-Gitea-Event": "ping"},
    )
    assert res.status_code == 200
    assert res.json()["handled"] is False


@pytest.mark.asyncio
async def test_webhook_bad_json_with_valid_signature_400(pg_client: AsyncClient):
    payload = b"this is not json"
    res = await pg_client.post(
        "/api/v1/webhooks/gitea",
        content=payload,
        headers={"X-Gitea-Signature": _sig(payload), "X-Gitea-Event": "push"},
    )
    assert res.status_code == 400


# ── Last-push ПУ surface ───────────────────────────────────────────────

async def _seed_forge_app(pg_client: AsyncClient):
    await pg_client.post("/api/v1/domains", json={
        "id": "fc-dom", "label": "Forge Cycle Domain",
        "forge_binding": {"forge_type": "gitea", "url": "http://gitea",
                          "token_ref": "vault:secret/data/token"},
    })
    res = await pg_client.post("/api/v1/apps", json={
        "id": "fc-app", "domain_id": "fc-dom", "level": 1,
        "repo_binding": {"forge_id": "gitea", "repo_path": "fc-org/fc-repo"},
    })
    assert res.status_code in (200, 201), res.text


@pytest.mark.asyncio
async def test_last_push_unknown_app_404(pg_client: AsyncClient):
    res = await pg_client.get("/api/v1/apps/no-such-app/forge/last-push")
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_last_push_no_binding_404(pg_client: AsyncClient):
    await _seed_forge_app(pg_client)
    # App создан с обязательным repo_binding — снимаем привязку напрямую
    # в БД, чтобы получить честное приложение без forge-привязки.
    from sqlalchemy import delete as _delete
    from sqlalchemy.ext.asyncio import create_async_engine
    import _testpg
    from orchestrator.cosmo.db.models import RepositoryBinding as RepoBindingModel

    engine = create_async_engine(_testpg.TEST_PG_URL, echo=False)
    try:
        async with engine.begin() as conn:
            await conn.execute(
                _delete(RepoBindingModel).where(RepoBindingModel.app_id == "fc-app"))
    finally:
        await engine.dispose()

    res = await pg_client.get("/api/v1/apps/fc-app/forge/last-push")
    assert res.status_code == 404
    assert "no repo binding" in res.json()["detail"]


@pytest.mark.asyncio
async def test_last_push_empty_is_honest(pg_client: AsyncClient, fake_adapter):
    """Без пушей last_push=None; forge_unreachable честно назван, не скрыт."""
    fake_adapter["adapter"] = FakeAdapter()
    await _seed_forge_app(pg_client)
    res = await pg_client.get("/api/v1/apps/fc-app/forge/last-push")
    assert res.status_code == 200
    body = res.json()
    assert body["last_push"] is None
    assert body["recent_commits"], "fake adapter должен отдать живые коммиты"
    assert body["forge_unreachable"] is None


@pytest.mark.asyncio
async def test_last_push_webhook_cache_visible(pg_client: AsyncClient, fake_adapter):
    fake_adapter["adapter"] = FakeAdapter()
    await _seed_forge_app(pg_client)
    payload = _push_payload(repo="fc-org/fc-repo", branch="feat/x")
    await pg_client.post(
        "/api/v1/webhooks/gitea",
        content=payload,
        headers={"X-Gitea-Signature": _sig(payload), "X-Gitea-Event": "push"},
    )
    res = await pg_client.get("/api/v1/apps/fc-app/forge/last-push")
    assert res.status_code == 200
    body = res.json()
    assert body["last_push"]["branch"] == "feat/x"
    assert body["last_push"]["source"] == "webhook_cache"


@pytest.mark.asyncio
async def test_last_push_forge_down_honest_degradation(pg_client: AsyncClient,
                                                       fake_adapter):
    """Gitea недоступен → recent_commits=[] + причина, а не 500 и не фейк."""
    import requests as _requests

    class DownAdapter:
        def list_commits(self, *a, **kw):
            raise _requests.ConnectionError("connection refused (simulated)")

    fake_adapter["adapter"] = DownAdapter()
    await _seed_forge_app(pg_client)
    res = await pg_client.get("/api/v1/apps/fc-app/forge/last-push")
    assert res.status_code == 200
    body = res.json()
    assert body["recent_commits"] == []
    assert body["forge_unreachable"] and "unreachable" in body["forge_unreachable"]
    assert body["last_push"] is None


# ── Webhook setup (идемпотентный, через fake adapter) ──────────────────

@pytest.mark.asyncio
async def test_webhook_setup_idempotent(pg_client: AsyncClient, fake_adapter):
    adapter = FakeAdapter()
    fake_adapter["adapter"] = adapter
    await _seed_forge_app(pg_client)
    res = await pg_client.post("/api/v1/apps/fc-app/forge/webhook-setup")
    assert res.status_code == 200
    body = res.json()
    assert body["webhook_id"] == 777
    assert body["created"] is True
    assert len(adapter.ensure_calls) == 1
    owner, repo, url, secret = adapter.ensure_calls[0]
    assert (owner, repo) == ("fc-org", "fc-repo")
    assert url.endswith("/api/v1/webhooks/gitea")
    assert secret  # секрет передан, не пустышка


# ── Compile-from-source ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_compile_from_source_happy(pg_client: AsyncClient, fake_adapter):
    fake_adapter["adapter"] = FakeAdapter()
    await _seed_forge_app(pg_client)
    for brick in [
        {"id": "fc-build", "name": "FC Build", "type": "build", "source": "internal",
         "definition": {"image": "golang:1.22", "timeout_s": 600}},
        {"id": "fc-sast", "name": "FC SAST", "type": "sast", "source": "internal",
         "definition": {"image": "sonarqube:scanner", "timeout_s": 1200},
         "depends_on": ["fc-build"]},
    ]:
        assert (await pg_client.post("/api/v1/bricks", json=brick)).status_code == 201

    res = await pg_client.post("/api/v1/plans/compile-from-source", json={
        "plan_id": "plan-fc-1", "app_id": "fc-app",
    }, headers={"X-Cosmo-Domain": "fc-dom"})
    assert res.status_code == 201, res.text
    plan = res.json()
    assert plan["brick_ids"] == ["fc-build", "fc-sast"]
    assert plan["compiled_hash"]


@pytest.mark.asyncio
async def test_compile_from_source_unknown_brick_404(pg_client: AsyncClient,
                                                     fake_adapter):
    yaml = PIPELINE_YAML.replace("fc-sast", "ghost-brick")
    fake_adapter["adapter"] = FakeAdapter(file_content=yaml)
    await _seed_forge_app(pg_client)
    for brick in [
        {"id": "fc-build", "name": "FC Build", "type": "build", "source": "internal",
         "definition": {"image": "golang:1.22"}},
    ]:
        await pg_client.post("/api/v1/bricks", json=brick)

    res = await pg_client.post("/api/v1/plans/compile-from-source", json={
        "plan_id": "plan-fc-404", "app_id": "fc-app",
    }, headers={"X-Cosmo-Domain": "fc-dom"})
    assert res.status_code == 404
    assert "ghost-brick" in res.json()["detail"]


@pytest.mark.asyncio
async def test_compile_from_source_no_stages_400(pg_client: AsyncClient,
                                                 fake_adapter):
    fake_adapter["adapter"] = FakeAdapter(file_content="pipeline:\n  stages: []\n")
    await _seed_forge_app(pg_client)
    res = await pg_client.post("/api/v1/plans/compile-from-source", json={
        "plan_id": "plan-fc-empty", "app_id": "fc-app",
    }, headers={"X-Cosmo-Domain": "fc-dom"})
    assert res.status_code == 400
    assert "nothing to compile" in res.json()["detail"]


@pytest.mark.asyncio
async def test_compile_from_source_file_missing_404(pg_client: AsyncClient,
                                                    fake_adapter):
    fake_adapter["adapter"] = FakeAdapter(
        raise_on_read=LookupError("File '.cosmo/pipeline.yaml' not found in fc-org/fc-repo"))
    await _seed_forge_app(pg_client)
    res = await pg_client.post("/api/v1/plans/compile-from-source", json={
        "plan_id": "plan-fc-nofile", "app_id": "fc-app",
    }, headers={"X-Cosmo-Domain": "fc-dom"})
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_compile_from_source_forge_down_502(pg_client: AsyncClient,
                                                  fake_adapter):
    import requests as _requests

    class DownAdapter:
        def read_file(self, *a, **kw):
            raise _requests.ConnectionError("connection refused (simulated)")

    fake_adapter["adapter"] = DownAdapter()
    await _seed_forge_app(pg_client)
    res = await pg_client.post("/api/v1/plans/compile-from-source", json={
        "plan_id": "plan-fc-down", "app_id": "fc-app",
    }, headers={"X-Cosmo-Domain": "fc-dom"})
    assert res.status_code == 502
    assert "unreachable" in res.json()["detail"]


@pytest.mark.asyncio
async def test_compile_from_source_no_binding_404(pg_client: AsyncClient):
    await _seed_forge_app(pg_client)
    from sqlalchemy import delete as _delete
    from sqlalchemy.ext.asyncio import create_async_engine
    import _testpg
    from orchestrator.cosmo.db.models import RepositoryBinding as RepoBindingModel

    engine = create_async_engine(_testpg.TEST_PG_URL, echo=False)
    try:
        async with engine.begin() as conn:
            await conn.execute(
                _delete(RepoBindingModel).where(RepoBindingModel.app_id == "fc-app"))
    finally:
        await engine.dispose()

    res = await pg_client.post("/api/v1/plans/compile-from-source", json={
        "plan_id": "plan-fc-nobind", "app_id": "fc-app",
    }, headers={"X-Cosmo-Domain": "fc-dom"})
    assert res.status_code == 404
    assert "no repo binding" in res.json()["detail"]


@pytest.mark.asyncio
async def test_compile_from_source_duplicate_plan_409(pg_client: AsyncClient,
                                                      fake_adapter):
    fake_adapter["adapter"] = FakeAdapter()
    await _seed_forge_app(pg_client)
    for brick in [
        {"id": "fc-build", "name": "FC Build", "type": "build", "source": "internal",
         "definition": {"image": "golang:1.22"}},
        {"id": "fc-sast", "name": "FC SAST", "type": "sast", "source": "internal",
         "definition": {"image": "sonarqube:scanner"}, "depends_on": ["fc-build"]},
    ]:
        await pg_client.post("/api/v1/bricks", json=brick)

    body = {"plan_id": "plan-fc-dup", "app_id": "fc-app"}
    hdr = {"X-Cosmo-Domain": "fc-dom"}
    r1 = await pg_client.post("/api/v1/plans/compile-from-source", json=body, headers=hdr)
    assert r1.status_code == 201
    r2 = await pg_client.post("/api/v1/plans/compile-from-source", json=body, headers=hdr)
    assert r2.status_code == 409


# ── forge_http_error mapping (unit) ────────────────────────────────────

class TestForgeHttpErrorMapping:
    def _map(self, exc, what="thing"):
        from orchestrator.cosmo.api.forge_client import forge_http_error
        return forge_http_error(exc, what)

    def test_not_configured_503(self):
        from orchestrator.cosmo.api.forge_client import ForgeNotConfigured
        err = self._map(ForgeNotConfigured("PK_GITEA_URL is not set"))
        assert err.status_code == 503
        assert "not configured" in err.detail

    def test_auth_rejected_502_no_secret_leak(self):
        import requests as _requests
        resp = _requests.Response()
        resp.status_code = 401
        exc = _requests.HTTPError("401", response=resp)
        err = self._map(exc, "commits for org/repo")
        assert err.status_code == 502
        assert "rejected credentials" in err.detail

    def test_forge_404_maps_404(self):
        import requests as _requests
        resp = _requests.Response()
        resp.status_code = 404
        exc = _requests.HTTPError("404", response=resp)
        err = self._map(exc, ".cosmo/pipeline.yaml in org/repo")
        assert err.status_code == 404
        assert "Not found in forge" in err.detail

    def test_forge_500_maps_502(self):
        import requests as _requests
        resp = _requests.Response()
        resp.status_code = 500
        exc = _requests.HTTPError("500", response=resp)
        err = self._map(exc)
        assert err.status_code == 502

    def test_connection_error_502(self):
        import requests as _requests
        err = self._map(_requests.ConnectionError("refused"))
        assert err.status_code == 502
        assert "unreachable" in err.detail

    def test_timeout_502(self):
        import requests as _requests
        err = self._map(_requests.Timeout("timed out"))
        assert err.status_code == 502

    def test_lookup_error_404(self):
        err = self._map(LookupError("File not found"))
        assert err.status_code == 404
