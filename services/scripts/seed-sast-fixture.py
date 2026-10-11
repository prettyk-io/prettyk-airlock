# -*- coding: utf-8 -*-
"""SAST-STEP-1: self-seed живого source-SAST контура стенда (идемпотентно).

Прогоняет ПОЛНУЮ цепочку brick → plan → run → Woodpecker pipeline → отчёт →
durable evidence, и отдельный НЕГАТИВ (CE недостижим → честный фейл шага +
alert-след). Зеркалит инфраструктурные приёмы COS-188 (сид WP-контура) и
COS-179 (сид фикстуры через живой Cosmo API).

  1. OpenBao: secret/cosmo/sast (url+token) — предусловие (seed-sonar-stand.py).
  2. Gitea: репо cosmo/sast-fixture — уязвимая программа-фикстура (app/sample.py),
     скрипт отчёта (sast_report.py: CE api/issues/search → JSON + канонический
     маркер ``[prettyk-sast-report]``) и .woodpecker.yml (шаги sonar-scan + sonar-report).
  3. Woodpecker: PAT/юзер/активация (как COS-188) + repo-секреты
     ``sonar_token`` / ``sonar_host_url`` (значения — из секретницы/env, НЕ plaintext).
  4. Cosmo API (живой, login admin): domain/app-binding + кирпич ``type=sast``
     (+ группа ``sast-sonarqube``) + план (compile) + run → ``running``
     (executor submit_batches; нужен ``COSMO_EXECUTOR_ENABLED=1`` у cosmo-api).
  5. Ожидание durable-следа: ``GET /api/v1/runs/{id}/evidence`` → запись
     ``raw_response`` c ``artifact://…sast-report`` (захват из логов маркера).
  6. Негатив: repo-секрет ``sonar_host_url`` → недостижимый хост → НОВЫЙ run →
     шаг падает честно → alert-след ``cosmo-sast-report-missing``; секрет восстановлен.
  7. Вердикт PASS/FAIL + сводка.

Env:
  COSMO_API_URL       default http://127.0.0.1:8100
  COSMO_API_EMAIL     default admin@cosmoport.local
  COSMO_API_PASSWORD  default cosmo-admin-dev
  SAST_CE_HOST_URL    default http://host.docker.internal:9000 (как CE виден ИЗ ШАГА)
  COSMO_GITEA_URL / COSMO_WOODPECKER_URL / COSMO_FORGE_* / COSMO_PG_CONTAINER — как COS-188
  VAULT_ADDR / VAULT_APPROLE_ROLE_ID / VAULT_APPROLE_SECRET_ID — AppRole (services/.env)

Usage:
  python services/scripts/seed-sast-fixture.py
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
import urllib.parse
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

API = os.getenv("COSMO_API_URL", "http://127.0.0.1:8100").rstrip("/")
EMAIL = os.getenv("COSMO_API_EMAIL", "admin@cosmoport.local")
PASSWORD = os.getenv("COSMO_API_PASSWORD", "cosmo-admin-dev")
GITEA = os.getenv("COSMO_GITEA_URL", "http://127.0.0.1:3100").rstrip("/")
WP = os.getenv("COSMO_WOODPECKER_URL", "http://127.0.0.1:8000").rstrip("/")
GITEA_USER = os.getenv("COSMO_FORGE_USER", "cosmo")
GITEA_PASSWORD = os.getenv("COSMO_FORGE_ADMIN_PASSWORD", "cosmo-admin-dev")
PG = os.getenv("COSMO_PG_CONTAINER", "cosmo-postgres")
CE_HOST_URL = os.getenv("SAST_CE_HOST_URL", "http://host.docker.internal:9000").rstrip("/")
DEAD_CE_HOST_URL = "http://127.0.0.1:9099"  # негатив: недостижимый порт из шага

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)
REPO_NAME = "sast-fixture"
REPO_FULL = f"{GITEA_USER}/{REPO_NAME}"
BRANCH = "main"
PROJECT_KEY = "cosmo__sast-fixture"
DOMAIN_ID = "dom-sast-fixture"
APP_ID = "app-sast-fixture"
BRICK_ID = "sast-sonarqube"
CONFIG_PATH = ".woodpecker.yml"

CONFIG_CONTENT = """\
steps:
  - name: sonar-scan
    image: sonarsource/sonar-scanner-cli:latest
    environment:
      SONAR_HOST_URL:
        from_secret: sonar_host_url
      SONAR_TOKEN:
        from_secret: sonar_token
    commands:
      - sonar-scanner -Dsonar.host.url=$SONAR_HOST_URL -Dsonar.token=$SONAR_TOKEN -Dsonar.projectKey=cosmo__sast-fixture -Dsonar.sources=app -Dsonar.projectBaseDir=. -Dsonar.scm.disabled=true
  - name: sonar-report
    image: python:3.12-slim
    depends_on: [sonar-scan]
    environment:
      SONAR_HOST_URL:
        from_secret: sonar_host_url
      SONAR_TOKEN:
        from_secret: sonar_token
      SONAR_PROJECT_KEY: cosmo__sast-fixture
    commands:
      - python sast_report.py
