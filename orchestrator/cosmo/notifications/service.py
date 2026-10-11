"""
COS-065: Notification Service — события жизненного цикла.

Каналы: WebhookNotifier (POST JSON), LogNotifier (структурированный аудит).
Триггеры:
  - Gate blocked / Run FAILED → alert
  - Transfer completed (reach zpe) → notification
  - General жизненный цикл (status_change)
"""
from __future__ import annotations

import json
import logging
import threading
import time
import urllib.request
import urllib.error
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Literal, Optional

logger = logging.getLogger("cosmoport.notifications")

# ── Model ───────────────────────────────────────────────────────────────────

NotificationSeverity = Literal["critical", "high", "medium", "low", "info"]
NotificationType = Literal["gate_blocked", "gate_passed", "run_failed", "run_succeeded",
                              "run_blocked", "transfer_completed", "transfer_failed",
                              "status_change", "batch_failed", "deploy_started",
                              "release_approved"]

_notif_severity_map: dict[NotificationType, NotificationSeverity] = {
    "gate_blocked": "critical",
    "run_failed": "high",
    "run_blocked": "high",
    "batch_failed": "high",
    "gate_passed": "info",
    "run_succeeded": "info",
    "transfer_completed": "medium",
    "transfer_failed": "high",
    "status_change": "info",
    "deploy_started": "low",
    "release_approved": "info",
}


@dataclass
class NotificationEvent:
    """COS-065: унифицированное событие нотификации."""
    type: NotificationType
    title: str
    message: str
    details: Dict[str, Any] = field(default_factory=dict)
    severity: NotificationSeverity = "info"
    recipients: List[str] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)
    domain_id: str = ""
    run_id: str = ""
    plan_id: str = ""

    def __post_init__(self):
        if not self.severity or self.severity == "info":
            self.severity = _notif_severity_map.get(self.type, "info")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.type,
            "severity": self.severity,
            "title": self.title,
            "message": self.message,
            "details": self.details,
            "recipients": self.recipients,
            "timestamp": self.timestamp,
            "domain_id": self.domain_id,
            "run_id": self.run_id,
            "plan_id": self.plan_id,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, default=str)


# ── Notifier Interface ──────────────────────────────────────────────────────

class BaseNotifier:
    """Абстрактный канал доставки."""
    def send(self, event: NotificationEvent) -> bool:
        raise NotImplementedError


# ── WebhookNotifier ─────────────────────────────────────────────────────────

class WebhookNotifier(BaseNotifier):
    """POST JSON на указанный URL с retry (до 3 попыток, exponential backoff)."""

    def __init__(self, webhook_url: str, secret: str = "", timeout: float = 10.0):
        self._url = webhook_url.rstrip("/")
        self._secret = secret
        self._timeout = timeout
        self._sent_count = 0
        self._failed_count = 0

    @property
    def url(self) -> str:
        return self._url

    @property
    def sent_count(self) -> int:
        return self._sent_count

    @property
    def failed_count(self) -> int:
        return self._failed_count

    def send(self, event: NotificationEvent) -> bool:
        payload = event.to_json().encode("utf-8")
        headers = {"Content-Type": "application/json; charset=utf-8"}

        if self._secret:
            import hmac, hashlib
            sig = hmac.new(self._secret.encode(), payload, hashlib.sha256).hexdigest()
            headers["X-Cosmo-Signature"] = sig

        for attempt in range(3):
            try:
                req = urllib.request.Request(
                    self._url, data=payload, headers=headers, method="POST",
                )
                with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                    if 200 <= resp.status < 300:
                        self._sent_count += 1
                        return True
                    logger.warning("Webhook %s returned %s", self._url, resp.status)
            except Exception as exc:
                logger.debug("Webhook attempt %d failed: %s", attempt + 1, exc)
                if attempt < 2:
                    time.sleep(2 ** attempt)

        self._failed_count += 1
        logger.error("Webhook %s failed after 3 attempts", self._url)
        return False


# ── LogNotifier ─────────────────────────────────────────────────────────────

