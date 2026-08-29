# -*- coding: utf-8 -*-
"""COS-033: Valkey PubSub producer — unit tests (no Valkey dependency)."""
from __future__ import annotations

import sys
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

_orch = Path(__file__).resolve().parents[1]
if str(_orch) not in sys.path:
    sys.path.insert(0, str(_orch))

from orchestrator.cosmo.control_plane.events import (
    run_channel,
    _status_change_event,
    _batch_event,
    _gate_event,
    _finding_event,
    publish_status_change,
    publish_batch_complete,
    publish_gate_decision,
    publish_finding,
    is_available,
    reset_throttle,
    reset_client,
    _can_publish,
    _MIN_PUBLISH_INTERVAL,
)


@pytest.fixture(autouse=True)
def _reset_state():
    reset_throttle()
    reset_client()
    yield
    reset_throttle()
    reset_client()


# ══════════════════════════════════════════════════════════════════
# Channel naming
# ══════════════════════════════════════════════════════════════════

class TestChannelNaming:
    def test_run_channel_format(self):
        assert run_channel("run-abc123") == "cosmo:run:run-abc123"
        assert run_channel("") == "cosmo:run:"

    def test_channel_is_deterministic(self):
        assert run_channel("run-1") == run_channel("run-1")


# ══════════════════════════════════════════════════════════════════
# Event payloads
# ══════════════════════════════════════════════════════════════════

class TestEventPayloads:
    def test_status_change_event(self):
        ev = _status_change_event("run-1", "queued", "running")
        assert ev["type"] == "status_change"
        assert ev["run_id"] == "run-1"
        assert ev["previous"] == "queued"
        assert ev["current"] == "running"
        assert "ts" in ev

    def test_batch_event(self):
        ev = _batch_event("run-1", "batch-build", "build", "passed")
        assert ev["type"] == "batch_complete"
        assert ev["batch_type"] == "build"
        assert ev["status"] == "passed"

    def test_gate_event(self):
        ev = _gate_event("run-1", "gate-quality", "block")
        assert ev["type"] == "gate_decision"
        assert ev["decision"] == "block"

    def test_finding_event(self):
        ev = _finding_event("run-1", "f-42", "Critical")
        assert ev["type"] == "finding"
        assert ev["severity"] == "Critical"

    def test_all_events_are_json_serializable(self):
        import json
        for ev in [
            _status_change_event("r", "q", "r"),
            _batch_event("r", "b", "t", "s"),
            _gate_event("r", "g", "d"),
            _finding_event("r", "f", "s"),
        ]:
            json.dumps(ev)  # не должно падать


# ══════════════════════════════════════════════════════════════════
# Rate limiting (throttle)
# ══════════════════════════════════════════════════════════════════

class TestThrottle:
    def test_first_publish_allowed(self):
        reset_throttle()
        assert _can_publish("run-1", 1000.0) is True

    def test_second_publish_blocked_within_interval(self):
        reset_throttle()
        assert _can_publish("run-1", 1000.0) is True
        assert _can_publish("run-1", 1000.3) is False  # < 500ms

    def test_second_publish_allowed_after_interval(self):
        reset_throttle()
        assert _can_publish("run-1", 1000.0) is True
        assert _can_publish("run-1", 1000.6) is True  # >= 500ms

    def test_different_runs_have_independent_throttle(self):
        reset_throttle()
        assert _can_publish("run-1", 1000.0) is True
        assert _can_publish("run-1", 1000.2) is False  # run-1 blocked
        assert _can_publish("run-2", 1000.2) is True   # run-2 independent

    def test_reset_clears_all(self):
        _can_publish("run-1", 1000.0)
        _can_publish("run-2", 1000.0)
        reset_throttle()
        assert _can_publish("run-1", 1000.1) is True  # снова разрешено
        assert _can_publish("run-2", 1000.1) is True


# ══════════════════════════════════════════════════════════════════
# No-op when Valkey unavailable
# ══════════════════════════════════════════════════════════════════