"""

SAMPLE_CONTENT = '''\
"""SAST fixture sample: deliberate findings for the source-SAST smoke (SAST-STEP-1/GATE-3)."""

import hashlib

DB_PASSWORD = "SuperSecret123!"  # deliberate hard-coded credential (S2068/S6418)

# Deliberate FAKE GitHub PAT (S6418 secret detection, BLOCKER -> канон Critical).
# Не является реальным токеном: фикстура stand-контура.
GITHUB_TOKEN = "ghp_Ab1Cd2Ef3Gh4Ij5Kl6Mn7Op8Qr9St0UvWxYz"


def hash_password(password: str) -> str:
    """Deliberate weak hash (S4790, CRITICAL): MD5 для пароля."""
    return hashlib.md5(password.encode()).hexdigest()


def find_user(cursor, name: str):
    """Deliberate SQL-injection (S2077): форматирование SQL-строки."""
    cursor.execute("SELECT * FROM users WHERE name = '%s'" % name)


def dsn() -> str:
    return "postgres://app:" + DB_PASSWORD + "@db:5432/app"
'''

REPORT_SCRIPT_CONTENT = '''\
#!/usr/bin/env python3
"""SAST fixture report step: SonarQube CE issues -> JSON + canonical marker (SAST-STEP-1/GATE-3).

