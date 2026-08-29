"""
COS-096: Domain RBAC Engine — 5 канонических ролей + team scopes + inheritance.

Роли:
  admin_sec      — полный доступ к гейтам, утверждению актов, трансферу
  sec_expert     — запуск сканов, маркеры находок, просмотр улик
  admin_abnormal — управление аномалиями, admission-решения
  admin_service  — конфигурация пайплайнов, каталог bricks
  user           — только чтение своего скоупа

Inheritance modes:
  merge    — права родительского домена наследуются дочерним
  isolate  — дочерний домен получает только свои права

DomainRBAC связывает Domain с набором DomainMember и режимом наследования.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, FrozenSet, List, Literal, Optional

InheritanceMode = Literal["merge", "isolate"]


class Role(str, Enum):
    ADMIN_SEC = "admin_sec"
    SEC_EXPERT = "sec_expert"
    ADMIN_ABNORMAL = "admin_abnormal"
    ADMIN_SERVICE = "admin_service"
    USER = "user"


# ── Permission matrix ────────────────────────────────────────────────────────

# Каноническая матрица: role → {allowed_actions}
_PERMISSIONS: Dict[Role, FrozenSet[str]] = {
    Role.ADMIN_SEC: frozenset({
        "gate:decide",           # подписывать допуск (block/pass)
        "gate:override",         # override gate в ручном режиме
        "release:transfer",      # трансфер в ЗПЭ
        "release:approve",       # утверждение релиза
        "act:sign",              # подписание ГОСТ-Акта
        "scan:start",            # запуск сканов
        "scan:stop",             # остановка сканов
        "finding:tag",           # маркеры находок
        "finding:view_all",      # просмотр всех находок
        "evidence:view_all",     # просмотр всех улик
        "pipeline:configure",    # конфигурация пайплайнов
        "rbac:manage",           # управление RBAC
        "domain:configure",      # настройка домена
        "report:export",         # экспорт отчётов
        "read",                  # базовое чтение
    }),
    Role.SEC_EXPERT: frozenset({
        "scan:start",
        "scan:stop",
        "finding:tag",
        "finding:view_all",
        "evidence:view_all",
        "report:export",
        "read",
    }),
    Role.ADMIN_ABNORMAL: frozenset({
        "gate:decide",           # admission-решения
        "gate:override",
        "finding:view_all",
        "evidence:view_all",
        "report:export",
        "read",
    }),
    Role.ADMIN_SERVICE: frozenset({
        "pipeline:configure",
        "scan:start",
        "finding:tag",
        "finding:view_all",
        "evidence:view_all",
        "report:export",
        "read",
    }),
    Role.USER: frozenset({
        "read",
        "report:export",
    }),
}

# read-only permissions: если у пользователя нет write-прав, но есть read —
# ему разрешён только просмотр своего scope
_READ_ONLY_PERMISSIONS = frozenset({"read", "report:export"})


# ── DomainMember / DomainRBAC ────────────────────────────────────────────────

@dataclass
class DomainMember:
    """Пользователь в контексте домена: роль + team scopes."""
    user_id: str
    role: Role
    team_scopes: List[str] = field(default_factory=list)  # список scope_id


@dataclass
class DomainRBAC:
    """Конфигурация RBAC для одного Domain."""
    domain_id: str
    members: List[DomainMember] = field(default_factory=list)
    inheritance_mode: InheritanceMode = "isolate"
    parent_domain_id: Optional[str] = None  # для merge-наследования

    def get_member(self, user_id: str) -> DomainMember | None:
        """Найти пользователя в домене. При merge — искать рекурсивно."""
        for m in self.members:
            if m.user_id == user_id:
                return m

        # merge: поискать в parent
        if self.inheritance_mode == "merge" and self.parent_domain_id:
            # parent lookup is external (caller provides parent RBAC)
            return None  # caller must resolve parent externally

        return None

    def resolve_permissions(self, user_id: str,
                            parent_rbac: DomainRBAC | None = None) -> FrozenSet[str]:
        """Разрешить эффективные права пользователя.

        При merge: родительские права объединяются.
        """
        member = self.get_member(user_id)

        # not in domain — check parent if merge
        if member is None:
            if parent_rbac and self.inheritance_mode == "merge":
                parent_member = parent_rbac.get_member(user_id)
                if parent_member and self._scope_match(
                    parent_member.team_scopes, None,
                ):
                    return _PERMISSIONS.get(parent_member.role, frozenset())
            return frozenset()

        role_perms = _PERMISSIONS.get(member.role, frozenset())
        if role_perms == frozenset({"read", "report:export"}):
            return role_perms  # user only — no merge expansion

        # merge: добавить родительские права
        if parent_rbac and self.inheritance_mode == "merge":
            parent_perms = parent_rbac.resolve_permissions(user_id)
            role_perms = role_perms | parent_perms

        return role_perms

    def has_permission(self, user_id: str, action: str,
                       parent_rbac: DomainRBAC | None = None,
                       required_scope: str | None = None) -> bool:
        """Проверить право пользователя на действие.

        Args:
            user_id: ID пользователя
            action: строка действия (e.g. 'gate:decide', 'release:transfer')
            parent_rbac: RBAC родительского домена для merge
            required_scope: требуемый scope_id для изоляции команд
        """
        member = self.get_member(user_id)

        # scope check
        if required_scope and member:
            if not self._scope_match(member.team_scopes, required_scope):
                return False

        perms = self.resolve_permissions(user_id, parent_rbac)
        return action in perms

    @staticmethod
    def _scope_match(member_scopes: List[str], required: str | None) -> bool:
        """Проверка совпадения team scopes.

        None — глобальный доступ (admin_sec, admin_abnormal).
        Пустой список — пользователь без скоупов → denied для scoped действий.
        """
        if required is None:
            return True  # глобальное действие — доступно всем ролям
        if not member_scopes:
            return False  # нет скоупов → не может выполнять scoped действия
        return required in member_scopes

    def validate_role(self, allowed_roles: List[Role], user_id: str) -> bool:
        """Проверить, что пользователь имеет одну из разрешённых ролей."""
        member = self.get_member(user_id)
        if member is None:
            return False
        return member.role in allowed_roles


# ── FastAPI dependency — require_role ──────────────────────────────────────

def require_role(
    allowed_roles: List[Role],
    required_scope: str | None = None,
    action: str | None = None,
):
    """COS-096: FastAPI dependency — проверка прав пользователя.

    Usage:
        @router.post("/{release_id}/transfer")
        async def transfer(..., _rbac: None = Depends(require_role(
            [Role.ADMIN_SEC], action="release:transfer",
        ))):
            ...

    При неудаче — HTTPException 403.
    Пока без реальной auth (COS-017) — заглушка, пропускает всех.
    """
    def _check() -> bool:
        # TODO: extract user_id from request (COS-017 auth)
        # TODO: resolve domain context from URL/params
        # Placeholder: разрешить всё
        return True

    return _check


def require_scoped_role(
    allowed_roles: List[Role],
    scope: str,
    action: str | None = None,
):
    """Проверка прав с привязкой к scope.

    Требует: пользователь ∈ allowed_roles И scope ∈ member.team_scopes.
    """
    # Placeholder — заглушка до COS-017
    return lambda: True


# ── Helpers ──────────────────────────────────────────────────────────────────

def is_readonly_permissions(perms: FrozenSet[str]) -> bool:
    return perms.issubset(_READ_ONLY_PERMISSIONS)


def can_manage_rbac(user_perms: FrozenSet[str]) -> bool:
    return "rbac:manage" in user_perms


def can_sign_gate(user_perms: FrozenSet[str]) -> bool:
    return "gate:decide" in user_perms


def can_transfer_to_prod(user_perms: FrozenSet[str]) -> bool:
    return "release:transfer" in user_perms


def can_approve_release(user_perms: FrozenSet[str]) -> bool:
    return "release:approve" in user_perms


def can_start_scan(user_perms: FrozenSet[str]) -> bool:
    return "scan:start" in user_perms


def can_tag_findings(user_perms: FrozenSet[str]) -> bool:
    return "finding:tag" in user_perms