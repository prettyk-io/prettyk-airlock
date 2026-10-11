# -*- coding: utf-8 -*-
"""COS-157: auth-роуты — боевой логин (self-managed) + JWKS.

Публичные эндпоинты (без identity-guard — это точка входа в доверие):

- ``POST /api/v1/auth/login`` — проверка креденшелов против OpenBao
  ``secret/cosmo/auth`` (OpenBao-seeded admin, хэш PBKDF2) и выдача
  подписанного RS256 access-токена («боевой» путь, не dev-stub, не root).
- ``GET /.well-known/jwks.json`` — JWKS (RFC 7517) с публичным ключом из
  ``secret/cosmo/jwt-keys``; verifier COS-156 читает его по
  ``COSMO_JWT_JWKS_URL`` для сквозной проверки выпущенного токена.

Fail-closed: нет vault → 503 (``get_vault``); не seeded ``auth``/``jwt-keys``
→ явная ошибка (503/500), НЕ silent-success и НЕ unsigned-токен. Приватный
ключ никогда не покидает OpenBao.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from orchestrator.cosmo.api import deps
from orchestrator.cosmo.infra.vault import VaultClient, VaultError, VaultLookupError
from orchestrator.cosmo.security import credentials
from orchestrator.cosmo.security.jwt_issuer import (
    IssuerConfig,
    IssuerConfigError,
    build_jwks,
    mint_access_token,
)

AUTH_SECRET = "auth"

router = APIRouter(tags=["auth"])


# ── Модели ───────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    email: str = Field(..., min_length=1, description="Email пользователя")
    password: str = Field(..., min_length=1, description="Пароль")


class UserView(BaseModel):
    sub: str
    email: str
    roles: list[str] = []
    is_admin: bool = False


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserView


# ── Вспомогательные ──────────────────────────────────────────────────────

def _read_auth(vault: VaultClient) -> dict:
    """Прочитать ``secret/cosmo/auth``; явный 503 если не seeded."""
    try:
        data = vault.read_secret(AUTH_SECRET)
    except VaultLookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="auth secret not bootstrapped (secret/cosmo/auth not seeded)",
        ) from exc
    except VaultError as exc:
        # COS-178: sealed/unavailable vault — честный 503, не 500.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"vault unavailable: {exc}",
        ) from exc
    if not isinstance(data, dict) or not data.get("email") or not data.get("password_hash"):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="auth secret not bootstrapped (email/password_hash missing)",
        )
    return data


def _auth_users(data: dict) -> list[dict]:
    """Кандидаты-пользователи: основная запись + optional ``users`` (COS-187).

    Второй seeded-пользователь живёт в ``users`` (свой email/sub/roles);
    идемпотентный сид пишет его туда. Невалидные записи (без email/hash)
    молча пропускаются — fail-closed: такая запись никогда не залогинится.
    """
    users: list[dict] = []
    primary_email = str(data.get("email") or "").strip()
    primary_hash = str(data.get("password_hash") or "")
    if primary_email and primary_hash:
        users.append({
            "email": primary_email,
            "password_hash": primary_hash,
            "sub": str(data.get("sub") or primary_email).strip(),
            "roles": [str(r) for r in data.get("roles")] if isinstance(data.get("roles"), list) else [],
            "is_admin": bool(data.get("is_admin", False)),
        })
    extra = data.get("users")
    if isinstance(extra, list):
        for item in extra:
            if not isinstance(item, dict):
                continue
            u_email = str(item.get("email") or "").strip()
            u_hash = str(item.get("password_hash") or "")
            if not u_email or not u_hash:
                continue
            users.append({
                "email": u_email,
                "password_hash": u_hash,
                "sub": str(item.get("sub") or u_email).strip(),
                "roles": [str(r) for r in item.get("roles")] if isinstance(item.get("roles"), list) else [],
                "is_admin": bool(item.get("is_admin", False)),
            })
    return users


def _load_issuer_config(vault: VaultClient) -> IssuerConfig:
    """Загрузить signing-конфигурацию из OpenBao; явная ошибка при отсутствии ключа."""
    try:
        return IssuerConfig.load(vault.read_secret)
    except (IssuerConfigError, VaultLookupError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"JWT issuer not configured: {exc}",
        ) from exc
    except VaultError as exc:
        # COS-178: sealed/unavailable vault — честный 503, не 500.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"vault unavailable: {exc}",
        ) from exc


# ── Login ────────────────────────────────────────────────────────────────

@router.post(
    "/api/v1/auth/login",
    response_model=LoginResponse,
    status_code=status.HTTP_200_OK,
)
async def login(
    payload: LoginRequest,
    vault: VaultClient = Depends(deps.get_vault),
) -> LoginResponse:
    """Self-managed логин: проверка креденшелов → подписанный RS256 access-токен.

    COS-187: поддерживается несколько пользователей — основная запись +
    optional ``users``-список в ``secret/cosmo/auth``. Email ищется точным
    совпадением; пароль всегда сверяется с PBKDF2-хэшем (для отсутствующего
    email — с хэшем первой записи, чтобы не давать timing-оракул на перебор
    адресов).
    """
    auth = _read_auth(vault)
    users = _auth_users(auth)
    if not users:  # pragma: no cover — _read_auth уже гарантирует primary-запись
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="auth secret not bootstrapped (no usable user records)",
        )

    requested_email = payload.email.strip()
    matched = next((u for u in users if u["email"] == requested_email), None)
    password_ok = credentials.verify_password(
        payload.password, (matched or users[0])["password_hash"]
    )
    if matched is None or not password_ok:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="401_UNAUTHORIZED: invalid credentials",
        )

    email = matched["email"]
    sub = matched["sub"]
    roles = matched["roles"]
    is_admin = matched["is_admin"]

    cfg = _load_issuer_config(vault)
    token = mint_access_token(
        cfg,
        sub=sub,
        email=email,
        roles=roles or ["user"],
        is_admin=is_admin,
    )

    return LoginResponse(
        access_token=token,
        token_type="bearer",
        expires_in=cfg.ttl_seconds,
        user=UserView(sub=sub, email=email, roles=roles or ["user"], is_admin=is_admin),
    )


# ── JWKS ─────────────────────────────────────────────────────────────────

@router.get("/.well-known/jwks.json")
async def jwks(
    vault: VaultClient = Depends(deps.get_vault),
) -> dict:
    """JWKS (RFC 7517) — публичный ключ подписи для verifier COS-156."""
    cfg = _load_issuer_config(vault)
    return build_jwks(cfg)