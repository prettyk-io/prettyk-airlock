# -*- coding: utf-8 -*-
"""COS-197: демо-контур «нормальный билд» — идемпотентный сид + живая верификация + очистка.

Что создаёт (идемпотентно, повтор не плодит дубли):
  1. Gitea: repo ``cosmo/build-demo`` + реальный ``Dockerfile`` + исполняемый
     ``.woodpecker.yml`` (docker build + push в registry зоны ZR по каноническому
     тегу, digest-маркер COS-142) — фактическая команда живёт в repo-конфиге
     (канон SAST-STEP-1; brick = каталожная дефиниция).
  2. Woodpecker: активация репо (PAT/WP-user) + ``config_file=.woodpecker.yml``.
  3. Cosmo: domain ``dom-build-demo`` + app ``app-build-demo`` (binding →
     ``cosmo/build-demo``) + brick ``docker-build-demo`` (``definition.type=docker_build``,
     спека COS-162) + plan ``plan-build-demo`` — готовые к прогону.

Живая верификация (``--run``) — на принятой runs-поверхности (механизм, который
оборачивает COS-196): прогон → WP success → digest-маркер шага → образ по digest
в registry ``:5100`` → durable artifact-record (EvidenceLedger decision,
``source=cosmo-artifact-record``).

Очистка (``--clean``): снимает демо-репо (Gitea) + best-effort domain/app и
WP-запись; durable следы ledger/registry по канону не удаляются (retention).

Usage:
  python services/scripts/seed-build-demo.py              # сид + проверки (идемпотентно)
  python services/scripts/seed-build-demo.py --run        # + живой прогон (реальная сборка)
  python services/scripts/seed-build-demo.py --run --runs 2   # два прогона подряд
  python services/scripts/seed-build-demo.py --clean      # снять демо-следы

Env (канон стенда): COSMO_API_URL, COSMO_GITEA_URL, COSMO_WOODPECKER_URL,
COSMO_PG_CONTAINER, E2E_COSMO_EMAIL/PASSWORD, COSMO_FORGE_USER/ADMIN_PASSWORD.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

API = os.getenv("COSMO_API_URL", "http://127.0.0.1:8100").rstrip("/")
GITEA = os.getenv("COSMO_GITEA_URL", "http://127.0.0.1:3100").rstrip("/")
WP = os.getenv("COSMO_WOODPECKER_URL", "http://127.0.0.1:8000").rstrip("/")
GITEA_USER = os.getenv("COSMO_FORGE_USER", "cosmo")
GITEA_PASSWORD = os.getenv("COSMO_FORGE_ADMIN_PASSWORD", "cosmo-admin-dev")
EMAIL = os.getenv("E2E_COSMO_EMAIL", "admin@cosmoport.local")
PASSWORD = os.getenv("E2E_COSMO_PASSWORD", "cosmo-admin-dev")
PG = os.getenv("COSMO_PG_CONTAINER", "cosmo-postgres")

REPO_NAME = "build-demo"
REPO_FULL = f"{GITEA_USER}/{REPO_NAME}"
BRANCH = "main"
DOMAIN_ID = "dom-build-demo"
APP_ID = "app-build-demo"
BRICK_ID = "docker-build-demo"
PLAN_ID = "plan-build-demo"
IMAGE_NAME = "build-demo"
VERSION = "1.0.0"
REPOSITORY = "cosmoport"
NAMESPACE = "zr"
#: Registry ZR: host-published порт (docker-демон=хост видит localhost:5100;
#: канон COS-162/163 — push шага идёт в registry зоны).
REGISTRY_SPEC = "localhost:5100"
REGISTRY_HOST_CHECK = "http://127.0.0.1:5100"
QUALIFIED_TAG = f"{REGISTRY_SPEC}/{REPOSITORY}/{NAMESPACE}/{IMAGE_NAME}:{VERSION}"
CONFIG_PATH = ".woodpecker.yml"

DOCKERFILE_CONTENT = """\
FROM alpine:3.20
LABEL org.opencontainers.image.title="build-demo"
LABEL org.opencontainers.image.description="COS-197 demo build (few bytes, fast)"
CMD ["sh", "-c", "echo build-demo-ok"]
"""

#: Исполняемый build-пайплайн repo-конфига — зеркало канона COS-162
#: (render_docker_build_commands): build → push по тегу → manifest-digest из
#: ответа push → маркер ``<name>:<version>@sha256:<digest>`` (COS-142).
WOODPECKER_CONFIG = f"""\
when:
  - event: [manual]
