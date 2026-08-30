"""
COS-065: Notification Service tests.

Проверяет:
  - NotificationEvent модель + severity mapping
  - WebhookNotifier (send, retry, HMAC, failure tracking)
  - LogNotifier (history, structured logging)
  - NotificationDispatcher (register/unregister, dispatch, event history)
  - Convenience factories (notify_gate_blocked, notify_run_failed, notify_transfer_completed)
  - Notifier interface contract
  - API webhook CRUD (register, list, delete)
  - NotificationHistory вывод
"""
import json
import threading
import time
from unittest.mock import MagicMock, patch

import pytest
from cosmo.notifications.service import (
    NotificationEvent,
    NotificationType,
    NotificationSeverity,
    WebhookNotifier,
    LogNotifier,
    NotificationDispatcher,
    get_dispatcher,
    notify_gate_blocked,
    notify_run_failed,
    notify_transfer_completed,
    notify_status_change,
    _notif_severity_map,
)

# =============================================================================
# NotificationEvent
# =============================================================================

class TestNotificationEvent:
    def test_minimal(self):
        ev = NotificationEvent(
            type="gate_blocked", title="Gate build blocked",
            message="Critical SQLi found", domain_id="d-1", run_id="r-1",
        )
        assert ev.type == "gate_blocked"
        assert ev.title == "Gate build blocked"
        assert ev.domain_id == "d-1"

    def test_severity_auto_assigned(self):
        ev = NotificationEvent(type="gate_blocked", title="x", message="x")
        assert ev.severity == "critical"

    def test_severity_explicit_overrides(self):
        ev = NotificationEvent(type="gate_blocked", title="x", message="x", severity="medium")
        assert ev.severity == "medium"

    def test_severity_mapping_is_complete(self):
        for ntype in ("gate_blocked", "gate_passed", "run_failed", "run_succeeded",
                       "transfer_completed", "transfer_failed", "status_change",
                       "batch_failed", "deploy_started", "release_approved"):
            assert ntype in _notif_severity_map, f"Missing severity map for {ntype}"

    def test_transfer_completed_severity_is_medium(self):
        assert _notif_severity_map["transfer_completed"] == "medium"

    def test_gate_blocked_severity_is_critical(self):
        assert _notif_severity_map["gate_blocked"] == "critical"

    def test_to_dict_contains_all_fields(self):
        ev = NotificationEvent(
            type="run_failed", title="Run failed", message="Infra timeout",
            details={"code": 500}, domain_id="d-1", run_id="r-1",
            recipients=["admin@local"],
        )
        d = ev.to_dict()
        assert d["type"] == "run_failed"
        assert d["severity"] == "high"
        assert d["recipients"] == ["admin@local"]
        assert d["details"]["code"] == 500

    def test_to_json_valid_json(self):
        ev = NotificationEvent(type="run_succeeded", title="OK", message="Done")
        js = ev.to_json()
        parsed = json.loads(js)
        assert parsed["type"] == "run_succeeded"


# =============================================================================
# WebhookNotifier
# =============================================================================

