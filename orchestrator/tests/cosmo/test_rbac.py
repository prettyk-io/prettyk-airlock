"""
COS-096: Domain RBAC tests — 5 roles, team scopes, inheritance merge/isolate.

Проверяет:
  - Permission matrix (admin_sec vs sec_expert vs user)
  - Team scope isolation (пользователь не видит чужие скоупы)
  - Inheritance merge (родительские права добавляются)
  - Inheritance isolate (родительские права НЕ наследуются)
  - Helper functions (can_sign_gate, can_transfer, is_readonly, etc.)
  - Edge cases (нет скоупов, нет роли, пустой RBAC)
"""
import pytest
from cosmo.domain.rbac import (
    DomainMember, DomainRBAC, Role, InheritanceMode,
    _PERMISSIONS,
    is_readonly_permissions, can_manage_rbac, can_sign_gate,
    can_transfer_to_prod, can_approve_release, can_start_scan,
    can_tag_findings,
)


# ── Helpers ──────────────────────────────────────────────────────────────

def _member(uid="u1", role=Role.ADMIN_SEC, scopes=None):
    return DomainMember(user_id=uid, role=role, team_scopes=scopes or ["payments"])

def _rbac(domain_id="d1", members=None, mode="isolate", parent=None):
    return DomainRBAC(domain_id=domain_id, members=members or [],
                      inheritance_mode=mode, parent_domain_id=parent)


# =============================================================================
# Permission Matrix
# =============================================================================

class TestPermissionMatrix:
    """Каноническая матрица прав для каждой роли."""

    def test_admin_sec_has_all_critical_actions(self):
        perms = _PERMISSIONS[Role.ADMIN_SEC]
        assert "gate:decide" in perms
        assert "release:transfer" in perms
        assert "release:approve" in perms
        assert "act:sign" in perms
        assert "rbac:manage" in perms

    def test_admin_abnormal_can_decide_gate(self):
        perms = _PERMISSIONS[Role.ADMIN_ABNORMAL]
        assert "gate:decide" in perms
        assert "gate:override" in perms
        assert "release:transfer" not in perms  # только admin_sec
        assert "act:sign" not in perms

    def test_sec_expert_can_scan_tag_view(self):
        perms = _PERMISSIONS[Role.SEC_EXPERT]
        assert "scan:start" in perms
        assert "finding:tag" in perms
        assert "gate:decide" not in perms  # не может подписывать допуск
        assert "release:transfer" not in perms

    def test_admin_service_can_configure_pipelines(self):
        perms = _PERMISSIONS[Role.ADMIN_SERVICE]
        assert "pipeline:configure" in perms
        assert "scan:start" in perms
        assert "gate:decide" not in perms

    def test_user_is_read_only(self):
        perms = _PERMISSIONS[Role.USER]
        assert perms == frozenset({"read", "report:export"})
        assert is_readonly_permissions(perms)

    def test_no_role_has_unexpected_permissions(self):
        """Ни у одной роли нет несуществующих действий."""
        all_actions = set()
        for perms in _PERMISSIONS.values():
            all_actions |= perms
        known = {"gate:decide", "gate:override", "release:transfer",
                 "release:approve", "act:sign", "scan:start", "scan:stop",
                 "finding:tag", "finding:view_all", "evidence:view_all",
                 "pipeline:configure", "rbac:manage", "domain:configure",
                 "report:export", "read"}
        assert all_actions.issubset(known)


# =============================================================================
# Role Validation
# =============================================================================

class TestRoleValidation:
    def test_member_has_role(self):
        rbac = _rbac(members=[_member(uid="u1", role=Role.ADMIN_SEC)])
        assert rbac.validate_role([Role.ADMIN_SEC], "u1") is True

    def test_member_not_found(self):
        rbac = _rbac()
        assert rbac.validate_role([Role.ADMIN_SEC], "ghost") is False

    def test_wrong_role(self):
        rbac = _rbac(members=[_member(uid="u2", role=Role.USER)])
        assert rbac.validate_role([Role.ADMIN_SEC], "u2") is False

    def test_get_member_found(self):
        rbac = _rbac(members=[_member(uid="u3")])
        m = rbac.get_member("u3")
        assert m is not None
        assert m.role == Role.ADMIN_SEC


