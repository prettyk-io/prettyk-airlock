# -*- coding: utf-8 -*-
"""COS-096: Live Gitea forge cycle — opt-in E2E.

Запуск:  $env:COSMO_LIVE_GITEA = "1"; pytest .../test_forge_gitea_live.py -v
Без флага — весь модуль skip (паттерн test_int_registry_smoke).

Что проверяет против ЖИВОГО Gitea (localhost:3100) и живого ПУ (8100):
  1. Адаптер с basic auth: create repo → read_file → list_commits.
  2. ensure_webhook идемпотентен (×2 → один hook, created=False).
  3. Полный цикл: binding в ПУ → webhook-setup (из контейнера) → Gitea
     test-delivery → last-push в ПУ показывает пуш (HMAC подписан Gitea).
  4. compile-from-source от живого дерева (.cosmo/pipeline.yaml).

Auth: opaque bearer закрыт COS-085; live-контур минтит подписанный RS256
(COS-160, через `_jwt_testkey.mint_rs256`) — ПУ требует крипто-верификацию.
"""
from __future__ import annotations

import os
import sys
import time
import uuid
from pathlib import Path

import pytest

_orch = Path(__file__).resolve().parents[1]
if str(_orch) not in sys.path:
    sys.path.insert(0, str(_orch))

if not os.getenv("COSMO_LIVE_GITEA"):
    pytest.skip("COSMO_LIVE_GITEA not set — live forge cycle skipped",
                allow_module_level=True)

import requests

GITEA_URL = os.getenv("PK_GITEA_URL_LIVE", "http://localhost:3100").rstrip("/")
GITEA_USER = os.getenv("PK_GITEA_USER", "cosmo")
GITEA_PASSWORD = os.getenv("COSMO_FORGE_ADMIN_PASSWORD", "cosmo-admin-dev")
API_URL = os.getenv("PK_API_URL_LIVE", "http://localhost:8100").rstrip("/")

RUN_TAG = "fc" + uuid.uuid4().hex[:8]
ORG = "fc-live"
REPO = f"{RUN_TAG}-repo"
APP_ID = f"app-{RUN_TAG}"
DOMAIN_ID = f"dom-{RUN_TAG}"
PLAN_ID = f"plan-{RUN_TAG}"

PIPELINE_YAML = """\
pipeline:
  name: live-fc pipeline
  stages:
    - name: build
      brick: go_builder
    - name: sast
      brick: sonarqube_scanner
"""


def _gitea(method: str, path: str, **kw):
    return requests.request(method, f"{GITEA_URL}/api/v1{path}",
                            auth=(GITEA_USER, GITEA_PASSWORD), timeout=15, **kw)


def _mint_jwt(sub: str = "gate-agent", roles: list | None = None) -> str:
    """Подписанный RS256 JWT (COS-160): live ПУ требует крипто-верификацию."""
    from _jwt_testkey import mint_rs256

    roles = roles or ["admin_sec"]
    return mint_rs256({"sub": sub, "roles": roles, "is_admin": True})


@pytest.fixture(scope="module")
def jwt() -> str:
    return _mint_jwt()


@pytest.fixture(scope="module")
def live_api(jwt: str):
    """Живой ПУ должен быть поднят и с новой сборкой (COS-096 endpoints)."""
    try:
        r = requests.get(f"{API_URL}/live", timeout=5)
        assert r.status_code == 200
    except requests.ConnectionError:
        pytest.skip("live cosmo-api not reachable on :8100")
    r = requests.get(f"{API_URL}/openapi.json", timeout=10)
    paths = r.json().get("paths", {})
    if "/api/v1/webhooks/gitea" not in paths:
        pytest.skip("live cosmo-api image is stale (no COS-096 endpoints) — rebuild it")
    return {"base": API_URL, "auth": jwt}


def _commit_via_git(repo_full: str, files: dict[str, str], message: str) -> None:
    """Реальный git push против живого Gitea.

    Contents API этой сборки Gitea (1.22.6) требует sha даже на создание
    файла и не умеет nested-пути — git push честнее и ближе к прод-циклу.
    """
    import subprocess
    import tempfile

    work = Path(tempfile.mkdtemp(prefix=f"fc-{RUN_TAG}-"))
    url = f"http://{GITEA_USER}:{GITEA_PASSWORD}@{GITEA_URL.split('//', 1)[1]}/{repo_full}.git"
    git = lambda *args, **kw: subprocess.run(  # noqa: E731
        ["git", "-C", str(work), *args], check=True, capture_output=True, **kw)
    try:
        subprocess.run(["git", "init", str(work)], check=True, capture_output=True)
        git("checkout", "-b", "main")
        for rel, content in files.items():
            p = work / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
        git("-c", "user.name=cosmo", "-c", "user.email=cosmo@local",
            "add", "-A")
        git("-c", "user.name=cosmo", "-c", "user.email=cosmo@local",
            "commit", "-m", message)
        git("remote", "add", "origin", url)
        git("push", "-u", "origin", "main")
    finally:
        import shutil
        shutil.rmtree(work, ignore_errors=True)


