# -*- coding: utf-8 -*-
"""COS-056: Domain event triggers → durable Notification Manager.

Safe wrapper'ы для вызова из domain routes. Каждый триггер:
  * создаёт durable outbox event (transactional);
  * НИКОГДА не бросает исключение — domain transaction не ломается;
  * логирует ошибку с scrubbed payload при failure.

Использование из route handler'ов (после commit):
    from orchestrator.cosmo.notifications.integration import notify_run_status_safe
    notify_run_status_safe(run_id="r-1", domain_id="d-1", status="failed", ...)

Все функции sync (fire-and-forget): асинхронная обработка outbox —
через POST /process или фоновый таск.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, Optional

from orchestrator.cosmo.notifications.policy import safe_log_line

logger = logging.getLogger("cosmoport.notifications.integration")


def _run_async(coro):
    """Fire-and-forget async call from sync context (route handler после commit)."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.ensure_future(coro)
        else:
            loop.run_until_complete(coro)
    except RuntimeError:
        # Нет event loop в текущем потоке — создаём временный.
        asyncio.run(coro)
    except Exception:
        logger.exception("[INTEGRATION:fire-error]")


# ── Run events ──────────────────────────────────────────────────────────


def notify_run_status_safe(
    *,
    run_id: str,
    domain_id: str,
    status: str,
    plan_id: str = "",
    initiator: str = "",
    reason: str = "",
    gate_decisions: Optional[Dict[str, Any]] = None,
) -> None:
    """Run status change → durable outbox event.

    Значимые переходы: succeeded → run_succeeded, failed → run_failed,
    blocked → run_blocked (SAST-GATE-3: решение гейта/терминальная причина
    видны внешнему контуру — reason + gate_decisions, без пересчёта на клиенте).
    Другие переходы (running, queued) — не уведомление.
    """
    if status == "failed":
        event_type = "run_failed"
    elif status == "succeeded":
        event_type = "run_succeeded"
    elif status == "blocked":
        event_type = "run_blocked"
    else:
        return  # не значимый переход

    title = f"Run {run_id} {status}"
    message = f"Run {run_id} ({plan_id}) — {status}"
    if reason:
        message = f"{message} [{reason}]"

    payload: Dict[str, Any] = {
        "run_id": run_id,
        "domain_id": domain_id,
        "plan_id": plan_id,
        "initiator": initiator,
        "status": status,
    }
    if reason:
        payload["reason"] = reason
    if gate_decisions:
        payload["gate_decisions"] = gate_decisions

    _run_async(_emit(
        event_type=event_type,
        aggregate_type="run",
        aggregate_id=run_id,
        title=title,
        message=message,
        correlation_id=run_id,
        domain_id=domain_id,
        payload=payload,
    ))


# ── Gate events ─────────────────────────────────────────────────────────


def notify_gate_decision_safe(
    *,
    gate_id: str,
    plan_id: str,
    decision: str,
    decided_by: str = "",
    domain_id: str = "",
) -> None:
    """Gate decision → durable outbox event (blocked / passed)."""
    if decision == "block":
        event_type = "gate_blocked"
        title = f"Gate {gate_id} blocked"
        message = f"Security gate {gate_id} blocked release pipeline."
    elif decision == "pass":
        event_type = "gate_passed"
        title = f"Gate {gate_id} passed"
        message = f"Security gate {gate_id} passed."
    else:
        return  # manual_required и др. — не уведомление

    _run_async(_emit(
        event_type=event_type,
        aggregate_type="gate",
        aggregate_id=gate_id,
        title=title,
        message=message,
        correlation_id=gate_id,
        domain_id=domain_id,
        payload={
            "gate_id": gate_id,
            "plan_id": plan_id,
            "decision": decision,
            "decided_by": decided_by,
            "domain_id": domain_id,
        },
    ))


# ── Batch events ────────────────────────────────────────────────────────


