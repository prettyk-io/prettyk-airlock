# -*- coding: utf-8 -*-
"""COS-175: сидирование боевых auth-секретов в standalone OpenBao (AppRole).

Пишет в платформенный OpenBao (``prettyk-openbao``, сеть ``pk-infra``) через
AppRole ``cosmo-app`` (клиент COS-105, НЕ root token) два секрета:

  secret/cosmo/auth     → {email, password_hash, sub, roles, is_admin}
  secret/cosmo/jwt-keys → {rsa_private, rsa_public, public_key, issuers, audience}

- ``password_hash`` — self-describing PBKDF2-HMAC-SHA256 (формат COS-157,
  ``pbkdf2_sha256$<iterations>$<salt_b64url>$<hash_b64url>``), генерируется
  функцией ``orchestrator.cosmo.security.credentials.hash_password``.
- ``rsa_private``/``rsa_public`` — RSA-2048 (PKCS#8 / SPKI PEM), тот же
  контракт, что читает ``security/jwt_issuer.py`` и отдаёт JWKS (RFC 7517).
- Приватный ключ живёт ТОЛЬКО в OpenBao. В git/``.env``/выводе скрипта его нет.

Идемпотентность:
- повторный запуск НЕ плодит дубли (kv-v2 — та же запись перезаписывается
  теми же значениями) и НЕ роняет существующее: если в ``jwt-keys`` уже лежит
  валидный RSA-ключ (не плейсхолдер), он сохраняется → ``kid`` (выводится из
  SPKI) стабилен, уже выпущенные токены остаются валидными;
- если ``auth`` уже содержит валидный self-describing хэш → сохраняется;
- ``--rotate`` принудительно перегенерирует keypair (осознанная ротация).

Usage:
  python services/scripts/seed-auth-secrets.py [--rotate]

Env (AppRole; совпадает с энв cosmo-api в docker-compose.yml):
  VAULT_ADDR               (default http://localhost:8200)
  VAULT_APPROLE_ROLE_ID
  VAULT_APPROLE_SECRET_ID
  COSMO_AUTH_ADMIN_EMAIL   (default admin@cosmoport.local)
  COSMO_AUTH_ADMIN_PASSWORD(default cosmo-admin-dev — ТОЛЬКО dev-контур)
  COSMO_AUTH_VIEWER_EMAIL  (default viewer@cosmoport.local — COS-187)
  COSMO_AUTH_VIEWER_PASSWORD(default cosmo-viewer-dev — ТОЛЬКО dev-контур)
  COSMO_AUTH_VIEWER_SUB    (default viewer)
"""
from __future__ import annotations

import argparse
import os
import sys

# Путь до корня репозитория (скрипт лежит в services/scripts/).
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)


# ── Константы ──────────────────────────────────────────────────────────────

JWT_KEYS = "jwt-keys"
AUTH = "auth"

PLACEHOLDER_MARKER = "DEV-ONLY-PLACEHOLDER"

DEFAULT_VAULT_ADDR = "http://localhost:8200"
DEFAULT_EMAIL = "admin@cosmoport.local"
DEFAULT_PASSWORD = "cosmo-admin-dev"  # dev-контур; prod — через env/оператора
DEFAULT_SUB = "admin"
DEFAULT_ROLES = ["admin_sec"]
# COS-187: второй seeded-пользователь (отдельный principal; inbox-разделение e2e).
DEFAULT_VIEWER_EMAIL = "viewer@cosmoport.local"
DEFAULT_VIEWER_PASSWORD = "cosmo-viewer-dev"  # dev-контур
DEFAULT_VIEWER_SUB = "viewer"
DEFAULT_VIEWER_ROLES = ["user"]
DEFAULT_ISSUERS = ["cosmoport"]
DEFAULT_AUDIENCE = "cosmo-api"


# ── Keypair / валидация ────────────────────────────────────────────────────

