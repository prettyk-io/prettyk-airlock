# -*- coding: utf-8 -*-
"""COS-188 live-smoke: реальный Woodpecker-пайплайн → SSE log_chunk по проводу.

Проверяет путь COS-109/180 end-to-end на живом стенде:

  1. preflight: cosmo-api :8100, Woodpecker :8000, БД стенда;
  2. свежий реальный прогон пайплайна (WP API) → terminal=success;
  3. durable handle (INSERT в cosmo_execution_handles) на этот пайплайн
     для существующего pending-run (dev-приём: executor на стенде opt-in);
  4. SSE GET /api/v1/runs/{run}/logs/stream (ticket COS-075) — реальный провод;
  5. ассерты: step_start'ы (clone/prepare/verify), log_chunk с реальными
     строками логов пайплайна, терминальный run_finish;
  6. cleanup handle.

Self-skip (exit 0 + SKIP): стенд оффлайн / сид не выполнен / нет pending-run.
Сид выполнять заранее: services/scripts/seed-woodpecker-fixture.py.

Env:
  COSMO_API_URL         default http://127.0.0.1:8100
  COSMO_WOODPECKER_URL  default http://127.0.0.1:8000
  COSMO_PG_CONTAINER    default cosmo-postgres
  COSMO_FIXTURE_REPO    default cosmo/pipeline-fixture
  E2E_COSMO_EMAIL/PASSWORD  default admin@cosmoport.local / cosmo-admin-dev

Usage:
  python services/scripts/smoke-woodpecker-chunks.py
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

import requests

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

API = os.getenv("COSMO_API_URL", "http://127.0.0.1:8100").rstrip("/")
WP = os.getenv("COSMO_WOODPECKER_URL", "http://127.0.0.1:8000").rstrip("/")
PG = os.getenv("COSMO_PG_CONTAINER", "cosmo-postgres")
REPO_FULL = os.getenv("COSMO_FIXTURE_REPO", "cosmo/pipeline-fixture")
BRANCH = "main"
BATCH_ID = "cos188-chunks-smoke"
EMAIL = os.getenv("E2E_COSMO_EMAIL", "admin@cosmoport.local")
PASSWORD = os.getenv("E2E_COSMO_PASSWORD", "cosmo-admin-dev")

POLL_SECS = 150
SSE_DEADLINE_S = 45


def skip(reason: str) -> int:
    print(f"[SKIP] {reason}")
    return 0


# ── infra helpers ─────────────────────────────────────────────────────────

def psql(db: str, sql: str) -> str | None:
    try:
        r = subprocess.run(
            ["docker", "exec", PG, "psql", "-U", "cosmo", "-d", db,
             "-t", "-A", "-c", sql],
            capture_output=True, text=True, timeout=30,
        )
    except (subprocess.SubprocessError, FileNotFoundError):
        return None
    if r.returncode != 0:
        return None
    return r.stdout.strip()


def wp_jwt() -> str | None:
    uid = psql("cosmo_woodpecker", "select id from users where login='cosmo';")
    uhash = psql("cosmo_woodpecker", "select hash from users where login='cosmo';")
    if not uid or not uhash:
        return None
    if not psql("cosmo", "select 1;"):
        return None

    def b64u(d: bytes) -> str:
        return base64.urlsafe_b64encode(d).rstrip(b"=").decode()

    h = b64u(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    p = b64u(json.dumps({"user-id": uid, "type": "user"}, separators=(",", ":")).encode())
    s = hmac.new(uhash.encode(), f"{h}.{p}".encode(), hashlib.sha256).digest()
    return f"{h}.{p}.{b64u(s)}"


def api_json(method: str, path: str, *, token: str = "", body: dict | None = None,
             timeout: int = 60) -> tuple[int, object]:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"{API}{path}", data=data, headers=headers,
                                 method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = resp.read().decode("utf-8", "replace")
            return resp.status, (json.loads(payload) if payload else {})
    except urllib.error.HTTPError as exc:
        payload = exc.read().decode("utf-8", "replace")
        try:
            return exc.code, (json.loads(payload) if payload else {})
        except ValueError:
            return exc.code, {"raw": payload[:200]}
    except urllib.error.URLError:
        return 0, {}


def wp_json(method: str, path: str, token: str, *, body: dict | None = None,
            timeout: int = 90) -> tuple[int, object]:
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"{WP}{path}", data=data, headers=headers,
                                 method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = resp.read().decode("utf-8", "replace")
            return resp.status, (json.loads(payload) if payload else {})
    except urllib.error.HTTPError as exc:
        payload = exc.read().decode("utf-8", "replace")
        try:
            return exc.code, (json.loads(payload) if payload else {})
        except ValueError:
            return exc.code, {"raw": payload[:200]}
    except urllib.error.URLError:
        return 0, {}


# ── main flow ─────────────────────────────────────────────────────────────

def main() -> int:
    print("=== COS-188: run-log chunks live-smoke ===")

    # 0. preflight
    code, _ = api_json("GET", "/live")
    if code != 200:
        return skip(f"cosmo-api недоступен ({API})")
    token = wp_jwt()
    if token is None:
        return skip("Woodpecker user/БД недоступны (docker/psql?)")

    code, repo = wp_json("GET", f"/api/repos/lookup/{REPO_FULL}", token)
    if code == 404:
        return skip(f"repo '{REPO_FULL}' не активирован — прогони seed-woodpecker-fixture.py")
    if code != 200 or not isinstance(repo, dict):
        return skip(f"Woodpecker API недоступен (HTTP {code})")
    repo_id = int(repo["id"])

    # 1. свежий реальный прогон пайплайна
    code, run = wp_json("POST", f"/api/repos/{repo_id}/pipelines",
                        token, body={"branch": BRANCH})
    if code not in (200, 201) or not isinstance(run, dict):
        print(f"[FAIL] trigger pipeline: HTTP {code} {str(run)[:200]}")
        return 1
    number = int(run["number"])
    pipeline_id = int(run["id"])
    print(f"[wp] fixture pipeline #{number} triggered")

    deadline = time.time() + POLL_SECS
    status = "?"
    while time.time() < deadline:
        code, detail = wp_json("GET", f"/api/repos/{repo_id}/pipelines/{number}", token)
        status = str((detail or {}).get("status", "?"))
        if status in ("success", "failure", "error", "killed", "declined", "skipped"):
            break
        time.sleep(3)
    print(f"[wp] pipeline #{number} terminal: {status}")
    if status != "success":
        print("[FAIL] fixture pipeline не success — смотри шаги/логи в WP")
        return 1

    # 2. pending-run + durable handle
    run_id = psql("cosmo", "select id from runs where status='pending' "
                           "order by created_at desc limit 1;")
    if not run_id:
        return skip("в cosmo БД нет pending-run для якоря лог-стрима")
    ins = psql("cosmo", (
        "insert into cosmo_execution_handles (batch_id, run_id, plan_id, repo_id, "
        "repo_owner, repo_name, branch, wp_number, wp_pipeline_id, last_status, "
        "unknown_count, degraded, details_json, created_at, updated_at) values ("
        f"'{BATCH_ID}', '{run_id}', 'cos188-smoke', {repo_id}, 'cosmo', "
        f"'pipeline-fixture', '{BRANCH}', {number}, {pipeline_id}, 'success', 0, "
        "false, '{}'::jsonb, now(), now()) "
        "on conflict (batch_id) do update set run_id=excluded.run_id, "
        "wp_number=excluded.wp_number, wp_pipeline_id=excluded.wp_pipeline_id, "
        "last_status=excluded.last_status, updated_at=now() returning batch_id;"
    ))
    if not ins:
        print("[FAIL] не удалось посадить handle (psql)")
        return 1
    print(f"[db] handle '{BATCH_ID}' → run={run_id}, pipeline #{number}")

    try:
        # 3. auth + ticket
        code, auth = api_json("POST", "/api/v1/auth/login",
                              body={"email": EMAIL, "password": PASSWORD})
        if code != 200 or not isinstance(auth, dict):
            return skip(f"login недоступен (HTTP {code}) — смоук не воспроизводим")
        jwt_tok = str(auth.get("access_token") or "")
        code, t = api_json("POST", "/api/v1/notifications/sse-ticket", token=jwt_tok)
        ticket = str((t or {}).get("ticket") or "") if isinstance(t, dict) else ""
        if code != 200 or not ticket:
            return skip(f"sse-ticket не выдан (HTTP {code})")

        # 4. SSE лог-стрим — реальный провод
        events: list[dict] = []
        url = f"{API}/api/v1/runs/{run_id}/logs/stream"
        with requests.get(url, params={"ticket": ticket}, stream=True,
                          timeout=(10, 30)) as resp:
            if resp.status_code != 200:
                print(f"[FAIL] logs/stream HTTP {resp.status_code}: {resp.text[:150]}")
                return 1
            buf: dict = {}
            started = time.time()
            for raw in resp.iter_lines(decode_unicode=True):
                if time.time() - started > SSE_DEADLINE_S:
                    break
                line = raw or ""
                if line.startswith("event:"):
                    buf["event"] = line[6:].strip()
                elif line.startswith("data:"):
                    buf["data"] = buf.get("data", "") + line[5:].strip()
                elif line.startswith("id:"):
                    buf["id"] = line[3:].strip()
                elif line == "" and buf:
                    events.append(buf)
                    buf = {}
                    if events[-1].get("event") == "run_finish":
                        break
    finally:
        psql("cosmo", f"delete from cosmo_execution_handles where batch_id='{BATCH_ID}';")

    # 5. assertions
    starts = [e for e in events if e.get("event") == "step_start"]
    chunks = [e for e in events if e.get("event") == "log_chunk"]
    finish = [e for e in events if e.get("event") == "run_finish"]
    chunk_lines: list[str] = []
    for e in chunks:
        try:
            d = json.loads(e.get("data") or "{}")
        except ValueError:
            continue
        chunk_lines.extend(str(x) for x in (d.get("lines") or []))
    fixture_lines = [ln for ln in chunk_lines if "cosmo-fixture" in ln]

    print(f"[sse] events: {len(events)} (step_start={len(starts)}, "
          f"log_chunk={len(chunks)}, run_finish={len(finish)})")
    for e in starts[:6]:
        try:
            d = json.loads(e.get("data") or "{}")
        except ValueError:
            d = {}
        print(f"    step_start: {d.get('step_name')} (id={d.get('step_id')})")
    for ln in fixture_lines[:6]:
        print(f"    log_chunk | {ln}")

    ok = len(starts) >= 2 and len(fixture_lines) >= 2 and bool(finish)
    print(f"=== verdict: {'PASS' if ok else 'FAIL'} ===")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
