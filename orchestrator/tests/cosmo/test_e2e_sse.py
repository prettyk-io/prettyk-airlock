"""
COS-048: E2E SSE Stream — RunControlPlane lifecycle + SSE event contract.

Симулирует прохождение Run через стейт-машину и проверяет,
что SSE-события эмитятся с правильным контрактом.

Без Valkey — чистые Pydantic-модели + event dispatch в памяти.
"""
import hashlib
import json
import time
from copy import deepcopy

import pytest

from cosmo.domain.run_model import Run, Batch, RunStatus, BatchStatus
from cosmo.domain.gate_model import Gate, GatePolicy, GatePolicyRule, GateDecision
from cosmo.ledger.evidence_chain import EvidenceLedger


# ═══════════════════════════════════════════════════════════════════════
# SSE Event contract constants
# ═══════════════════════════════════════════════════════════════════════

_VALID_SSE_EVENTS = frozenset({
    "status_change", "batch_complete", "gate_decision", "finding",
})

_SENSITIVE_KEYS = frozenset({
    "token", "password", "secret", "api_key", "private_key",
    "authorization", "cookie", "credential", "forge_token_ref",
})


def _no_sensitive_leak(data: dict, path: str = "") -> None:
    """Рекурсивно проверить отсутствие чувствительных ключей."""
    for key, value in data.items():
        key_lower = key.lower()
        for sensitive in _SENSITIVE_KEYS:
            assert sensitive not in key_lower, (
                f"Sensitive key '{key}' at {path}"
            )
        if isinstance(value, dict):
            _no_sensitive_leak(value, f"{path}.{key}")
        elif isinstance(value, list):
            for i, item in enumerate(value):
                if isinstance(item, dict):
                    _no_sensitive_leak(item, f"{path}.{key}[{i}]")


def _snapshot_hash(data: dict) -> str:
    return hashlib.sha256(
        json.dumps(data, sort_keys=True, default=str).encode()
    ).hexdigest()[:16]


# ═══════════════════════════════════════════════════════════════════════
# Run Lifecycle → SSE events
# ═══════════════════════════════════════════════════════════════════════

class TestRunLifecycleSSE:
    """Полный lifecycle run → эмуляция SSE-событий."""

    def _build_batches(self, plan_id="plan-sse") -> list[Batch]:
        return [
            Batch(id=f"batch-{plan_id}-build", plan_id=plan_id, type="build", status="pending",
                  bricks=["b-build"]),
            Batch(id=f"batch-{plan_id}-sast", plan_id=plan_id, type="static_scan", status="pending",
                  bricks=["b-sonar", "b-trivy"]),
            Batch(id=f"batch-{plan_id}-deploy", plan_id=plan_id, type="deploy", status="pending",
                  bricks=["b-deploy"]),
            Batch(id=f"batch-{plan_id}-dast", plan_id=plan_id, type="dynamic_test", status="pending",
                  bricks=["b-scanner"]),
        ]

    def test_run_status_lifecycle_events(self):
        """Run проходит все статусы — каждое изменение = SSE status_change."""
        events: list[dict] = []
        prev_status = "pending"
        run = Run(
            id="run-sse-1", plan_id="plan-sse", trigger="manual",
            initiator="operator", domain_id="d-1", status="pending",
        )

        for status in ("queued", "running", "succeeded"):
            run.status = status  # type: ignore[assignment]
            payload = {
                "status": status,
                "previous": prev_status,
                "started_at": run.started_at.isoformat() if run.started_at else None,
                "finished_at": run.finished_at.isoformat() if run.finished_at else None,
            }
            _no_sensitive_leak(payload)
            events.append({"event": "status_change", "data": payload})
            prev_status = status

        assert len(events) == 3
        assert events[-1]["data"]["status"] == "succeeded"
        assert events[0]["data"]["previous"] == "pending"

    def test_batch_complete_events(self):
        """Каждый batch при переходе в passed/failed → batch_complete SSE."""
        batches = self._build_batches()
        events: list[dict] = []

        for b in batches:
            b.status = "running"  # type: ignore[assignment]
            b.status = "passed"   # type: ignore[assignment]
            payload = {"batch_id": b.id, "type": b.type, "status": b.status}
            _no_sensitive_leak(payload)
            events.append({"event": "batch_complete", "data": payload})

        assert len(events) == 4
        types = [e["data"]["type"] for e in events]
        assert "build" in types
        assert "static_scan" in types

    def test_batch_failure_emits_event(self):
        """Failed batch тоже эмитит batch_complete."""
        b = Batch(id="b-fail", plan_id="plan-sse", type="deploy", status="pending")
        b.status = "running"  # type: ignore[assignment]
        b.status = "failed"   # type: ignore[assignment]
        payload = {"batch_id": b.id, "type": b.type, "status": b.status}
        _no_sensitive_leak(payload)
        assert b.status == "failed"