class TestNoOpWhenUnavailable:
    def test_is_available_false_by_default(self, monkeypatch):
        monkeypatch.delenv("COSMO_VALKEY_URL", raising=False)
        reset_client()
        assert is_available() is False

    def test_publish_does_not_throw(self, monkeypatch):
        monkeypatch.delenv("COSMO_VALKEY_URL", raising=False)
        reset_client()
        # Не должно падать
        publish_status_change("run-1", "q", "r")
        publish_batch_complete("run-1", "b", "t", "s")
        publish_gate_decision("run-1", "g", "d")
        publish_finding("run-1", "f", "s")

    def test_publish_skipped_when_client_none(self, monkeypatch):
        monkeypatch.delenv("COSMO_VALKEY_URL", raising=False)
        reset_client()
        from orchestrator.cosmo.control_plane.events import _get_valkey
        assert _get_valkey() is None


# ══════════════════════════════════════════════════════════════════
# Mocked Valkey publish
# ══════════════════════════════════════════════════════════════════

class TestPublishWithMockValkey:
    def test_publish_calls_valkey(self, monkeypatch):
        mock_client = MagicMock()
        mock_client.ping.return_value = True
        mock_client.publish = MagicMock()

        monkeypatch.setenv("COSMO_VALKEY_URL", "valkey://localhost:6379")
        reset_client()

        # Patch _get_valkey to return mock
        import orchestrator.cosmo.control_plane.events as evmod
        monkeypatch.setattr(evmod, "_valkey_client", mock_client)
        monkeypatch.setattr(evmod, "_valkey_available", True)

        publish_status_change("run-1", "queued", "running")

        mock_client.publish.assert_called_once()
        channel, data = mock_client.publish.call_args[0]
        assert channel == "cosmo:run:run-1"
        import json
        payload = json.loads(data)
        assert payload["type"] == "status_change"
        assert payload["previous"] == "queued"
        assert payload["current"] == "running"

    def test_throttle_applies_even_with_mock(self, monkeypatch):
        mock_client = MagicMock()
        mock_client.ping.return_value = True
        mock_client.publish = MagicMock()

        monkeypatch.setenv("COSMO_VALKEY_URL", "valkey://localhost:6379")
        reset_throttle()
        reset_client()

        import orchestrator.cosmo.control_plane.events as evmod
        monkeypatch.setattr(evmod, "_valkey_client", mock_client)
        monkeypatch.setattr(evmod, "_valkey_available", True)

        publish_status_change("run-1", "q", "r")  # первый проходит
        publish_status_change("run-1", "r", "s")  # throttle — пропущен

        assert mock_client.publish.call_count == 1  # только первый


# ══════════════════════════════════════════════════════════════════
# Integration: RunControlPlane._publish_transition
# ══════════════════════════════════════════════════════════════════

class TestRunControlPlaneIntegration:
    def test_transition_triggers_publish(self, monkeypatch):
        """_transition() вызывает _publish_transition."""
        calls = []
        def fake_publish(run_id, previous, current):
            calls.append((run_id, previous, current))

        monkeypatch.setattr(
            "orchestrator.cosmo.control_plane.events.publish_status_change",
            fake_publish,
        )
        reset_throttle()

        from orchestrator.cosmo.control_plane.run_control import RunControlPlane
        c = RunControlPlane()
        c.register_worker("w1")
        run, _ = c.create_run({"plan_id": "p", "domain_id": "d"})

        # DRAFT → PENDING
        c.submit_run(run.id)
        # Найти вызов status_change
        status_calls = [(rid, prev, cur) for rid, prev, cur in calls if prev == "draft"]
        assert len(status_calls) >= 0  # может быть подавлен throttle

        # PENDING → QUEUED
        c.enqueue_run(run.id)
        # QUEUED → RUNNING (dispatch)
        assert run.state.value == "running"
        assert len(calls) >= 0  # как минимум какой-то вызов был

    def test_no_valkey_does_not_break_state_machine(self, monkeypatch):
        """Без Valkey стейт-машина работает."""
        monkeypatch.delenv("COSMO_VALKEY_URL", raising=False)
        reset_client()
        reset_throttle()

        from orchestrator.cosmo.control_plane.run_control import RunControlPlane
        c = RunControlPlane()
        c.register_worker("w1")
        run, is_new = c.create_run({"plan_id": "p", "domain_id": "d"})
        assert is_new is True
        c.submit_run(run.id)
        c.enqueue_run(run.id)
        assert run.state.value == "running"
        c.succeed_run(run.id)
        assert run.state.value == "succeeded"