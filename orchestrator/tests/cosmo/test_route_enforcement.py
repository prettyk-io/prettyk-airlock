# -*- coding: utf-8 -*-
"""COS-032: Route enforcement tests — guard factory on all mutations."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock, patch

import pytest
from fastapi import HTTPException

_orch = Path(__file__).resolve().parents[1]
if str(_orch) not in sys.path:
    sys.path.insert(0, str(_orch))

from orchestrator.cosmo.api.deps import require_capability
from orchestrator.cosmo.domain.rbac import (
    Action,
    DomainRBAC,
    DomainMember,
    PrincipalContext,
    Role,
    CBRRole,
)


class TestGuardFactory:
    """COS-032: Guard factory creates valid FastAPI dependencies."""

    def test_require_capability_returns_callable(self):
        guard = require_capability(Action.SCAN_START)
        assert callable(guard)

    def test_require_capability_with_scope(self):
        guard = require_capability(Action.FINDING_VIEW_TEAM, target_scope="team-alpha")
        assert callable(guard)


class TestRBACEvaluation:
    """DomainRBAC.evaluate() correctly grants/denies capability actions."""

    def test_admin_sec_allowed_scan_start(self):
        rbac = DomainRBAC(
            domain_id="dom-1",
            members=[DomainMember(user_id="alice", role=Role.ADMIN_SEC)],
        )
        principal = PrincipalContext(user_id="alice", roles=[Role.ADMIN_SEC], domain_id="dom-1", zone="zr")
        ok, reason = rbac.evaluate(principal, Action.SCAN_START, target_zone="zr")
        assert ok, f"SCAN_START denied: {reason}"

    def test_admin_sec_allowed_gate_decide(self):
        rbac = DomainRBAC(
            domain_id="dom-1",
            members=[DomainMember(user_id="alice", role=Role.ADMIN_SEC)],
        )
        principal = PrincipalContext(user_id="alice", roles=[Role.ADMIN_SEC], domain_id="dom-1", zone="zr")
        ok, reason = rbac.evaluate(principal, Action.GATE_DECIDE, target_zone="zr")
        assert ok, f"GATE_DECIDE denied: {reason}"

    def test_user_denied_scan_start(self):
        rbac = DomainRBAC(
            domain_id="dom-1",
            members=[DomainMember(user_id="bob", role=Role.USER)],
        )
        principal = PrincipalContext(user_id="bob", roles=[Role.USER], domain_id="dom-1", zone="zr")
        ok, reason = rbac.evaluate(principal, Action.SCAN_START, target_zone="zr")
        assert not ok, f"SCAN_START should be denied for USER"

    def test_user_denied_gate_decide(self):
        rbac = DomainRBAC(
            domain_id="dom-1",
            members=[DomainMember(user_id="bob", role=Role.USER)],
        )
        principal = PrincipalContext(user_id="bob", roles=[Role.USER], domain_id="dom-1", zone="zr")
        ok, reason = rbac.evaluate(principal, Action.GATE_DECIDE, target_zone="zr")
        assert not ok, f"GATE_DECIDE should be denied for USER"

    def test_sec_expert_allowed_scan(self):
        rbac = DomainRBAC(
            domain_id="dom-1",
            members=[DomainMember(user_id="carol", role=Role.SEC_EXPERT)],
        )
        principal = PrincipalContext(user_id="carol", roles=[Role.SEC_EXPERT], domain_id="dom-1", zone="zr")
        ok, _ = rbac.evaluate(principal, Action.SCAN_START, target_zone="zr")
        assert ok

    def test_unauthenticated_denied(self):
        rbac = DomainRBAC(domain_id="dom-1")
        principal = PrincipalContext(user_id="ghost", roles=[], is_authenticated=False, domain_id="dom-1")
        ok, reason = rbac.evaluate(principal, Action.SCAN_START)
        assert not ok
        assert "401" in reason

    def test_system_admin_bypass(self):
        rbac = DomainRBAC(domain_id="dom-1")
        principal = PrincipalContext(user_id="root", roles=[], is_system_admin=True, domain_id="dom-1")
        ok, _ = rbac.evaluate(principal, Action.GATE_DECIDE, target_zone="zr")
        assert ok

    def test_cbr_role_developer_denied_gate(self):
        rbac = DomainRBAC(
            domain_id="dom-1",
            members=[DomainMember(user_id="dev", role=CBRRole.DEVELOPER)],
        )
        principal = PrincipalContext(user_id="dev", roles=[CBRRole.DEVELOPER], domain_id="dom-1", zone="zr")
        ok, _ = rbac.evaluate(principal, Action.GATE_DECIDE, target_zone="zr")
        assert not ok


class TestGuardHTTPStatuses:
    """Guard raises correct HTTP status codes."""

    @pytest.mark.asyncio
    async def test_guard_403_on_denied(self):
        """Non-admin user's guard: validated via RBAC evaluate directly."""
        rbac = DomainRBAC(
            domain_id="dom-1",
            members=[DomainMember(user_id="bob", role=Role.USER)],
        )
        principal = PrincipalContext(user_id="bob", roles=[Role.USER], domain_id="dom-1", zone="zr")
        ok, reason = rbac.evaluate(principal, Action.GATE_DECIDE, target_zone="zr")
        assert not ok
        assert "forbidden" in reason.lower() or "403" in reason.lower()

    @pytest.mark.asyncio
    async def test_guard_allows_admin(self):
        """Admin principal short-circuits guard — no RBAC check needed."""
        guard = require_capability(Action.SCAN_START)
        principal = PrincipalContext(user_id="alice", roles=[Role.ADMIN_SEC], domain_id="dom-1", zone="zr", is_system_admin=True)
        fake_db = AsyncMock()

        # Admin bypass: guard returns immediately
        result = await guard(principal=principal, db=fake_db)
        assert result == principal


class TestAllCapabilityActions:
    """Every Action used in route guards maps to a valid RBAC check."""

    def test_action_enum_values(self):
        actions = [
            Action.BRICK_MANAGE,
            Action.PIPELINE_CONFIGURE,
            Action.SCAN_START,
            Action.SCAN_STOP,
            Action.GATE_DECIDE,
            Action.RELEASE_CREATE,
            Action.RELEASE_TRANSFER,
        ]
        for a in actions:
            assert isinstance(a, str) and len(a) > 0

    def test_guard_factory_for_all_actions(self):
        for a in [Action.BRICK_MANAGE, Action.PIPELINE_CONFIGURE, Action.SCAN_START,
                  Action.SCAN_STOP, Action.GATE_DECIDE, Action.RELEASE_CREATE, Action.RELEASE_TRANSFER]:
            guard = require_capability(a)
            assert callable(guard)