Гонка (вскрыта live-прогоном GATE-3): sonar-scanner завершается раньше, чем CE
обработает отчёт (результаты CE видны с задержкой ~40 c) → imemediate-запрос
issues/search давал пустой отчёт. Шаг сначала дожидается обработки CE-задач.
"""
import base64
import datetime
import gzip
import hashlib
import json
import os
import sys
import time
import urllib.parse
import urllib.request

MARKER = "[prettyk-sast-report]"
HOST = os.environ.get("SONAR_HOST_URL", "").rstrip("/")
TOKEN = os.environ.get("SONAR_TOKEN", "")
PROJECT = os.environ.get("SONAR_PROJECT_KEY", "")
OUT = os.environ.get("SAST_REPORT_FILE", "sonar-report.json")


def _ts(value: str) -> float:
    try:
        return datetime.datetime.strptime(value, "%Y-%m-%dT%H:%M:%S%z").timestamp()
    except Exception:  # noqa: BLE001
        return 0.0


def wait_for_ce(started_at: float, timeout_s: int = 240) -> None:
    """Дождаться, пока CE обработает анализ этого запуска (иначе пустой отчёт)."""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        query = urllib.parse.urlencode({"component": PROJECT, "ps": "5"})
        request = urllib.request.Request(
            f"{HOST}/api/ce/activity?{query}",
            headers={"Authorization": f"Bearer {TOKEN}"})
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                activity = json.loads(response.read().decode("utf-8"))
        except Exception as exc:  # noqa: BLE001
            print(f"ce-activity unavailable ({exc}); continuing", file=sys.stderr)
            return
        tasks = activity.get("tasks") or []
        pending = [t for t in tasks if t.get("status") in ("PENDING", "IN_PROGRESS")]
        done = [t for t in tasks if t.get("status") == "SUCCESS"
                and _ts(str(t.get("executedAt") or t.get("submittedAt") or "")) >= started_at - 120]
        if not pending and done:
            return
        time.sleep(5)


def fetch_issues() -> dict:
    query = urllib.parse.urlencode(
        {"componentKeys": PROJECT, "resolved": "false", "ps": "500"})
    request = urllib.request.Request(
        f"{HOST}/api/issues/search?{query}",
        headers={"Authorization": f"Bearer {TOKEN}"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> int:
    if not (HOST and TOKEN and PROJECT):
        sys.exit("missing SONAR_HOST_URL / SONAR_TOKEN / SONAR_PROJECT_KEY")
    wait_for_ce(time.time())
    data = fetch_issues()
    report = json.dumps(
        {"source": "sonarqube", "project_key": PROJECT,
         "total": data.get("total"), "issues": data.get("issues", [])},
        sort_keys=True, ensure_ascii=False,
    ).encode("utf-8")
    with open(OUT, "wb") as fh:
        fh.write(report)
    digest = hashlib.sha256(report).hexdigest()
    print(f"{MARKER} format=ce-issues sha256={digest} bytes={len(report)} "
          f"b64={base64.b64encode(gzip.compress(report)).decode('ascii')}")
    print(f"sast-report: total={data.get('total')} file={OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''

FIXTURE_FILES = {
    CONFIG_PATH: CONFIG_CONTENT,
    "app/sample.py": SAMPLE_CONTENT,
    "sast_report.py": REPORT_SCRIPT_CONTENT,
}

PASSED: list[str] = []
FAILED: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    (PASSED if ok else FAILED).append(name)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


# ── HTTP / DB helpers (зеркало COS-188) ───────────────────────────────────

def _request(url: str, *, method: str = "GET", body: dict | None = None,
             token: str | None = None, basic: tuple[str, str] | None = None,
             extra_headers: dict[str, str] | None = None
             ) -> tuple[int, object]:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if basic:
        raw = base64.b64encode(f"{basic[0]}:{basic[1]}".encode()).decode()
        headers["Authorization"] = f"Basic {raw}"
    if extra_headers:
        headers.update(extra_headers)
    data = json.dumps(body).encode() if body is not None else None
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
            return exc.code, json.loads(payload) if payload else {}
        except ValueError:
            return exc.code, {"raw": payload[:300]}


def _tolerate(status: int, *, ok: tuple[int, ...], what: str) -> None:
    if status not in ok:
        raise SystemExit(f"[FAIL] {what}: HTTP {status}")


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


# ── OpenBao ───────────────────────────────────────────────────────────────

def read_sast_secret() -> dict:
    role_id = os.getenv("VAULT_APPROLE_ROLE_ID", "").strip()
    secret_id = os.getenv("VAULT_APPROLE_SECRET_ID", "").strip()
    if not role_id or not secret_id:
        raise SystemExit("[FAIL] VAULT_APPROLE_ROLE_ID/SECRET_ID не заданы (services/.env)")
    from orchestrator.cosmo.infra.vault import VaultClient
    vault = VaultClient()
    vault.authenticate()
    try:
        data = vault.read_secret("sast") or {}
    except Exception:  # noqa: BLE001
        data = {}
    if not data.get("token"):
        raise SystemExit("[FAIL] secret/cosmo/sast пуст — сначала seed-sonar-stand.py")
    return data


# ── Gitea ─────────────────────────────────────────────────────────────────

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


def ensure_file(path: str, content: str) -> None:
    base = f"{GITEA}/api/v1/repos/{REPO_FULL}/contents/{path}"
    code, body = _request(base, basic=(GITEA_USER, GITEA_PASSWORD))
    if code == 200 and isinstance(body, dict):
        current_b64 = str(body.get("content") or "").replace("\n", "")
        try:
            current = base64.b64decode(current_b64).decode("utf-8")
        except Exception:  # noqa: BLE001
            current = ""
        if current == content:
            print(f"[gitea] {path} in sync — PRESERVED")
            return
        code, body = _request(base, method="PUT", basic=(GITEA_USER, GITEA_PASSWORD),
                              body={"content": base64.b64encode(content.encode()).decode(),
                                    "message": f"seed: sync {path} (SAST-STEP-1)",
                                    "sha": body.get("sha"), "branch": BRANCH})
        if code not in (200, 201):
            raise SystemExit(f"[FAIL] {path} update: HTTP {code} {body}")
        print(f"[gitea] {path} updated (content drift)")
        return
    code, body = _request(base, method="POST", basic=(GITEA_USER, GITEA_PASSWORD),
                          body={"content": base64.b64encode(content.encode()).decode(),
                                "message": f"seed: add {path} (SAST-STEP-1)",
                                "branch": BRANCH})
    if code not in (200, 201):
        raise SystemExit(f"[FAIL] {path} create: HTTP {code} {body}")
    print(f"[gitea] {path} created")


# ── Woodpecker ────────────────────────────────────────────────────────────

def ensure_wp_user(pat: str, gitea_uid: str) -> None:
    code, uid = _psql(f"select id from users where login='{GITEA_USER}';")
    if code != 0:
        raise SystemExit("[FAIL] WP DB not reachable (docker/psql?)")
    if uid:
        _psql(f"update users set access_token='{pat}', expiry=4102444800, "
              f"admin=true, forge_id=1, forge_remote_id='{gitea_uid}', "
              f"email='{GITEA_USER}@cosmoport.local' where id={uid};")
        print(f"[wp] user '{GITEA_USER}' refreshed — forge access PRESERVED")
        return
    user_hash = base64.b32encode(secrets.token_bytes(32)).decode()
    _psql("insert into users (forge_id, forge_remote_id, login, email, admin, hash, "
          f"access_token, refresh_token, expiry) values (1, '{gitea_uid}', "
          f"'{GITEA_USER}', '{GITEA_USER}@cosmoport.local', true, '{user_hash}', "
          f"'{pat}', '', 4102444800);")
    print(f"[wp] user '{GITEA_USER}' created (admin, forge-bound)")


def ensure_pat(current_pat: str) -> str:
    if current_pat:
        code, _ = _request(f"{GITEA}/api/v1/user", token=current_pat)
        if code == 200:
            print("[gitea] PAT valid — PRESERVED")
            return current_pat
    name = f"cosmo-sast-fixture-{int(time.time())}"
    code, body = _request(f"{GITEA}/api/v1/users/{GITEA_USER}/tokens", method="POST",
                          body={"name": name, "scopes": ["all"]},
                          basic=(GITEA_USER, GITEA_PASSWORD))
    if code not in (200, 201) or not isinstance(body, dict):
        raise SystemExit(f"[FAIL] gitea PAT create: HTTP {code} {body}")
    pat = body.get("sha1") or body.get("token") or ""
    if not pat:
        raise SystemExit("[FAIL] gitea PAT response has no token")
    print(f"[gitea] PAT created ({name})")
    return pat


def ensure_activated(token: str, forge_remote_id: int) -> dict:
    code, body = _request(f"{WP}/api/repos/lookup/{REPO_FULL}", token=token)
    if code == 200 and isinstance(body, dict) and body.get("id"):
        print(f"[wp] repo active (id={body.get('id')}) — PRESERVED")
        return body
    code, body = _request(f"{WP}/api/repos?forge_remote_id={forge_remote_id}",
                          method="POST", token=token)
    if code not in (200, 201):
        raise SystemExit(f"[FAIL] repo activate: HTTP {code} {body}")
    code, body = _request(f"{WP}/api/repos/lookup/{REPO_FULL}", token=token)
    if code != 200 or not isinstance(body, dict):
        raise SystemExit(f"[FAIL] repo lookup after activate: HTTP {code} {body}")
    print(f"[wp] repo activated (id={body.get('id')})")
    return body


def ensure_config_file_set(token: str, repo_id: int) -> None:
    code, body = _request(f"{WP}/api/repos/{repo_id}", method="PATCH",
                          body={"config_file": CONFIG_PATH}, token=token)
    if code != 200:
        raise SystemExit(f"[FAIL] repo config_file PATCH: HTTP {code} {body}")
    print(f"[wp] repo config_file = {CONFIG_PATH}")


def ensure_secret(token: str, repo_id: int, name: str, value: str) -> str:
    """Repo-секрет: создать или обновить (значение — из секретницы/env).

    WP v3.5 требует `events` (для каких событий секрет виден шагам);
    стенд-прогоны идут `manual` (+ `push` для вебхуков).
    """
    payload = {"value": value, "events": ["manual", "push"]}
    code, body = _request(f"{WP}/api/repos/{repo_id}/secrets", method="POST",
                          token=token, body={"name": name, **payload})
    if code in (200, 201):
        return "created"
    quoted = urllib.parse.quote(name, safe="")
    code2, body2 = _request(f"{WP}/api/repos/{repo_id}/secrets/{quoted}",
                            method="PATCH", token=token, body=payload)
    if code2 in (200, 201):
        return "updated"
    raise SystemExit(f"[FAIL] secret {name}: POST {code} {body}; PATCH {code2} {body2}")


# ── Cosmo API ─────────────────────────────────────────────────────────────

def api_login() -> str:
    code, body = _request(f"{API}/api/v1/auth/login", method="POST",
                          body={"email": EMAIL, "password": PASSWORD})
    _tolerate(code, ok=(200,), what="login")
    token = str((body or {}).get("access_token") or "")
    if not token:
        raise SystemExit("[FAIL] login response has no access_token")
    return token


def ensure_binding(token: str) -> tuple[str, str]:
    """Свой домен + app-binding на фикстуру (idempotent).

    Домен-контекст обязателен: run/evidence-ручки резолвят caller-domain
    (X-Cosmo-Domain) и ghost-404'ят при несовпадении (COS-061/067).
    """
    code, body = _request(f"{API}/api/v1/domains", method="POST", token=token,
                          body={"id": DOMAIN_ID, "label": "SAST fixture domain (SAST-STEP-1)",
                                "forge_binding": {"forge_type": "gitea",
                                                  "url": "http://gitea",
                                                  "token_ref": "vault:secret/data/sast"}})
    _tolerate(code, ok=(200, 201, 409, 422), what=f"domain {DOMAIN_ID}")
    # app пересоздаём детерминированно в НАШЕМ домене (старый мог осесть в чужом).
    code, _ = _request(f"{API}/api/v1/apps/{APP_ID}", method="DELETE", token=token,
                       extra_headers={"X-Cosmo-Domain": DOMAIN_ID})
    if code not in (200, 204, 404):
        print(f"[cosmo] warn: delete app {APP_ID}: HTTP {code}")
    code, _ = _request(f"{API}/api/v1/apps", method="POST", token=token,
                       extra_headers={"X-Cosmo-Domain": DOMAIN_ID},
                       body={"id": APP_ID, "domain_id": DOMAIN_ID, "level": 1,
                             "repo_binding": {"forge_id": "gitea",
                                              "repo_path": REPO_FULL,
                                              "default_branch": BRANCH}})
    _tolerate(code, ok=(200, 201, 409), what=f"app {APP_ID} → {REPO_FULL}")
    print(f"[cosmo] domain {DOMAIN_ID}; app {APP_ID} → {REPO_FULL}")
    return DOMAIN_ID, APP_ID


def ensure_brick(token: str) -> None:
    """Кирпич source-SAST в каталоге (idempotent upsert).

    Канон brick-дефиниции — {executor, image, inputs, timeout_s}; фактическая
    скан-команда живёт в ``.woodpecker.yml`` репозитория (её исполняет шаг),
    не в каталоге.
    """
    definition = {
        "executor": "woodpecker",
        "image": "sonarsource/sonar-scanner-cli:latest",
        "timeout_s": 1200,
        "inputs": {"SONAR_PROJECT_KEY": PROJECT_KEY},
    }
    payload = {"name": "Sonar SAST", "type": "sast", "source": "internal",
               "definition": definition}
    code, body = _request(f"{API}/api/v1/bricks", method="POST", token=token,
                          extra_headers={"X-Cosmo-Domain": DOMAIN_ID},
                          body={"id": BRICK_ID, **payload})
    if code in (200, 201):
        print(f"[cosmo] brick {BRICK_ID} created")
        return
    if code == 409:
        code2, body2 = _request(f"{API}/api/v1/bricks/{BRICK_ID}", method="PUT",
                                token=token,
                                extra_headers={"X-Cosmo-Domain": DOMAIN_ID},
                                body=payload)
        if code2 not in (200, 201):
            raise SystemExit(f"[FAIL] brick {BRICK_ID} update: HTTP {code2} {body2}")
        print(f"[cosmo] brick {BRICK_ID} exists — synced")
        return
    raise SystemExit(f"[FAIL] brick {BRICK_ID}: HTTP {code} {body}")


def start_run(token: str, domain_id: str, tag: str,
              *, gate_policy: dict | None = None,
              gate_id_suffix: str = "") -> str:
    plan_id = f"plan-sast-{tag}"
    run_id = f"run-sast-{tag}"
    domain_header = {"X-Cosmo-Domain": domain_id}
    code, body = _request(f"{API}/api/v1/plans/compile", method="POST", token=token,
                          extra_headers=domain_header,
                          body={"plan_id": plan_id, "app_id": APP_ID,
                                "brick_ids": [BRICK_ID]})
    _tolerate(code, ok=(200, 201, 409), what=f"plans/compile {plan_id}")
    if gate_policy is not None:
        gate_id = f"gate-sast-{tag}{gate_id_suffix}"
        code, body = _request(f"{API}/api/v1/gates", method="POST", token=token,
                              extra_headers=domain_header,
                              body={"id": gate_id, "plan_id": plan_id,
                                    "type": "automatic", "position": 0,
                                    "policy": gate_policy})
        _tolerate(code, ok=(200, 201, 409), what=f"gates POST {gate_id}")
        print(f"[cosmo] gate {gate_id} policy={json.dumps(gate_policy, ensure_ascii=False)}")
    code, body = _request(f"{API}/api/v1/runs", method="POST", token=token,
                          extra_headers=domain_header,
                          body={"id": run_id, "plan_id": plan_id, "trigger": "manual",
                                "domain_id": domain_id,
                                "initiator_user_id": "sast-fixture-seed",
                                "initiator_role": "secops"})
    _tolerate(code, ok=(200, 201), what=f"runs POST {run_id}")
    code, body = _request(f"{API}/api/v1/runs/{run_id}/status", method="PATCH",
                          token=token, extra_headers=domain_header,
                          body={"status": "running"})
    _tolerate(code, ok=(200, 201, 204), what=f"run {run_id} → running")
    print(f"[cosmo] run {run_id} → running (plan {plan_id})")
    return run_id


def wait_evidence_source(token: str, run_id: str, source: str,
                         timeout_s: int = 300) -> tuple[dict | None, dict]:
    """Ждать evidence-запись с source == source. Возвращает (entry, chain).

    Форма ручки `/runs/{id}/evidence`: `chain.entries[] = {index, type, content,
    provenance, hash, ...}`; поля provenance_json из БД лежат в `content`
    (совместимо с raw-формой `provenance_json`).
    """
    deadline = time.time() + timeout_s
    chain: dict = {}
    while time.time() < deadline:
        code, body = _request(f"{API}/api/v1/runs/{run_id}/evidence", token=token,
                              extra_headers={"X-Cosmo-Domain": DOMAIN_ID})
        if code == 200 and isinstance(body, dict):
            chain = body
            entries = ((body.get("chain") or {}).get("entries")) or []
            for entry in entries:
                payload = entry.get("content") or entry.get("provenance_json") or {}
                if isinstance(payload, dict) and payload.get("source") == source:
                    return entry, body
        time.sleep(5)
    return None, chain


def wait_batch_status(token: str, plan_id: str, expect: set[str],
                      timeout_s: int = 300) -> list[str]:
    """Ждать терминального статуса всех batch'ей плана (Cosmo SoT)."""
    deadline = time.time() + timeout_s
    last: list[str] = []
    while time.time() < deadline:
        code, body = _request(f"{API}/api/v1/batches?plan_id={plan_id}", token=token,
                              extra_headers={"X-Cosmo-Domain": DOMAIN_ID})
        if code == 200 and isinstance(body, list) and body:
            last = [str(b.get("status")) for b in body]
            if all(s in expect for s in last):
                return last
        time.sleep(5)
    return last