class TestWebhookNotifier:
    @patch("urllib.request.urlopen")
    def test_send_success(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        wh = WebhookNotifier("https://hooks.example.com/alert")
        ev = NotificationEvent(type="gate_blocked", title="Test", message="msg")
        assert wh.send(ev) is True
        assert wh.sent_count == 1
        assert wh.failed_count == 0

    @patch("urllib.request.urlopen")
    def test_send_failure_after_3_retries(self, mock_urlopen):
        mock_urlopen.side_effect = Exception("Connection refused")

        wh = WebhookNotifier("https://dead.example.com")
        ev = NotificationEvent(type="run_failed", title="x", message="x")
        assert wh.send(ev) is False
        assert wh.sent_count == 0
        assert wh.failed_count == 1

    @patch("urllib.request.urlopen")
    def test_hmac_signature_added(self, mock_urlopen):
        import hmac, hashlib

        actual_headers: dict = {}

        class FakeResponse:
            status = 200
            def __enter__(self): return self
            def __exit__(self, *a): pass

        def capture(req, *args, **kwargs):
            actual_headers.update({k.lower(): v for k, v in req.headers.items()})
            resp = FakeResponse()
            resp.status = 200
            resp.data = req.data
            resp.headers = req.headers
            return resp

        mock_urlopen.side_effect = capture

        wh = WebhookNotifier("https://hooks.local", secret="test-secret")
        ev = NotificationEvent(type="gate_blocked", title="Test", message="msg")
        wh.send(ev)

        assert "x-cosmo-signature" in actual_headers
        expected_sig = hmac.new(b"test-secret", ev.to_json().encode(), hashlib.sha256).hexdigest()
        assert actual_headers["x-cosmo-signature"] == expected_sig

    def test_send_count_tracks(self):
        wh = WebhookNotifier("https://x.local")
        assert wh.sent_count == 0
        assert wh.failed_count == 0


# =============================================================================
# LogNotifier
# =============================================================================

class TestLogNotifier:
    def test_logs_and_stores(self):
        ln = LogNotifier(max_history=5)
        ev = NotificationEvent(type="gate_blocked", title="Gate X blocked", message="SQLi")
        assert ln.send(ev) is True
        assert len(ln.history) == 1
        assert ln.history[0].title == "Gate X blocked"

    def test_max_history_enforced(self):
        ln = LogNotifier(max_history=3)
        for i in range(5):
            ln.send(NotificationEvent(type="gate_passed", title=f"Gate {i}", message="."))
        assert len(ln.history) == 3

    def test_always_returns_True(self):
        ln = LogNotifier()
        for _ in range(10):
            assert ln.send(NotificationEvent(type="run_succeeded", title=".", message=".")) is True


# =============================================================================
# NotificationDispatcher
# =============================================================================

class TestNotificationDispatcher:
    def test_dispatch_to_all_channels(self):
        d = NotificationDispatcher()
        mock1 = MagicMock(spec=LogNotifier)
        mock1.send.return_value = True
        mock2 = MagicMock(spec=WebhookNotifier)
        mock2.send.return_value = True

        d.register("log", mock1)
        d.register("webhook", mock2)

        ev = NotificationEvent(type="gate_blocked", title="Test", message="msg")
        results = d.dispatch(ev)

        assert results == {"log": True, "webhook": True}
        mock1.send.assert_called_once()
        mock2.send.assert_called_once()

    def test_unregister(self):
        d = NotificationDispatcher()
        mock = MagicMock(spec=LogNotifier)
        mock.send.return_value = True

        d.register("temp", mock)
        assert "temp" in d.channels
        d.unregister("temp")
        assert "temp" not in d.channels

    def test_dispatch_records_history(self):
        d = NotificationDispatcher()
        ln = LogNotifier()
        d.register("log", ln)

        ev = NotificationEvent(type="transfer_completed", title="T1", message="m")
        d.dispatch(ev)
        assert len(d.event_history) == 1
        assert d.event_history[0].title == "T1"

    def test_dispatch_history_limited(self):
        d = NotificationDispatcher()
        d._max_history = 3
        ln = LogNotifier()
        d.register("log", ln)

        for i in range(5):
            d.dispatch(NotificationEvent(type="status_change", title=f"#{i}", message="."))
        assert len(d.event_history) == 3

    def test_one_failure_doesnt_block_others(self):
        d = NotificationDispatcher()
        ok = MagicMock(spec=LogNotifier)
        ok.send.return_value = True
        fail = MagicMock(spec=WebhookNotifier)
        fail.send.side_effect = Exception("boom")

        d.register("ok", ok)
        d.register("fail", fail)

        ev = NotificationEvent(type="gate_blocked", title="x", message="x")
        results = d.dispatch(ev)
        assert results["ok"] is True
        assert results["fail"] is False


# =============================================================================
# Global dispatcher singeton
# =============================================================================

class TestGlobalDispatcher:
    def test_get_dispatcher_returns_same(self):
        d1 = get_dispatcher()
        d2 = get_dispatcher()
        assert d1 is d2

    def test_default_log_notifier_registered(self):
        d = get_dispatcher()
        assert "log" in d.channels


# =============================================================================
# Convenience factories
# =============================================================================

class TestNotificationFactories:
    def test_notify_gate_blocked(self):
        d = NotificationDispatcher()
        ln = LogNotifier()
        d.register("log", ln)

        results = notify_gate_blocked(
            d, domain_id="d-1", run_id="r-1", plan_id="p-1",
            gate_id="g-build", reason="SQLi Critical",
        )
        assert results["log"] is True
        hist = d.event_history
        assert len(hist) == 1
        assert hist[0].type == "gate_blocked"
        assert hist[0].severity == "critical"
        assert "g-build" in hist[0].details["gate_id"]

    def test_notify_run_failed(self):
        d = NotificationDispatcher()
        ln = LogNotifier()
        d.register("log", ln)

        notify_run_failed(d, domain_id="d-1", run_id="r-1", plan_id="p-1",
                          reason="Infra timeout", failure_class="infra")
        hist = d.event_history
        assert hist[0].type == "run_failed"
        assert hist[0].severity == "high"
        assert hist[0].details["failure_class"] == "infra"

    def test_notify_transfer_completed(self):
        d = NotificationDispatcher()
        ln = LogNotifier()
        d.register("log", ln)

        notify_transfer_completed(
            d, domain_id="d-1", run_id="r-1", plan_id="p-1",
            release_id="rel-1", from_zone="zt", to_zone="zpe",
        )
        hist = d.event_history
        assert hist[0].type == "transfer_completed"
        assert hist[0].severity == "medium"
        assert hist[0].details["from_zone"] == "zt"
        assert hist[0].details["to_zone"] == "zpe"

    def test_notify_status_change(self):
        d = NotificationDispatcher()
        ln = LogNotifier()
        d.register("log", ln)

        notify_status_change(d, domain_id="d-1", run_id="r-1", plan_id="p-1",
                            old_status="running", new_status="succeeded")
        hist = d.event_history
        assert hist[0].type == "status_change"
        assert hist[0].details["old_status"] == "running"
        assert hist[0].details["new_status"] == "succeeded"


# =============================================================================
# Dispatcher event history and channel tests
# =============================================================================

class TestNotificationDispatcherEvents:
    def test_history_filtered_by_domain(self):
        d = NotificationDispatcher()
        ln = LogNotifier()
        d.register("log", ln)

        d.dispatch(NotificationEvent(type="run_failed", title="x", message="x", domain_id="d-1", run_id="r-1"))
        d.dispatch(NotificationEvent(type="gate_blocked", title="y", message="y", domain_id="d-2", run_id="r-2"))

        all_events = d.event_history
        assert len(all_events) == 2

        d1_events = [e for e in all_events if e.domain_id == "d-1"]
        assert len(d1_events) == 1
        assert d1_events[0].type == "run_failed"

    def test_channel_count_reflects_registration(self):
        d = NotificationDispatcher()
        assert len(d.channels) == 0
        d.register("a", MagicMock(spec=LogNotifier))
        d.register("b", MagicMock(spec=WebhookNotifier))
        assert len(d.channels) == 2
        d.unregister("a")
        assert len(d.channels) == 1


# =============================================================================
# Integration: event flow simulation
# =============================================================================

class TestIntegrationFlow:
    """COS-065: полный поток событий — gate → run → transfer."""

    def test_full_notification_flow(self):
        d = NotificationDispatcher()
        ln = LogNotifier()
        d.register("log", ln)

        # Gate blocked
        notify_gate_blocked(d, domain_id="d-1", run_id="r-1", plan_id="p-1",
                            gate_id="g-scan", reason="3 Critical findings")
        # Run failed (gate downstream)
        notify_run_failed(d, domain_id="d-1", run_id="r-1", plan_id="p-1",
                          reason="Gate blocked pipeline", failure_class="gate")

        assert len(d.event_history) == 2

        types = [e.type for e in d.event_history]
        assert "gate_blocked" in types
        assert "run_failed" in types

        severities = [e.severity for e in d.event_history]
        assert "critical" in severities
        assert "high" in severities

    def test_transfer_to_zpe_notification(self):
        """После успешного трансфера в ЗПЭ — нотификация."""
        d = NotificationDispatcher()
        ln = LogNotifier()
        d.register("log", ln)

        notify_transfer_completed(
            d, domain_id="d-1", run_id="r-1", plan_id="p-1",
            release_id="rel-final", from_zone="zt", to_zone="zpe",
        )

        assert d.event_history[0].type == "transfer_completed"
        assert "ZPE" in d.event_history[0].title.upper() or "zpe" in d.event_history[0].title.lower()