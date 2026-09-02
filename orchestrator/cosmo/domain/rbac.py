"""
COS-096 / COS-110: Grand RBAC Engine & 12 Role Capability Bundles.

Иерархия:
  12 специализированных ролей ЦБ РФ, маппирующихся в capability-бандлы поверх
  канонических базовых ролей.
  Поддержка:
    - PrincipalContext (user_id, roles, domain_id, zones, team_scopes, claims)
    - Межзонные ограничения (ЗР / ЗТ / ЗПЭ)
    - Team scopes и изоляция КИТС
    - Режимы наследования (merge / isolate)
    - Проверка принципа разделения обязанностей (Separation of Duties, SoD)
    - Комплексная функция оценки `evaluate()`
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, FrozenSet, List, Literal, Optional, Set, Tuple

InheritanceMode = Literal["merge", "isolate"]
ZoneType = Literal["zr", "zt", "zpe", "all"]


# ── Canonical 5 Base Roles ───────────────────────────────────────────────────

class Role(str, Enum):
    ADMIN_SEC = "admin_sec"
    SEC_EXPERT = "sec_expert"
    ADMIN_ABNORMAL = "admin_abnormal"
    ADMIN_SERVICE = "admin_service"
    USER = "user"


# ── 12 CBR Specialized Roles (COS-110) ───────────────────────────────────────

class CBRRole(str, Enum):
    SECURITY_OFFICER = "security_officer"            # Офицер ИБ / Руководитель СБ
    SECURITY_ANALYST = "security_analyst"            # Аналитик ИБ / SecOps
    ABNORMAL_ADMIN = "abnormal_admin"                # Администратор аномалий
    SERVICE_ADMIN = "service_admin"                  # Администратор сервисов / DevOps Lead
    DEVELOPER_LEAD = "developer_lead"                # Тимлид разработки
    DEVELOPER = "developer"                          # Разработчик
    QA_ENGINEER = "qa_engineer"                      # Инженер тестирования
    AUDITOR_INTERNAL = "auditor_internal"            # Внутренний аудитор ИБ
    AUDITOR_EXTERNAL = "auditor_external"            # Внешний регулятор / Аудитор ЦБ
    RELEASE_MANAGER = "release_manager"              # Релиз-менеджер
    ZONE_OPERATOR_ZPE = "zone_operator_zpe"          # Оператор ЗПЭ
    PRODUCT_OWNER = "product_owner"                  # Владелец продукта / КИТС


# ── Actions & Capabilities ───────────────────────────────────────────────────

class Action:
    # Read / Discovery
    READ = "read"
    REPORT_EXPORT = "report:export"
    REPORT_EXPORT_ALL = "report:export_all"
    DASHBOARD_VIEW = "dashboard:view"
    TELEMETRY_VIEW = "telemetry:view"

    # Scans & Findings
    SCAN_START = "scan:start"
    SCAN_STOP = "scan:stop"
    FINDING_TAG = "finding:tag"
    FINDING_SUPPRESS = "finding:suppress"
    FINDING_VIEW_ALL = "finding:view_all"
    FINDING_VIEW_TEAM = "finding:view_team"
    EVIDENCE_VIEW_ALL = "evidence:view_all"

    # Gates & Policies
    GATE_DECIDE = "gate:decide"
    GATE_OVERRIDE = "gate:override"
    POLICY_WRITE = "policy:write"
    ANOMALY_MANAGE = "anomaly:manage"
    ADMISSION_APPROVE = "admission:approve"

    # Releases & Deployments
    RELEASE_CREATE = "release:create"
    RELEASE_SUBMIT = "release:submit"
    RELEASE_APPROVE = "release:approve"
    RELEASE_REJECT = "release:reject"
    RELEASE_DEPLOY = "release:deploy"
    RELEASE_TRANSFER = "release:transfer"
    RELEASE_ROLLBACK = "release:rollback"

    # Envelopes & Compliance Acts
    ACT_SIGN = "act:sign"
    ACT_VIEW_ALL = "act:view_all"
    ACT_VERIFY = "act:verify"
    ENVELOPE_EXPORT = "envelope:export"
    ENVELOPE_IMPORT = "envelope:import"
    ENVELOPE_VERIFY = "envelope:verify"

    # Config & Administration
    PIPELINE_CONFIGURE = "pipeline:configure"
    BRICK_MANAGE = "brick:manage"
    DOMAIN_CONFIGURE = "domain:configure"
    RBAC_MANAGE = "rbac:manage"
    AUDIT_READ_ALL = "audit:read_all"
    ZPE_DEPLOY = "zpe:deploy"
    ZPE_ROLLBACK = "zpe:rollback"

    # First-class entity writes (COS-083 capability granularity pass 2)
    BUILD_RUN = "build:run"          # trigger / abort builds
    DEPLOY_MANAGE = "deploy:manage"  # create deployments / rollback
    PROJECT_WRITE = "project:write"  # create/update projects, attach apps, KITS tags


# ── Canonical Base Permission Matrix (COS-096) ───────────────────────────────

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
        "gate:decide",
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
        # COS-083: service admin — first-class entity writes
        "build:run",
        "deploy:manage",
        "project:write",
    }),
    Role.USER: frozenset({
        "read",
        "report:export",
    }),
}

_READ_ONLY_PERMISSIONS = frozenset({"read", "report:export"})


# ── 12 CBR Role Capability Bundles (COS-110) ─────────────────────────────────

_CBR_ROLE_CAPABILITIES: Dict[CBRRole, FrozenSet[str]] = {
    CBRRole.SECURITY_OFFICER: frozenset({
        Action.READ,
        Action.DASHBOARD_VIEW,
        Action.TELEMETRY_VIEW,
        Action.REPORT_EXPORT_ALL,
        Action.REPORT_EXPORT,
        Action.SCAN_START,
        Action.SCAN_STOP,
        Action.FINDING_TAG,
        Action.FINDING_SUPPRESS,
        Action.FINDING_VIEW_ALL,
        Action.EVIDENCE_VIEW_ALL,
        Action.GATE_DECIDE,
        Action.GATE_OVERRIDE,
        Action.POLICY_WRITE,
        Action.RELEASE_APPROVE,
        Action.RELEASE_REJECT,
        Action.RELEASE_TRANSFER,
        Action.ACT_SIGN,
        Action.ACT_VIEW_ALL,
        Action.ACT_VERIFY,
        Action.ENVELOPE_EXPORT,
        Action.ENVELOPE_VERIFY,
        Action.RBAC_MANAGE,
        Action.AUDIT_READ_ALL,
    }),
    CBRRole.SECURITY_ANALYST: frozenset({
        Action.READ,
        Action.DASHBOARD_VIEW,
        Action.REPORT_EXPORT,
        Action.SCAN_START,
        Action.SCAN_STOP,
        Action.FINDING_TAG,
        Action.FINDING_SUPPRESS,
        Action.FINDING_VIEW_ALL,
        Action.EVIDENCE_VIEW_ALL,
        Action.ACT_VIEW_ALL,
        Action.ACT_VERIFY,
        Action.ENVELOPE_VERIFY,
    }),
    CBRRole.ABNORMAL_ADMIN: frozenset({
        Action.READ,
        Action.DASHBOARD_VIEW,
        Action.REPORT_EXPORT,
        Action.FINDING_VIEW_ALL,
        Action.EVIDENCE_VIEW_ALL,
        Action.GATE_DECIDE,
        Action.GATE_OVERRIDE,
        Action.ANOMALY_MANAGE,
        Action.ADMISSION_APPROVE,
    }),
    CBRRole.SERVICE_ADMIN: frozenset({
        Action.READ,
        Action.DASHBOARD_VIEW,
        Action.REPORT_EXPORT,
        Action.SCAN_START,
        Action.PIPELINE_CONFIGURE,
        Action.BRICK_MANAGE,
        Action.DOMAIN_CONFIGURE,
        Action.FINDING_VIEW_ALL,
        Action.EVIDENCE_VIEW_ALL,
        # COS-083: first-class entity writes
        Action.BUILD_RUN,
        Action.DEPLOY_MANAGE,
        Action.PROJECT_WRITE,
    }),
    CBRRole.DEVELOPER_LEAD: frozenset({
        Action.READ,
        Action.DASHBOARD_VIEW,
        Action.REPORT_EXPORT,
        Action.SCAN_START,
        Action.FINDING_TAG,
        Action.FINDING_VIEW_TEAM,
        Action.RELEASE_CREATE,
        Action.RELEASE_SUBMIT,
        Action.RELEASE_DEPLOY,
        Action.ENVELOPE_EXPORT,
        # COS-083: first-class entity writes
        Action.BUILD_RUN,
        Action.DEPLOY_MANAGE,
        Action.PROJECT_WRITE,
    }),
    CBRRole.DEVELOPER: frozenset({
        Action.READ,
        Action.DASHBOARD_VIEW,
        Action.REPORT_EXPORT,
        Action.SCAN_START,
        Action.FINDING_VIEW_TEAM,
        # COS-083: developer triggers builds
        Action.BUILD_RUN,
    }),
    CBRRole.QA_ENGINEER: frozenset({
        Action.READ,
        Action.DASHBOARD_VIEW,
        Action.REPORT_EXPORT,
        Action.SCAN_START,
        Action.FINDING_VIEW_ALL,
        Action.EVIDENCE_VIEW_ALL,
        Action.ENVELOPE_VERIFY,
        # COS-083: QA triggers builds for testing
        Action.BUILD_RUN,
    }),
    CBRRole.AUDITOR_INTERNAL: frozenset({
        Action.READ,
        Action.DASHBOARD_VIEW,
        Action.TELEMETRY_VIEW,
        Action.REPORT_EXPORT_ALL,
        Action.REPORT_EXPORT,
        Action.FINDING_VIEW_ALL,
        Action.EVIDENCE_VIEW_ALL,
        Action.ACT_VIEW_ALL,
        Action.ACT_VERIFY,
        Action.AUDIT_READ_ALL,
        Action.ENVELOPE_VERIFY,
    }),
    CBRRole.AUDITOR_EXTERNAL: frozenset({
        Action.READ,
        Action.REPORT_EXPORT_ALL,
        Action.REPORT_EXPORT,
        Action.ACT_VIEW_ALL,
        Action.ACT_VERIFY,
        Action.ENVELOPE_VERIFY,
        Action.EVIDENCE_VIEW_ALL,
    }),
    CBRRole.RELEASE_MANAGER: frozenset({
        Action.READ,
        Action.DASHBOARD_VIEW,
        Action.REPORT_EXPORT,
        Action.RELEASE_CREATE,
        Action.RELEASE_SUBMIT,
        Action.RELEASE_DEPLOY,
        Action.RELEASE_TRANSFER,
        Action.ENVELOPE_EXPORT,
        Action.ENVELOPE_IMPORT,
        Action.ENVELOPE_VERIFY,
        # COS-083: release manager operates deployments
        Action.DEPLOY_MANAGE,
    }),
    CBRRole.ZONE_OPERATOR_ZPE: frozenset({
        Action.READ,
        Action.DASHBOARD_VIEW,
        Action.TELEMETRY_VIEW,
        Action.ZPE_DEPLOY,
        Action.ZPE_ROLLBACK,
        Action.ENVELOPE_IMPORT,
        Action.ENVELOPE_VERIFY,
        # COS-083: zone operator operates deployments in own zone
        Action.DEPLOY_MANAGE,
    }),
    CBRRole.PRODUCT_OWNER: frozenset({
        Action.READ,
        Action.DASHBOARD_VIEW,
        Action.TELEMETRY_VIEW,
        Action.REPORT_EXPORT,
        Action.FINDING_VIEW_TEAM,
        # COS-083: product owner owns КИТС project structure
        Action.PROJECT_WRITE,
    }),
}

_READ_ONLY_PERMISSIONS = frozenset({
    Action.READ,
    Action.REPORT_EXPORT,
    Action.DASHBOARD_VIEW,
    Action.TELEMETRY_VIEW,
    Action.ACT_VIEW_ALL,
    Action.ACT_VERIFY,
})


# ── Zone Restriction Matrix ──────────────────────────────────────────────────

_ZONE_ZR_ACTIONS: FrozenSet[str] = frozenset({
    Action.READ, Action.DASHBOARD_VIEW, Action.TELEMETRY_VIEW,
    Action.REPORT_EXPORT, Action.REPORT_EXPORT_ALL,
    Action.SCAN_START, Action.SCAN_STOP,
    Action.FINDING_TAG, Action.FINDING_SUPPRESS, Action.FINDING_VIEW_ALL, Action.FINDING_VIEW_TEAM,
    Action.EVIDENCE_VIEW_ALL,
    Action.GATE_DECIDE, Action.GATE_OVERRIDE, Action.POLICY_WRITE, Action.ANOMALY_MANAGE, Action.ADMISSION_APPROVE,
    Action.RELEASE_CREATE, Action.RELEASE_SUBMIT, Action.RELEASE_APPROVE, Action.RELEASE_REJECT,
    Action.RELEASE_TRANSFER,
    Action.ACT_SIGN, Action.ACT_VIEW_ALL, Action.ACT_VERIFY,
    Action.ENVELOPE_EXPORT, Action.ENVELOPE_VERIFY,
    Action.PIPELINE_CONFIGURE, Action.BRICK_MANAGE, Action.DOMAIN_CONFIGURE, Action.RBAC_MANAGE, Action.AUDIT_READ_ALL,
    # COS-083: first-class entity writes in ЗР (development zone)
    Action.BUILD_RUN, Action.DEPLOY_MANAGE, Action.PROJECT_WRITE,
})

_ZONE_ZT_ACTIONS: FrozenSet[str] = frozenset({
    Action.READ, Action.DASHBOARD_VIEW, Action.TELEMETRY_VIEW,
    Action.REPORT_EXPORT, Action.REPORT_EXPORT_ALL,
    Action.SCAN_START, Action.SCAN_STOP,
    Action.FINDING_TAG, Action.FINDING_SUPPRESS, Action.FINDING_VIEW_ALL, Action.FINDING_VIEW_TEAM,
    Action.EVIDENCE_VIEW_ALL,
    Action.GATE_DECIDE, Action.GATE_OVERRIDE, Action.ANOMALY_MANAGE, Action.ADMISSION_APPROVE,
    Action.RELEASE_DEPLOY, Action.RELEASE_TRANSFER,
    Action.ACT_SIGN, Action.ACT_VIEW_ALL, Action.ACT_VERIFY,
    Action.ENVELOPE_EXPORT, Action.ENVELOPE_IMPORT, Action.ENVELOPE_VERIFY,
    Action.AUDIT_READ_ALL,
    # COS-083: builds и деплои в тестовой зоне; администрация проектов — ЗР
    Action.BUILD_RUN, Action.DEPLOY_MANAGE,
})

_ZONE_ZPE_ACTIONS: FrozenSet[str] = frozenset({
    Action.READ, Action.DASHBOARD_VIEW, Action.TELEMETRY_VIEW,
    Action.REPORT_EXPORT, Action.REPORT_EXPORT_ALL,
    Action.ZPE_DEPLOY, Action.ZPE_ROLLBACK,
    Action.ENVELOPE_IMPORT, Action.ENVELOPE_VERIFY,
    Action.ACT_VIEW_ALL, Action.ACT_VERIFY,
    Action.AUDIT_READ_ALL,
    # COS-083: эксплуатационные деплои/откаты в продуктиве
    Action.DEPLOY_MANAGE,
})

_ZONE_ALLOWED_ACTIONS: Dict[ZoneType, FrozenSet[str]] = {
    "zr": _ZONE_ZR_ACTIONS,
    "zt": _ZONE_ZT_ACTIONS,
    "zpe": _ZONE_ZPE_ACTIONS,
    "all": _ZONE_ZR_ACTIONS | _ZONE_ZT_ACTIONS | _ZONE_ZPE_ACTIONS,
}


# ── PrincipalContext ─────────────────────────────────────────────────────────

@dataclass
class PrincipalContext:
    """SAN-006 [COS-031]: Честный контекст авторизованного субъекта."""
    user_id: str
    email: str = ""
    roles: List[Role | CBRRole | str] = field(default_factory=list)
    domain_memberships: Dict[str, DomainMember] = field(default_factory=dict)
    domain_id: str = ""
    zone: ZoneType = "zr"
    team_scopes: List[str] = field(default_factory=list)
    is_authenticated: bool = True
    auth_claims: Dict[str, Any] = field(default_factory=dict)
    is_system_admin: bool = False

    def has_role(self, role: Any) -> bool:
        r_str = role.value if hasattr(role, "value") else str(role)
        r_clean = r_str.split(".")[-1].lower() if ("." in r_str and not hasattr(role, "value")) else r_str.lower()
        for r in self.roles:
            curr_str = r.value if hasattr(r, "value") else str(r)
            curr_clean = curr_str.split(".")[-1].lower() if ("." in curr_str and not hasattr(r, "value")) else curr_str.lower()
            if curr_clean == r_clean:
                return True
        return False


# ── DomainMember / DomainRBAC ────────────────────────────────────────────────

@dataclass
class DomainMember:
    """Пользователь в контексте домена: роль + team scopes."""
    user_id: str
    role: Role | CBRRole | str
    team_scopes: List[str] = field(default_factory=list)
    allowed_zones: List[ZoneType] = field(default_factory=lambda: ["zr", "zt", "zpe"])


@dataclass
class DomainRBAC:
    """Конфигурация RBAC для одного Domain."""
    domain_id: str
    members: List[DomainMember] = field(default_factory=list)
    inheritance_mode: InheritanceMode = "isolate"
    parent_domain_id: Optional[str] = None

    def get_member(self, user_id: str) -> DomainMember | None:
        """Найти пользователя в домене."""
        for m in self.members:
            if m.user_id == user_id:
                return m
        return None

    def resolve_permissions(
        self,
        user_id: str,
        parent_rbac: DomainRBAC | None = None,
    ) -> FrozenSet[str]:
        """Разрешить эффективные права пользователя с учетом базовых и CBR ролей."""
        member = self.get_member(user_id)

        if member is None:
            if parent_rbac and self.inheritance_mode == "merge":
                parent_member = parent_rbac.get_member(user_id)
                if parent_member and self._scope_match(parent_member.team_scopes, None):
                    return self._resolve_member_role_perms(parent_member.role)
            return frozenset()

        role_perms = self._resolve_member_role_perms(member.role)
        if role_perms == frozenset({"read", "report:export"}):
            return role_perms  # user only — no merge expansion

        if parent_rbac and self.inheritance_mode == "merge":
            parent_perms = parent_rbac.resolve_permissions(user_id)
            role_perms = role_perms | parent_perms

        return role_perms

    @staticmethod
    def _resolve_member_role_perms(role: Role | CBRRole | str) -> FrozenSet[str]:
        """Разрешить права для конкретной роли (базовой или CBR)."""
        if isinstance(role, Role) or (isinstance(role, str) and role in Role._value2member_map_):
            r_enum = Role(role) if isinstance(role, str) else role
            return _PERMISSIONS.get(r_enum, frozenset())

        if isinstance(role, CBRRole) or (isinstance(role, str) and role in CBRRole._value2member_map_):
            cbr_enum = CBRRole(role) if isinstance(role, str) else role
            return _CBR_ROLE_CAPABILITIES.get(cbr_enum, frozenset())

        return frozenset()

    def has_permission(
        self,
        user_id: str,
        action: str,
        parent_rbac: DomainRBAC | None = None,
        required_scope: str | None = None,
        zone: ZoneType = "zr",
    ) -> bool:
        """Проверить право пользователя с учетом прав, скоупов и зоны."""
        member = self.get_member(user_id)

        # Проверка зоны
        if zone != "all":
            allowed_zone_actions = _ZONE_ALLOWED_ACTIONS.get(zone, frozenset())
            if action not in allowed_zone_actions:
                return False

            if member and member.allowed_zones and zone not in member.allowed_zones and "all" not in member.allowed_zones:
                return False

        # Проверка team scope
        if required_scope and member:
            if not self._scope_match(member.team_scopes, required_scope):
                return False

        perms = self.resolve_permissions(user_id, parent_rbac)
        return action in perms

    def evaluate(
        self,
        principal: PrincipalContext,
        action: str,
        target_zone: Optional[ZoneType] = None,
        target_scope: Optional[str] = None,
        parent_rbac: DomainRBAC | None = None,
    ) -> Tuple[bool, str]:
        """COS-110 / COS-125: Главный метод оценки авторизации (Grand RBAC Engine).

        Returns:
            (is_allowed, reason_code)
        """
        if not principal.is_authenticated:
            return False, "401_UNAUTHORIZED"

        if principal.is_system_admin:
            return True, "200_SYSTEM_ADMIN"

        zone_to_check = target_zone or principal.zone or "zr"

        # 1. Проверка зоны действия
        if zone_to_check != "all":
            zone_actions = _ZONE_ALLOWED_ACTIONS.get(zone_to_check, frozenset())
            if action not in zone_actions:
                return False, f"403_ZONE_FORBIDDEN: action '{action}' not permitted in zone '{zone_to_check}'"

        # 2. Проверка team scopes
        if target_scope:
            if not self._scope_match(principal.team_scopes, target_scope):
                return False, f"403_SCOPE_MISMATCH: required scope '{target_scope}' not in principal scopes"

        # 3. Разрешение всех capability из ролей субъекта
        combined_perms: Set[str] = set()
        for r in principal.roles:
            combined_perms.update(self._resolve_member_role_perms(r))

        # Если пользователь также зарегистрирован как DomainMember
        member = self.get_member(principal.user_id)
        if not member and principal.domain_memberships:
            member = principal.domain_memberships.get(self.domain_id)
        if member:
            combined_perms.update(self._resolve_member_role_perms(member.role))

        # Наследование merge
        if parent_rbac and self.inheritance_mode == "merge":
            parent_perms = parent_rbac.resolve_permissions(principal.user_id)
            combined_perms.update(parent_perms)

        if action in combined_perms:
            return True, "200_ALLOWED"

        return False, f"403_ACTION_FORBIDDEN: action '{action}' not granted to principal roles"

    @staticmethod
    def _scope_match(member_scopes: List[str], required: str | None) -> bool:
        """Проверка team scopes."""
        if required is None:
            return True
        if not member_scopes:
            return False
        return required in member_scopes or "*" in member_scopes

    def validate_role(self, allowed_roles: List[Role | CBRRole | str], user_id: str) -> bool:
        """Проверить, что пользователь имеет одну из разрешённых ролей."""
        member = self.get_member(user_id)
        if member is None:
            return False
        mem_r = member.role.value if isinstance(member.role, (Role, CBRRole)) else str(member.role)
        for r in allowed_roles:
            r_str = r.value if isinstance(r, (Role, CBRRole)) else str(r)
            if mem_r == r_str:
                return True
        return False


# ── Separation of Duties (SoD) Engine ────────────────────────────────────────

class SeparationOfDutiesEngine:
    """COS-110 / COS-115: Движок проверки принципа разделения обязанностей (SoD)."""

    @staticmethod
    def check_release_approval_sod(
        release_created_by: str,
        approver_id: str,
    ) -> Tuple[bool, str]:
        """Правило SoD 1: Создатель/автор релиза не может сам его утверждать."""
        if release_created_by and release_created_by == approver_id:
            return False, "409_SOD_VIOLATION: creator cannot approve their own release"
        return True, "200_SOD_CLEAN"

    @staticmethod
    def check_double_approval_sod(
        existing_approvers: List[str],
        current_approver: str,
    ) -> Tuple[bool, str]:
        """Правило SoD 2: Один и тот же человек не может дважды подписывать один этап."""
        if current_approver in existing_approvers:
            return False, "409_SOD_VIOLATION: user has already approved this release stage"
        return True, "200_SOD_CLEAN"

    @staticmethod
    def check_transfer_gatekeeper_sod(
        transfer_initiator: str,
        gate_decider: str,
    ) -> Tuple[bool, str]:
        """Правило SoD 3: Инициатор трансфера и лицо, подтверждающее гейты, должны быть разными."""
        if transfer_initiator and transfer_initiator == gate_decider:
            return False, "409_SOD_VIOLATION: transfer initiator cannot be sole gate decider"
        return True, "200_SOD_CLEAN"


# ── FastAPI Dependencies ─────────────────────────────────────────────────────

def require_role(
    allowed_roles: List[Role | CBRRole | str],
    required_scope: str | None = None,
    action: str | None = None,
):
    """SAN-006 [COS-031]: Боевая FastAPI dependency — строгая авторизация без заглушек.

    Единственный источник истины — DomainRBAC.evaluate().
    """
    from fastapi import Depends, HTTPException, status
    try:
        from cosmo.api.deps import get_current_principal
    except ImportError:
        from orchestrator.cosmo.api.deps import get_current_principal  # type: ignore

    async def _check_rbac_dependency(
        principal: PrincipalContext = Depends(get_current_principal),
    ) -> PrincipalContext:
        if not principal.is_authenticated:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="401_UNAUTHORIZED: Missing or invalid credentials",
            )

        if principal.is_system_admin:
            return principal

        # Если указано конкретное действие action — оцениваем через DomainRBAC.evaluate
        if action:
            rbac = DomainRBAC(domain_id=principal.domain_id or "default")
            allowed, reason = rbac.evaluate(
                principal=principal,
                action=action,
                target_scope=required_scope,
            )
            if not allowed:
                if "401" in reason:
                    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=reason)
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=reason)
            return principal

        # Проверка допустимых ролей
        allowed_role_strs = {
            r.value if isinstance(r, (Role, CBRRole)) else str(r)
            for r in allowed_roles
        }
        user_role_strs = {
            r.value if isinstance(r, (Role, CBRRole)) else str(r)
            for r in principal.roles
        }
        if not user_role_strs.intersection(allowed_role_strs):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"403_FORBIDDEN: User roles {sorted(list(user_role_strs))} do not have required {sorted(list(allowed_role_strs))}",
            )

        if required_scope:
            if required_scope not in principal.team_scopes and "*" not in principal.team_scopes:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"403_FORBIDDEN: Team scope '{required_scope}' required",
                )

        return principal

    return _check_rbac_dependency


def require_scoped_role(
    allowed_roles: List[Role | CBRRole | str],
    scope: str,
    action: str | None = None,
):
    """SAN-006 [COS-031]: Проверка роли со scope-ограничением."""
    return require_role(allowed_roles=allowed_roles, required_scope=scope, action=action)


# ── Helper accessors ─────────────────────────────────────────────────────────

def is_readonly_permissions(perms: FrozenSet[str]) -> bool:
    return perms.issubset(_READ_ONLY_PERMISSIONS)


def can_manage_rbac(user_perms: FrozenSet[str]) -> bool:
    return Action.RBAC_MANAGE in user_perms


def can_sign_gate(user_perms: FrozenSet[str]) -> bool:
    return Action.GATE_DECIDE in user_perms


def can_transfer_to_prod(user_perms: FrozenSet[str]) -> bool:
    return Action.RELEASE_TRANSFER in user_perms


def can_approve_release(user_perms: FrozenSet[str]) -> bool:
    return Action.RELEASE_APPROVE in user_perms


def can_start_scan(user_perms: FrozenSet[str]) -> bool:
    return Action.SCAN_START in user_perms


def can_tag_findings(user_perms: FrozenSet[str]) -> bool:
    return Action.FINDING_TAG in user_perms
