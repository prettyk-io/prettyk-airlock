"""
COS-125: Complete 726-Row RBAC Matrix Verification Suite (8,712 Combinations Test).

Выполняет исчерпывающую матричную верификацию Grand RBAC Engine (DomainRBAC.evaluate):
  - 12 ролей ЦБ РФ
  - 22 репрезентативных действия
  - 3 зоны (ЗР / ЗТ / ЗПЭ)
  - 11 контекстов принципала / скоупа
  = 12 x 22 x 3 x 11 = 8,712 комбинаций с проверкой каждого вердикта.
"""
import pytest
from cosmo.domain.rbac import (
    Action,
    CBRRole,
    DomainMember,
    DomainRBAC,
    PrincipalContext,
    _CBR_ROLE_CAPABILITIES,
    _ZONE_ALLOWED_ACTIONS,
)

ALL_12_ROLES = list(CBRRole)

REPRESENTATIVE_22_ACTIONS = [
    Action.READ,
    Action.REPORT_EXPORT,
    Action.REPORT_EXPORT_ALL,
    Action.DASHBOARD_VIEW,
    Action.TELEMETRY_VIEW,
    Action.SCAN_START,
    Action.SCAN_STOP,
    Action.FINDING_TAG,
    Action.FINDING_SUPPRESS,
    Action.FINDING_VIEW_ALL,
    Action.FINDING_VIEW_TEAM,
    Action.EVIDENCE_VIEW_ALL,
    Action.GATE_DECIDE,
    Action.GATE_OVERRIDE,
    Action.POLICY_WRITE,
    Action.RELEASE_CREATE,
    Action.RELEASE_SUBMIT,
    Action.RELEASE_APPROVE,
    Action.RELEASE_DEPLOY,
    Action.RELEASE_TRANSFER,
    Action.ACT_SIGN,
    Action.ZPE_DEPLOY,
]

ZONES = ["zr", "zt", "zpe"]

# 11 контекстов принципала и области видимости
CONTEXTS = [
    {"desc": "authenticated_valid_scope", "auth": True, "admin": False, "p_scopes": ["team_alpha", "team_beta"], "req_scope": "team_alpha"},
    {"desc": "authenticated_scope_mismatch", "auth": True, "admin": False, "p_scopes": ["team_gamma"], "req_scope": "team_alpha"},
    {"desc": "authenticated_no_scope_req", "auth": True, "admin": False, "p_scopes": ["team_alpha"], "req_scope": None},
    {"desc": "authenticated_empty_scopes", "auth": True, "admin": False, "p_scopes": [], "req_scope": "team_alpha"},
    {"desc": "authenticated_wildcard_scope", "auth": True, "admin": False, "p_scopes": ["*"], "req_scope": "team_alpha"},
    {"desc": "unauthenticated", "auth": False, "admin": False, "p_scopes": ["team_alpha"], "req_scope": "team_alpha"},
    {"desc": "system_admin_valid_scope", "auth": True, "admin": True, "p_scopes": ["team_alpha"], "req_scope": "team_alpha"},
    {"desc": "system_admin_no_scope", "auth": True, "admin": True, "p_scopes": [], "req_scope": "team_beta"},
    {"desc": "authenticated_multi_scopes", "auth": True, "admin": False, "p_scopes": ["team_1", "team_2", "team_3"], "req_scope": "team_2"},
    {"desc": "authenticated_multi_scopes_fail", "auth": True, "admin": False, "p_scopes": ["team_1", "team_2"], "req_scope": "team_4"},
    {"desc": "authenticated_global_scope_none", "auth": True, "admin": False, "p_scopes": [], "req_scope": None},
]


