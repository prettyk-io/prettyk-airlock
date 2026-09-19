# -*- coding: utf-8 -*-
"""COS-139: Contract B — диспетчер внешней оценки релиза в PrettyK Hub.

Сервис между API и транспортом: превращает валидный конверт Contract B в
отправку в Hub, держит идемпотентность по ``evaluation_id`` и фиксирует
каждое событие в audit trail (``cosmo_audit_events``).

Правила (docs/research/2026-09-02-cross-product-contract-bridge.md §5, §7):

  - **Clearance gate:** обязательный контекст проверяется ДО отправки —
    Studio-вердикт обязан быть ``PASS``, а ``qualifying_context=True``
    обязателен для production-профилей. Иначе — отказ, не warning;
  - **Идемпотентность:** повтор с тем же ``evaluation_id`` не порождает
    вторую отправку; повтор с тем же ``evaluation_id``, но другой
    immutable-identity (release/run/build/digest) — дрейф контракта;
  - **Honest failure:** сбой/таймаут Hub не превращается в PASS — событие
    уходит в аудит со ``status="failed"``, вызывающая сторона получает
    :class:`~orchestrator.cosmo.adapters.hub_client.HubDispatchError`;
  - **Durability (COS-153):** исход каждой отправки запечатывается durable-
    якорем в ``evidence_ledger`` (см. ``ledger/hub_evaluation_ledger.py``);
    in-memory реестра-дубликата больше нет — ``GET`` читает статус из ledger
    и переживает рестарт процесса.
"""
from __future__ import annotations

import datetime
from typing import Any, Callable, Optional

from orchestrator.cosmo.adapters.hub_client import (
    HubDispatchError,
    HubEvaluationClient,
)
from orchestrator.cosmo.domain.hub_evaluation import (
    HubEvaluationDispatchResponse,
    HubEvaluationRequest,
    evaluation_identity,
)
from orchestrator.cosmo.ledger.hub_evaluation_ledger import (
    DISPATCH_OUTCOME_DISPATCHED,
    DISPATCH_OUTCOME_FAILED,
    HubEvaluationLedger,
)

#: Action в audit trail для отправки оценки в Hub.
HUB_EVALUATION_AUDIT_ACTION = "hub_evaluation_dispatch"

#: Resource type в audit trail.
HUB_EVALUATION_AUDIT_RESOURCE = "evaluation"

#: Статус идемпотентного повтора в ответе.
DISPATCH_STATUS_DUPLICATE = "duplicate"


def _default_clock() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def _record_audit(
    *,
    actor: str,
    evaluation_id: str,
    status: str,
    details: dict[str, Any],
) -> None:
    """Записать событие в audit trail (lazy import — без цикла импортов)."""
    from orchestrator.cosmo.api.routes.audit import record_system_event

    record_system_event(
        user_id=actor,
        action=HUB_EVALUATION_AUDIT_ACTION,
        resource_type=HUB_EVALUATION_AUDIT_RESOURCE,
        resource_id=evaluation_id,
        status=status,
        details=details,
    )