def _generate_keypair() -> tuple[str, str]:
    """RSA-2048 → (PKCS#8 private PEM, SPKI public PEM)."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    priv = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode("utf-8")
    pub = key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")
    return priv, pub


def _is_valid_keypair(priv: str, pub: str) -> bool:
    """Проверить, что пара — настоящий RSA-ключ (не плейсхолдер, не мусор)."""
    if not priv or not pub or PLACEHOLDER_MARKER in priv or PLACEHOLDER_MARKER in pub:
        return False
    try:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import rsa

        k = serialization.load_pem_private_key(priv.encode("utf-8"), password=None)
        p = serialization.load_pem_public_key(pub.encode("utf-8"))
        return isinstance(k, rsa.RSAPrivateKey) and isinstance(p, rsa.RSAPublicKey)
    except Exception:  # noqa: BLE001 — любая ошибка парсинга = "не валидна"
        return False


def _is_valid_hash(encoded: str) -> bool:
    """Признак self-describing PBKDF2-хэша (формат COS-157)."""
    return isinstance(encoded, str) and encoded.startswith("pbkdf2_sha256$")


def _derive_kid(public_pem: str) -> str:
    """Стабильный kid = SHA-256(SPKI-der) → base64url (как в jwt_issuer)."""
    from orchestrator.cosmo.security.jwt_issuer import derive_kid

    return derive_kid(public_pem)


# ── Основной поток ─────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(description="Seed COS-175 auth secrets into OpenBao")
    parser.add_argument("--rotate", action="store_true", help="force regenerate keypair")
    args = parser.parse_args()

    role_id = os.getenv("VAULT_APPROLE_ROLE_ID", "").strip()
    secret_id = os.getenv("VAULT_APPROLE_SECRET_ID", "").strip()
    if not role_id or not secret_id:
        print("ERROR: VAULT_APPROLE_ROLE_ID and VAULT_APPROLE_SECRET_ID must be set", file=sys.stderr)
        return 2

    from orchestrator.cosmo.infra.vault import VaultClient

    client = VaultClient()  # VAULT_ADDR from env (default http://localhost:8200)
    client.authenticate()
    health = client.health()
    print(f"[openbao] health: initialized={health.get('initialized')} sealed={health.get('sealed')}")

    # ── jwt-keys ──────────────────────────────────────────────────────────
    existing_keys = {}
    try:
        existing_keys = client.read_secret(JWT_KEYS) or {}
    except Exception:  # noqa: BLE001 — 404 → ещё не сидировано
        existing_keys = {}

    cur_priv = str(existing_keys.get("rsa_private") or "")
    cur_pub = str(existing_keys.get("rsa_public") or "")
    rotated = False
    if args.rotate or not _is_valid_keypair(cur_priv, cur_pub):
        cur_priv, cur_pub = _generate_keypair()
        rotated = True

    jwt_data = {
        "rsa_private": cur_priv,
        "rsa_public": cur_pub,
        # COS-156 verifier (jwt_verifier.default_vault_reader) в OpenBao-fallback
        # читает поле ``public_key`` (не ``rsa_public``). Кладём синоним SPKI-PEM,
        # чтобы выпущенный issuer'ом токен верифицировался тем же процессом
        # (same-process: статичный PEM, НЕ self-JWKS — COS-157 doc, примечание).
        "public_key": cur_pub,
        "issuers": DEFAULT_ISSUERS,
        "audience": DEFAULT_AUDIENCE,
    }
    client.write_secret(JWT_KEYS, jwt_data)
    kid = _derive_kid(cur_pub)
    print(
        f"[jwt-keys] {'ROTATED (new RSA-2048)' if rotated else 'PRESERVED (existing key)'} "
        f"| issuers={DEFAULT_ISSUERS} audience={DEFAULT_AUDIENCE} kid={kid}"
    )

    # ── auth ─────────────────────────────────────────────────────────────
    email = os.getenv("COSMO_AUTH_ADMIN_EMAIL", DEFAULT_EMAIL).strip()
    sub = os.getenv("COSMO_AUTH_ADMIN_SUB", DEFAULT_SUB).strip()
    password = os.getenv("COSMO_AUTH_ADMIN_PASSWORD", DEFAULT_PASSWORD)

    existing_auth = {}
    try:
        existing_auth = client.read_secret(AUTH) or {}
    except Exception:  # noqa: BLE001 — 404 → ещё не сидировано
        existing_auth = {}

    cur_hash = str(existing_auth.get("password_hash") or "")
    preserved = False
    if _is_valid_hash(cur_hash) and existing_auth.get("email"):
        # Идемпотентность: не трогаем действующие креды без --rotate.
        email = str(existing_auth.get("email")).strip()
        sub = str(existing_auth.get("sub") or email).strip()
        preserved = True
    else:
        from orchestrator.cosmo.security.credentials import hash_password

        cur_hash = hash_password(password)

    # ── COS-187: второй seeded-пользователь (отдельный principal/inbox) ──
    viewer_email = os.getenv("COSMO_AUTH_VIEWER_EMAIL", DEFAULT_VIEWER_EMAIL).strip()
    viewer_sub = os.getenv("COSMO_AUTH_VIEWER_SUB", DEFAULT_VIEWER_SUB).strip()
    viewer_password = os.getenv("COSMO_AUTH_VIEWER_PASSWORD", DEFAULT_VIEWER_PASSWORD)

    existing_users = existing_auth.get("users") if isinstance(existing_auth.get("users"), list) else []
    existing_viewer = next(
        (
            u
            for u in existing_users
            if isinstance(u, dict) and str(u.get("email") or "").strip() == viewer_email
        ),
        None,
    )
    viewer_preserved = False
    if existing_viewer and _is_valid_hash(str(existing_viewer.get("password_hash") or "")):
        # Идемпотентность: повторный сид не трогает viewer-креды.
        viewer_hash = str(existing_viewer["password_hash"])
        viewer_sub = str(existing_viewer.get("sub") or viewer_sub).strip()
        viewer_preserved = True
    else:
        from orchestrator.cosmo.security.credentials import hash_password as _hash

        viewer_hash = _hash(viewer_password)

    viewer_record = {
        "email": viewer_email,
        "password_hash": viewer_hash,
        "sub": viewer_sub,
        "roles": DEFAULT_VIEWER_ROLES,
        "is_admin": False,
    }

    auth_data = {
        "email": email,
        "password_hash": cur_hash,
        "sub": sub,
        "roles": DEFAULT_ROLES,
        "is_admin": True,
        "users": [viewer_record],
    }
    client.write_secret(AUTH, auth_data)
    print(
        f"[auth] {'PRESERVED (existing hash)' if preserved else 'SEEDED (new PBKDF2 hash)'} "
        f"| email={email} sub={sub} roles={DEFAULT_ROLES} is_admin=True"
    )
    print(
        f"[auth:viewer] {'PRESERVED (existing hash)' if viewer_preserved else 'SEEDED (new PBKDF2 hash)'} "
        f"| email={viewer_email} sub={viewer_sub} roles={DEFAULT_VIEWER_ROLES} is_admin=False"
    )

    print(
        "\nDONE. Private key is ONLY in OpenBao (not in git/.env/output). "
        f"Verify via:\n  login: curl -X POST http://localhost:8100/api/v1/auth/login "
        f"-d '{{\"email\":\"{email}\",\"password\":\"<admin password>\"}}'\n"
        f"  jwks:  curl http://localhost:8100/.well-known/jwks.json"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())