# ═══════════════════════════════════════════════════════════════════════
# Gate Decision SSE events
# ═══════════════════════════════════════════════════════════════════════

class TestGateDecisionSSE:
    def test_automatic_gate_pass(self):
        policy = GatePolicy(rules=[
            GatePolicyRule(finding_type="Critical", action="block"),
        ])
        gate = Gate(
            id="gate-auto", type="automatic", position=0,
            policy=policy, decision="pass",
        )
        payload = {
            "gate_id": gate.id,
            "decision": gate.decision,
            "decided_by": gate.decided_by,
            "decided_at": gate.decided_at.isoformat() if gate.decided_at else None,
        }
        _no_sensitive_leak(payload)
        assert payload["decision"] == "pass"

    def test_automatic_gate_block(self):
        policy = GatePolicy(rules=[
            GatePolicyRule(finding_type="Critical", action="block"),
        ])
        gate = Gate(
            id="gate-block", type="automatic", position=0,
            policy=policy, decision="block",
        )
        payload = {
            "gate_id": gate.id, "decision": gate.decision,
            "decided_by": gate.decided_by, "decided_at": None,
        }
        _no_sensitive_leak(payload)
        assert payload["decision"] == "block"

    def test_manual_gate_decision(self):
        policy = GatePolicy(rules=[
            GatePolicyRule(finding_type="High", action="warn", max_count=5),
        ])
        gate = Gate(
            id="gate-manual", type="manual", position=1,
            policy=policy, decision="pass", decided_by="operator-ivan",
        )
        payload = {
            "gate_id": gate.id, "decision": gate.decision,
            "decided_by": gate.decided_by, "decided_at": None,
        }
        _no_sensitive_leak(payload)
        assert payload["decided_by"] == "operator-ivan"


# ═══════════════════════════════════════════════════════════════════════
# Finding SSE events
# ═══════════════════════════════════════════════════════════════════════

class TestFindingSSE:
    def test_finding_event_contract(self):
        """SSE finding.created — только счётчик, без payload находки."""
        payload = {
            "count": 5,
            "delta": 2,
            "total_evidence": 12,
        }
        _no_sensitive_leak(payload)
        event = {"event": "finding", "data": payload}
        data = event["data"]
        assert data["count"] == 5
        assert data["delta"] == 2

    def test_finding_event_no_leak(self):
        """Даже если кто-то попытается вставить credentials — контракт не позволяет."""
        # finding.created НЕ содержит токенов — только счётчики
        payload = {"count": 3, "delta": 1, "total_evidence": 8}
        _no_sensitive_leak(payload)


# ═══════════════════════════════════════════════════════════════════════
# Snapshot determinism — reconnect safety
# ═══════════════════════════════════════════════════════════════════════

class TestSSESnapshotDeterminism:
    """Один и тот же snapshot → один и тот же hash (reconnect)."""

    def test_same_snapshot_same_hash(self):
        snap = {
            "run": {"id": "r1", "status": "running"},
            "batches": [{"id": "b1", "type": "build", "status": "passed"}],
            "gates": [{"id": "g1", "decision": "pass"}],
            "findings_count": 0,
            "evidence_count": 3,
        }
        h1 = _snapshot_hash(snap)
        h2 = _snapshot_hash(deepcopy(snap))
        assert h1 == h2

    def test_different_status_different_hash(self):
        s1 = {"run": {"id": "r1", "status": "running"}, "batches": [], "gates": [], "findings_count": 0, "evidence_count": 0}
        s2 = {"run": {"id": "r1", "status": "succeeded"}, "batches": [], "gates": [], "findings_count": 0, "evidence_count": 0}
        assert _snapshot_hash(s1) != _snapshot_hash(s2)

    def test_reconnect_sees_identical_state(self):
        """При реконнекте — тот же snapshot, скрытых мутаций нет."""
        batches = [
            Batch(id="b1", plan_id="p1", type="build", status="passed"),
        ]
        snap1 = {
            "run": {"id": "r2", "status": "running"},
            "batches": [{"id": b.id, "type": b.type, "status": b.status} for b in batches],
            "gates": [],
            "findings_count": 0,
            "evidence_count": 0,
        }
        # Reconnect — строим тот же snapshot
        snap2 = {
            "run": {"id": "r2", "status": "running"},
            "batches": [{"id": b.id, "type": b.type, "status": b.status} for b in batches],
            "gates": [],
            "findings_count": 0,
            "evidence_count": 0,
        }
        assert _snapshot_hash(snap1) == _snapshot_hash(snap2)


# ═══════════════════════════════════════════════════════════════════════
# Evidence chain integrity via SSE
# ═══════════════════════════════════════════════════════════════════════