class HubEvaluationDispatcher:
    """Оркестрация отправки Contract B: валидация → отправка → якорь → аудит."""

    def __init__(
        self,
        client: HubEvaluationClient | None = None,
        *,
        ledger: HubEvaluationLedger | None = None,
        clock: Callable[[], datetime.datetime] | None = None,
    ) -> None:
        self._client = client or HubEvaluationClient()
        self._ledger = ledger or HubEvaluationLedger()
        self._clock = clock or _default_clock

    @property
    def client(self) -> HubEvaluationClient:
        return self._client

    async def get(
        self, session, evaluation_id: str,
    ) -> Optional[HubEvaluationDispatchResponse]:
        """Durable-статус отправки по ``evaluation_id`` (``None`` — не было)."""
        record = await self._ledger.latest_for_evaluation(session, evaluation_id)
        return record.response if record is not None else None

    async def dispatch(
        self,
        request: HubEvaluationRequest,
        *,
        session,
        actor: str = "system",
    ) -> HubEvaluationDispatchResponse:
        """Отправить оценку в Hub (идемпотентно по ``evaluation_id``).

        Raises:
            HubEvaluationContextError: обязательный контекст нарушен
                (``qualifying_context``/Studio-вердикт) — отправка запрещена.
            HubDispatchError: транспортный сбой/таймаут/отказ хаба.
        """
        # 1. Clearance gate — обязательный контекст до любого I/O.
        request.enforce_required_context()

        identity = evaluation_identity(request)
        existing = await self._ledger.latest_dispatched_for_evaluation(
            session, request.evaluation_id,
        )
        if existing is not None:
            if existing.identity != identity:
                raise _context_drift(request.evaluation_id, existing.identity,
                                     identity)
            _record_audit(
                actor=actor,
                evaluation_id=request.evaluation_id,
                status="success",
                details={
                    "duplicate": True,
                    "release_id": request.release_id,
                    "run_id": request.run_id,
                    "artifact_digest": request.artifact_digest,
                },
            )
            return HubEvaluationDispatchResponse(
                dispatched=False,
                request_id=existing.response.request_id,
                evaluation_id=request.evaluation_id,
                status=DISPATCH_STATUS_DUPLICATE,
                dispatched_at=existing.response.dispatched_at,
            )

        payload = request.model_dump()

        # 2. Отправка. Сбой не превращается в PASS — фиксируем и пробрасываем.
        try:
            hub_response = await self._client.dispatch(payload)
        except HubDispatchError as exc:
            await self._ledger.record(
                session,
                request=request,
                response=HubEvaluationDispatchResponse(
                    dispatched=False,
                    request_id=request.request_id,
                    evaluation_id=request.evaluation_id,
                    status=DISPATCH_OUTCOME_FAILED,
                    dispatched_at=self._clock().isoformat(),
                ),
                outcome=DISPATCH_OUTCOME_FAILED,
                actor=actor,
            )
            _record_audit(
                actor=actor,
                evaluation_id=request.evaluation_id,
                status="failed",
                details={
                    "release_id": request.release_id,
                    "run_id": request.run_id,
                    "artifact_digest": request.artifact_digest,
                    "attempts": exc.attempts,
                    "status_code": exc.status_code,
                    "error": str(exc),
                },
            )
            raise

        dispatched_at = self._clock().isoformat()
        status = _hub_status(hub_response)
        response = HubEvaluationDispatchResponse(
            dispatched=True,
            request_id=request.request_id,
            evaluation_id=request.evaluation_id,
            status=status,
            dispatched_at=dispatched_at,
        )
        await self._ledger.record(
            session,
            request=request,
            response=response,
            outcome=DISPATCH_OUTCOME_DISPATCHED,
            hub_response=hub_response,
            actor=actor,
        )

        _record_audit(
            actor=actor,
            evaluation_id=request.evaluation_id,
            status="success",
            details={
                "release_id": request.release_id,
                "run_id": request.run_id,
                "build_id": request.build_id,
                "artifact_digest": request.artifact_digest,
                "release_profile": request.release_profile,
                "target_zone": request.target_zone,
                "qualifying_context": request.qualifying_context,
                "hub_status": status,
            },
        )
        return response


def _hub_status(hub_response: dict[str, Any]) -> str:
    """Статус оценки из ответа Hub (Contract C → ``qg_clearance``)."""
    for key in ("status", "qg_clearance", "verdict"):
        value = hub_response.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return "dispatched"


def _context_drift(
    evaluation_id: str,
    existing: dict[str, str],
    incoming: dict[str, str],
):
    """Дрейф контекста: тот же ``evaluation_id`` — другая identity."""
    from orchestrator.cosmo.domain.hub_evaluation import HubEvaluationContextError

    changed = sorted(
        key for key in incoming
        if existing.get(key) != incoming[key]
    )
    return HubEvaluationContextError(
        f"evaluation_id {evaluation_id!r} already dispatched with a different "
        f"context (changed: {', '.join(changed) or 'unknown'})"
    )


__all__ = [
    "DISPATCH_STATUS_DUPLICATE",
    "HUB_EVALUATION_AUDIT_ACTION",
    "HUB_EVALUATION_AUDIT_RESOURCE",
    "HubEvaluationDispatcher",
]