def notify_batch_status_safe(
    *,
    batch_id: str,
    plan_id: str,
    status: str,
    domain_id: str = "",
) -> None:
    """Batch status → durable outbox event (только failed)."""
    if status != "failed":
        return
    _run_async(_emit(
        event_type="batch_failed",
        aggregate_type="batch",
        aggregate_id=batch_id,
        title=f"Batch {batch_id} failed",
        message=f"Pipeline batch {batch_id} ({plan_id}) failed.",
        correlation_id=batch_id,
        domain_id=domain_id,
        payload={
            "batch_id": batch_id,
            "plan_id": plan_id,
            "status": status,
            "domain_id": domain_id,
        },
    ))


# ── Release events ──────────────────────────────────────────────────────


def notify_release_approved_safe(
    *,
    release_id: str,
    domain_id: str,
    approved_by: str = "",
    version: str = "",
) -> None:
    """Release approval → durable outbox event."""
    _run_async(_emit(
        event_type="release_approved",
        aggregate_type="release",
        aggregate_id=release_id,
        title=f"Release {release_id} approved",
        message=f"Release {release_id} (v{version}) approved by {approved_by}.",
        correlation_id=release_id,
        domain_id=domain_id,
        payload={
            "release_id": release_id,
            "domain_id": domain_id,
            "approved_by": approved_by,
            "version": version,
        },
    ))


# ── Transfer events ─────────────────────────────────────────────────────


def notify_transfer_completed_safe(
    *,
    release_id: str,
    domain_id: str,
    from_zone: str,
    to_zone: str,
    initiated_by: str = "",
) -> None:
    """Transfer completed → durable outbox event."""
    _run_async(_emit(
        event_type="transfer_completed",
        aggregate_type="transfer",
        aggregate_id=f"{release_id}:{from_zone}->{to_zone}",
        title=f"Release {release_id} → {to_zone.upper()}",
        message=f"Release {release_id}: {from_zone.upper()} → {to_zone.upper()}",
        correlation_id=release_id,
        domain_id=domain_id,
        payload={
            "release_id": release_id,
            "domain_id": domain_id,
            "from_zone": from_zone,
            "to_zone": to_zone,
            "initiated_by": initiated_by,
        },
    ))


# COS-055 compat: releases.py uses this name
notify_transfer_durable_safe = notify_transfer_completed_safe


def notify_transfer_failed_safe(
    *,
    release_id: str,
    domain_id: str,
    from_zone: str,
    to_zone: str,
    reason: str = "",
) -> None:
    """Transfer failed → durable outbox event."""
    _run_async(_emit(
        event_type="transfer_failed",
        aggregate_type="transfer",
        aggregate_id=f"{release_id}:{from_zone}->{to_zone}",
        title=f"Release {release_id} transfer failed",
        message=f"Transfer {from_zone} → {to_zone} failed: {reason}",
        correlation_id=release_id,
        domain_id=domain_id,
        payload={
            "release_id": release_id,
            "domain_id": domain_id,
            "from_zone": from_zone,
            "to_zone": to_zone,
            "reason": reason,
        },
    ))


# ── Core emit (async) ───────────────────────────────────────────────────


async def _emit(
    *,
    event_type: str,
    aggregate_type: str,
    aggregate_id: str,
    title: str,
    message: str,
    correlation_id: Optional[str],
    domain_id: Optional[str],
    payload: Dict[str, Any],
) -> None:
    """Записать событие в durable outbox. Ошибка → лог, не raise."""
    try:
        from orchestrator.cosmo.db.session import get_sessionmaker
        from orchestrator.cosmo.notifications.manager import get_manager

        sm = get_sessionmaker()
        async with sm() as session:
            mgr = get_manager()
            await mgr.record_event(
                session,
                event_type=event_type,
                aggregate_type=aggregate_type,
                aggregate_id=aggregate_id,
                payload=payload,
                title=title,
                message=message,
                correlation_id=correlation_id,
                domain_id=domain_id,
            )
            await session.commit()
            logger.info(safe_log_line("[INTEGRATION:emitted]", {
                "event_type": event_type, "aggregate": f"{aggregate_type}/{aggregate_id}",
            }))
    except Exception as exc:
        logger.error(safe_log_line("[INTEGRATION:error]", {
            "event_type": event_type,
            "aggregate": f"{aggregate_type}/{aggregate_id}",
            "error": str(exc)[:200],
        }))
