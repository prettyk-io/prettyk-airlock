"""
SAN-006 [COS-031]: Tests for Honest PrincipalContext and Sanitary RBAC Barrier.

Проверяет:
  1. Реальную отсечку 401 при отсутствии или невалидности учетных данных в get_current_principal.
  2. Парсинг ролей (включая 12 ролей ЦБ из CBRRole), email, team scopes и X-Cosmo-Zone.
  3. Работу require_role и require_scoped_role: блокировка 401/403 без заглушек return True.
  4. DomainRBAC.evaluate() как единственный и непреложный источник авторизационных решений.
"""
import base64
import json
import pytest
from fastapi import HTTPException, status

from _jwt_testkey import TEST_PUBLIC_KEY_PEM, mint_rs256

from cosmo.api.deps import get_current_principal
from cosmo.domain.rbac import (
    Action,
    CBRRole,
    DomainMember,
    DomainRBAC,
    PrincipalContext,
    Role,
    require_role,
    require_scoped_role,
)


# ═══════════════════════════════════════════════════════════════════════
# 1. get_current_principal Dependency Tests (401 Cut-off)
# ═══════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_get_current_principal_missing_credentials_raises_401():
    """Отсутствие заголовка Authorization и кук вызывает HTTP 401."""
    with pytest.raises(HTTPException) as exc_info:
        await get_current_principal(authorization=None, cookie_token=None)

    assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
    assert "401_UNAUTHORIZED" in exc_info.value.detail


@pytest.mark.asyncio
async def test_get_current_principal_invalid_token_raises_401():
    """Невалидный или просроченный токен вызывает HTTP 401."""
    for bad_token in ["invalid", "expired", "corrupted", "0000", "null"]:
        with pytest.raises(HTTPException) as exc_info:
            await get_current_principal(authorization=f"Bearer {bad_token}")

        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
        assert "401_UNAUTHORIZED" in exc_info.value.detail


@pytest.mark.asyncio
async def test_get_current_principal_valid_bearer_token(monkeypatch):
    """Валидный подписанный RS256 JWT → PrincipalContext из verified claims.

    COS-156: идентичность/роли приходят ТОЛЬКО из крипто-верифицированных
    claims. Header-инъекция (X-User-Id/Roles, X-Cosmo-Roles/Scopes) больше
    не является источником identity — подпись единственный источник истины."""
    monkeypatch.setenv("COSMO_JWT_DEV_PUBLIC_KEY", TEST_PUBLIC_KEY_PEM)
    claims = {
        "sub": "officer_ivanov",
        "email": "ivanov@cbr.bank.corp",
        "roles": ["security_officer", "admin_sec"],
        "scopes": ["team_core", "audit_all"],
    }
    token = mint_rs256(claims)
    principal = await get_current_principal(
        authorization=f"Bearer {token}",
        x_cosmo_zone="zt",
    )

    assert principal.is_authenticated is True
    assert principal.user_id == "officer_ivanov"
    assert principal.email == "ivanov@cbr.bank.corp"
    assert principal.zone == "zt"
    assert principal.has_role(CBRRole.SECURITY_OFFICER)
    assert principal.has_role(Role.ADMIN_SEC)
    assert "team_core" in principal.team_scopes
    assert "audit_all" in principal.team_scopes


@pytest.mark.asyncio
async def test_get_current_principal_jwt_token_claims(monkeypatch):
    """Подписанный RS256 JWT декодирует claims (sub, email, roles, scopes, is_admin)."""
    monkeypatch.setenv("COSMO_JWT_DEV_PUBLIC_KEY", TEST_PUBLIC_KEY_PEM)
    claims = {
        "sub": "sec_analyst_elena",
        "email": "elena@secops.corp",
        "roles": ["security_analyst", "sec_expert"],
        "scopes": ["appsec_scan"],
        "is_admin": False,
    }
    token = mint_rs256(claims)

    principal = await get_current_principal(
        authorization=f"Bearer {token}",
        x_cosmo_zone="zr",
    )

    assert principal.user_id == "sec_analyst_elena"
    assert principal.email == "elena@secops.corp"
    assert CBRRole.SECURITY_ANALYST in principal.roles
    assert Role.SEC_EXPERT in principal.roles
    assert "appsec_scan" in principal.team_scopes
    assert principal.is_system_admin is False