steps:
  - name: docker-build
    image: docker:24-cli
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
    commands:
      - set -eu
      - docker build -f Dockerfile -t {QUALIFIED_TAG} .
      - "docker push {QUALIFIED_TAG} 2>&1 | grep -oE 'digest: sha256:[0-9a-f]{{64}}' | head -n 1 | sed 's/^digest: //' > .woodpecker-image-digest"
      - 'DIGEST=$(cat .woodpecker-image-digest)'
      - 'test -n "$DIGEST"'
      - 'echo {IMAGE_NAME}:{VERSION}@$DIGEST'
"""

#: Generic build-кирпич (BrickDefinition-канон): исполнение — из repo-конфига
#: (`.woodpecker.yml`), brick = каталожная дефиниция. Полная `docker_build`-спека
#: (COS-162) каталогом **не носится** (BrickDefinition требует image и режет
#: extras; DockerBuildSpec extra=forbid) — шов COS-196; см. `--docker-build-def`.
BRICK_DEFINITION_GENERIC = {
    "executor": "woodpecker",
    "image": "docker:24-cli",
    "timeout_s": 1200,
    "inputs": {"COSMO_DEMO": "build-demo"},
}

#: Полная docker_build-спека COS-162 (для `--docker-build-def`; compile
#: положительно заработает после расширения продуктовой схемы — COS-196).
BRICK_DEFINITION_DOCKER_BUILD = {
    "type": "docker_build",
    "image_name": IMAGE_NAME,
    "version": VERSION,
    "dockerfile": "Dockerfile",
    "context": ".",
    "registry": REGISTRY_SPEC,
    "repository": REPOSITORY,
    "namespace": NAMESPACE,
}

FIXTURE_FILES = {
    "Dockerfile": DOCKERFILE_CONTENT,
    CONFIG_PATH: WOODPECKER_CONFIG,
}

PASSED: list[str] = []
FAILED: list[str] = []
SKIPPED: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    (PASSED if ok else FAILED).append(name)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


def skip(name: str, reason: str = "") -> None:
    """Честный SKIP: проверка неприменима по названной причине (не PASS)."""
    SKIPPED.append(name)
    print(f"[SKIP] {name}" + (f" — {reason}" if reason else ""))


# ── HTTP / DB helpers ─────────────────────────────────────────────────────


def _request(url: str, *, method: str = "GET", body: dict | None = None,
             token: str | None = None, basic: tuple[str, str] | None = None,
             extra_headers: dict | None = None, timeout: int = 20) -> tuple[int, dict]:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if basic:
        raw = base64.b64encode(f"{basic[0]}:{basic[1]}".encode()).decode()
        headers["Authorization"] = f"Basic {raw}"
    if extra_headers:
        headers.update(extra_headers)
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = resp.read().decode("utf-8")
            return resp.status, (json.loads(payload) if payload else {})
    except urllib.error.HTTPError as exc:
        payload = exc.read().decode("utf-8")
        try:
            parsed = json.loads(payload) if payload else {}
        except ValueError:
            parsed = {"raw": payload}
        return exc.code, parsed


def _tolerate(status: int, *, ok: tuple[int, ...], what: str) -> None:
    if status not in ok:
        raise SystemExit(f"[FAIL] {what}: HTTP {status}")


def _psql(sql: str) -> tuple[int, str]:
    """PSQL в БД Woodpecker (PAT/WP-user)."""
    r = subprocess.run(
        ["docker", "exec", PG, "psql", "-U", "cosmo", "-d", "cosmo_woodpecker",
         "-t", "-A", "-c", sql],
        capture_output=True, text=True, timeout=30,
    )
    return r.returncode, r.stdout.strip()


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def api_login() -> str:
    status, body = _request(
        f"{API}/api/v1/auth/login", method="POST",
        body={"email": EMAIL, "password": PASSWORD},
    )
    _tolerate(status, ok=(200,), what="login")
    token = str(body.get("access_token") or "")
    if not token:
        raise SystemExit("[FAIL] login response has no access_token")
    return token


# ── Woodpecker ────────────────────────────────────────────────────────────


def wp_token_for(login: str) -> str:
    code, uid = _psql(f"select id from users where login='{login}';")
    if code != 0 or not uid:
        raise SystemExit(f"[FAIL] WP user '{login}' not found")
    code, uhash = _psql(f"select hash from users where id={uid};")
    if code != 0 or not uhash:
        raise SystemExit(f"[FAIL] WP user '{login}' has empty hash")
    header = _b64url(json.dumps({"alg": "HS256", "typ": "JWT"},
                                separators=(",", ":")).encode())
    payload = _b64url(json.dumps({"user-id": str(uid), "type": "user"},
                                 separators=(",", ":")).encode())
    sig = hmac.new(uhash.encode(), f"{header}.{payload}".encode(),
                   hashlib.sha256).digest()
    return f"{header}.{payload}.{_b64url(sig)}"


def ensure_wp_user(pat: str, gitea_uid: str) -> None:
    """Канон seed-woodpecker-fixture: ``hash`` (ключ токенов) НЕ трогаем —
    освежаем только forge-доступ (access_token/expiry/admin/forge identity).
    """
    code, uid = _psql(f"select id from users where login='{GITEA_USER}';")
    if code != 0:
        raise SystemExit("[FAIL] WP DB not reachable (docker/psql?)")
    if uid:
        _psql(
            f"update users set access_token='{pat}', expiry=4102444800, "
            f"admin=true, forge_id=1, forge_remote_id='{gitea_uid}', "
            f"email='{GITEA_USER}@cosmoport.local' where id={uid};"
        )
        print(f"[wp] user '{GITEA_USER}' (id={uid}) refreshed — forge access PRESERVED")
        return
    import secrets as _secrets
    user_hash = base64.b32encode(_secrets.token_bytes(32)).decode()
    _psql(
        "insert into users (forge_id, forge_remote_id, login, email, admin, hash, "
        f"access_token, refresh_token, expiry) values (1, '{gitea_uid}', "
        f"'{GITEA_USER}', '{GITEA_USER}@cosmoport.local', true, '{user_hash}', "
        f"'{pat}', '', 4102444800);"
    )
    print(f"[wp] user '{GITEA_USER}' created (admin, forge-bound)")


def ensure_pat(current_pat: str) -> str:
    if current_pat.strip():
        status, _ = _request(f"{GITEA}/api/v1/user", basic=(GITEA_USER, current_pat.strip()))
        if status == 200:
            print("[gitea] PAT valid — PRESERVED")
            return current_pat.strip()
    import secrets as _secrets
    token = "cosmo_" + _secrets.token_hex(20)
    status, body = _request(
        f"{GITEA}/api/v1/users/{GITEA_USER}/tokens", method="POST",
        basic=(GITEA_USER, GITEA_PASSWORD),
        body={"name": f"build-demo-{int(time.time())}", "scopes": ["write:repository", "write:user"]},
    )
    if status not in (200, 201):
        raise SystemExit(f"[FAIL] PAT create: HTTP {status} {body}")
    new_token = str(body.get("sha1") or "")
    if not new_token:
        raise SystemExit("[FAIL] PAT response has no sha1")
    _psql(f"update users set access_token='{new_token}' where login='{GITEA_USER}';")
    print("[gitea] PAT created")
    return new_token


def ensure_repo() -> dict:
    status, body = _request(f"{GITEA}/api/v1/repos/{REPO_FULL}",
                            basic=(GITEA_USER, GITEA_PASSWORD))
    if status == 200 and isinstance(body, dict):
        print(f"[gitea] repo {REPO_FULL} exists — PRESERVED")
        return body
    status, body = _request(f"{GITEA}/api/v1/user/repos", method="POST",
                            basic=(GITEA_USER, GITEA_PASSWORD),
                            body={"name": REPO_NAME, "auto_init": True,
                                  "default_branch": BRANCH, "private": False})
    if status not in (201, 409):
        raise SystemExit(f"[FAIL] repo create: HTTP {status} {body}")
    status, body = _request(f"{GITEA}/api/v1/repos/{REPO_FULL}",
                            basic=(GITEA_USER, GITEA_PASSWORD))
    if status != 200 or not isinstance(body, dict):
        raise SystemExit(f"[FAIL] repo lookup after create: HTTP {status}")
    print(f"[gitea] repo {REPO_FULL} created")
    return body


def ensure_file(path: str, content: str) -> None:
    base = f"{GITEA}/api/v1/repos/{REPO_FULL}/contents/{path}"
    status, body = _request(base, basic=(GITEA_USER, GITEA_PASSWORD))
    sha = ""
    if status == 200 and isinstance(body, dict):
        try:
            current = base64.b64decode(
                str(body.get("content") or "").replace("\n", "")).decode("utf-8")
        except Exception:  # noqa: BLE001
            current = ""
        if current == content:
            print(f"[gitea] {path} in sync — PRESERVED")
            return
        sha = str(body.get("sha") or "")
    payload = {
        "content": base64.b64encode(content.encode("utf-8")).decode(),
        "message": "COS-197: build-demo fixture",
        "branch": BRANCH,
    }
    if sha:
        payload["sha"] = sha
    status, body = _request(base, method="PUT" if sha else "POST",
                            basic=(GITEA_USER, GITEA_PASSWORD), body=payload)
    if status not in (200, 201, 409, 422):
        raise SystemExit(f"[FAIL] gitea file {path}: HTTP {status} {body}")
    print(f"[gitea] {path} {'updated' if sha else 'created'}")


def _trust_repo(wp_token: str, repo_id: int) -> None:
    """Trust для docker-socket шага: WP linter требует ``trusted.volumes``.

    Канон-формат (swagger model.TrustedConfiguration): простые bool-поля;
    ``volumes`` нужен для socket-mount шага docker_build (COS-162).
    """
    _request(f"{WP}/api/repos/{repo_id}", method="PATCH", token=wp_token,
             body={"trusted": {"network": False, "volumes": True, "security": False}})


def ensure_activated(wp_token: str, forge_remote_id: int) -> dict:
    """Активация репо каноном WP API: ``POST /api/repos?forge_remote_id=`` (QUERY).

    Body-вариант v3.5 не читает (forge_remote_id=0 → 500 «no rows»).
    Trusted.volumes выставляется и при свежей активации, и при повторной.
    """
    status, body = _request(f"{WP}/api/repos/lookup/{REPO_FULL}", token=wp_token)
    if status == 200 and isinstance(body, dict) and body.get("id"):
        repo_id = int(body["id"])
        # После clean/пересоздания Gitea-репо remote id меняется — перепривязка
        # записи WP (иначе stale forge_remote_id ломает синк).
        current_remote = str(body.get("forge_remote_id") or "")
        if current_remote != str(forge_remote_id):
            _psql(f"update repos set forge_remote_id='{forge_remote_id}' where id={repo_id};")
            print(f"[wp] repo id={repo_id}: forge_remote_id re-linked "
                  f"{current_remote or '-'} → {forge_remote_id}")
        _trust_repo(wp_token, repo_id)
        print(f"[wp] repo active (id={repo_id}) — trust synced PRESERVED")
        return body
    status, body = _request(f"{WP}/api/repos?forge_remote_id={forge_remote_id}",
                            method="POST", token=wp_token)
    if status not in (200, 201):
        raise SystemExit(f"[FAIL] wp repo activate: HTTP {status} {body}")
    status, body = _request(f"{WP}/api/repos/lookup/{REPO_FULL}", token=wp_token)
    if status != 200 or not isinstance(body, dict):
        raise SystemExit(f"[FAIL] wp repo lookup after activate: HTTP {status} {body}")
    _trust_repo(wp_token, int(body["id"]))
    print(f"[wp] repo activated (id={body.get('id')}) + trust.volumes")
    return body


def ensure_config_file_set(wp_token: str, repo_id: int) -> None:
    status, body = _request(f"{WP}/api/repos/{repo_id}", token=wp_token)
    if status == 200 and str((body or {}).get("config_file") or "") == CONFIG_PATH:
        return
    _request(f"{WP}/api/repos/{repo_id}", method="PATCH", token=wp_token,
             body={"config_file": CONFIG_PATH})
    print(f"[wp] repo config_file = {CONFIG_PATH}")


# ── Cosmo ─────────────────────────────────────────────────────────────────


def ensure_domain(token: str) -> str:
    status, _ = _request(
        f"{API}/api/v1/domains", method="POST", token=token,
        body={
            "id": DOMAIN_ID,
            "label": "Build demo domain (COS-197)",
            "forge_binding": {
                "forge_type": "gitea",
                "url": GITEA,
                "token_ref": "vault:secret/data/token",
            },
        },
    )
    _tolerate(status, ok=(200, 201, 409), what=f"domain {DOMAIN_ID}")
    print(f"[cosmo] domain {DOMAIN_ID}")
    return DOMAIN_ID


def ensure_app(token: str) -> None:
    status, _ = _request(
        f"{API}/api/v1/apps", method="POST", token=token,
        body={
            "id": APP_ID,
            "domain_id": DOMAIN_ID,
            "level": 1,
            "repo_binding": {
                "forge_id": "gitea",
                "repo_path": REPO_FULL,
                "default_branch": BRANCH,
            },
        },
    )
    _tolerate(status, ok=(200, 201, 409), what=f"app {APP_ID} → {REPO_FULL}")
    print(f"[cosmo] app {APP_ID} → {REPO_FULL}")


def _cosmo_psql(sql: str) -> tuple[int, str]:
    """PSQL в БД Cosmo (каталог кирпичей — сверка/fallback)."""
    r = subprocess.run(
        ["docker", "exec", PG, "psql", "-U", "cosmo", "-d", "cosmo",
         "-t", "-A", "-c", sql],
        capture_output=True, text=True, timeout=30,
    )
    return r.returncode, r.stdout.strip()


def _brick_definition_in_db(brick_id: str) -> str:
    code, out = _cosmo_psql(
        f"select definition_json::text from pipeline_bricks where id='{brick_id}';")
    return out if code == 0 else ""


def _upsert_brick_db(definition: dict) -> None:
    """Прямой upsert каталога только демо-строки ``{BRICK_ID}`` (идемпотентно).

    Fallback для случая, когда API-схема не несёт выбранную дефиницию
    (docker_build — шов COS-196). Stand-фикстуры канонически пишут WP-БД
    напрямую; здесь — строго одна демо-строка каталога Cosmo.
    """
    payload = json.dumps(definition, ensure_ascii=False, sort_keys=True)
    sql = (
        "insert into pipeline_bricks (id, name, type, source, definition_json, "
        "depends_on, gates) values "
        f"('{BRICK_ID}', 'Docker Build (demo)', 'build', 'internal', "
        f"'{payload}', '[]'::jsonb, '[]'::jsonb) "
        "on conflict (id) do update set name=excluded.name, type=excluded.type, "
        "source=excluded.source, definition_json=excluded.definition_json;"
    )
    code, out = _cosmo_psql(sql)
    if code != 0:
        raise SystemExit(f"[FAIL] brick {BRICK_ID} direct upsert: {out[:200]}")


def ensure_brick(token: str, *, docker_build_def: bool) -> None:
    """Кирпич демо: API-путь; для docker_build-дефиниции — fallback upsert (COS-196 шов)."""
    definition = BRICK_DEFINITION_DOCKER_BUILD if docker_build_def else BRICK_DEFINITION_GENERIC
    payload = {"name": "Docker Build (demo)", "type": "build",
               "source": "internal", "definition": definition}
    status, body = _request(f"{API}/api/v1/bricks", method="POST", token=token,
                            extra_headers={"X-Cosmo-Domain": DOMAIN_ID},
                            body={"id": BRICK_ID, **payload})
    if status in (200, 201):
        print(f"[cosmo] brick {BRICK_ID} created (API)")
    elif status == 409:
        status2, body2 = _request(f"{API}/api/v1/bricks/{BRICK_ID}", method="PUT",
                                  token=token,
                                  extra_headers={"X-Cosmo-Domain": DOMAIN_ID},
                                  body=payload)
        if status2 not in (200, 201):
            raise SystemExit(f"[FAIL] brick {BRICK_ID} update: HTTP {status2} {body2}")
        print(f"[cosmo] brick {BRICK_ID} exists — synced (API)")
    elif status == 422 and docker_build_def:
        print(f"[cosmo] brick {BRICK_ID}: API-схема не носит docker_build-дефиницию "
              f"(шов COS-196) — прямой upsert каталога")
    else:
        raise SystemExit(f"[FAIL] brick {BRICK_ID}: HTTP {status} {body}")

    marker = '"type": "docker_build"' if docker_build_def else '"image": "docker:24-cli"'
    stored = _brick_definition_in_db(BRICK_ID)
    if marker not in stored.replace("'", '"'):
        _upsert_brick_db(definition)
        stored = _brick_definition_in_db(BRICK_ID)
    if marker in stored.replace("'", '"'):
        kind = "docker_build (канон COS-162)" if docker_build_def else "generic build (image)"
        print(f"[cosmo] brick {BRICK_ID} definition: {kind} OK")
    else:
        raise SystemExit(f"[FAIL] brick {BRICK_ID}: дефиниция не сохранена ({marker})")


def ensure_plan(token: str) -> None:
    status, body = _request(f"{API}/api/v1/plans/compile", method="POST", token=token,
                            extra_headers={"X-Cosmo-Domain": DOMAIN_ID},
                            body={"plan_id": PLAN_ID, "app_id": APP_ID,
                                  "brick_ids": [BRICK_ID], "level": "app"})
    _tolerate(status, ok=(200, 201, 409), what=f"plans/compile {PLAN_ID}")
    print(f"[cosmo] plan {PLAN_ID} ready")


# ── Registry / verification helpers ───────────────────────────────────────


def registry_up() -> bool:
    try:
        req = urllib.request.Request(f"{REGISTRY_HOST_CHECK}/v2/", method="GET")
        with urllib.request.urlopen(req, timeout=6) as resp:
            return resp.status == 200
    except Exception:  # noqa: BLE001
        return False


def registry_manifest_exists(digest: str) -> bool:
    url = (f"{REGISTRY_HOST_CHECK}/v2/{REPOSITORY}/{NAMESPACE}/{IMAGE_NAME}"
           f"/manifests/{digest}")
    req = urllib.request.Request(
        url, method="HEAD",
        headers={"Accept": "application/vnd.docker.distribution.manifest.v2+json"})
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            return resp.status == 200
    except urllib.error.HTTPError as exc:
        return exc.code == 200
    except Exception:  # noqa: BLE001
        return False


def wait_batch_status(token: str, plan_id: str, expect: set[str],
                      timeout_s: int = 420) -> list[str]:
    deadline = time.time() + timeout_s
    last: list[str] = []
    while time.time() < deadline:
        try:
            code, body = _request(f"{API}/api/v1/batches?plan_id={plan_id}", token=token,
                                  extra_headers={"X-Cosmo-Domain": DOMAIN_ID})
        except Exception:  # noqa: BLE001 — транзиент (рестарт стенда) не роняет показ
            time.sleep(5)
            continue
        if code == 200 and isinstance(body, list) and body:
            last = [str(b.get("status")) for b in body]
            if all(s in expect for s in last):
                return last
        time.sleep(5)
    return last


def wait_run_status(token: str, run_id: str, expect: set[str],
                    timeout_s: int = 420) -> str:
    deadline = time.time() + timeout_s
    last = ""
    while time.time() < deadline:
        try:
            code, body = _request(f"{API}/api/v1/runs/{run_id}", token=token,
                                  extra_headers={"X-Cosmo-Domain": DOMAIN_ID})
        except Exception:  # noqa: BLE001
            time.sleep(4)
            continue
        if code == 200 and isinstance(body, dict):
            last = str(body.get("status") or "")
            if last in expect:
                return last
        time.sleep(4)
    return last


def wait_evidence_source(token: str, run_id: str, source: str,
                         timeout_s: int = 300) -> tuple[dict | None, dict]:
    """Ждать ledger-запись с provenance.source == source (durable)."""
    deadline = time.time() + timeout_s
    chain: dict = {}
    while time.time() < deadline:
        try:
            code, body = _request(f"{API}/api/v1/runs/{run_id}/evidence", token=token,
                                  extra_headers={"X-Cosmo-Domain": DOMAIN_ID})
        except Exception:  # noqa: BLE001
            time.sleep(5)
            continue
        if code == 200 and isinstance(body, dict):
            chain = body
            entries = ((body.get("chain") or {}).get("entries")) or []
            for entry in entries:
                payload = entry.get("content") or entry.get("provenance_json") or {}
                if isinstance(payload, dict) and payload.get("source") == source:
                    return entry, body
        time.sleep(5)
    return None, chain


def wp_latest_pipeline(wp_token: str, repo_id: int) -> dict:
    try:
        status, body = _request(f"{WP}/api/repos/{repo_id}/pipelines?perPage=1",
                                token=wp_token)
    except Exception:  # noqa: BLE001
        return {}
    if status == 200 and isinstance(body, list) and body:
        return body[0]
    return {}


def wp_step_states_db(repo_id: int, number: int) -> dict[str, str]:
    """Состояния шагов пайплайна из WP-БД.

    WP v3.5 detail-API не отдаёт steps (проверено: steps=None и у sast-репо) —
    канон stand-фикстур пишет/читает WP-БД напрямую (как users/PAT).
    """
    code, out = _psql(
        "select s.name||'='||s.state from steps s "
        "join pipelines p on s.pipeline_id=p.id "
        f"where p.repo_id={int(repo_id)} and p.number={int(number)} order by s.id;")
    states: dict[str, str] = {}
    if code != 0:
        return states
    for line in out.splitlines():
        if "=" in line:
            key, _, value = line.partition("=")
            states[key] = value
    return states


def wp_digest_marker_db(repo_id: int, number: int) -> str:
    """Строка канонического digest-маркера из логов шага docker-build (WP-БД).

    ``log_entries.data`` — ``bytea``: psql отдаёт hex-форму ``\\x…`` — декодируем.
    """
    code, out = _psql(
        "select le.data from log_entries le "
        "join steps s on le.step_id=s.id "
        "join pipelines p on s.pipeline_id=p.id "
        f"where p.repo_id={int(repo_id)} and p.number={int(number)} "
        f"and s.name='docker-build' and le.data like '%{IMAGE_NAME}:{VERSION}@sha256:%' "
        "order by le.id desc limit 1;")
    raw = out.strip() if code == 0 else ""
    if not raw:
        return ""
    if raw.startswith("\\x"):
        try:
            return bytes.fromhex(raw[2:]).decode("utf-8", "replace")
        except ValueError:
            return raw
    return raw


# ── Прогон (живая верификация) ────────────────────────────────────────────


def start_run(token: str, tag: str) -> tuple[str, str]:
    """Показ-прогон: свой план на запуск (канон SAST-фикстуры).

    План/батч — общие по plan_id; повторный прогон на том же плане унаследовал бы
    терминальный батч (и после отмены — failed). Поэтому каждый показ компилирует
    ``plan-build-demo-<tag>`` и стартует свежий батч.
    """
    plan_id = f"plan-build-demo-{tag}"
    run_id = f"run-build-demo-{tag}"
    domain_header = {"X-Cosmo-Domain": DOMAIN_ID}
    code, body = _request(f"{API}/api/v1/plans/compile", method="POST", token=token,
                          extra_headers=domain_header,
                          body={"plan_id": plan_id, "app_id": APP_ID,
                                "brick_ids": [BRICK_ID], "level": "app"})
    _tolerate(code, ok=(200, 201, 409), what=f"plans/compile {plan_id}")
    code, body = _request(f"{API}/api/v1/runs", method="POST", token=token,
                          extra_headers=domain_header,
                          body={"id": run_id, "plan_id": plan_id, "trigger": "manual",
                                "domain_id": DOMAIN_ID,
                                "initiator_user_id": "build-demo-seed",
                                "initiator_role": "secops"})
    _tolerate(code, ok=(200, 201), what=f"runs POST {run_id}")
    code, body = _request(f"{API}/api/v1/runs/{run_id}/status", method="PATCH",
                          token=token, extra_headers=domain_header,
                          body={"status": "running"})
    _tolerate(code, ok=(200, 201, 204), what=f"run {run_id} → running")
    print(f"[cosmo] run {run_id} → running (plan {plan_id})")
    return run_id, plan_id


def verify_run(token: str, wp_token: str, repo_id: int, run_id: str, plan_id: str,
               tag: str) -> None:
    statuses = wait_batch_status(token, plan_id, {"passed", "failed"})
    check(f"run {tag}: batch passed", bool(statuses) and all(s == "passed" for s in statuses),
          str(statuses))

    # Evidence-след прогона (COS-097 log-запись; есть на passed-батче).
    log_entry, _chain = wait_evidence_source(token, run_id, "woodpecker")
    check(f"run {tag}: evidence-след прогона (log-запись COS-097)",
          log_entry is not None, "")

    # Durable digest-record (COS-164) — только если каталог несёт docker_build-дефиницию.
    record_digest = ""
    stored = _brick_definition_in_db(BRICK_ID)
    if '"type": "docker_build"' in stored.replace("'", '"'):
        entry, _chain2 = wait_evidence_source(token, run_id, "cosmo-artifact-record")
        if entry is not None:
            payload = entry.get("content") or entry.get("provenance_json") or {}
            record_digest = str(payload.get("digest") or "")
            check(f"run {tag}: durable artifact-record (digest)",
                  bool(record_digest) and record_digest.startswith("sha256:"),
                  f"{payload.get('canonical_ref') or record_digest}")
        else:
            check(f"run {tag}: durable artifact-record (digest)", False,
                  "не найден в evidence")
    else:
        skip(f"run {tag}: durable artifact-record (digest)",
             "дефиниция docker_build каталогом не носится (шов COS-196) — "
             "digest проверяется по логам шага и registry")

    pl = wp_latest_pipeline(wp_token, repo_id)
    number = int(pl.get("number") or 0)
    states = wp_step_states_db(repo_id, number) if number else {}
    check(f"run {tag}: WP pipeline success (docker-build)",
          str(pl.get("status")) == "success" and states.get("docker-build") == "success",
          f"#{number} {pl.get('status')} {states}")

    log_digest = ""
    if number:
        marker_line = wp_digest_marker_db(repo_id, number)
        check(f"run {tag}: digest-маркер канона COS-142 в логах шага",
              bool(marker_line), marker_line[:90])
        match = re.search(
            rf"{re.escape(IMAGE_NAME)}:{re.escape(VERSION)}@(sha256:[0-9a-f]{{64}})",
            marker_line)
        log_digest = match.group(1) if match else ""
        if record_digest and log_digest:
            check(f"run {tag}: digest из логов == durable record",
                  record_digest == log_digest, record_digest)

    digest = record_digest or log_digest
    if digest:
        check(f"run {tag}: образ по digest существует в registry (:5100)",
              registry_manifest_exists(digest), f"{QUALIFIED_TAG} @ {digest[:19]}…")
    else:
        check(f"run {tag}: образ по digest существует в registry (:5100)", False,
              "digest не получен (логи/запись)")

    run_status = wait_run_status(token, run_id, {"succeeded", "blocked", "failed"})
    check(f"run {tag}: run succeeded (без гейтов)", run_status == "succeeded",
          f"status={run_status}")


# ── Очистка ───────────────────────────────────────────────────────────────


def clean(token: str) -> int:
    print("=== COS-197: clean (снятие демо-следов) ===")
    # 1. Gitea repo (демо-репозиторий: Dockerfile + .woodpecker.yml + история).
    status, _ = _request(f"{GITEA}/api/v1/repos/{REPO_FULL}", method="DELETE",
                         basic=(GITEA_USER, GITEA_PASSWORD))
    if status in (204, 200, 404):
        print(f"[clean] gitea repo {REPO_FULL}: removed" if status != 404
              else f"[clean] gitea repo {REPO_FULL}: already absent")
    else:
        print(f"[clean] WARN gitea repo delete: HTTP {status}")

    # 1b. WP-репо: снять запись (stale forge_remote_id иначе мешает повторной
    #     активации после пересоздания Gitea-репо).
    try:
        wp_token = wp_token_for(GITEA_USER)
        lstatus, lbody = _request(f"{WP}/api/repos/lookup/{REPO_FULL}", token=wp_token)
        if lstatus == 200 and isinstance(lbody, dict) and lbody.get("id"):
            rid = int(lbody["id"])
            dstatus, _ = _request(f"{WP}/api/repos/{rid}", method="DELETE", token=wp_token)
            if dstatus in (200, 204, 404):
                print(f"[clean] wp repo {REPO_FULL}: removed (id={rid})")
            else:
                print(f"[clean] WARN wp repo delete: HTTP {dstatus}")
        elif lstatus == 404:
            print(f"[clean] wp repo {REPO_FULL}: already absent")
        else:
            print(f"[clean] WARN wp repo lookup: HTTP {lstatus}")
    except Exception as exc:  # noqa: BLE001 — очистка не роняет демо-контур
        print(f"[clean] WARN wp repo cleanup: {exc}")

    # 2. Cosmo app/domain — best-effort: durable прогоны/планы держат FK,
    #    честно сообщаем, если снять нельзя (не маскируем).
    for kind, ident in (("apps", APP_ID), ("domains", DOMAIN_ID)):
        status, body = _request(f"{API}/api/v1/{kind}/{ident}", method="DELETE", token=token)
        if status in (200, 204, 404):
            print(f"[clean] {kind}/{ident}: removed" if status != 404
                  else f"[clean] {kind}/{ident}: already absent")
        else:
            detail = str((body or {}).get("detail") or body)[:160]
            print(f"[clean] WARN {kind}/{ident}: HTTP {status} — {detail} "
                  f"(durable прогоны/планы держат связь; снятие — решением PO)")

    print("[clean] durable следы (ledger-записи, образ в registry) не удаляются "
          "по канону immutable/ledger — снимаются retention-политикой")
    print("[clean] OK")
    return 0


# ── main ──────────────────────────────────────────────────────────────────


def main() -> int:
    ap = argparse.ArgumentParser(description="COS-197: build-demo сид/проверка/очистка")
    ap.add_argument("--run", action="store_true", help="живой прогон (реальная сборка)")
    ap.add_argument("--runs", type=int, default=1, help="сколько прогонов подряд (default 1)")
    ap.add_argument("--clean", action="store_true", help="снять демо-следы и выйти")
    ap.add_argument("--docker-build-def", action="store_true",
                    help="сеять полную docker_build-дефиницию (позитивный compile — "
                         "после расширения схемы каталога, COS-196)")
    args = ap.parse_args()

    print("=== COS-197: build-demo seed/verify ===")
    print(f"[env] API={API} GITEA={GITEA} WP={WP} registry={REGISTRY_HOST_CHECK}")

    check("registry ZR reachable (/v2/)", registry_up(), REGISTRY_HOST_CHECK)

    token = api_login()

    if args.clean:
        return clean(token)

    gitea = ensure_repo()
    for path, content in FIXTURE_FILES.items():
        ensure_file(path, content)

    # Forge identity пользователя cosmo (для WP forge_remote_id) — отдельно от id репо.
    status, gitea_user = _request(f"{GITEA}/api/v1/users/{GITEA_USER}",
                                  basic=(GITEA_USER, GITEA_PASSWORD))
    if status != 200 or not isinstance(gitea_user, dict):
        raise SystemExit(f"[FAIL] gitea user lookup {GITEA_USER}: HTTP {status}")

    code, current_pat = _psql(f"select access_token from users where login='{GITEA_USER}';")
    pat = ensure_pat(current_pat if code == 0 else "")
    ensure_wp_user(pat, str(gitea_user.get("id")))
    wp_token = wp_token_for(GITEA_USER)
    active = ensure_activated(wp_token, int(gitea.get("id")))
    wp_repo_id = int(active.get("id"))
    ensure_config_file_set(wp_token, wp_repo_id)

    ensure_domain(token)
    ensure_app(token)
    ensure_brick(token, docker_build_def=args.docker_build_def)
    ensure_plan(token)

    if args.run:
        for i in range(1, max(1, args.runs) + 1):
            tag = f"{int(time.time())}-{i}"
            print("")
            print(f"--- RUN #{i} (реальная сборка через runs-поверхность) ---")
            run_id, plan_id = start_run(token, tag)
            verify_run(token, wp_token, wp_repo_id, run_id, plan_id, tag)

    print("")
    print("=== summary ===")
    print(f"  repo     : {REPO_FULL} (wp id={wp_repo_id})")
    print(f"  image    : {QUALIFIED_TAG} (registry {REGISTRY_HOST_CHECK})")
    print(f"  plan     : {PLAN_ID} / brick {BRICK_ID}")
    print(f"  PASSED={len(PASSED)} FAILED={len(FAILED)} SKIPPED={len(SKIPPED)}")
    if FAILED:
        print("  FAILED:", FAILED)
        return 1
    if SKIPPED:
        print("  SKIPPED:", SKIPPED)
    print("COS-197 BUILD-DEMO: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