# =============================================================================
# Permission Resolution
# =============================================================================

class TestResolvePermissions:
    def test_admin_sec_full_perms(self):
        rbac = _rbac(members=[_member(uid="a", role=Role.ADMIN_SEC)])
        perms = rbac.resolve_permissions("a")
        assert "gate:decide" in perms
        assert "release:transfer" in perms

    def test_user_readonly(self):
        rbac = _rbac(members=[_member(uid="u", role=Role.USER)])
        perms = rbac.resolve_permissions("u")
        assert perms == frozenset({"read", "report:export"})

    def test_unknown_user_empty(self):
        rbac = _rbac()
        perms = rbac.resolve_permissions("nobody")
        assert perms == frozenset()


# =============================================================================
# Team Scope Isolation
# =============================================================================

class TestScopeIsolation:
    def test_scope_match_grants(self):
        rbac = _rbac(members=[_member(uid="a", scopes=["payments", "crypto"])])
        assert rbac.has_permission("a", "read", required_scope="payments")

    def test_scope_mismatch_denied(self):
        rbac = _rbac(members=[_member(uid="a", scopes=["payments"])])
        assert not rbac.has_permission("a", "read", required_scope="crypto")

    def test_scope_none_is_global(self):
        """required_scope=None — глобальное действие, доступно всем."""
        rbac = _rbac(members=[_member(uid="a")])
        assert rbac.has_permission("a", "read", required_scope=None)

    def test_no_scopes_denied_for_scoped_action(self):
        """Пользователь без team_scopes не может выполнять scoped-действия."""
        rbac = _rbac(members=[DomainMember(user_id="u", role=Role.USER, team_scopes=[])])
        assert not rbac.has_permission("u", "read", required_scope="payments")


# =============================================================================
# Inheritance: Merge
# =============================================================================

class TestInheritanceMerge:
    def test_merge_child_inherits_parent(self):
        parent = _rbac("d-parent", members=[_member(uid="a", role=Role.ADMIN_SEC)])
        child = _rbac("d-child", members=[_member(uid="a", role=Role.USER)],
                      mode="merge", parent="d-parent")

        perms = child.resolve_permissions("a", parent_rbac=parent)
        assert perms == frozenset({"read", "report:export"})

    def test_merge_no_member_in_child_uses_parent(self):
        parent = _rbac("d-parent", members=[_member(uid="b", role=Role.ADMIN_SEC)])
        child = _rbac("d-child", mode="merge", parent="d-parent")

        perms = child.resolve_permissions("b", parent_rbac=parent)
        assert "gate:decide" in perms

    def test_merge_user_in_child_only(self):
        parent = _rbac("d-parent")
        child = _rbac("d-child", members=[_member(uid="c", role=Role.USER)],
                      mode="merge", parent="d-parent")

        perms = child.resolve_permissions("c", parent_rbac=parent)
        assert perms == frozenset({"read", "report:export"})


# =============================================================================
# Inheritance: Isolate
# =============================================================================

class TestInheritanceIsolate:
    def test_isolate_no_parent_perms(self):
        parent = _rbac("d-parent", members=[_member(uid="a", role=Role.ADMIN_SEC)])
        child = _rbac("d-child", members=[_member(uid="a", role=Role.USER)],
                      mode="isolate", parent="d-parent")

        perms = child.resolve_permissions("a", parent_rbac=parent)
        # isolate: только свои права
        assert perms == frozenset({"read", "report:export"})
        assert "gate:decide" not in perms

    def test_isolate_no_member_no_parent_lookup(self):
        parent = _rbac("d-parent", members=[_member(uid="x", role=Role.ADMIN_SEC)])
        child = _rbac("d-child", mode="isolate", parent="d-parent")

        perms = child.resolve_permissions("x", parent_rbac=parent)
        assert perms == frozenset()


