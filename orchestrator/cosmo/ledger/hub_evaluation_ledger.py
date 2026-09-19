# -*- coding: utf-8 -*-
"""COS-153: durable read-through для dispatch-статуса Contract B.

COS-139 держал реестр отправок in-memory (один процесс cosmo-api): после
рестарта ``GET /hub/evaluations/{id}`` терял статус. Здесь — durable-якорь
в ``evidence_ledger``: каждая отправка (успех/сбой) запечатывается как
``type='decision'`` с маркером
``provenance_json.evaluation_type == 'HUB_EVALUATION_DISPATCH'`` и
``provenance_json.source == 'prettyk-hub'``.

Тип строки — ``decision``: колонка ``type`` ограничена frozen-enum
``evidence_type`` (7 значений) и CHECK-констрейнтом, поэтому маркер Contract B
фиксируется в provenance, а не в колонке (миграционная цепочка заморожена;
конвенция гейтов COS-136/138/141/142/147).

Правила:

  - **state-changing исходы**: якорь пишется на ``dispatched`` (успех) и
    ``failed`` (честный сбой — не PASS). Повтор-дубликат состояние не меняет
    и нового якоря не создаёт;
  - **latest wins**: чтение по ``evaluation_id`` возвращает последнюю запись
    (``created_at desc, id desc``) — как promotion-gate Contract A;
  - **идемпотентность/дрейф**: повтор ловится по последнему *успешному*
    якорю (сбой не блокирует retry);
  - **крипто-якорь**: SHA256 канонического payload запечатывается в
    ``content_hash`` и ``provenance_json.dispatch_hash``; цепочку подписывает
    ``commit_evidence_entry`` (COS-082/087).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.cosmo.db.models import EvidenceLedgerEntry
from orchestrator.cosmo.domain.hub_evaluation import (
    HUB_EVALUATION_LEDGER_TYPE,
    HubEvaluationDispatchResponse,
    HubEvaluationRequest,
    evaluation_dispatch_hash,
    evaluation_identity,
)
from orchestrator.cosmo.ledger.evidence_writer import commit_evidence_entry

#: Источник записи dispatch в provenance_json.
HUB_EVALUATION_SOURCE = "prettyk-hub"

#: Ключ маркера Contract B в provenance_json.
HUB_EVALUATION_TYPE_KEY = "evaluation_type"

#: Ключ исхода отправки в provenance_json.
HUB_EVALUATION_OUTCOME_KEY = "outcome"

#: Исход: отправка состоялась (Hub ответил).
DISPATCH_OUTCOME_DISPATCHED = "dispatched"

#: Исход: отправка не состоялась (транспортный сбой/отказ Hub) — не PASS.
DISPATCH_OUTCOME_FAILED = "failed"


@dataclass
class DispatchRecord:
    """Durable-запись отправки: ответ, immutable identity, ответ Hub."""

    response: HubEvaluationDispatchResponse
    identity: dict[str, str]
    hub_response: dict[str, Any] = field(default_factory=dict)


def _evaluation_filter(stmt):
    """Ограничить выборку записями Contract B."""
    return (
        stmt
        .where(EvidenceLedgerEntry.type == "decision")
        .where(
            EvidenceLedgerEntry.provenance_json["source"].astext
            == HUB_EVALUATION_SOURCE
        )
        .where(
            EvidenceLedgerEntry.provenance_json[HUB_EVALUATION_TYPE_KEY].astext
            == HUB_EVALUATION_LEDGER_TYPE
        )
    )


def _ordered(stmt):
    return stmt.order_by(
        EvidenceLedgerEntry.created_at.desc(),
        EvidenceLedgerEntry.id.desc(),
    )


def _row_to_record(row: EvidenceLedgerEntry) -> DispatchRecord:
    prov = row.provenance_json or {}
    response = HubEvaluationDispatchResponse(
        dispatched=bool(prov.get("dispatched", False)),
        request_id=prov.get("request_id") or "unknown",
        evaluation_id=prov.get("evaluation_id") or "",
        status=prov.get("response_status") or "unknown",
        dispatched_at=prov.get("dispatched_at") or "",
    )
    identity = {
        key: str(prov.get(key) or "")
        for key in ("release_id", "run_id", "build_id", "artifact_digest")
    }
    return DispatchRecord(
        response=response,
        identity=identity,
        hub_response=prov.get("hub_response") or {},
    )


class HubEvaluationLedger:
    """Durable якорь dispatch-событий Contract B (evidence_ledger)."""

    async def _find(
        self,
        session: AsyncSession,
        *,
        evaluation_id: str,
        dispatched_only: bool = False,
    ) -> EvidenceLedgerEntry | None:
        stmt = _evaluation_filter(select(EvidenceLedgerEntry)).where(
            EvidenceLedgerEntry.provenance_json["evaluation_id"].astext
            == evaluation_id
        )
        if dispatched_only:
            stmt = stmt.where(
                EvidenceLedgerEntry.provenance_json[
                    HUB_EVALUATION_OUTCOME_KEY
                ].astext == DISPATCH_OUTCOME_DISPATCHED
            )
        stmt = _ordered(stmt).limit(1)
        return (await session.execute(stmt)).scalars().first()

    async def record(
        self,
        session: AsyncSession,
        *,
        request: HubEvaluationRequest,
        response: HubEvaluationDispatchResponse,
        outcome: str,
        hub_response: dict[str, Any] | None = None,
        actor: str = "system",
    ) -> EvidenceLedgerEntry:
        """Запечатать исход отправки в ledger (успех или честный сбой)."""
        payload = {
            "evaluation_id": request.evaluation_id,
            "request_id": response.request_id,
            "release_id": request.release_id,
            "run_id": request.run_id,
            "build_id": request.build_id,
            "artifact_digest": request.artifact_digest,
            HUB_EVALUATION_OUTCOME_KEY: outcome,
            "response_status": response.status,
            "dispatched": response.dispatched,
            "dispatched_at": response.dispatched_at,
        }
        content_hash = evaluation_dispatch_hash(payload)
        provenance = dict(payload)
        provenance.update({
            "source": HUB_EVALUATION_SOURCE,
            "contract": "B",
            HUB_EVALUATION_TYPE_KEY: HUB_EVALUATION_LEDGER_TYPE,
            "dispatch_hash": content_hash,
            "hub_response": hub_response or {},
            "actor": actor,
        })

        entry = EvidenceLedgerEntry(
            run_id=request.run_id,
            type="decision",
            content_ref=f"hub://evaluation/{request.evaluation_id}",
            content_hash=content_hash,
            provenance_json=provenance,
        )
        await commit_evidence_entry(session, entry)
        return entry

    async def latest_for_evaluation(
        self, session: AsyncSession, evaluation_id: str,
    ) -> Optional[DispatchRecord]:
        """Последняя durable-запись по ``evaluation_id`` (любой исход)."""
        row = await self._find(session, evaluation_id=evaluation_id)
        return _row_to_record(row) if row else None

    async def latest_dispatched_for_evaluation(
        self, session: AsyncSession, evaluation_id: str,
    ) -> Optional[DispatchRecord]:
        """Последняя *успешная* отправка (для идемпотентности/дрейфа)."""
        row = await self._find(
            session, evaluation_id=evaluation_id, dispatched_only=True,
        )
        return _row_to_record(row) if row else None


__all__ = [
    "DISPATCH_OUTCOME_DISPATCHED",
    "DISPATCH_OUTCOME_FAILED",
    "DispatchRecord",
    "HUB_EVALUATION_OUTCOME_KEY",
    "HUB_EVALUATION_SOURCE",
    "HUB_EVALUATION_TYPE_KEY",
    "HubEvaluationLedger",
]