def wait_run_status(token: str, run_id: str, expect: set[str],
                    timeout_s: int = 420) -> str:
    """Ждать терминального run-статуса (Cosmo SoT)."""
    deadline = time.time() + timeout_s
    last = ""
    while time.time() < deadline:
        code, body = _request(f"{API}/api/v1/runs/{run_id}", token=token,
                              extra_headers={"X-Cosmo-Domain": DOMAIN_ID})
        if code == 200 and isinstance(body, dict):
            last = str(body.get("status") or "")
            if last in expect:
                return last
        time.sleep(4)
    return last


def _cosmo_psql(sql: str) -> tuple[int, str]:
    """PSQL в БД `cosmo` (gate decisions / notifications) — не WP-база."""
    r = subprocess.run(
        ["docker", "exec", PG, "psql", "-U", "cosmo", "-d", "cosmo",
         "-t", "-A", "-c", sql],
        capture_output=True, text=True, timeout=30,
    )
    return r.returncode, r.stdout.strip()


def run_verdict_evidence(run_id: str) -> int:
    """Кол-во durable decision-записей решения гейта у прогона (SAST-GATE-3)."""
    code, out = _cosmo_psql(
        "select count(*) from evidence_ledger "
        f"where run_id='{run_id}' and type='decision';")
    return int(out or 0) if code == 0 else -1


