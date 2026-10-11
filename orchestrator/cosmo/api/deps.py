"""Cosmoport 2.0 — FastAPI shared dependencies.

SAN-006 [COS-031]: Честный PrincipalContext и авторизационный барьер.
"""
from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any, List, Optional
from fastapi import Cookie, Depends, Header, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.cosmo.db.session import get_sessionmaker
from orchestrator.cosmo.domain.rbac import (
    Action,
    CBRRole,
    DomainRBAC,
    PrincipalContext,
    Role,
    ZoneType,
)
from orchestrator.cosmo.security.jwt_verifier import (
    JwtVerificationError,
    verify_jwt,
)


# ── Database session ──

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Yield an async SQLAlchemy session per request."""
    session_factory = get_sessionmaker()
    async with session_factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


# ── COS-105: Vault dependency ──────────────────────────────────────────

_vault_client: "VaultClient | None" = None  # type: ignore[name-defined]  # noqa: F821


def init_vault() -> "VaultClient":  # type: ignore[name-defined]  # noqa: F821
    """Вызывается lifespan'ом перед yield.

    COS-178: auth — best-effort. Недоступный/sealed vault НЕ роняет старт:
    клиент остаётся в deps, а lazy-auth (``VaultClient._ensure_token``) догонит
    сессию при первом запросе. Surface отдаёт честный 503, пока vault не готов.
    """
    from orchestrator.cosmo.infra.vault import VaultClient

    global _vault_client
    _vault_client = VaultClient()
    _vault_client.authenticate()
    return _vault_client


def get_vault() -> "VaultClient":  # type: ignore[name-defined]  # noqa: F821
    """FastAPI dependency: 503, если Vault-клиент не создан стартом.

    Готовность самого vault проверяется на поверхности: read/write кидают
    VaultError/VaultUnavailableError → роуты отдают 503 (COS-178).
    """
    if _vault_client is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Vault not initialized (startup bootstrap skipped)",
        )
    return _vault_client


# ── Principal extraction (SAN-006 [COS-031]) ──

def _clean_str(val: Any) -> Optional[str]:
    if isinstance(val, str):
        s = val.strip()
        return s if s else None
    return None


def _parse_role(role_raw: str) -> Role | CBRRole | str:
    """Парсинг строки роли в CBRRole, Role или кастомную строку."""
    r_clean = role_raw.strip().lower()
    for cbr in CBRRole:
        if cbr.value.lower() == r_clean:
            return cbr
    for r in Role:
        if r.value.lower() == r_clean:
            return r
    return r_clean


def _extract_bearer_token(
    authorization: Optional[str], cookie_token: Optional[str]
) -> Optional[str]:
    """Извлечь JWT из Authorization: Bearer (приоритет) или cookie session_token."""
    auth_str = _clean_str(authorization)
    if auth_str:
        parts = auth_str.split()
        if len(parts) == 2 and parts[0].lower() == "bearer":
            return parts[1]
        if len(parts) == 1 and parts[0].lower() != "bearer":
            return parts[0]
        return None
    return _clean_str(cookie_token)


async def get_current_principal(
    authorization: Optional[str] = Header(None, alias="Authorization"),
    cookie_token: Optional[str] = Cookie(None, alias="session_token"),
    x_cosmo_zone: Optional[str] = Header(None, alias="X-Cosmo-Zone"),
    x_cosmo_domain: Optional[str] = Header(None, alias="X-Cosmo-Domain"),
) -> PrincipalContext:
    """SAN-006 [COS-031] + COS-156: крипто-верифицированный PrincipalContext.

    1. Читает заголовок Authorization: Bearer <token> или cookie session_token.
    2. Отсутствие/невалидность учётных данных -> HTTP 401.
    3. COS-085: opaque-bearer legacy контракт закрыт. COS-156: формат ``ey…``
       больше НЕ достаточен — токен обязан пройти **верификацию подписи**
       (RS256/ES256 через ``security.jwt_verifier``, fail-closed). Подделанная
       подпись / истёкший ``exp`` / неверный ``iss`` / ``alg=none`` → 401.
    4. Identity (sub/email/roles/scopes/is_admin) читается ТОЛЬКО из
       верифицированных claims. Заголовки-инъекции идентичности
       (X-User-Id/Roles, X-Cosmo-Principal/Roles/Scopes) больше не являются
       источником identity — это был spoof-вектор ролей вплоть до system admin.
       Зона/домен (X-Cosmo-Zone/X-Cosmo-Domain) остаются контекстом, не identity.
    """
    raw_token: Optional[str] = _extract_bearer_token(authorization, cookie_token)

    # COS-156: единственный путь аутентификации — крипто-подпись JWT.
    # Fail-closed: не сконфигурированы ключи → 401 (не дефолтный success).
    try:
        claims = verify_jwt(raw_token)
    except JwtVerificationError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="401_UNAUTHORIZED: Missing or invalid credentials",
        )

    # Identity claims — только из верифицированного token.
    user_id = _clean_str(claims.get("sub")) or _clean_str(claims.get("user_id"))
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="401_UNAUTHORIZED: token has no subject (sub)",
        )
    email = _clean_str(claims.get("email")) or f"{user_id}@kits.bank.corp"
    roles: List[Role | CBRRole | str] = []
    if isinstance(claims.get("roles"), list):
        roles = [_parse_role(r) for r in claims["roles"] if isinstance(r, str)]
    scopes: List[str] = (
        [s for s in claims.get("scopes", []) if isinstance(s, str)]
        if isinstance(claims.get("scopes"), list) else []
    )
    is_admin = bool(claims.get("is_admin", False))

    if not roles:
        roles.append(Role.USER)

    is_system_admin = is_admin or any(
        (r.value if isinstance(r, (Role, CBRRole)) else str(r)) in ("admin_sec", "security_officer")
        for r in roles
    )

    zone_val = (_clean_str(x_cosmo_zone) or "zr").lower()
    if zone_val not in ("zr", "zt", "zpe"):
        zone_val = "zr"

    domain_val = _clean_str(x_cosmo_domain) or "default"

    return PrincipalContext(
        user_id=user_id,
        email=email,
        roles=roles,
        domain_id=domain_val,
        zone=zone_val,  # type: ignore
        team_scopes=scopes,
        is_authenticated=True,
        auth_claims=claims,
        is_system_admin=is_system_admin,
    )


# ── Guard factory (COS-032) ──

def require_capability(
    action: str,
    target_scope: str | None = None,
    domain_binding: str = "header",
):
    """Фабрика FastAPI dependency для проверки RBAC-доступа.

    domain_binding (COS-067 domain binding hardening):
      - "header" (default, legacy COS-032/COS-058): контекст домена берётся
        из X-Cosmo-Domain/domain_id (400 — нет, 404 — домена нет в БД).
        Заголовок НЕ связывается с identity. Используется transfer-маршрутами:
        их binding реализован на уровне обработчика (COS-066, anti-spoofing).
      - "header_bound": то же + явный отказ 403, если запрошенный домен не
        совпадает с principal.domain_id не-админа (spoof → 403 до проверки
        существования — без утечки существования доменов).
      - "identity" (рекомендуемый): контекст домена = principal.domain_id;
        клиентский заголовок не требуется и не влияет на решение (UX:
        избыточный 400 устранён). Binding по построению.
    """

    async def _guard(
        principal: PrincipalContext = Depends(get_current_principal),
        db: AsyncSession = Depends(get_db),
        x_cosmo_domain: Optional[str] = Header(None, alias="X-Cosmo-Domain"),
        domain_id_query: Optional[str] = Query(None),
    ) -> PrincipalContext:
        # COS-032: System admin bypasses domain and RBAC checks
        if principal.is_system_admin:
            return principal

        identity_domain = (principal.domain_id or "").strip()

        if domain_binding == "identity":
            # COS-067: контекст = identity домен principal; заголовок игнорируется
            domain_id = identity_domain or "default"
        elif domain_binding == "header_bound":
            raw_requested = x_cosmo_domain or domain_id_query
            requested = raw_requested.strip() if raw_requested else None
            if not requested:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="X-Cosmo-Domain header or domain_id query parameter required",
                )
            # COS-067: binding ДО проверки существования — spoof чужого домена
            # даёт единообразный 403 без утечки существования доменов.
            if identity_domain and requested != identity_domain:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=(
                        f"X-Cosmo-Domain '{requested}' does not match "
                        f"authenticated principal domain"
                    ),
                )
            from orchestrator.cosmo.api.domain_guard import require_domain as _rd
            domain_id = await _rd(x_cosmo_domain=x_cosmo_domain, domain_id=domain_id_query, db=db)
        else:
            # "header" — legacy поведение (COS-058 fix: реальные значения,
            # а не marker-объекты Header/Query).
            from orchestrator.cosmo.api.domain_guard import require_domain as _rd
            domain_id = await _rd(x_cosmo_domain=x_cosmo_domain, domain_id=domain_id_query, db=db)

        # Non-admin: check domain + RBAC.

        rbac = await _load_domain_rbac(domain_id, db)

        is_allowed, reason = rbac.evaluate(
            principal=principal,
            action=action,
            target_zone=principal.zone,
            target_scope=target_scope,
        )

        if not is_allowed:
            if reason == "401_UNAUTHORIZED":
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
            role_names = [
                r.value if isinstance(r, (Role, CBRRole)) else str(r)
                for r in principal.roles
            ]
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Action '{action}' forbidden for roles {role_names} in zone '{principal.zone}'",
            )

        return principal

    return _guard


def require_principal():
    """COS-068: authentication-only guard (без capability и домена).

    Базовый барьер для read-поверхностей: get_current_principal сам
    возвращает 401 для анонима. Любой аутентифицированный principal
    проходит; domain-scoping при необходимости выполняет хендлер.
    """

    async def _guard(
        principal: PrincipalContext = Depends(get_current_principal),
    ) -> PrincipalContext:
        return principal

    return _guard


def require_system_admin():
    """COS-068: system-admin-only guard для привилегированных мутаций.

    Применяется там, где capability-модель не покрывает операцию
    (управление доменами, прямая запись в audit trail, очистка
    артефактов): 401 — аноним, 403 — аутентифицированный не-админ.
    """

    async def _guard(
        principal: PrincipalContext = Depends(get_current_principal),
    ) -> PrincipalContext:
        if not principal.is_system_admin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="System administrator role required",
            )
        return principal

    return _guard


def _get_require_domain():
    """Lazy import to avoid circular dependency with domain_guard."""
    from orchestrator.cosmo.api.domain_guard import require_domain
    return require_domain


async def _load_domain_rbac(domain_id: str, db: AsyncSession) -> DomainRBAC:
    """Load DomainRBAC from DB or return default."""
    from orchestrator.cosmo.db.models import Domain as DomainModel

    result = await db.execute(select(DomainModel).where(DomainModel.id == domain_id))
    domain = result.scalar_one_or_none()

    if domain is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Domain {domain_id} not found")

    return DomainRBAC(domain_id=domain_id, members=[], inheritance_mode="isolate")
