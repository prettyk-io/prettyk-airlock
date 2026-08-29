# -*- coding: utf-8 -*-
"""COS-055: tests for GatePolicyEngine + RunControlPlane integration."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_orch = Path(__file__).resolve().parents[1]
if str(_orch) not in sys.path:
    sys.path.insert(0, str(_orch))

from orchestrator.cosmo.control_plane.gate_engine import GatePolicyEngine
from orchestrator.cosmo.domain.gate_model import GatePolicy, GatePolicyRule
from orchestrator.cosmo.control_plane.run_control import (
    FailureClass,
    RunControlPlane,
    RunState,
)


def _f(severity="Medium", **kw):
    return {"severity": severity, **kw}


def _findings(*sevs):
    return [_f(s) for s in sevs]


# ── CLASS 1: Policy evaluation (no PG) ──

class TestPolicyEvaluation:
    def test_empty_pass(self):
        policy = GatePolicy(rules=[GatePolicyRule(finding_type="Critical", action="block")])
        assert GatePolicyEngine._apply_policy(policy, []) == "pass"

    def test_critical_block(self):
        policy = GatePolicy(rules=[GatePolicyRule(finding_type="Critical", action="block")])
        assert GatePolicyEngine._apply_policy(policy, _findings("Critical")) == "block"

    def test_critical_among_lows(self):
        policy = GatePolicy(rules=[GatePolicyRule(finding_type="Critical", action="block")])
        assert GatePolicyEngine._apply_policy(policy, _findings("Low", "Critical")) == "block"

    def test_high_warn_within_limit(self):
        policy = GatePolicy(rules=[GatePolicyRule(finding_type="High", action="warn", max_count=3)])
        assert GatePolicyEngine._apply_policy(policy, _findings("High", "High")) == "pass"

    def test_high_warn_exceeds_limit(self):
        policy = GatePolicy(rules=[GatePolicyRule(finding_type="High", action="warn", max_count=2)])
        assert GatePolicyEngine._apply_policy(policy, _findings("High", "High", "High")) == "block"

    def test_warn_no_limit_blocks_any(self):
        policy = GatePolicy(rules=[GatePolicyRule(finding_type="High", action="warn", max_count=None)])
        assert GatePolicyEngine._apply_policy(policy, _findings("High")) == "block"

    def test_pass_never_blocks(self):
        policy = GatePolicy(rules=[GatePolicyRule(finding_type="Critical", action="pass")])
        assert GatePolicyEngine._apply_policy(policy, _findings("Critical", "Critical")) == "pass"

    def test_first_block_wins(self):
        policy = GatePolicy(rules=[
            GatePolicyRule(finding_type="Critical", action="block"),
            GatePolicyRule(finding_type="High", action="warn", max_count=10),
        ])
        assert GatePolicyEngine._apply_policy(policy, _findings("Critical")) == "block"

    def test_second_rule_blocks(self):
        policy = GatePolicy(rules=[
            GatePolicyRule(finding_type="Critical", action="pass"),
            GatePolicyRule(finding_type="High", action="block"),
        ])
        assert GatePolicyEngine._apply_policy(policy, _findings("High")) == "block"

    def test_unknown_severity_ignored(self):
        policy = GatePolicy(rules=[GatePolicyRule(finding_type="Critical", action="block")])
        assert GatePolicyEngine._apply_policy(policy, [_f("Unknown")]) == "pass"

    def test_warn_exact_limit_passes(self):
        policy = GatePolicy(rules=[GatePolicyRule(finding_type="High", action="warn", max_count=2)])
        assert GatePolicyEngine._apply_policy(policy, _findings("High", "High")) == "pass"

    def test_multiple_severities_separate_counts(self):
        policy = GatePolicy(rules=[
            GatePolicyRule(finding_type="High", action="warn", max_count=2),
            GatePolicyRule(finding_type="Medium", action="warn", max_count=1),
        ])
        # High: 2 <= 2 ok, Medium: 2 > 1 → block
        assert GatePolicyEngine._apply_policy(
            policy, _findings("High", "High", "Medium", "Medium")) == "block"

    def test_complex_pass(self):
        policy = GatePolicy(rules=[
            GatePolicyRule(finding_type="Critical", action="block"),
            GatePolicyRule(finding_type="High", action="warn", max_count=5),
            GatePolicyRule(finding_type="Medium", action="pass"),
        ])
        assert GatePolicyEngine._apply_policy(
            policy, _findings("High", "High", "Medium", "Medium", "Medium")) == "pass"

    def test_complex_blocked_by_critical(self):
        policy = GatePolicy(rules=[
            GatePolicyRule(finding_type="Critical", action="block"),
            GatePolicyRule(finding_type="High", action="warn", max_count=5),
        ])
        assert GatePolicyEngine._apply_policy(policy, _findings("High", "Critical")) == "block"

    def test_warn_max_count_zero(self):
        """warn with max_count=0: any finding → block (like warn with no limit)"""
        policy = GatePolicy(rules=[GatePolicyRule(finding_type="Medium", action="warn", max_count=0)])
        assert GatePolicyEngine._apply_policy(policy, _findings("Medium")) == "block"

    def test_no_matching_rule_means_pass(self):
        policy = GatePolicy(rules=[GatePolicyRule(finding_type="Critical", action="block")])
        assert GatePolicyEngine._apply_policy(policy, _findings("Medium", "Low")) == "pass"


# ── CLASS 2: Policy parsing ──

class TestPolicyParsing:
    def test_valid(self):
        p = GatePolicyEngine._parse_policy({
            "rules": [
                {"finding_type": "Critical", "action": "block"},
                {"finding_type": "High", "action": "warn", "max_count": 5},
            ]
        })
        assert p is not None
        assert len(p.rules) == 2
        assert p.rules[0].finding_type == "Critical"

    def test_empty_rules_returns_none(self):
        assert GatePolicyEngine._parse_policy({"rules": []}) is None

    def test_no_rules_key(self):
        assert GatePolicyEngine._parse_policy({}) is None

    def test_none(self):
        assert GatePolicyEngine._parse_policy(None) is None

    def test_invalid(self):
        assert GatePolicyEngine._parse_policy({"rules": [{"bad": True}]}) is None


# ── CLASS 3: Automatic gate evaluation (mocked PG) ──

def _mock_gate(gate_id="g1", gate_type="automatic", rules=None, decision=None):
    return {
        "id": gate_id, "plan_id": "p1", "type": gate_type,
        "position": 0, "policy_json": {"rules": rules or [{"finding_type": "Critical", "action": "block"}]},
        "decision": decision, "decided_by": None, "signature": None,
    }


class TestEvaluateGate:
    def test_block(self):
        engine = GatePolicyEngine()
        engine._load_gate = MagicMock(return_value=_mock_gate())
        engine._persist_decision = MagicMock()
        assert engine.evaluate_gate("g1", [_f("Critical")]) == "block"
        engine._persist_decision.assert_called_once()

    def test_pass(self):
        engine = GatePolicyEngine()
        engine._load_gate = MagicMock(return_value=_mock_gate())
        engine._persist_decision = MagicMock()
        assert engine.evaluate_gate("g1", [_f("Low")]) == "pass"

    def test_manual_delegates(self):
        engine = GatePolicyEngine()
        engine._load_gate = MagicMock(return_value=_mock_gate(gate_type="manual"))
        engine.request_manual_decision = MagicMock()
        engine._persist_decision = MagicMock()
        assert engine.evaluate_gate("g2", []) == "manual_required"
        engine.request_manual_decision.assert_called_once_with("g2", "system")

    def test_not_found_returns_pass(self):
        engine = GatePolicyEngine()
        engine._load_gate = MagicMock(return_value=None)
        assert engine.evaluate_gate("nonexistent", []) == "pass"

    def test_sets_decided_by_for_block(self):
        engine = GatePolicyEngine()
        engine._load_gate = MagicMock(return_value=_mock_gate())
        args = []
        engine._persist_decision = MagicMock(side_effect=lambda g, d, b, r, **kw: args.append((d, b)))
        engine.evaluate_gate("g1", [_f("Critical")])
        assert args[0] == ("block", "system")

    def test_no_decided_by_for_pass(self):
        engine = GatePolicyEngine()
        engine._load_gate = MagicMock(return_value=_mock_gate())
        args = []
        engine._persist_decision = MagicMock(side_effect=lambda g, d, b, r, **kw: args.append((d, b)))
        engine.evaluate_gate("g1", [_f("Low")])
        assert args[0] == ("pass", None)


class TestEvaluatePlanGates:
    def test_empty(self):
        engine = GatePolicyEngine()
        engine._query_gates = MagicMock(return_value=[])
        assert engine.evaluate_plan_gates("p1", []) == {}

    def test_two_gates(self):
        engine = GatePolicyEngine()
        engine._query_gates = MagicMock(return_value=[_mock_gate("g1"), _mock_gate("g2")])
        engine.evaluate_gate = MagicMock(return_value="pass")
        decisions = engine.evaluate_plan_gates("p1", [_f("Low")])
        assert decisions == {"g1": "pass", "g2": "pass"}
        assert engine.evaluate_gate.call_count == 2

    def test_one_blocks(self):
        engine = GatePolicyEngine()
        engine._query_gates = MagicMock(return_value=[_mock_gate("g1"), _mock_gate("g2")])
        engine.evaluate_gate = MagicMock(side_effect=["block", "pass"])
        assert engine.evaluate_plan_gates("p1", [_f("Critical")]) == {"g1": "block", "g2": "pass"}


# ── CLASS 4: Manual gate workflow ──

class TestManualGate:
    def test_request(self):
        engine = GatePolicyEngine()
        engine._persist_decision = MagicMock()
        engine.request_manual_decision("gm", "alice")
        engine._persist_decision.assert_called_once_with("gm", "manual_required", "alice", "")

    def test_record_valid(self):
        engine = GatePolicyEngine()
        engine._load_gate = MagicMock(return_value=_mock_gate(gate_type="manual", decision="manual_required"))
        engine._persist_decision = MagicMock()
        assert engine.record_manual_decision("gm", decided_by="alice", decision="pass") is True

    def test_record_automatic_rejected(self):
        engine = GatePolicyEngine()
        engine._load_gate = MagicMock(
            return_value=_mock_gate(gate_type="automatic", decision="manual_required"))
        assert engine.record_manual_decision("ga", "alice", "pass") is False

    def test_record_not_pending(self):
        engine = GatePolicyEngine()
        engine._load_gate = MagicMock(
            return_value=_mock_gate(gate_type="manual", decision="pass"))
        assert engine.record_manual_decision("gm", "alice", "block") is False

    def test_record_empty_decided_by(self):
        engine = GatePolicyEngine()
        engine._load_gate = MagicMock(
            return_value=_mock_gate(gate_type="manual", decision="manual_required"))
        assert engine.record_manual_decision("gm", "", "pass") is False

    def test_record_rejects_manual_required_decision(self):
        engine = GatePolicyEngine()
        engine._load_gate = MagicMock(
            return_value=_mock_gate(gate_type="manual", decision="manual_required"))
        assert engine.record_manual_decision("gm", "alice", "manual_required") is False

    def test_record_generates_signature(self):
        engine = GatePolicyEngine()
        engine._load_gate = MagicMock(
            return_value=_mock_gate(gate_type="manual", decision="manual_required"))
        sigs = []
        engine._persist_decision = MagicMock(
            side_effect=lambda g, d, b, r, **kw: sigs.append(kw.get("signature", "")))
        engine.record_manual_decision("gm", "alice", "block")
        assert len(sigs[0]) == 32

    def test_record_gate_not_found(self):
        engine = GatePolicyEngine()
        engine._load_gate = MagicMock(return_value=None)
        assert engine.record_manual_decision("nonexistent", "alice", "pass") is False

    def test_get_decision(self):
        engine = GatePolicyEngine()
        engine._load_gate = MagicMock(return_value=_mock_gate(decision="pass"))
        assert engine.get_decision("g1") == "pass"

    def test_get_decision_nonexistent(self):
        engine = GatePolicyEngine()
        engine._load_gate = MagicMock(return_value=None)
        assert engine.get_decision("nonexistent") is None


# ── CLASS 5: RunControlPlane integration ──

class TestIntegration:
    def test_set_gate_engine_shares_db(self):
        fake = MagicMock()
        c = RunControlPlane(db_session_factory=fake)
        engine = GatePolicyEngine()
        c.set_gate_engine(engine)
        assert engine._db_session_factory is fake

    def test_set_findings_provider(self):
        c = RunControlPlane()
        provider = MagicMock()
        c.set_findings_provider(provider)
        assert c._findings_provider is provider

    def test_batches_terminal_gate_pass(self):
        c = RunControlPlane()
        c.register_worker("w1", frozenset({"dast"}))
        run, _ = c.create_run({"plan_id": "p", "domain_id": "d"}, frozenset({"dast"}))
        c.submit_run(run.id)
        c.enqueue_run(run.id)
        assert run.state == RunState.RUNNING

        engine = GatePolicyEngine()
        engine.evaluate_plan_gates = MagicMock(return_value={"g1": "pass"})
        c.set_gate_engine(engine)
        c.set_findings_provider(lambda rid: [])

        c._on_batches_terminal(run.id, all_passed=True)
        assert run.state == RunState.SUCCEEDED

    def test_batches_terminal_gate_block(self):
        c = RunControlPlane()
        c.register_worker("w1", frozenset({"dast"}))
        run, _ = c.create_run({"plan_id": "p", "domain_id": "d"}, frozenset({"dast"}))
        c.submit_run(run.id)
        c.enqueue_run(run.id)

        engine = GatePolicyEngine()
        engine.evaluate_plan_gates = MagicMock(return_value={"g1": "block"})
        c.set_gate_engine(engine)
        c.set_findings_provider(lambda rid: [])

        c._on_batches_terminal(run.id, all_passed=True)
        assert run.state == RunState.BLOCKED
        assert run.failure_class == FailureClass.GATE

    def test_batches_terminal_no_engine_succeeds(self):
        c = RunControlPlane()
        c.register_worker("w1", frozenset({"dast"}))
        run, _ = c.create_run({"plan_id": "p", "domain_id": "d"}, frozenset({"dast"}))
        c.submit_run(run.id)
        c.enqueue_run(run.id)
        c._on_batches_terminal(run.id, all_passed=True)
        assert run.state == RunState.SUCCEEDED

    def test_batches_terminal_no_engine_batch_fail(self):
        c = RunControlPlane()
        c.register_worker("w1", frozenset({"dast"}))
        run, _ = c.create_run({"plan_id": "p", "domain_id": "d"}, frozenset({"dast"}))
        c.submit_run(run.id)
        c.enqueue_run(run.id)
        c._on_batches_terminal(run.id, all_passed=False)
        assert run.state == RunState.BLOCKED
        assert run.failure_class == FailureClass.GATE

    def test_batches_terminal_engine_error_fail_open(self):
        c = RunControlPlane()
        c.register_worker("w1", frozenset({"dast"}))
        run, _ = c.create_run({"plan_id": "p", "domain_id": "d"}, frozenset({"dast"}))
        c.submit_run(run.id)
        c.enqueue_run(run.id)

        engine = GatePolicyEngine()
        engine.evaluate_plan_gates = MagicMock(side_effect=Exception("Boom"))
        c.set_gate_engine(engine)
        c.set_findings_provider(lambda rid: [])

        c._on_batches_terminal(run.id, all_passed=True)
        assert run.state == RunState.SUCCEEDED  # fail-open

    def test_reset_clears_gate(self):
        c = RunControlPlane()
        c.set_gate_engine(GatePolicyEngine())
        c.reset()
        assert c._findings_provider is None

    def test_ignores_non_running(self):
        c = RunControlPlane()
        engine = GatePolicyEngine()
        engine.evaluate_plan_gates = MagicMock()
        c.set_gate_engine(engine)
        c.set_findings_provider(lambda rid: [])

        run, _ = c.create_run({"plan_id": "p", "domain_id": "d"})
        c._on_batches_terminal(run.id, all_passed=True)
        assert run.state == RunState.DRAFT
        engine.evaluate_plan_gates.assert_not_called()