# =============================================================================
# Permission check (has_permission)
# =============================================================================

class TestHasPermission:
    def test_admin_can_gate_decide(self):
        rbac = _rbac(members=[_member(uid="a", role=Role.ADMIN_SEC)])
        assert rbac.has_permission("a", "gate:decide")

    def test_user_cannot_gate_decide(self):
        rbac = _rbac(members=[_member(uid="u", role=Role.USER)])
        assert not rbac.has_permission("u", "gate:decide")

    def test_user_can_read(self):
        rbac = _rbac(members=[_member(uid="u", role=Role.USER)])
        assert rbac.has_permission("u", "read")

    def test_sec_cannot_transfer(self):
        rbac = _rbac(members=[_member(uid="e", role=Role.SEC_EXPERT)])
        assert not rbac.has_permission("e", "release:transfer")

    def test_admin_service_cannot_sign_act(self):
        rbac = _rbac(members=[_member(uid="s", role=Role.ADMIN_SERVICE)])
        assert not rbac.has_permission("s", "act:sign")


# =============================================================================
# Helper Functions
# =============================================================================

class TestHelpers:
    def test_is_readonly(self):
        assert is_readonly_permissions({"read", "report:export"})
        assert not is_readonly_permissions({"read", "scan:start"})

    def test_can_manage_rbac(self):
        assert can_manage_rbac({"rbac:manage"})
        assert not can_manage_rbac(_PERMISSIONS[Role.USER])

    def test_can_sign_gate(self):
        assert can_sign_gate(_PERMISSIONS[Role.ADMIN_SEC])
        assert not can_sign_gate(_PERMISSIONS[Role.USER])

    def test_can_transfer(self):
        assert can_transfer_to_prod(_PERMISSIONS[Role.ADMIN_SEC])
        assert not can_transfer_to_prod(_PERMISSIONS[Role.SEC_EXPERT])

    def test_can_approve_release(self):
        assert can_approve_release(_PERMISSIONS[Role.ADMIN_SEC])
        assert not can_approve_release(_PERMISSIONS[Role.ADMIN_SERVICE])

    def test_can_start_scan(self):
        assert can_start_scan(_PERMISSIONS[Role.SEC_EXPERT])
        assert not can_start_scan(_PERMISSIONS[Role.USER])

    def test_can_tag(self):
        assert can_tag_findings(_PERMISSIONS[Role.SEC_EXPERT])
        assert not can_tag_findings(_PERMISSIONS[Role.USER])


# =============================================================================
# Edge Cases
# =============================================================================

class TestEdgeCases:
    def test_empty_rbac_no_members(self):
        rbac = _rbac()
        assert not rbac.has_permission("anyone", "read")
        perms = rbac.resolve_permissions("nobody")
        assert perms == frozenset()

    def test_multi_members_different_roles(self):
        rbac = _rbac(members=[
            _member(uid="admin", role=Role.ADMIN_SEC),
            _member(uid="expert", role=Role.SEC_EXPERT),
            _member(uid="user", role=Role.USER, scopes=["payments"]),
        ])
        assert rbac.has_permission("admin", "release:transfer")
        assert rbac.has_permission("expert", "scan:start")
        assert not rbac.has_permission("expert", "release:transfer")
        assert rbac.has_permission("user", "read", required_scope="payments")

    def test_scope_list_empty(self):
        rbac = _rbac(members=[DomainMember(user_id="u", role=Role.USER,
                                             team_scopes=[])])
        assert not rbac.has_permission("u", "read", required_scope="payments")

    def test_rbac_validate_role_with_user_scope(self):
        rbac = _rbac(members=[_member(uid="a", role=Role.ADMIN_SEC, scopes=["s1"])])
        assert rbac.has_permission("a", "gate:decide", required_scope="s1")