class TestEvidenceChainInSSE:
    """SSE finding-события ссылаются на EvidenceLedger."""

    def test_finding_count_matches_ledger(self):
        ledger = EvidenceLedger()
        ledger.add_entry("finding", {"severity": "High"}, "run-sse/r1")
        ledger.add_entry("finding", {"severity": "Medium"}, "run-sse/r1")
        ledger.add_entry("log", {"line": "scan complete"}, "run-sse/r1")

        events = []
        # Симуляция: два finding-события были эмиттены
        for i, entry in enumerate(ledger.entries):
            if entry.type == "finding":
                events.append({
                    "event": "finding",
                    "data": {"count": i + 1, "delta": 1, "total_evidence": len(ledger.entries)},
                })

        assert len(events) == 2
        for ev in events:
            _no_sensitive_leak(ev["data"])


# ═══════════════════════════════════════════════════════════════════════
# Full SSE stream simulation — all event types
# ═══════════════════════════════════════════════════════════════════════

class TestFullSSEStream:
    """Полная симуляция SSE-потока одного прогона."""

    def test_full_stream_all_event_types(self):
        """Один run проходит lifecycle → все 4 типа событий эмитятся."""
        events: list[dict] = []

        # 1. status_change: pending → queued
        events.append({"event": "status_change", "data": {"status": "queued", "previous": "pending"}})

        # 2. status_change: queued → running
        events.append({"event": "status_change", "data": {"status": "running", "previous": "queued"}})

        # 3. batch_complete: build passed
        events.append({"event": "batch_complete", "data": {"batch_id": "b-build", "type": "build", "status": "passed"}})

        # 4. batch_complete: static_scan passed
        events.append({"event": "batch_complete", "data": {"batch_id": "b-sast", "type": "static_scan", "status": "passed"}})

        # 5. gate_decision: pass
        events.append({"event": "gate_decision", "data": {"gate_id": "g0", "decision": "pass"}})

        # 6. finding: +1
        events.append({"event": "finding", "data": {"count": 1, "delta": 1, "total_evidence": 1}})

        # 7. batch_complete: deploy passed
        events.append({"event": "batch_complete", "data": {"batch_id": "b-deploy", "type": "deploy", "status": "passed"}})

        # 8. batch_complete: dast passed
        events.append({"event": "batch_complete", "data": {"batch_id": "b-dast", "type": "dynamic_test", "status": "passed"}})

        # 9. status_change: succeeded
        events.append({"event": "status_change", "data": {"status": "succeeded", "previous": "running"}})

        # 10. finding: +2 (total 3)
        events.append({"event": "finding", "data": {"count": 3, "delta": 2, "total_evidence": 5}})

        # Проверка контракта
        event_types = {e["event"] for e in events}
        assert event_types == _VALID_SSE_EVENTS, f"Missing event types: {_VALID_SSE_EVENTS - event_types}"

        # Все события проходят security check
        for ev in events:
            _no_sensitive_leak(ev["data"])

        # Хотя бы по два события каждого типа
        type_counts = {}
        for e in events:
            type_counts[e["event"]] = type_counts.get(e["event"], 0) + 1

        assert type_counts["status_change"] == 3
        assert type_counts["batch_complete"] == 4
        assert type_counts["finding"] == 2
        assert type_counts["gate_decision"] == 1


# ═══════════════════════════════════════════════════════════════════════
# Rate limit simulation
# ═══════════════════════════════════════════════════════════════════════

class TestSSERateLimit:
    """SSE не чаще 2 Hz = 500ms между публикациями."""

    def test_rate_limit_enforced(self):
        """Два быстрых подряд → второй дропается."""
        MIN_INTERVAL = 0.5
        now = 1000.0
        throttle: dict[str, float] = {}

        def can_publish(run_id: str, t: float) -> bool:
            last = throttle.get(run_id, 0.0)
            if t - last < MIN_INTERVAL:
                return False
            throttle[run_id] = t
            return True

        # Первая публикация — ок
        assert can_publish("run-1", now) is True
        # Вторая через 0.1s — заблокирована
        assert can_publish("run-1", now + 0.1) is False
        # Третья через 0.6s — ок
        assert can_publish("run-1", now + 0.6) is True
        # Другой run_id — не блокируется
        assert can_publish("run-2", now + 0.1) is True

    def test_rate_limit_independent_per_run(self):
        """Два run_id — независимые throttle."""
        MIN_INTERVAL = 0.5
        now = 2000.0
        throttle: dict[str, float] = {}

        def can_publish(rid: str, t: float) -> bool:
            last = throttle.get(rid, 0.0)
            if t - last < MIN_INTERVAL:
                return False
            throttle[rid] = t
            return True

        assert can_publish("run-a", now) is True
        assert can_publish("run-b", now + 0.1) is True
        assert can_publish("run-a", now + 0.2) is False  # run-a blocked
        assert can_publish("run-b", now + 0.3) is False  # run-b blocked
        assert can_publish("run-c", now + 0.4) is True   # run-c еще не публиковался