def run_blocked_notification(run_id: str) -> dict | None:
    """Последний run_blocked outbox-ивент прогона (проводка наружу)."""
    code, out = _cosmo_psql(
        "select payload::text from notification_events "
        f"where event_type='run_blocked' and aggregate_id='{run_id}' "
        "order by created_at desc limit 1;")
    if code != 0 or not out:
        return None
    try:
        return json.loads(out)
    except ValueError:
        return None


def wp_latest_pipeline(wp_token: str, repo_id: int) -> dict:
    code, body = _request(f"{WP}/api/repos/{repo_id}/pipelines?limit=1", token=wp_token)
    items = body if isinstance(body, list) else []
    return items[0] if items else {}


def wp_pipeline_detail(wp_token: str, repo_id: int, number: int) -> dict:
    code, body = _request(f"{WP}/api/repos/{repo_id}/pipelines/{number}", token=wp_token)
    return body if isinstance(body, dict) else {}


def wp_step_states(detail: dict) -> dict[str, str]:
    states: dict[str, str] = {}
    for wf in detail.get("workflows") or []:
        for st in wf.get("steps") or wf.get("children") or []:
            name = st.get("name")
            if name:
                states[str(name)] = str(st.get("state"))
    return states


def wp_step_log_text(wp_token: str, repo_id: int, number: int, detail: dict,
                     step_name: str) -> str:
    for wf in detail.get("workflows") or []:
        for st in wf.get("steps") or wf.get("children") or []:
            if str(st.get("name")) != step_name or st.get("id") is None:
                continue
            code, body = _request(
                f"{WP}/api/repos/{repo_id}/logs/{number}/{st.get('id')}", token=wp_token)
            if code == 200 and isinstance(body, list):
                lines = []
                for entry in body:
                    raw = entry.get("data") if isinstance(entry, dict) else None
                    if raw is not None:
                        try:
                            lines.append(base64.b64decode(raw).decode("utf-8", "replace"))
                        except Exception:  # noqa: BLE001
                            lines.append(str(raw))
                    elif isinstance(entry, dict):
                        lines.append(str(entry.get("line", entry.get("message", ""))))
                return "".join(lines)
    return ""