@pytest.fixture(scope="module")
def gitea_repo():
    """Создаёт org+repo; коммитит живое дерево git push'ем; чистит после."""
    r = _gitea("POST", "/orgs", json={"username": ORG})
    assert r.status_code in (201, 422), r.text  # 422 = уже существует

    r = _gitea("POST", f"/orgs/{ORG}/repos", json={
        "name": REPO, "auto_init": False, "default_branch": "main",
        "private": False,
    })
    assert r.status_code == 201, f"repo create failed: {r.text}"

    repo_full = f"{ORG}/{REPO}"
    _commit_via_git(
        repo_full,
        {".cosmo/pipeline.yaml": PIPELINE_YAML},
        "feat: live pipeline declaration (COS-096)",
    )

    # Гард: push обязан был дойти ДО yield. Gitea 1.22 отдаёт пустой репо
    # (409 на commits / 200+[] на contents) ещё пару секунд после push —
    # eventual consistency, поллим честно, не спим вслепую.
    deadline = time.time() + 15
    commits = None
    while time.time() < deadline:
        commits = _gitea("GET", f"/repos/{ORG}/{REPO}/commits")
        if commits.status_code == 200 and commits.json():
            break
        time.sleep(0.5)
    assert commits is not None and commits.status_code == 200 and commits.json(), (
        f"git push did not land in 15s: repo {repo_full} "
        f"(HTTP {commits.status_code if commits else 'n/a'})"
    )

    yield repo_full

    # cleanup: удаляем репо (org оставляем — переиспользуется)
    _gitea("DELETE", f"/repos/{ORG}/{REPO}")


class TestLiveAdapter:
    """Адаптер против живого Gitea: auth, read, commits, webhook idempotency."""

    def test_read_file_roundtrip(self, gitea_repo: str):
        from orchestrator.cosmo.adapters.forge_gitea import GiteaForgeAdapter
        owner, _, name = gitea_repo.partition("/")
        with GiteaForgeAdapter(base_url=GITEA_URL, username=GITEA_USER,
                               password=GITEA_PASSWORD) as ad:
            content, sha = ad.read_file(owner, name, ".cosmo/pipeline.yaml", ref="main")
            assert "go_builder" in content
            assert sha

    def test_list_commits_sees_live_commit(self, gitea_repo: str):
        from orchestrator.cosmo.adapters.forge_gitea import GiteaForgeAdapter
        owner, _, name = gitea_repo.partition("/")
        with GiteaForgeAdapter(base_url=GITEA_URL, username=GITEA_USER,
                               password=GITEA_PASSWORD) as ad:
            commits = ad.list_commits(owner, name, ref="main", limit=5)
            assert commits
            assert any("COS-096" in c.message for c in commits)

    def test_bad_credentials_rejected(self, gitea_repo: str):
        import requests as _requests
        from orchestrator.cosmo.adapters.forge_gitea import GiteaForgeAdapter
        owner, _, name = gitea_repo.partition("/")
        with GiteaForgeAdapter(base_url=GITEA_URL, username=GITEA_USER,
                               password="wrong-password") as ad:
            with pytest.raises(_requests.HTTPError) as ei:
                ad.read_file(owner, name, ".cosmo/pipeline.yaml", ref="main")
            assert ei.value.response is not None \
                and ei.value.response.status_code == 401

    def test_ensure_webhook_idempotent(self, gitea_repo: str):
        from orchestrator.cosmo.adapters.forge_gitea import GiteaForgeAdapter
        owner, _, name = gitea_repo.partition("/")
        # Фейковый URL: тест проверяет идемпотентность адаптера, а не
        # доставку. Путь НЕ совпадает с ПУ-endpoint, иначе (а) test-delivery
        # полного цикла может уйти в fake-hook, (б) его DNS-таймаут
        # блокирует очередь доставок Gitea.
        hook_url = "http://hook-fake.invalid/__adapter_idempotency__"
        with GiteaForgeAdapter(base_url=GITEA_URL, username=GITEA_USER,
                               password=GITEA_PASSWORD) as ad:
            hook_id_1, created_1 = ad.ensure_webhook(
                owner, name, hook_url, "live-webhook-secret")
            hook_id_2, created_2 = ad.ensure_webhook(
                owner, name, hook_url, "live-webhook-secret")
        assert created_1 is True
        assert created_2 is False, "второй вызов обязан reuse, не дублировать"
        assert hook_id_1 == hook_id_2


