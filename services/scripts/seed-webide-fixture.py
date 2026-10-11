# -*- coding: utf-8 -*-
"""COS-179: self-seed live stand fixture for the Web IDE e2e (idempotent).

Создаёт ровно то, что нужно web-ide-спеку против живого стенда:

  1. Gitea: org ``payments`` + repo ``api`` (auto_init, branch ``main``)
     + файл ``scenarios/auth.wire`` (deep-link цель COS-100/179).
  2. PG (через production API): app-binding ``repo_path=payments/api``
     в первом существующем домене (или в созданном ``dom-webide``) —
     без binding'а workspace-роуты честно отдают 404 (anti-enumeration).

Аутентификация — реальный RS256 login (COS-157/158); dev-минтинг стенд
не принимает (COS-156). Скрипт идемпотентен: повторный запуск ничего не
ломает (409/422 существующих объектов терпятся), в конце печатает
bootstrap-сводку (branch/head_sha) — она же evidence.

Env:
  COSMO_API_URL             default http://127.0.0.1:8100
  COSMO_GITEA_URL           default http://127.0.0.1:3100
  COSMO_FORGE_USER          default cosmo
  COSMO_FORGE_ADMIN_PASSWORD default cosmo-admin-dev
  E2E_COSMO_EMAIL           default admin@cosmoport.local
  E2E_COSMO_PASSWORD        default cosmo-admin-dev

Usage:
  python services/scripts/seed-webide-fixture.py
"""
from __future__ import annotations

import base64
import json
import os
import sys
import urllib.error
import urllib.request

API = os.getenv("COSMO_API_URL", "http://127.0.0.1:8100").rstrip("/")
GITEA = os.getenv("COSMO_GITEA_URL", "http://127.0.0.1:3100").rstrip("/")
GITEA_USER = os.getenv("COSMO_FORGE_USER", "cosmo")
GITEA_PASSWORD = os.getenv("COSMO_FORGE_ADMIN_PASSWORD", "cosmo-admin-dev")
EMAIL = os.getenv("E2E_COSMO_EMAIL", "admin@cosmoport.local")
PASSWORD = os.getenv("E2E_COSMO_PASSWORD", "cosmo-admin-dev")

ORG = "payments"
REPO = "api"
REPO_FULL = f"{ORG}/{REPO}"
BRANCH = "main"
WIRE_PATH = "scenarios/auth.wire"
WIRE_CONTENT = (
    'navigate "https://bank.local/login"\n'
    'fill "#user", "admin"\n'
    'click "button[type=submit]"\n'
    'assert_url "/dashboard"\n'
)
DOMAIN_ID = "dom-webide"
APP_ID = "webide-api"


def _request(url: str, *, method: str = "GET", body: dict | None = None,
             token: str | None = None, basic: tuple[str, str] | None = None) -> tuple[int, dict]:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if basic:
        raw = base64.b64encode(f"{basic[0]}:{basic[1]}".encode()).decode()
        headers["Authorization"] = f"Basic {raw}"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
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


def login() -> str:
    status, body = _request(
        f"{API}/api/v1/auth/login", method="POST",
        body={"email": EMAIL, "password": PASSWORD},
    )
    _tolerate(status, ok=(200,), what="login")
    token = str(body.get("access_token") or "")
    if not token:
        raise SystemExit("[FAIL] login response has no access_token")
    return token


def ensure_gitea() -> None:
    status, _ = _request(
        f"{GITEA}/api/v1/orgs", method="POST", body={"username": ORG},
        basic=(GITEA_USER, GITEA_PASSWORD),
    )
    _tolerate(status, ok=(201, 409, 422), what=f"gitea org {ORG}")

    status, _ = _request(
        f"{GITEA}/api/v1/orgs/{ORG}/repos", method="POST",
        body={"name": REPO, "auto_init": True, "default_branch": BRANCH, "private": False},
        basic=(GITEA_USER, GITEA_PASSWORD),
    )
    _tolerate(status, ok=(201, 409, 422), what=f"gitea repo {REPO_FULL}")

    status, _ = _request(
        f"{GITEA}/api/v1/repos/{REPO_FULL}/contents/{WIRE_PATH}", method="POST",
        body={
            "content": base64.b64encode(WIRE_CONTENT.encode()).decode(),
            "message": "COS-179: Web IDE e2e fixture",
            "branch": BRANCH,
        },
        basic=(GITEA_USER, GITEA_PASSWORD),
    )
    _tolerate(status, ok=(201, 422, 409), what=f"gitea file {WIRE_PATH}")


def ensure_binding(token: str) -> str:
    status, domains = _request(f"{API}/api/v1/domains", token=token)
    _tolerate(status, ok=(200,), what="list domains")
    domain_id = domains[0]["id"] if isinstance(domains, list) and domains else ""

    if not domain_id:
        status, _ = _request(
            f"{API}/api/v1/domains", method="POST", token=token,
            body={
                "id": DOMAIN_ID,
                "label": "Web IDE fixture domain (COS-179)",
                "forge_binding": {
                    "forge_type": "gitea",
                    "url": "http://gitea",
                    "token_ref": "vault:secret/data/token",
                },
            },
        )
        _tolerate(status, ok=(200, 201, 409), what=f"domain {DOMAIN_ID}")
        domain_id = DOMAIN_ID

    status, _ = _request(
        f"{API}/api/v1/apps", method="POST", token=token,
        body={
            "id": APP_ID,
            "domain_id": domain_id,
            "level": 1,
            "repo_binding": {
                "forge_id": "gitea",
                "repo_path": REPO_FULL,
                "default_branch": BRANCH,
            },
        },
    )
    _tolerate(status, ok=(200, 201, 409), what=f"app {APP_ID} → {REPO_FULL}")
    return domain_id


def verify(token: str) -> dict:
    status, boot = _request(
        f"{API}/api/v1/repos/workspace/bootstrap?repo={REPO_FULL}", token=token,
    )
    _tolerate(status, ok=(200,), what="workspace bootstrap")
    status, tree = _request(
        f"{API}/api/v1/repos/tree?repo={REPO_FULL}"
        f"&branch={boot.get('branch')}&head_sha={boot.get('headSha')}",
        token=token,
    )
    _tolerate(status, ok=(200,), what="workspace tree (CAS)")
    entries = tree.get("entries") or []
    return {"bootstrap": boot, "tree_entries": len(entries)}


def main() -> int:
    token = login()
    ensure_gitea()
    domain_id = ensure_binding(token)
    info = verify(token)
    print(json.dumps({
        "ok": True,
        "repo": REPO_FULL,
        "file": WIRE_PATH,
        "domain_id": domain_id,
        "branch": info["bootstrap"].get("branch"),
        "head_sha": info["bootstrap"].get("headSha"),
        "tree_entries": info["tree_entries"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