class LogNotifier(BaseNotifier):
    """Структурированный аудит-лог (пишет в логгер + in-memory history)."""

    def __init__(self, max_history: int = 200):
        self._history: List[NotificationEvent] = []
        self._max_history = max_history

    @property
    def history(self) -> list[NotificationEvent]:
        return list(self._history)

    def send(self, event: NotificationEvent) -> bool:
        logger.info(
            "[NOTIFY] %s | %s | domain=%s run=%s | %s",
            event.severity.upper(), event.type, event.domain_id,
            event.run_id, event.title,
        )
        self._history.append(event)
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history:]
        return True


# ── NotificationDispatcher ──────────────────────────────────────────────────

class NotificationDispatcher:
    """COS-065: центральный диспетчер — fan-out по всем каналам."""

    def __init__(self):
        self._notifiers: Dict[str, BaseNotifier] = {}  # channel_name → notifier
        self._lock = threading.Lock()
        self._event_history: List[NotificationEvent] = []
        self._max_history = 500

    def register(self, name: str, notifier: BaseNotifier) -> None:
        with self._lock:
            self._notifiers[name] = notifier

    def unregister(self, name: str) -> None:
        with self._lock:
            self._notifiers.pop(name, None)

    @property
    def channels(self) -> list[str]:
        with self._lock:
            return list(self._notifiers.keys())

    def dispatch(self, event: NotificationEvent) -> dict[str, bool]:
        """Разослать событие по всем каналам. Возвращает {channel: ok}."""
        results: dict[str, bool] = {}
        with self._lock:
            self._event_history.append(event)
            if len(self._event_history) > self._max_history:
                self._event_history = self._event_history[-self._max_history:]

            for name, notifier in self._notifiers.items():
                try:
                    results[name] = notifier.send(event)
                except Exception as exc:
                    logger.exception("Notifier %s failed: %s", name, exc)
                    results[name] = False
        return results

    @property
    def event_history(self) -> list[NotificationEvent]:
        with self._lock:
            return list(self._event_history)


# ── Convenience factories ───────────────────────────────────────────────────

def notify_gate_blocked(
    dispatcher: NotificationDispatcher,
    *,
    domain_id: str,
    run_id: str,
    plan_id: str,
    gate_id: str,
    reason: str,
) -> dict[str, bool]:
    return dispatcher.dispatch(NotificationEvent(
        type="gate_blocked",
        title=f"Gate {gate_id} blocked",
        message=f"Gate blocked: {reason}",
        details={"gate_id": gate_id, "reason": reason},
        domain_id=domain_id, run_id=run_id, plan_id=plan_id,
    ))


def notify_run_failed(
    dispatcher: NotificationDispatcher,
    *,
    domain_id: str,
    run_id: str,
    plan_id: str,
    reason: str,
    failure_class: str = "",
) -> dict[str, bool]:
    return dispatcher.dispatch(NotificationEvent(
        type="run_failed",
        title=f"Run {run_id} failed",
        message=reason,
        details={"failure_class": failure_class, "reason": reason},
        domain_id=domain_id, run_id=run_id, plan_id=plan_id,
    ))


def notify_transfer_completed(
    dispatcher: NotificationDispatcher,
    *,
    domain_id: str,
    run_id: str,
    plan_id: str,
    release_id: str,
    from_zone: str,
    to_zone: str,
) -> dict[str, bool]:
    return dispatcher.dispatch(NotificationEvent(
        type="transfer_completed",
        title=f"Release {release_id} transferred to {to_zone.upper()}",
        message=f"Release {release_id}: {from_zone.upper()} → {to_zone.upper()}",
        details={"release_id": release_id, "from_zone": from_zone, "to_zone": to_zone},
        domain_id=domain_id, run_id=run_id, plan_id=plan_id,
    ))


def notify_status_change(
    dispatcher: NotificationDispatcher,
    *,
    domain_id: str,
    run_id: str,
    plan_id: str,
    old_status: str,
    new_status: str,
) -> dict[str, bool]:
    return dispatcher.dispatch(NotificationEvent(
        type="status_change",
        title=f"Run {run_id}: {old_status} → {new_status}",
        message=f"Status transition: {old_status} → {new_status}",
        details={"old_status": old_status, "new_status": new_status},
        domain_id=domain_id, run_id=run_id, plan_id=plan_id,
    ))


# ── Global singleton ────────────────────────────────────────────────────────

_global_dispatcher = NotificationDispatcher()
_global_dispatcher.register("log", LogNotifier())


def get_dispatcher() -> NotificationDispatcher:
    return _global_dispatcher