class TestLiveFullCycle:
    """Полный цикл через живой ПУ: binding → webhook-setup → test delivery
    → last-push → compile-from-source."""

    @pytest.fixture(scope="class")
    def bound_app(self, live_api, gitea_repo: str):
        auth = {"Authorization": f"Bearer {live_api['auth']}"}
        base = live_api["base"]

        r = requests.post(f"{base}/api/v1/domains", headers=auth, json={
            "id": DOMAIN_ID, "label": f"FC Live {RUN_TAG}",
            "forge_binding": {"forge_type": "gitea", "url": GITEA_URL,
                              "token_ref": "vault:secret/data/fc-live"},
        }, timeout=10)
        assert r.status_code in (200, 201), r.text

        r = requests.post(f"{base}/api/v1/apps", headers=auth, json={
            "id": APP_ID, "domain_id": DOMAIN_ID, "level": 1,
            "repo_binding": {"forge_id": "gitea", "repo_path": gitea_repo},
        }, timeout=10)
        assert r.status_code in (200, 201), r.text

        # Идемпотентный setup webhook'а СТОРОНОЙ ПУ (из контейнера:
        # cosmo-gitea:3000; секрет из env стенда)
        r = requests.post(f"{base}/api/v1/apps/{APP_ID}/forge/webhook-setup",
                          headers=auth, timeout=15)
        assert r.status_code == 200, r.text
        assert r.json()["repo_path"] == gitea_repo

        yield {"repo_path": gitea_repo, "auth": auth, "base": base}

        requests.delete(f"{base}/api/v1/apps/{APP_ID}", headers=auth, timeout=10)
        requests.delete(f"{base}/api/v1/domains/{DOMAIN_ID}", headers=auth, timeout=10)

    def _deliver_test_push(self, repo_path: str) -> None:
        """Gitea test delivery: шлёт push текущего HEAD на HOOK ПУ.

        Выбираем hook строго по URL ПУ — на репо могут быть и чужие
        hooks (доставка в них ПУ не видит).
        """
        owner, _, name = repo_path.partition("/")
        r = _gitea("GET", f"/repos/{owner}/{name}/hooks")
        assert r.status_code == 200, r.text
        hooks = [hk for hk in (r.json() or [])
                 if hk.get("config", {}).get("url", "").endswith("/api/v1/webhooks/gitea")]
        assert hooks, "webhook ПУ не зарегистрирован в Gitea"
        hook_id = hooks[0]["id"]
        # Test delivery триггерит push-событие последнего коммита
        r = _gitea("POST", f"/repos/{owner}/{name}/hooks/{hook_id}/tests",
                   json={})
        assert r.status_code in (200, 202, 204), f"hook test failed: {r.text}"

    def test_webhook_delivery_visible_in_last_push(self, bound_app):
        base = bound_app["base"]
        auth = bound_app["auth"]

        self._deliver_test_push(bound_app["repo_path"])

        # Gitea доставляет асинхронно — поллинг с честным таймаутом
        last = None
        body = {}
        for _ in range(20):
            r = requests.get(f"{base}/api/v1/apps/{APP_ID}/forge/last-push",
                             headers=auth, timeout=10)
            assert r.status_code == 200, r.text
            body = r.json()
            last = body.get("last_push")
            if last:
                break
            time.sleep(0.5)
        if last is None:
            # Диагностика на месте: что Gitea реально доставил
            owner, _, name = bound_app["repo_path"].partition("/")
            r = _gitea("GET", f"/repos/{owner}/{name}/hooks")
            for hk in (r.json() or []):
                try:
                    r2 = _gitea("GET",
                                f"/repos/{owner}/{name}/hooks/{hk['id']}/deliveries")
                    print(f"\nHOOK {hk['id']} ({hk['config'].get('url')}) deliveries:",
                          r2.text[:600])
                except Exception as exc:  # noqa: BLE001 — диагностика не роняет тест
                    print(f"\nHOOK {hk['id']} deliveries unavailable: {exc}")
        assert last is not None, (
            "webhook push не дошёл до ПУ за 10s: "
            f"last_push={last}, unreachable={body.get('forge_unreachable')}, "
            f"recent_commits={len(body.get('recent_commits', []))}"
        )
        assert last["source"] == "webhook_cache"
        assert last["repo_path"] == bound_app["repo_path"]
        assert last["head_sha"]

    def test_compile_from_live_source(self, bound_app):
        base = bound_app["base"]
        auth = bound_app["auth"]

        # Кирпичи из живого .cosmo/pipeline.yaml должны существовать в каталоге
        for brick in [
            {"id": "go_builder", "name": "Go Builder", "type": "build",
             "source": "internal", "definition": {"image": "golang:1.22"}},
            {"id": "sonarqube_scanner", "name": "Sonar Scanner", "type": "sast",
             "source": "internal", "definition": {"image": "sonarqube:scanner"}},
        ]:
            r = requests.post(f"{base}/api/v1/bricks", headers=auth, json=brick,
                              timeout=10)
            assert r.status_code in (200, 201, 409), r.text

        r = requests.post(f"{base}/api/v1/plans/compile-from-source", headers=auth,
                          json={"plan_id": PLAN_ID, "app_id": APP_ID}, timeout=15)
        assert r.status_code == 201, r.text
        plan = r.json()
        assert plan["brick_ids"] == ["go_builder", "sonarqube_scanner"]
        assert plan["compiled_hash"]

        # План реально заперсистен: читается обратно
        r = requests.get(f"{base}/api/v1/plans/{PLAN_ID}", headers=auth, timeout=10)
        assert r.status_code == 200
        assert r.json()["id"] == PLAN_ID
