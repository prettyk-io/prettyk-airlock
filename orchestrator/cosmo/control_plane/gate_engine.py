# -*- coding: utf-8 -*-
"""COS-055: Gate Policy Engine — automatic/manual gate evaluation.

GatePolicyEngine:
  1. Automatic gate evaluation: проходит по findings, применяет policy rules
     (Critical → block, High → warn с max_count), выставляет gate.decision.
  2. Manual gate workflow: запрос human decision, валидация decided_by + signature,
     фиксация в audit (PG + Valkey).
  3. evaluate_plan_gates: все gates плана → {gate_id: decision}.

Интеграция: RunControlPlane._on_batches_terminal → gate_engine.evaluate_plan_gates.
"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from orchestrator.cosmo.domain.gate_model import (
    GateAction,
    GateDecision,
    GatePolicy,
    GatePolicyRule,
)

logger = logging.getLogger("cosmoport.gate_engine")

# Valid finding severities
_SEVERITIES = frozenset({"Critical", "High", "Medium", "Low", "Info"})


class GatePolicyEngine:
    """Evaluate security gates against findings using policy rules.

    Lifecycle:
      - evaluate_gate(id, findings)      → automatic gate decision
      - evaluate_plan_gates(plan, fnds)  → all gates for plan
      - request_manual_decision(id)      → marks gate as needing human input
      - record_manual_decision(...)      → validated manual decision + audit

    PG — Source of Truth (gate.decision в БД).
    Valkey — транспорт (publish_gate_decision через events.py).
    """

    def __init__(
        self,
        db_session_factory: Callable[[], Any] | None = None,
    ) -> None:
        self._db_session_factory = db_session_factory
        # COS-092: optional concurrency guard
        self._concurrency_guard: Any = None

    def set_concurrency_guard(self, guard: Any) -> None:
        self._concurrency_guard = guard

    # ━ Public API ━

    def evaluate_gate(
        self,
        gate_id: str,
        findings: list[dict[str, Any]],
        *,
        run_id: str = "",
    ) -> GateDecision:
        """Evaluate an automatic gate against findings.

        Algorithm:
          1. Load gate ORM + parse policy_json → GatePolicy.
          2. If gate.type == "manual" → delegate to request_manual_decision → "manual_required".
          3. For each finding:
             a. Match severity → GatePolicyRule.
             b. "block" → return "block" immediately.
             c. "warn" → count findings of this severity.
                If count > max_count → return "block".
             d. "pass" → no effect.
          4. No violations → return "pass".
          5. Persist decision to PG + publish Valkey event.

        Args:
            gate_id: Gate ORM primary key.
            findings: List of finding dicts, each at minimum {"severity": "Critical"|...}.
            run_id: Optional — run context for Valkey publishing.

        Returns: GateDecision — "pass" | "block" | "manual_required".
        """
        # COS-092: try-acquire gate lock to prevent concurrent evaluation
        if self._concurrency_guard is not None:
            if not self._concurrency_guard.try_acquire_gate(gate_id, ttl_seconds=15):
                return "pass"  # другой evaluator уже работает — не блокируем

        gate_orm = self._load_gate(gate_id)
        if gate_orm is None:
            logger.warning("Gate %s not found", gate_id)
            return "pass"  # gate doesn't exist → skip

        gate_type = gate_orm.get("type", "automatic")

        if gate_type == "manual":
            # Manual gate: delegate immediately
            self.request_manual_decision(gate_id, "system")
            return "manual_required"

        # Parse policy
        policy = self._parse_policy(gate_orm.get("policy_json", {}))
        if policy is None or not policy.rules:
            logger.debug("Gate %s has no policy rules → pass", gate_id)
            self._persist_decision(gate_id, "pass", None, run_id)
            return "pass"

        # Evaluate findings against policy
        decision = self._apply_policy(policy, findings)

        # Persist
        decided_by = None if decision == "pass" else "system"
        self._persist_decision(gate_id, decision, decided_by, run_id)
        return decision

    def evaluate_plan_gates(
        self,
        plan_id: str,
        findings: list[dict[str, Any]],
        *,
        run_id: str = "",
    ) -> dict[str, GateDecision]:
        """Evaluate all gates for a plan. Returns {gate_id: decision}."""
        gates = self._query_gates(plan_id)
        if not gates:
            return {}

        decisions: dict[str, GateDecision] = {}
        for gate in gates:
            gate_id = gate["id"]
            # Evaluate gate against same findings
            decision = self.evaluate_gate(gate_id, findings, run_id=run_id)
            decisions[gate_id] = decision

        return decisions

    def request_manual_decision(self, gate_id: str, requester: str = "system") -> None:
        """Mark gate as requiring manual decision. Records audit entry.

        Persists gate.decision = "manual_required" in PG.
        Publishes Valkey event.
        """
        logger.info("Gate %s: manual decision requested by %s", gate_id, requester)
        self._persist_decision(gate_id, "manual_required", requester, "")

    def record_manual_decision(
        self,
        gate_id: str,
        decided_by: str,
        decision: GateDecision,
        signature: str = "",
        *,
        run_id: str = "",
    ) -> bool:
        """Record a validated manual gate decision.

        Validates:
          - gate exists and is type "manual"
          - gate.decision was "manual_required" (pending)
          - decided_by is non-empty
          - decision is "pass" or "block" (NOT "manual_required")

        On success: persists to PG, publishes Valkey, returns True.
        On failure: returns False.
        """
        gate_orm = self._load_gate(gate_id)
        if gate_orm is None:
            logger.warning("Gate %s not found for manual decision", gate_id)
            return False

        gate_type = gate_orm.get("type", "")
        if gate_type != "manual":
            logger.warning("Gate %s is type=%s, not manual", gate_id, gate_type)
            return False

        current_decision = gate_orm.get("decision")
        if current_decision != "manual_required":
            logger.warning(
                "Gate %s current decision=%s, expected manual_required for manual flow",
                gate_id, current_decision,
            )
            return False

        if not decided_by:
            logger.warning("Manual decision for gate %s requires decided_by", gate_id)
            return False

        if decision == "manual_required":
            logger.warning("Manual decision cannot be manual_required (use request_manual_decision)")
            return False

        # Generate signature if not provided
        if not signature:
            payload = f"{gate_id}|{decided_by}|{decision}|{datetime.now(tz=timezone.utc).isoformat()}"
            signature = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]

        logger.info(
            "Gate %s: manual decision=%s by %s (sig=%s)",
            gate_id, decision, decided_by, signature[:8],
        )
        self._persist_decision(gate_id, decision, decided_by, run_id, signature=signature)
        return True

    def get_decision(self, gate_id: str) -> Optional[str]:
        """Read current gate decision from PG."""
        gate_orm = self._load_gate(gate_id)
        if gate_orm is None:
            return None
        return gate_orm.get("decision")

    # ━ Internal: Policy Evaluation ━

    @staticmethod
    def _parse_policy(policy_json: dict[str, Any]) -> Optional[GatePolicy]:
        """Parse policy_json from Gate ORM into GatePolicy pydantic model."""
        if not policy_json or not policy_json.get("rules"):
            return None
        try:
            return GatePolicy(**policy_json)
        except Exception as exc:
            logger.warning("Invalid policy_json for gate: %s", exc)
            return None

    @staticmethod
    def _apply_policy(policy: GatePolicy, findings: list[dict[str, Any]]) -> GateDecision:
        """Apply policy rules against findings. Returns decision.

        Algorithm:
          For each rule (evaluated in order):
            - Collect matching findings (severity == rule.finding_type).
            - "block" action: return "block" immediately if any finding matches.
            - "warn" action: count matches. If > max_count → "block".
            - "pass" action: no effect.
          If no rule blocks → "pass".
        """
        # Build severity → count map for efficiency
        severity_counts: dict[str, int] = {}
        for f in findings:
            sev = f.get("severity", "")
            if sev in _SEVERITIES:
                severity_counts[sev] = severity_counts.get(sev, 0) + 1

        for rule in policy.rules:
            count = severity_counts.get(rule.finding_type, 0)
            if count == 0:
                continue  # no findings of this type

            if rule.action == "block":
                logger.debug("Gate rule BLOCK: %d findings of type %s", count, rule.finding_type)
                return "block"

            if rule.action == "warn":
                limit = rule.max_count if rule.max_count is not None else 0
                if limit == 0:
                    # warn with no limit = block on any finding
                    logger.debug("Gate rule WARN (no limit): %d findings of type %s", count, rule.finding_type)
                    return "block"
                if count > limit:
                    logger.debug("Gate rule WARN exceeded: %d > %d for type %s",
                                count, limit, rule.finding_type)
                    return "block"
                # Within limit → pass for this rule
                logger.debug("Gate rule WARN within limit: %d <= %d for type %s",
                            count, limit, rule.finding_type)

            # "pass" action → no effect

        return "pass"

    # ━ Internal: PostgreSQL ━

    def _load_gate(self, gate_id: str) -> Optional[dict[str, Any]]:
        if self._db_session_factory is None:
            return None
        s = self._db_session_factory()
        try:
            from orchestrator.cosmo.db.models import Gate as GateORM
            orm = s.query(GateORM).filter(GateORM.id == gate_id).first()
            if orm is None:
                return None
            return {
                "id": orm.id, "plan_id": orm.plan_id, "type": orm.type,
                "position": orm.position, "policy_json": orm.policy_json or {},
                "decision": orm.decision, "decided_by": orm.decided_by,
                "signature": orm.signature,
            }
        finally:
            s.close()

    def _query_gates(self, plan_id: str) -> list[dict[str, Any]]:
        if self._db_session_factory is None or not plan_id:
            return []
        s = self._db_session_factory()
        try:
            from orchestrator.cosmo.db.models import Gate as GateORM
            orms = s.query(GateORM).filter(GateORM.plan_id == plan_id).order_by(GateORM.position).all()
            return [
                {
                    "id": o.id, "plan_id": o.plan_id, "type": o.type,
                    "position": o.position, "policy_json": o.policy_json or {},
                    "decision": o.decision, "decided_by": o.decided_by,
                    "signature": o.signature,
                }
                for o in orms
            ]
        finally:
            s.close()

    def _persist_decision(
        self,
        gate_id: str,
        decision: str,
        decided_by: Optional[str],
        run_id: str = "",
        *,
        signature: str = "",
    ) -> None:
        """Persist gate decision to PG + publish Valkey event."""
        if self._db_session_factory is not None:
            s = self._db_session_factory()
            try:
                from orchestrator.cosmo.db.models import Gate as GateORM
                orm = s.query(GateORM).filter(GateORM.id == gate_id).first()
                if orm is not None:
                    orm.decision = decision
                    orm.decided_at = datetime.now(tz=timezone.utc)
                    if decided_by is not None:
                        orm.decided_by = decided_by
                    if signature:
                        orm.signature = signature
                    s.commit()
            except Exception:
                s.rollback()
                raise
            finally:
                s.close()

        # Valkey event
        if run_id and decision:
            try:
                from orchestrator.cosmo.control_plane.events import publish_gate_decision
                publish_gate_decision(run_id, gate_id, decision)
            except Exception as exc:
                logger.warning("Valkey publish failed for gate %s: %s", gate_id, exc)

    def reset(self) -> None:
        """Test helper: no-op (stateless engine — all state in PG)."""
        pass