def test_rbac_8712_combination_matrix():
    """Тестирование 8,712 комбинаций авторизации."""
    rbac = DomainRBAC(domain_id="dom-cbr-matrix")
    total_evaluations = 0
    allow_count = 0
    deny_count = 0

    for role in ALL_12_ROLES:
        role_caps = _CBR_ROLE_CAPABILITIES[role]

        for action in REPRESENTATIVE_22_ACTIONS:
            for zone in ZONES:
                zone_allowed = _ZONE_ALLOWED_ACTIONS[zone]

                for ctx in CONTEXTS:
                    total_evaluations += 1
                    principal = PrincipalContext(
                        user_id=f"user-{role.value}",
                        roles=[role],
                        domain_id="dom-cbr-matrix",
                        zone=zone,  # type: ignore
                        team_scopes=list(ctx["p_scopes"]),
                        is_authenticated=ctx["auth"],
                        is_system_admin=ctx["admin"],
                    )

                    allowed, reason = rbac.evaluate(
                        principal=principal,
                        action=action,
                        target_zone=zone,  # type: ignore
                        target_scope=ctx["req_scope"],
                    )

                    # 1. Unauthenticated -> 401
                    if not ctx["auth"]:
                        assert allowed is False
                        assert reason == "401_UNAUTHORIZED"
                        deny_count += 1
                        continue

                    # 2. System Admin -> 200
                    if ctx["admin"]:
                        assert allowed is True
                        assert reason == "200_SYSTEM_ADMIN"
                        allow_count += 1
                        continue

                    # 3. Zone restriction check
                    if action not in zone_allowed:
                        assert allowed is False
                        assert "403_ZONE_FORBIDDEN" in reason
                        deny_count += 1
                        continue

                    # 4. Scope match check
                    req_scope = ctx["req_scope"]
                    p_scopes = ctx["p_scopes"]
                    scope_ok = (req_scope is None) or ("*" in p_scopes) or (req_scope in p_scopes)
                    if not scope_ok:
                        assert allowed is False
                        assert "403_SCOPE_MISMATCH" in reason
                        deny_count += 1
                        continue

                    # 5. Role capability check
                    if action not in role_caps:
                        assert allowed is False
                        assert "403_ACTION_FORBIDDEN" in reason
                        deny_count += 1
                        continue

                    # 6. All checks passed -> 200
                    assert allowed is True
                    assert reason == "200_ALLOWED"
                    allow_count += 1

    assert total_evaluations == 8712
    assert allow_count > 0
    assert deny_count > 0
    assert allow_count + deny_count == 8712


def test_rbac_cbr_role_assignments():
    """Проверка ролевых моделей членов домена и изоляции."""
    rbac = DomainRBAC(
        domain_id="dom-cbr",
        members=[
            DomainMember(user_id="officer_1", role=CBRRole.SECURITY_OFFICER, team_scopes=["all"]),
            DomainMember(user_id="dev_1", role=CBRRole.DEVELOPER, team_scopes=["team_front"]),
            DomainMember(user_id="auditor_1", role=CBRRole.AUDITOR_INTERNAL, team_scopes=["all"]),
        ],
    )

    # Офицер ИБ может подписывать ГОСТ акт в ЗР и ЗТ
    assert rbac.has_permission("officer_1", Action.ACT_SIGN, zone="zr") is True
    assert rbac.has_permission("officer_1", Action.ACT_SIGN, zone="zt") is True
    # В ЗПЭ подписание актов запрещено политикой зоны
    assert rbac.has_permission("officer_1", Action.ACT_SIGN, zone="zpe") is False

    # Разработчик может смотреть находки своей команды в ЗР
    assert rbac.has_permission("dev_1", Action.FINDING_VIEW_TEAM, required_scope="team_front", zone="zr") is True
    # Не может смотреть находки чужой команды
    assert rbac.has_permission("dev_1", Action.FINDING_VIEW_TEAM, required_scope="team_back", zone="zr") is False
    # Не может подписывать гейты
    assert rbac.has_permission("dev_1", Action.GATE_DECIDE, zone="zr") is False

    # Аудитор имеет доступ на чтение аудита
    assert rbac.has_permission("auditor_1", Action.AUDIT_READ_ALL, zone="zr") is True
    assert rbac.has_permission("auditor_1", Action.AUDIT_READ_ALL, zone="zt") is True
    assert rbac.has_permission("auditor_1", Action.AUDIT_READ_ALL, zone="zpe") is True
