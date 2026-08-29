# -*- coding: utf-8 -*-
"""COS-033: Valkey PubSub event publisher for Run Control Plane.

Публикует события жизненного цикла запусков в канал `cosmo:run:{run_id}`.

События:
  - status_change  — переход статуса (draft→pending→queued→running→...terminal)
  - batch_complete — батч завершён (build, static_scan, deploy, dynamic_test)
  - gate_decision  — гейт принял решение (pass / block / manual_required)
  - finding        — новая находка безопасности

Rate limit: не чаще 2 Гц (500ms между публикациями на один run_id).

Инварианты:
  - Valkey — только транспорт. При сбросе Valkey → восстановление из PG.
  - Если Valkey недоступен → publisher деградирует в no-op (не блокирует стейт-машину).
  - Сообщения — JSON, без бинарных payload.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any, Callable, Optional

logger = logging.getLogger("cosmoport.events")

# ── Rate limit per run_id ──
_MIN_PUBLISH_INTERVAL = 0.5  # 2 Hz

# Глобальный throttle: run_id → последний ts публикации
_throttle: dict[str, float] = {}


def _can_publish(run_id: str, now: float) -> bool:
    last = _throttle.get(run_id, 0.0)
    if now - last < _MIN_PUBLISH_INTERVAL:
        return False
    _throttle[run_id] = now
    return True


# ── Valkey client (lazy-init, singleton) ──

_valkey_client: Any = None
_valkey_available: bool | None = None  # None = не проверяли


def _get_valkey() -> Any | None:
    """Ленивый singleton для Valkey-клиента.

    Читает COSMO_VALKEY_URL из окружения.
    Если переменная не задана → возвращает None (no-op).
    """
    global _valkey_client, _valkey_available

    if _valkey_available is False:
        return None
    if _valkey_client is not None:
        return _valkey_client

    import os
    url = os.getenv("COSMO_VALKEY_URL", "").strip()
    if not url:
        _valkey_available = False
        logger.debug("COSMO_VALKEY_URL not set — Valkey publisher disabled")
        return None

    try:
        import valkey
        _valkey_client = valkey.Valkey.from_url(url)
        _valkey_client.ping()
        _valkey_available = True
        logger.info("Valkey publisher connected: %s", url)
        return _valkey_client
    except Exception as exc:
        _valkey_available = False
        _valkey_client = None
        logger.warning("Valkey unavailable (%s) — publisher degraded to no-op", exc)
        return None


# ── Channel naming ──

def run_channel(run_id: str) -> str:
    """Каноническое имя канала для run_id."""
    return f"cosmo:run:{run_id}"


# ── Event constructors ──

def _status_change_event(run_id: str, previous: str, current: str) -> dict[str, Any]:
    return {
        "type": "status_change",
        "run_id": run_id,
        "previous": previous,
        "current": current,
        "ts": time.time(),
    }


def _batch_event(run_id: str, batch_id: str, batch_type: str, status: str) -> dict[str, Any]:
    return {
        "type": "batch_complete",
        "run_id": run_id,
        "batch_id": batch_id,
        "batch_type": batch_type,
        "status": status,
        "ts": time.time(),
    }


def _gate_event(run_id: str, gate_id: str, decision: str) -> dict[str, Any]:
    return {
        "type": "gate_decision",
        "run_id": run_id,
        "gate_id": gate_id,
        "decision": decision,
        "ts": time.time(),
    }


def _finding_event(run_id: str, finding_id: str, severity: str) -> dict[str, Any]:
    return {
        "type": "finding",
        "run_id": run_id,
        "finding_id": finding_id,
        "severity": severity,
        "ts": time.time(),
    }


# ── Publisher API ──

def publish_status_change(run_id: str, previous: str, current: str) -> None:
    """Опубликовать смену статуса запуска."""
    v = _get_valkey()
    if v is None:
        return
    now = time.time()
    if not _can_publish(run_id, now):
        return

    payload = _status_change_event(run_id, previous, current)
    _publish(run_id, payload)


def publish_batch_complete(run_id: str, batch_id: str, batch_type: str, status: str) -> None:
    """Опубликовать завершение батча."""
    v = _get_valkey()
    if v is None:
        return
    now = time.time()
    if not _can_publish(run_id, now):
        return

    payload = _batch_event(run_id, batch_id, batch_type, status)
    _publish(run_id, payload)


def publish_gate_decision(run_id: str, gate_id: str, decision: str) -> None:
    """Опубликовать решение гейта."""
    v = _get_valkey()
    if v is None:
        return
    now = time.time()
    if not _can_publish(run_id, now):
        return

    payload = _gate_event(run_id, gate_id, decision)
    _publish(run_id, payload)


def publish_finding(run_id: str, finding_id: str, severity: str) -> None:
    """Опубликовать новую находку."""
    v = _get_valkey()
    if v is None:
        return
    now = time.time()
    if not _can_publish(run_id, now):
        return

    payload = _finding_event(run_id, finding_id, severity)
    _publish(run_id, payload)


def _publish(run_id: str, payload: dict[str, Any]) -> None:
    """Низкоуровневая публикация в Valkey PubSub."""
    v = _get_valkey()
    if v is None:
        return
    channel = run_channel(run_id)
    try:
        data = json.dumps(payload, ensure_ascii=False, default=str)
        v.publish(channel, data)
    except Exception as exc:
        logger.warning("Valkey publish failed for %s: %s", channel, exc)


# ── Bulk publish (для SSE bridge) ──

def publish_snapshot(run_id: str, snapshot: dict[str, Any]) -> None:
    """Опубликовать полный снапшот состояния (используется при reconnect SSE)."""
    v = _get_valkey()
    if v is None:
        return
    payload = {"type": "snapshot", "run_id": run_id, **snapshot, "ts": time.time()}
    _publish(run_id, payload)


# ── Health check ──

def is_available() -> bool:
    """Доступен ли Valkey для публикации событий."""
    return _get_valkey() is not None


# ── Test helpers ──

def reset_throttle() -> None:
    """Сбросить throttle (для тестов)."""
    _throttle.clear()


def reset_client() -> None:
    """Сбросить Valkey-клиент (для тестов)."""
    global _valkey_client, _valkey_available
    _valkey_client = None
    _valkey_available = None