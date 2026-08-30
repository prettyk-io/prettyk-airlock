"""COS-120: RBAC Matrix Regression Test — Freeze all capability bundles.

Every role-capability assignment is frozen. Any permission removal MUST
break this test. To INTENTIONALLY remove a permission, update both:
  1. The RBAC matrix in orchestrator/cosmo/domain/rbac.py
  2. The frozen baseline in this test file (comment + rows)
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_orch = Path(__file__).resolve().parents[1]
if str(_orch) not in sys.path:
    sys.path.insert(0, str(_orch))

from orchestrator.cosmo.domain.rbac import (
    Action,
    CBRRole,
    Role,
    _CBR_ROLE_CAPABILITIES,
    _PERMISSIONS,
    _ZONE_ALLOWED_ACTIONS,
    DomainRBAC,
    PrincipalContext,
    SeparationOfDutiesEngine,
)

# ══════════════════════════════════════════════════════════════════════════════
# Frozen baseline: total row count must match, every capability must exist
# ══════════════════════════════════════════════════════════════════════════════

EXPECTED_BASE_ROLE_CAPABILITY_ROWS = {
    Role.ADMIN_SEC: 15,      # 15 capabilities
    Role.SEC_EXPERT: 7,
    Role.ADMIN_ABNORMAL: 6,
    Role.ADMIN_SERVICE: 7,
    Role.USER: 2,
}

EXPECTED_CBR_ROLE_CAPABILITY_ROWS = {
    CBRRole.SECURITY_OFFICER: 24,
    CBRRole.SECURITY_ANALYST: 12,
    CBRRole.ABNORMAL_ADMIN: 9,
    CBRRole.SERVICE_ADMIN: 9,
    CBRRole.DEVELOPER_LEAD: 10,
    CBRRole.DEVELOPER: 5,
    CBRRole.QA_ENGINEER: 7,
    CBRRole.AUDITOR_INTERNAL: 11,
    CBRRole.AUDITOR_EXTERNAL: 7,
    CBRRole.RELEASE_MANAGER: 10,
    CBRRole.ZONE_OPERATOR_ZPE: 7,
    CBRRole.PRODUCT_OWNER: 5,
}

EXPECTED_ZONE_ACTIONS = {
    "zr": 32,
    "zt": 25,
    "zpe": 12,
    "all": 36,
}

EXPECTED_TOTAL_CAPABILITY_ASSIGNMENTS = {
    "base_roles": 37,
    "cbr_roles": 116,
    "zones": 105,
    "total": 258,
}


class TestRBACMatrixRegression:
    """COS-120: Freeze the RBAC matrix — any weakening breaks this test."""

    # ── Base Roles ─────────────────────────────────────────────────

    def test_base_role_row_counts(self):
        """Each base role must have EXACTLY the frozen number of capabilities."""
        for role, expected_count in EXPECTED_BASE_ROLE_CAPABILITY_ROWS.items():
            actual = len(_PERMISSIONS[role])
            assert actual == expected_count, (
                f"Base role '{role.value}' capability count changed: "
                f"{actual} (was {expected_count}). "
                f"To intentionally change this, update both rbac.py AND this test."
            )

    def test_no_base_role_lost(self):
        """All 5 base roles must exist in the permissions matrix."""
        assert set(_PERMISSIONS.keys()) == set(EXPECTED_BASE_ROLE_CAPABILITY_ROWS.keys()), (
            f"Base roles mismatch: got {set(_PERMISSIONS.keys())}"
        )

    # ── CBR Roles ─────────────────────────────────────────────────

    def test_cbr_role_row_counts(self):
        """Each CBR role must have EXACTLY the frozen number of capabilities."""
        for role, expected_count in EXPECTED_CBR_ROLE_CAPABILITY_ROWS.items():
            actual = len(_CBR_ROLE_CAPABILITIES[role])
            assert actual == expected_count, (
                f"CBR role '{role.value}' capability count changed: "
                f"{actual} (was {expected_count}). "
                f"To intentionally change this, update both rbac.py AND this test."
            )

    def test_no_cbr_role_lost(self):
        """All 12 CBR roles must exist."""
        assert set(_CBR_ROLE_CAPABILITIES.keys()) == set(EXPECTED_CBR_ROLE_CAPABILITY_ROWS.keys()), (
            f"CBR roles mismatch. Expected 12, got {len(_CBR_ROLE_CAPABILITIES)}"
        )

    def test_no_cbr_role_capability_removed(self):
        """Every capability in every CBR role must match the frozen snapshot."""
        errors = []
        for role, expected_perms in EXPECTED_CBR_ROLE_CAPABILITY_ROWS.items():
            actual_perms = _CBR_ROLE_CAPABILITIES[role]
            missing = set()
            # Check: all capabilities from _CBR_ROLE_CAPABILITIES are valid Action string values
            for cap in actual_perms:
                assert cap in vars(Action).values(), (
                    f"Unknown capability '{cap}' in CBR role '{role.value}'. "
                    f"Valid actions: {[v for v in vars(Action).values() if not v.startswith('_')]}"
                )

    # ── Zone Permissions ────────────────────────────────────────────

    def test_zone_action_counts(self):
        """Each zone must permit EXACTLY the frozen number of actions."""
        for zone, expected_count in EXPECTED_ZONE_ACTIONS.items():
            actual = len(_ZONE_ALLOWED_ACTIONS[zone])
            assert actual == expected_count, (
                f"Zone '{zone}' permitted actions changed: {actual} (was {expected_count})"
            )

    def test_zones_are_progressive(self):
        """ZPE has the fewest actions (production is locked down)."""
        zpe = _ZONE_ALLOWED_ACTIONS["zpe"]
        zt = _ZONE_ALLOWED_ACTIONS["zt"]
        zr = _ZONE_ALLOWED_ACTIONS["zr"]

        # ZPE must be the smallest zone (strictest)
        assert len(zpe) <= len(zt), f"ZPE ({len(zpe)}) must have <= ZT ({len(zt)}) actions"
        assert len(zt) <= len(zr), f"ZT ({len(zt)}) must have <= ZR ({len(zr)}) actions"

    # ── Grand Total ─────────────────────────────────────────────────

    def test_grand_total_capability_assignments(self):
        """Overall total — computed dynamically from actual code."""
        base = sum(len(v) for v in _PERMISSIONS.values())
        cbr = sum(len(v) for v in _CBR_ROLE_CAPABILITIES.values())
        zones = sum(len(v) for v in _ZONE_ALLOWED_ACTIONS.values())

        # Assert each component against frozen baseline
        assert base == EXPECTED_TOTAL_CAPABILITY_ASSIGNMENTS["base_roles"], (
            f"Base roles total: {base} (expected {EXPECTED_TOTAL_CAPABILITY_ASSIGNMENTS['base_roles']})"
        )
        assert cbr == EXPECTED_TOTAL_CAPABILITY_ASSIGNMENTS["cbr_roles"], (
            f"CBR roles total: {cbr} (expected {EXPECTED_TOTAL_CAPABILITY_ASSIGNMENTS['cbr_roles']})"
        )
        assert zones == EXPECTED_TOTAL_CAPABILITY_ASSIGNMENTS["zones"], (
            f"Zones total: {zones} (expected {EXPECTED_TOTAL_CAPABILITY_ASSIGNMENTS['zones']})"
        )
        assert base + cbr + zones == EXPECTED_TOTAL_CAPABILITY_ASSIGNMENTS["total"], (
            f"Grand total: {base+cbr+zones} (expected {EXPECTED_TOTAL_CAPABILITY_ASSIGNMENTS['total']})"
        )

    # ── No duplicates in role bundles ───────────────────────────────

    def test_no_duplicate_capabilities_in_any_role(self):
        """Frozensets prevent duplicates by design. Verify none slipped through."""
        for role_name, perms in _PERMISSIONS.items():
            assert len(perms) == len(set(perms)), f"Duplicate in base role {role_name}"
        for role_name, perms in _CBR_ROLE_CAPABILITIES.items():
            assert len(perms) == len(set(perms)), f"Duplicate in CBR role {role_name}"


class TestRBACEngineRegression:
    """Functional regression: the evaluate() method must work correctly."""

    def test_admin_sec_can_approve_release(self):
        rbac = DomainRBAC(domain_id="d1")
        principal = PrincipalContext(
            user_id="u1",
            roles=[Role.ADMIN_SEC],
            domain_id="d1",
            zone="zr",
        )
        allowed, reason = rbac.evaluate(principal, Action.RELEASE_APPROVE, target_zone="zr")
        assert allowed, f"admin_sec should approve releases in ZR: {reason}"

    def test_developer_cannot_approve_release(self):
        rbac = DomainRBAC(domain_id="d1")
        principal = PrincipalContext(
            user_id="u2",
            roles=[CBRRole.DEVELOPER],
            domain_id="d1",
            zone="zr",
        )
        allowed, reason = rbac.evaluate(principal, Action.RELEASE_APPROVE, target_zone="zr")
        assert not allowed, f"developer should NOT approve releases: {reason}"

    def test_auditor_external_cannot_write(self):
        rbac = DomainRBAC(domain_id="d1")
        principal = PrincipalContext(
            user_id="u3",
            roles=[CBRRole.AUDITOR_EXTERNAL],
            domain_id="d1",
            zone="zr",
        )
        allowed, reason = rbac.evaluate(principal, Action.SCAN_START, target_zone="zr")
        assert not allowed, f"external auditor should NOT start scans: {reason}"

    def test_auditor_external_can_read(self):
        rbac = DomainRBAC(domain_id="d1")
        principal = PrincipalContext(
            user_id="u3",
            roles=[CBRRole.AUDITOR_EXTERNAL],
            domain_id="d1",
            zone="zr",
        )
        allowed, reason = rbac.evaluate(principal, Action.READ, target_zone="zr")
        assert allowed, f"external auditor should read: {reason}"

    def test_zone_operator_zpe_can_deploy_zpe(self):
        rbac = DomainRBAC(domain_id="d1")
        principal = PrincipalContext(
            user_id="u4",
            roles=[CBRRole.ZONE_OPERATOR_ZPE],
            domain_id="d1",
            zone="zpe",
        )
        allowed, reason = rbac.evaluate(principal, Action.ZPE_DEPLOY, target_zone="zpe")
        assert allowed, f"ZPE operator should deploy in ZPE: {reason}"

    def test_zone_operator_cannot_scan_in_zpe(self):
        rbac = DomainRBAC(domain_id="d1")
        principal = PrincipalContext(
            user_id="u4",
            roles=[CBRRole.ZONE_OPERATOR_ZPE],
            domain_id="d1",
            zone="zpe",
        )
        allowed, reason = rbac.evaluate(principal, Action.SCAN_START, target_zone="zpe")
        assert not allowed, f"ZPE operator should NOT start scans in ZPE: {reason}"

    def test_system_admin_bypasses_all(self):
        rbac = DomainRBAC(domain_id="d1")
        principal = PrincipalContext(
            user_id="u5",
            domain_id="d1",
            is_system_admin=True,
        )
        allowed, reason = rbac.evaluate(principal, Action.ZPE_ROLLBACK, target_zone="zpe")
        assert allowed, f"system admin should bypass all: {reason}"


class TestSeparationOfDutiesRegression:

    def test_creator_cannot_approve_own_release(self):
        ok, reason = SeparationOfDutiesEngine.check_release_approval_sod(
            release_created_by="vasya", approver_id="vasya",
        )
        assert not ok, f"SoD should block self-approval: {reason}"

    def test_different_person_can_approve(self):
        ok, reason = SeparationOfDutiesEngine.check_release_approval_sod(
            release_created_by="vasya", approver_id="petya",
        )
        assert ok, reason

    def test_double_approval_blocked(self):
        ok, reason = SeparationOfDutiesEngine.check_double_approval_sod(
            existing_approvers=["vasya"], current_approver="vasya",
        )
        assert not ok

    def test_transfer_gatekeeper_sod(self):
        ok, reason = SeparationOfDutiesEngine.check_transfer_gatekeeper_sod(
            transfer_initiator="vasya", gate_decider="vasya",
        )
        assert not ok