# ── main ──────────────────────────────────────────────────────────────────

def main() -> int:
    print("=== SAST-STEP-1: source-SAST live fixture seed ===")
    sast = read_sast_secret()
    sonar_token = str(sast.get("token") or "")
    print(f"[vault] secret/cosmo/sast: token present (masked), url={sast.get('url')}")

    gitea = ensure_repo()
    for path, content in FIXTURE_FILES.items():
        ensure_file(path, content)

    code, current_pat = _psql(f"select access_token from users where login='{GITEA_USER}';")
    pat = ensure_pat(current_pat if code == 0 else "")
    ensure_wp_user(pat, str(gitea.get("id")))

    wp_token = wp_token_for(GITEA_USER)
    active = ensure_activated(wp_token, int(gitea.get("id")))
    wp_repo_id = int(active.get("id"))
    ensure_config_file_set(wp_token, wp_repo_id)
    print(f"[wp] secret sonar_token: {ensure_secret(wp_token, wp_repo_id, 'sonar_token', sonar_token)}")
    print(f"[wp] secret sonar_host_url: {ensure_secret(wp_token, wp_repo_id, 'sonar_host_url', CE_HOST_URL)}")

    api_token = api_login()
    domain_id, _app = ensure_binding(api_token)
    ensure_brick(api_token)

    tag = f"{int(time.time())}"
    print("")
    print("--- RUN #1: happy path (CE достижим) + гейт Critical/High → block ---")
    plan1 = f"plan-sast-{tag}-ok"
    gate1_policy = {"rules": [
        {"finding_type": "Critical", "action": "block"},
        {"finding_type": "High", "action": "block"},
    ]}
    run1 = start_run(api_token, domain_id, f"{tag}-ok", gate_policy=gate1_policy)
    entry, chain1 = wait_evidence_source(api_token, run1, "sonarqube")
    check("run#1: raw_response-отчёт захвачен durable",
          entry is not None,
          (json.dumps(entry.get("content") if entry else
                      {"total_entries": chain1.get("total_entries")}, ensure_ascii=False)[:220]))
    if entry is not None:
        payload = entry.get("content") or {}
        check("run#1: content_ref = artifact://…sast-report",
              "artifact://" in str(payload.get("content_ref") or ""),
              str(payload.get("content_ref")))
        check("run#1: chain verified", chain1.get("verified") is True,
              f"integrity={chain1.get('integrity')}")
        art_path = str(payload.get("artifact_path") or "")
        if art_path:
            probe = subprocess.run(
                ["docker", "exec", "cosmo-api", "sh", "-c",
                 f"test -s /app/cosmo-evidence/{art_path} && echo OK"],
                capture_output=True, text=True, timeout=30)
            check("run#1: файл отчёта durable в artifact store",
                  "OK" in probe.stdout, art_path)
    statuses1 = wait_batch_status(api_token, plan1, {"passed", "failed"})
    check("run#1: Cosmo batch passed", bool(statuses1) and all(s == "passed" for s in statuses1),
          str(statuses1))
    pl1 = wp_latest_pipeline(wp_token, wp_repo_id)
    num1 = int(pl1.get("number") or 0)
    det1 = wp_pipeline_detail(wp_token, wp_repo_id, num1) if num1 else {}
    states1 = wp_step_states(det1)
    check("run#1: WP pipeline success, шаги success",
          str(pl1.get("status")) == "success"
          and states1.get("sonar-scan") == "success"
          and states1.get("sonar-report") == "success",
          f"#{num1} {pl1.get('status')} {states1}")
    if num1:
        marker_log = wp_step_log_text(wp_token, wp_repo_id, num1, det1, "sonar-report")
        check("run#1: канонический маркер отчёта в логах шага",
              "[prettyk-sast-report]" in marker_log,
              f"chars={len(marker_log)}")
        check("run#1: секрет не светится в логах шага",
              sonar_token not in marker_log and "squ_" not in marker_log,
              "token masked")

    # SAST-GATE-3: findings → гейт-вердикт (авто-ingest отчёта) + durable/проводка.
    run1_status = wait_run_status(api_token, run1, {"blocked", "succeeded", "failed"})
    code, run1_body = _request(f"{API}/api/v1/runs/{run1}", token=api_token,
                               extra_headers={"X-Cosmo-Domain": domain_id})
    findings1 = (run1_body or {}).get("findings") or []
    sevs1 = [str(f.get("severity")) for f in findings1 if isinstance(f, dict)]
    check("run#1: findings авто-ingest'ятся из отчёта в прогон (мост COS-101)",
          len(findings1) >= 1, f"findings={len(findings1)} severities={sevs1}")
    check("run#1: гейт заблокировал прогон по политике (Critical/High → block)",
          run1_status == "blocked", f"status={run1_status}")
    decision_entries1 = run_verdict_evidence(run1)
    check("run#1: durable decision-след решения гейта",
          decision_entries1 >= 1, f"decision_entries={decision_entries1}")
    nb1 = run_blocked_notification(run1) or {}
    check("run#1: решение ушло наружу (run_blocked: reason + gate_decisions)",
          nb1.get("reason") == "gate_blocked" and bool(nb1.get("gate_decisions")),
          json.dumps(nb1, ensure_ascii=False)[:220])

    print("")
    print("--- RUN #2: negative (CE недостижим из шага) ---")
    print(f"[wp] secret sonar_host_url → {DEAD_CE_HOST_URL} (temp)")
    ensure_secret(wp_token, wp_repo_id, "sonar_host_url", DEAD_CE_HOST_URL)
    try:
        plan2 = f"plan-sast-{tag}-neg"
        run2 = start_run(api_token, domain_id, f"{tag}-neg")
        statuses2 = wait_batch_status(api_token, plan2, {"passed", "failed"})
        check("run#2: Cosmo batch честно failed (не фейк-pass)",
              bool(statuses2) and all(s == "failed" for s in statuses2),
              str(statuses2))
        pl2 = wp_latest_pipeline(wp_token, wp_repo_id)
        num2 = int(pl2.get("number") or 0)
        det2 = wp_pipeline_detail(wp_token, wp_repo_id, num2) if num2 else {}
        states2 = wp_step_states(det2)
        check("run#2: WP pipeline не success",
              str(pl2.get("status")) in ("failure", "error"),
              f"#{num2} {pl2.get('status')}")
        check("run#2: шаг sonar-scan упал честно (failure)",
              states2.get("sonar-scan") in ("failure", "error"),
              f"states={states2}")
        check("run#2: report-шаг не сфабриковал отчёт (не success)",
              states2.get("sonar-report") not in ("success",),
              f"states={states2}")
        run2_status = wait_run_status(api_token, run2, {"blocked", "failed", "succeeded"})
        check("run#2: run терминально честный (blocked, не PASS)",
              run2_status == "blocked", f"status={run2_status}")
        nb2 = run_blocked_notification(run2) or {}
        check("run#2: причина видима наружу (run_blocked: batch_failed)",
              nb2.get("reason") == "batch_failed",
              json.dumps(nb2, ensure_ascii=False)[:180])
    finally:
        print("[wp] secret sonar_host_url → восстановлен")
        ensure_secret(wp_token, wp_repo_id, "sonar_host_url", CE_HOST_URL)

    print("")
    print("--- RUN #3: политика в пределах warn-порога → прогон проходит ---")
    gate3_policy = {"rules": [
        {"finding_type": "Critical", "action": "warn", "max_count": 100},
        {"finding_type": "High", "action": "warn", "max_count": 100},
    ]}
    run3 = start_run(api_token, domain_id, f"{tag}-pass", gate_policy=gate3_policy,
                     gate_id_suffix="-pass")
    run3_status = wait_run_status(api_token, run3,
                                  {"blocked", "succeeded", "failed"}, timeout_s=600)
    check("run#3: findings в пределах порога политики → succeeded (не блок)",
          run3_status == "succeeded", f"status={run3_status}")

    print("")
    print("=== summary ===")
    print(f"  repo      : {REPO_FULL} (wp id={wp_repo_id})")
    print(f"  project   : {PROJECT_KEY} @ {CE_HOST_URL}")
    print(f"  runs      : {run1} (ok), run2 (neg)")
    print(f"  PASSED={len(PASSED)} FAILED={len(FAILED)}")
    if FAILED:
        print("  FAILED:", FAILED)
        return 1
    print("SAST-STEP-1 LIVE SMOKE: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
