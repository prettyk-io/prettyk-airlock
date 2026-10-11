# -*- coding: utf-8 -*-
"""COS-188: self-seed live Woodpecker pipeline fixture (idempotent).

Создаёт ровно то, что нужно live-смокам run-логов (SSE log_chunk, COS-109/180):

  1. Gitea: репо ``cosmo/pipeline-fixture`` (auto_init, branch ``main``) +
     ``.woodpecker.yml`` (два echo-шага — источник реальных логов пайплайна).
  2. Платформенный WP-юзер в БД Woodpecker (``cosmo``, admin) с валидным
     forge-доступом: Gitea PAT в ``users.access_token`` + ``expiry`` в будущем
     (WP не рефрешит OAuth; PAT-как-есть принимается forge-клиентом).
  3. Активация репо в Woodpecker (``POST /api/repos?forge_remote_id=...``;
     повтор → PRESERVED).
  4. Прогон пайплайна (``POST /api/repos/{id}/pipelines``) + ожидание терминала
     + чтение логов шагов — сводка в stdout (evidence для live-проверок).

WP API-токен (JWT HS256 {user-id, type:user}, подпись = ``users.hash``)
выпускается локально из БД — формально это dev-эквивалент PostToken.

Идемпотентность: повторный запуск ничего не ломает (существующие репо/файл/
юзер/активация — PRESERVED; прогон создаёт новый pipeline — так задумано).

Env:
  COSMO_GITEA_URL         default http://127.0.0.1:3100
  COSMO_WOODPECKER_URL    default http://127.0.0.1:8000
  COSMO_FORGE_USER        default cosmo
  COSMO_FORGE_ADMIN_PASSWORD default cosmo-admin-dev
  COSMO_PG_CONTAINER      default cosmo-postgres
  WOODPECKER_FIXTURE_POLL_SECS default 120

Usage:
  python services/scripts/seed-woodpecker-fixture.py
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import subprocess
import sys
import time
import urllib.error
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

GITEA = os.getenv("COSMO_GITEA_URL", "http://127.0.0.1:3100").rstrip("/")
WP = os.getenv("COSMO_WOODPECKER_URL", "http://127.0.0.1:8000").rstrip("/")
GITEA_USER = os.getenv("COSMO_FORGE_USER", "cosmo")
GITEA_PASSWORD = os.getenv("COSMO_FORGE_ADMIN_PASSWORD", "cosmo-admin-dev")
PG = os.getenv("COSMO_PG_CONTAINER", "cosmo-postgres")
POLL_SECS = int(os.getenv("WOODPECKER_FIXTURE_POLL_SECS", "120"))

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

REPO_NAME = "pipeline-fixture"
REPO_FULL = f"{GITEA_USER}/{REPO_NAME}"
BRANCH = "main"
CONFIG_PATH = ".woodpecker.yml"
CONFIG_CONTENT = (
    "steps:\n"
    "  - name: prepare\n"
    "    image: alpine:3.20\n"
    "    commands:\n"
    '      - echo "cosmo-fixture prepare"\n'
    '      - echo "artifact pipeline-fixture"\n'
    "  - name: verify\n"
    "    image: alpine:3.20\n"
    "    commands:\n"
    '      - echo "cosmo-fixture verify"\n'
    '      - echo "status ok"\n'
)


# ── HTTP helpers ──────────────────────────────────────────────────────────

def _request(url: str, *, method: str = "GET", body: dict | None = None,
             token: str | None = None, basic: tuple[str, str] | None = None,
             raw_body: bytes | None = None) -> tuple[int, object]:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if basic:
        raw = base64.b64encode(f"{basic[0]}:{basic[1]}".encode()).decode()
        headers["Authorization"] = f"Basic {raw}"
    data = raw_body if raw_body is not None else (
        json.dumps(body).encode() if body is not None else None)
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            payload = resp.read().decode("utf-8", "replace")
            try:
                return resp.status, json.loads(payload) if payload else {}
            except ValueError:
                return resp.status, payload
    except urllib.error.HTTPError as exc:
        payload = exc.read().decode("utf-8", "replace")
        try:
            parsed = json.loads(payload) if payload else {}
        except ValueError:
            parsed = {"raw": payload[:300]}
        return exc.code, parsed


def _psql(sql: str) -> tuple[int, str]:
    r = subprocess.run(
        ["docker", "exec", PG, "psql", "-U", "cosmo", "-d", "cosmo_woodpecker",
         "-t", "-A", "-c", sql],
        capture_output=True, text=True, timeout=30,
    )
    return r.returncode, r.stdout.strip()


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def wp_token_for(login: str) -> str:
    """Локально выпустить WP API-токен (dev-эквивалент PostToken)."""
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


def update_env_file(key: str, value: str) -> bool:
    """Идемпотентно прописать key=value в services/.env (gitignored)."""
    env_path = os.path.join(REPO_ROOT, "services", ".env")
    lines: list[str] = []
    if os.path.exists(env_path):
        with open(env_path, encoding="utf-8") as fh:
            lines = fh.read().splitlines()
    prefix = f"{key}="
    out: list[str] = []
    updated = False
    found = False
    for ln in lines:
        if ln.strip().startswith(prefix):
            found = True
            if ln.strip() != f"{key}={value}":
                out.append(f"{key}={value}")
                updated = True
            else:
                out.append(ln)
        else:
            out.append(ln)
    if not found:
        out.append(f"{key}={value}")
        updated = True
    if updated:
        with open(env_path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write("\n".join(out) + "\n")
    return updated


# ── Gitea ─────────────────────────────────────────────────────────────────

def gitea_user() -> dict:
    code, body = _request(f"{GITEA}/api/v1/users/{GITEA_USER}",
                          basic=(GITEA_USER, GITEA_PASSWORD))
    if code != 200 or not isinstance(body, dict):
        raise SystemExit(f"[FAIL] gitea user lookup: HTTP {code} {body}")
    return body


def ensure_pat(current_pat: str) -> str:
    """Валидный Gitea PAT: существующий (PRESERVED) либо новый."""
    if current_pat:
        code, _ = _request(f"{GITEA}/api/v1/user",
                           token=current_pat)
        if code == 200:
            print("[gitea] PAT valid — PRESERVED")
            return current_pat
    name = f"cosmo-woodpecker-ci-{int(time.time())}"
    code, body = _request(f"{GITEA}/api/v1/users/{GITEA_USER}/tokens",
                          method="POST", body={"name": name, "scopes": ["all"]},
                          basic=(GITEA_USER, GITEA_PASSWORD))
    if code not in (200, 201) or not isinstance(body, dict):
        raise SystemExit(f"[FAIL] gitea PAT create: HTTP {code} {body}")
    pat = body.get("sha1") or body.get("token") or ""
    if not pat:
        raise SystemExit("[FAIL] gitea PAT response has no token")
    print(f"[gitea] PAT created ({name})")
    return pat


def ensure_repo() -> dict:
    code, body = _request(f"{GITEA}/api/v1/repos/{REPO_FULL}",
                          basic=(GITEA_USER, GITEA_PASSWORD))
    if code == 200 and isinstance(body, dict):
        print(f"[gitea] repo {REPO_FULL} exists — PRESERVED")
        return body
    code, body = _request(f"{GITEA}/api/v1/user/repos", method="POST",
                          body={"name": REPO_NAME, "auto_init": True,
                                "default_branch": BRANCH, "private": False},
                          basic=(GITEA_USER, GITEA_PASSWORD))
    if code not in (201, 409):
        raise SystemExit(f"[FAIL] repo create: HTTP {code} {body}")
    code, body = _request(f"{GITEA}/api/v1/repos/{REPO_FULL}",
                          basic=(GITEA_USER, GITEA_PASSWORD))
    if code != 200 or not isinstance(body, dict):
        raise SystemExit(f"[FAIL] repo lookup after create: HTTP {code}")
    print(f"[gitea] repo {REPO_FULL} created")
    return body


def ensure_config_file() -> None:
    base = f"{GITEA}/api/v1/repos/{REPO_FULL}/contents/{CONFIG_PATH}"
    code, body = _request(base, basic=(GITEA_USER, GITEA_PASSWORD))
    if code == 200 and isinstance(body, dict):
        content_b64 = str(body.get("content") or "").replace("\n", "")
        try:
            current = base64.b64decode(content_b64).decode("utf-8")
        except Exception:  # noqa: BLE001
            current = ""
        if current == CONFIG_CONTENT:
            print(f"[gitea] {CONFIG_PATH} in sync — PRESERVED")
            return
        code, body = _request(base, method="PUT", basic=(GITEA_USER, GITEA_PASSWORD),
                              body={"content": base64.b64encode(
                                  CONFIG_CONTENT.encode()).decode(),
                                  "message": "seed: sync woodpecker fixture config",
                                  "sha": body.get("sha"), "branch": BRANCH})
        if code not in (200, 201):
            raise SystemExit(f"[FAIL] config update: HTTP {code} {body}")
        print(f"[gitea] {CONFIG_PATH} updated (content drift)")
        return
    code, body = _request(base, method="POST", basic=(GITEA_USER, GITEA_PASSWORD),
                          body={"content": base64.b64encode(
                              CONFIG_CONTENT.encode()).decode(),
                              "message": "seed: add woodpecker fixture config",
                              "branch": BRANCH})
    if code not in (200, 201):
        raise SystemExit(f"[FAIL] config create: HTTP {code} {body}")
    print(f"[gitea] {CONFIG_PATH} created")


# ── Woodpecker DB user ────────────────────────────────────────────────────

def ensure_wp_user(pat: str, gitea_uid: str) -> None:
    code, uid = _psql(f"select id from users where login='{GITEA_USER}';")
    if code != 0:
        raise SystemExit("[FAIL] WP DB not reachable (docker/psql?)")
    if uid:
        # PRESERVED: поле hash (ключ токенов) не трогаем; освежаем forge-доступ.
        _psql(
            f"update users set access_token='{pat}', expiry=4102444800, "
            f"admin=true, forge_id=1, forge_remote_id='{gitea_uid}', "
            f"email='{GITEA_USER}@cosmoport.local' where id={uid};"
        )
        print(f"[wp] user '{GITEA_USER}' (id={uid}) refreshed — forge access PRESERVED")
        return
    user_hash = base64.b32encode(secrets.token_bytes(32)).decode()
    _psql(
        "insert into users (forge_id, forge_remote_id, login, email, admin, hash, "
        f"access_token, refresh_token, expiry) values (1, '{gitea_uid}', "
        f"'{GITEA_USER}', '{GITEA_USER}@cosmoport.local', true, '{user_hash}', "
        f"'{pat}', '', 4102444800);"
    )
    print(f"[wp] user '{GITEA_USER}' created (admin, forge-bound)")


# ── Woodpecker activation + run ───────────────────────────────────────────

def ensure_activated(token: str, forge_remote_id: int) -> dict:
    code, body = _request(f"{WP}/api/repos/lookup/{REPO_FULL}", token=token)
    if code == 200 and isinstance(body, dict) and body.get("id"):
        print(f"[wp] repo {REPO_FULL} active (id={body.get('id')}) — PRESERVED")
        return body
    code, body = _request(f"{WP}/api/repos?forge_remote_id={forge_remote_id}",
                          method="POST", token=token)
    if code not in (200, 201):
        raise SystemExit(f"[FAIL] repo activate: HTTP {code} {body}")
    code, body = _request(f"{WP}/api/repos/lookup/{REPO_FULL}", token=token)
    if code != 200 or not isinstance(body, dict):
        raise SystemExit(f"[FAIL] repo lookup after activate: HTTP {code} {body}")
    print(f"[wp] repo {REPO_FULL} activated (id={body.get('id')})")
    return body


def ensure_config_file_set(token: str, repo_id: int) -> None:
    """Явный repo.config_file: детерминированный резолв конфига.

    Default-порядок WP перебирает и ``.woodpecker/`` (folder) — forge-клиент
    на отсутствующей папке отдаёт 'GetContentsOrList' и пайплайн падает в error.
    """
    code, body = _request(f"{WP}/api/repos/{repo_id}", method="PATCH",
                          body={"config_file": CONFIG_PATH}, token=token)
    if code != 200:
        raise SystemExit(f"[FAIL] repo config_file PATCH: HTTP {code} {body}")
    print(f"[wp] repo config_file = {CONFIG_PATH}")


def run_pipeline(token: str, repo_id: int) -> dict:
    code, body = _request(f"{WP}/api/repos/{repo_id}/pipelines", method="POST",
                          body={"branch": BRANCH}, token=token)
    if code not in (200, 201) or not isinstance(body, dict):
        raise SystemExit(f"[FAIL] pipeline trigger: HTTP {code} {body}")
    print(f"[wp] pipeline #{body.get('number')} triggered (id={body.get('id')})")
    return body


def wait_terminal(token: str, repo_id: int, number: int) -> dict:
    deadline = time.time() + POLL_SECS
    last = {}
    while time.time() < deadline:
        code, last = _request(
            f"{WP}/api/repos/{repo_id}/pipelines/{number}", token=token)
        status = str((last or {}).get("status", "?"))
        if status in ("success", "failure", "error", "killed", "declined", "skipped"):
            return last if isinstance(last, dict) else {}
        time.sleep(3)
    raise SystemExit(f"[FAIL] pipeline #{number} not terminal in {POLL_SECS}s "
                     f"(last status={ (last or {}).get('status') })")


def fetch_logs(token: str, repo_id: int, number: int, detail: dict) -> dict:
    logs: dict[str, list[str]] = {}
    for wf in detail.get("workflows") or []:
        # v3.5 API отдаёт шаги в children; steps — legacy (fallback).
        for st in wf.get("steps") or wf.get("children") or []:
            step_id = st.get("id")
            name = st.get("name") or f"step-{step_id}"
            if step_id is None:
                continue
            code, body = _request(
                f"{WP}/api/repos/{repo_id}/logs/{number}/{step_id}", token=token)
            lines = []
            if code == 200 and isinstance(body, list):
                for entry in body:
                    if isinstance(entry, dict):
                        raw = entry.get("data")
                        if raw is not None:
                            # v3.5: строка лога — base64 в ``data``.
                            try:
                                lines.append(base64.b64decode(
                                    raw).decode("utf-8", "replace"))
                            except Exception:  # noqa: BLE001
                                lines.append(str(raw))
                        else:
                            lines.append(str(entry.get("line", entry.get("message", ""))))
                    else:
                        lines.append(str(entry))
            logs[name] = lines
    return logs


# ── main ──────────────────────────────────────────────────────────────────

def main() -> int:
    print("=== COS-188: woodpecker pipeline fixture seed ===")
    gitea = gitea_user()
    gitea_uid = str(gitea.get("id"))

    code, current_pat = _psql(f"select access_token from users where login='{GITEA_USER}';")
    pat = ensure_pat(current_pat if code == 0 else "")

    repo = ensure_repo()
    ensure_config_file()
    ensure_wp_user(pat, gitea_uid)

    token = wp_token_for(GITEA_USER)
    env_updated = update_env_file("COSMO_WOODPECKER_TOKEN", token)
    print(f"[env] COSMO_WOODPECKER_TOKEN {'updated' if env_updated else 'in sync'} (services/.env)")
    active = ensure_activated(token, int(repo.get("id")))
    wp_repo_id = int(active.get("id"))
    ensure_config_file_set(token, wp_repo_id)

    run = run_pipeline(token, wp_repo_id)
    number = int(run.get("number"))
    detail = wait_terminal(token, wp_repo_id, number)
    time.sleep(2)  # логи шагов дописываются асинхронно после терминала
    logs = fetch_logs(token, wp_repo_id, number, detail)
    if sum(len(v) for v in logs.values()) == 0:
        time.sleep(3)
        logs = fetch_logs(token, wp_repo_id, number, detail)

    status = detail.get("status")
    print("")
    print("=== fixture summary ===")
    print(f"  repo            : {REPO_FULL} (gitea id={repo.get('id')}, wp id={wp_repo_id})")
    print(f"  pipeline        : #{number} status={status}")
    for name, lines in logs.items():
        print(f"  step '{name}': {len(lines)} lines")
        for ln in lines[:4]:
            print(f"      | {ln}")
    ok = status == "success" and sum(len(v) for v in logs.values()) > 0
    print(f"  verdict         : {'PASS' if ok else 'FAIL'}")
    print("  next            : docker compose -f services/docker-compose.yml up -d cosmo-api")
    print("                    (подхватить COSMO_WOODPECKER_TOKEN для SSE-логов/executor)")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