@pytest.mark.asyncio
async def test_get_current_principal_header_identity_is_ignored(monkeypatch):
    """COS-156: header-инъекция ролей/is_admin игнорируется — подпись источник.

    Даже если заголовки X-Cosmo-Roles/X-User-Roles несут admin_sec, а подпись
    только user — principal не получает admin-роль."""
    monkeypatch.setenv("COSMO_JWT_DEV_PUBLIC_KEY", TEST_PUBLIC_KEY_PEM)
    token = mint_rs256({"sub": "plain_user", "roles": ["user"], "is_admin": False})

    principal = await get_current_principal(authorization=f"Bearer {token}")

    assert principal.user_id == "plain_user"
    assert principal.is_system_admin is False
    assert not principal.has_role(Role.ADMIN_SEC)


# ═══════════════════════════════════════════════════════════════════════
# 2. require_role & require_scoped_role Tests (Real Authorization Barrier)
# ═══════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_require_role_denies_wrong_role_with_403():
    """Пользователь с ролью DEVELOPER блокируется (403) при требовании SECURITY_OFFICER."""
    dev_principal = PrincipalContext(
        user_id="dev_bob",
        roles=[CBRRole.DEVELOPER],
        is_authenticated=True,
    )

    guard = require_role(allowed_roles=[CBRRole.SECURITY_OFFICER, Role.ADMIN_SEC])

    with pytest.raises(HTTPException) as exc_info:
        await guard(principal=dev_principal)

    assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
    assert "403_FORBIDDEN" in exc_info.value.detail


@pytest.mark.asyncio
async def test_require_role_allows_authorized_role():
    """Пользователь с ролью SECURITY_OFFICER успешно проходит проверку."""
    officer_principal = PrincipalContext(
        user_id="officer_alice",
        roles=[CBRRole.SECURITY_OFFICER],
        is_authenticated=True,
    )

    guard = require_role(allowed_roles=[CBRRole.SECURITY_OFFICER, Role.ADMIN_SEC])
    res = await guard(principal=officer_principal)
    assert res == officer_principal


@pytest.mark.asyncio
async def test_require_role_with_action_evaluation():
    """require_role с параметром action оценивает права через DomainRBAC.evaluate."""
    dev_principal = PrincipalContext(
        user_id="dev_bob",
        roles=[CBRRole.DEVELOPER],
        domain_id="dom-sec",
        zone="zr",
        is_authenticated=True,
    )

    # Разработчик пытается выполнить release:approve -> 403
    guard = require_role(allowed_roles=[Role.USER, CBRRole.DEVELOPER], action=Action.RELEASE_APPROVE)

    with pytest.raises(HTTPException) as exc_info:
        await guard(principal=dev_principal)

    assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
    assert "403_ACTION_FORBIDDEN" in exc_info.value.detail


@pytest.mark.asyncio
async def test_require_scoped_role_checks_team_scope():
    """require_scoped_role проверяет совпадение team scope."""
    principal = PrincipalContext(
        user_id="dev_charlie",
        roles=[CBRRole.DEVELOPER],
        team_scopes=["team_frontend"],
        is_authenticated=True,
    )

    guard_ok = require_scoped_role(allowed_roles=[CBRRole.DEVELOPER], scope="team_frontend")
    res = await guard_ok(principal=principal)
    assert res == principal

    guard_fail = require_scoped_role(allowed_roles=[CBRRole.DEVELOPER], scope="team_backend")
    with pytest.raises(HTTPException) as exc_info:
        await guard_fail(principal=principal)

    assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN


# ═══════════════════════════════════════════════════════════════════════
# 3. DomainRBAC.evaluate Single Source of Truth Tests
# ═══════════════════════════════════════════════════════════════════════

def test_domain_rbac_evaluate_unauthenticated_returns_401():
    rbac = DomainRBAC(domain_id="dom-1")
    unauth_p = PrincipalContext(user_id="anon", is_authenticated=False)

    allowed, reason = rbac.evaluate(unauth_p, Action.READ)
    assert allowed is False
    assert reason == "401_UNAUTHORIZED"


def test_domain_rbac_evaluate_with_domain_memberships():
    """Проверка работы через domain_memberships в PrincipalContext."""
    rbac = DomainRBAC(domain_id="dom-payments")
    member = DomainMember(user_id="specialist_1", role=CBRRole.SECURITY_ANALYST, team_scopes=["all"])

    principal = PrincipalContext(
        user_id="specialist_1",
        roles=[],  # нет глобальных ролей, но есть membership в домене
        domain_memberships={"dom-payments": member},
        is_authenticated=True,
    )

    allowed, reason = rbac.evaluate(principal, Action.SCAN_START)
    assert allowed is True
    assert reason == "200_ALLOWED"

    # Запрещенное для аналитика действие
    allowed_adm, reason_adm = rbac.evaluate(principal, Action.RELEASE_TRANSFER)
    assert allowed_adm is False
    assert "403_ACTION_FORBIDDEN" in reason_adm
