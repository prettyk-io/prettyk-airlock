# -*- coding: utf-8 -*-
"""SAST-STAND-4: идемпотентный сид SonarQube CE стенда Airlock.

Порядок:
  1. Ждём готовности CE: GET /api/system/status → status=UP (первый boot 2-5 мин).
  2. Admin-доступ (dev): admin/<пароль>; если дефолтный admin/admin отвергнут
     (CE требует смену) — меняем на COSMO_SONAR_ADMIN_PASSWORD и сохраняем в OpenBao.
  3. Токен сканера `prettyk-airlock`: валидный из OpenBao переиспользуется
     (PRESERVED); иначе revoke+generate и запись в OpenBao (kv-v2 secret/cosmo/sast).
  4. Проект по конвенции v1 `owner__repo` (CE без branch-analysis) — создаётся,
     если отсутствует; quality-profile `PrettyK` (copy `Sonar way`, py/ts)
     назначается проекту.

Идемпотентность: повторный запуск → PRESERVED (ничего не пересоздаётся).
Секреты — только в OpenBao (AppRole `cosmo-app`); токен в выводе маскируется.

Usage:
  python services/scripts/seed-sonar-stand.py [--repo owner/repo] [--url http://127.0.0.1:9000]

Env:
  SONAR_URL                (default http://127.0.0.1:9000)
  SONAR_ADMIN_LOGIN        (default admin)
  COSMO_SONAR_ADMIN_PASSWORD (default cosmo-sonar-admin-dev) — на случай смены дефолта
  VAULT_ADDR / VAULT_APPROLE_ROLE_ID / VAULT_APPROLE_SECRET_ID
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

import requests

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

try:  # Windows-консоль (cp1251): не падать на юникоде в выводе сида
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

SAST_SECRET = "sast"                     # kv-v2: secret/cosmo/sast
TOKEN_NAME = "prettyk-airlock"
PROFILE_NAME = "PrettyK"
PROFILE_LANGS = ("py", "ts")
PROJECT_KEY_CONVENTION = "owner__repo"

DEFAULT_URL = "http://127.0.0.1:9000"
DEFAULT_ADMIN_LOGIN = "admin"
DEFAULT_DEV_ADMIN_PASSWORD = "cosmo-sonar-admin-dev"


def _mask(value: str) -> str:
    if not value:
        return "***"
    return value[:6] + "..." if len(value) > 6 else "***"


def project_key_for(repo: str) -> str:
    """owner/repo → owner__repo (v1-конвенция; CE без branch-analysis)."""
    owner, _, name = repo.partition("/")
    return f"{owner}__{name}" if name else repo.replace("/", "__")


class SonarQube:
    """Минимальный клиент SonarQube API (basic для админ-операций, bearer для токена)."""

    def __init__(self, url: str) -> None:
        self.url = url.rstrip("/")
        self._basic: tuple[str, str] | None = None
        self._token: str | None = None
        self._s = requests.Session()

    # ── auth ──
    def with_basic(self, login: str, password: str) -> None:
        self._basic = (login, password)
        self._token = None

    def with_token(self, token: str) -> None:
        self._token = token

    def _kwargs(self, force_basic: bool = False) -> dict:
        if self._basic is not None and (force_basic or self._token is None):
            return {"auth": self._basic}
        if self._token:
            return {"headers": {"Authorization": f"Bearer {self._token}"}}
        return {}  # анонимные вызовы (status/wait_up) auth не требуют

    def req(self, method: str, path: str, params: dict | None = None,
            *, force_basic: bool = False) -> tuple[int, dict | None]:
        r = self._s.request(method, self.url + path, params=params,
                            timeout=60, **self._kwargs(force_basic))
        try:
            body = r.json()
        except ValueError:
            body = None
        return r.status_code, body

    # ── probes ──
    def wait_up(self, timeout_s: int = 420) -> bool:
        deadline = time.time() + timeout_s
        last: object = None
        while time.time() < deadline:
            try:
                code, body = self.req("GET", "/api/system/status")
                last = (code, (body or {}).get("status"))
                if code == 200 and (body or {}).get("status") == "UP":
                    return True
            except requests.RequestException as exc:  # noqa: PERF203 — поллинг
                last = f"conn-error: {exc}"
            time.sleep(5)
        print(f"ERROR: SonarQube не поднялся за {timeout_s}s (last={last})", file=sys.stderr)
        return False

    def validate(self, *, basic: bool = False) -> bool:
        code, body = self.req("GET", "/api/authentication/validate", force_basic=basic)
        return code == 200 and bool((body or {}).get("valid"))


def ensure_admin_access(client: SonarQube, login: str,
                        candidates: list[str], rotate_to: str) -> tuple[str | None, bool]:
    """Найти рабочий admin-пароль или сменить дефолт. Возвращает (пароль, rotated)."""
    for pw in candidates:
        if not pw:
            continue
        client.with_basic(login, pw)
        if client.validate(basic=True):
            return pw, False
    # Дефолт отвергнут (CE требует смену) → пробуем штатную смену с admin/admin.
    client.with_basic(login, "admin")
    code, body = client.req(
        "POST", "/api/users/change_password",
        {"login": login, "previousPassword": "admin", "password": rotate_to},
    )
    if code in (200, 204):
        client.with_basic(login, rotate_to)
        if client.validate(basic=True):
            return rotate_to, True
    print(
        f"ERROR: не удалось аутентифицироваться в SonarQube как {login!r} "
        f"(проверены кандидаты; смена дефолта → {code} {body}). "
        f"Задайте SONAR_ADMIN_PASSWORD или смените пароль через UI :9000.",
        file=sys.stderr,
    )
    return None, False


def ensure_token(client: SonarQube, login: str, admin_pw: str,
                 existing_token: str) -> tuple[str, bool]:
    """Валидный токен переиспользуем; иначе revoke+generate. (token, rotated)."""
    if existing_token:
        client.with_token(existing_token)
        if client.validate():
            return existing_token, False
    client.with_basic(login, admin_pw)
    client.req("POST", "/api/user_tokens/revoke", {"name": TOKEN_NAME})  # 404 → ok
    code, body = client.req("POST", "/api/user_tokens/generate", {"name": TOKEN_NAME})
    token = str((body or {}).get("token") or "")
    if code != 200 or not token:
        raise RuntimeError(f"user_tokens/generate → {code}: {body}")
    return token, True


def ensure_project(client: SonarQube, key: str, name: str) -> bool:
    """True — создан; False — уже существует (PRESERVED)."""
    code, body = client.req("GET", "/api/projects/search", {"projects": key})
    for comp in (body or {}).get("components", []):
        if comp.get("key") == key:
            return False
    code, body = client.req("POST", "/api/projects/create", {"project": key, "name": name})
    if code != 200:
        raise RuntimeError(f"projects/create → {code}: {body}")
    return True


def ensure_profile(client: SonarQube, lang: str) -> tuple[str | None, bool]:
    """Copy `Sonar way` → PrettyK для языка. (key|None, created)."""
    code, body = client.req("GET", "/api/qualityprofiles/search", {"language": lang})
    profiles = (body or {}).get("profiles") or []
    for p in profiles:
        if p.get("name") == PROFILE_NAME:
            return str(p.get("key") or ""), False
    src = next((p for p in profiles if p.get("name") == "Sonar way"), None)
    if src is None:
        return None, False  # язык не поддержан в CE → не применимо
    code, body = client.req(
        "POST", "/api/qualityprofiles/copy",
        {"fromKey": src["key"], "toName": PROFILE_NAME},
    )
    if code != 200:
        raise RuntimeError(f"qualityprofiles/copy({lang}) → {code}: {body}")
    code, body = client.req("GET", "/api/qualityprofiles/search", {"language": lang})
    for p in (body or {}).get("profiles") or []:
        if p.get("name") == PROFILE_NAME:
            return str(p.get("key") or ""), True
    return None, True


def assign_profile(client: SonarQube, lang: str, project: str) -> str:
    code, body = client.req(
        "POST", "/api/qualityprofiles/add_project",
        {"language": lang, "qualityProfile": PROFILE_NAME, "project": project},
    )
    if code in (200, 204):  # SonarQube отвечает 204 No Content на успех
        return "assigned"
    return f"skip ({code}: {(body or {}).get('errors', body)})"


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed SonarQube CE stand (SAST-STAND-4)")
    parser.add_argument("--repo", default="payments/api",
                        help="repo для smoke-проекта (default fixtures payments/api)")
    parser.add_argument("--url", default=os.getenv("SONAR_URL", DEFAULT_URL))
    args = parser.parse_args()

    login = os.getenv("SONAR_ADMIN_LOGIN", DEFAULT_ADMIN_LOGIN).strip() or DEFAULT_ADMIN_LOGIN
    rotate_to = os.getenv("COSMO_SONAR_ADMIN_PASSWORD", DEFAULT_DEV_ADMIN_PASSWORD)
    project_key = project_key_for(args.repo)

    role_id = os.getenv("VAULT_APPROLE_ROLE_ID", "").strip()
    secret_id = os.getenv("VAULT_APPROLE_SECRET_ID", "").strip()
    if not role_id or not secret_id:
        print("ERROR: VAULT_APPROLE_ROLE_ID and VAULT_APPROLE_SECRET_ID must be set",
              file=sys.stderr)
        return 2

    from orchestrator.cosmo.infra.vault import VaultClient

    vault = VaultClient()
    vault.authenticate()
    try:
        vault_data = vault.read_secret(SAST_SECRET) or {}
    except Exception:  # noqa: BLE001 — 404 → ещё не сидировано
        vault_data = {}

    client = SonarQube(args.url)
    if not client.wait_up():
        return 1
    print(f"[sonar] UP {args.url}")

    admin_pw, admin_rotated = ensure_admin_access(
        client, login,
        candidates=[
            os.getenv("SONAR_ADMIN_PASSWORD", "").strip(),
            str(vault_data.get("admin_password") or "").strip(),
            "admin",
        ],
        rotate_to=rotate_to,
    )
    if admin_pw is None:
        return 1
    print(f"[admin] {'ROTATED (default admin → env-пароль)' if admin_rotated else 'PRESERVED'}")

    token, token_rotated = ensure_token(
        client, login, admin_pw, str(vault_data.get("token") or "").strip())
    print(f"[token] {'ROTATED (revoke+generate)' if token_rotated else 'PRESERVED'} "
          f"name={TOKEN_NAME} value={_mask(token)}")

    created = ensure_project(client, project_key, args.repo)
    print(f"[project] {'CREATED' if created else 'PRESERVED'} key={project_key} "
          f"(convention {PROJECT_KEY_CONVENTION})")

    client.with_token(token)
    for lang in PROFILE_LANGS:
        key, prof_created = ensure_profile(client, lang)
        if key is None:
            print(f"[profile:{lang}] NOT-APPLICABLE (нет Sonar way в CE)")
            continue
        status = "CREATED" if prof_created else "PRESERVED"
        print(f"[profile:{lang}] {status} {PROFILE_NAME}")
        print(f"[profile:{lang}] {assign_profile(client, lang, project_key)} → {project_key}")

    if token_rotated or admin_rotated or not vault_data:
        vault.write_secret(SAST_SECRET, {
            "url": args.url.rstrip("/"),
            "token": token,
            "token_name": TOKEN_NAME,
            "admin_login": login,
            "admin_password": admin_pw,
            "project_key_convention": PROJECT_KEY_CONVENTION,
            "project_key": project_key,
            "profile": PROFILE_NAME,
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        })
        print(f"[openbao] secret/cosmo/{SAST_SECRET} WRITTEN (token masked)")
    else:
        print(f"[openbao] secret/cosmo/{SAST_SECRET} PRESERVED")
    print("SEED OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
