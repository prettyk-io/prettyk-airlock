# -*- coding: utf-8 -*-
"""COS-141: Contract C — clearance-gate клиренса Quality Gate в ledger.

Клиренс Hub живёт в ``evidence_ledger`` как запись ``type='decision'`` с
маркером ``provenance_json.clearance_type == 'QG_CLEARANCE'`` и
``provenance_json.source == 'prettyk-hub'``. Тип строки — ``decision``:
колонка ``type`` ограничена frozen-enum ``evidence_type`` (7 значений) и
CHECK-констрейнтом, поэтому маркер Contract C фиксируется в provenance, а не
в колонке (миграционная цепочка заморожена; см. scope deviation карточки).

Правила:

  - **дедупликация** по ``(evaluation_id, release_id)``: повтор с тем же
    неизменяемым контекстом (``run_id``, ``policy_version``) → ``duplicate``
    (без второй записи); расхождение контекста → :class:`HubClearanceConflictError`
    (HTTP 400) — тихой перезаписи решения нет;
  - **крипто-якорь**: SHA256 канонического payload клиренса запечатывается в
    ``content_hash`` и ``provenance_json.clearance_hash``;
  - **авторизация трансфера** (fail-closed): ``transfer_allowed`` истинно
    строго при ``PASS_GRANTED`` + ``ok_to_transfer`` + execution in (PASS, WARN);
  - **последний клиренс побеждает**: более поздняя запись по релизу
    перекрывает раннюю (как promotion-gate Contract A).
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.cosmo.db.models import EvidenceLedgerEntry
from orchestrator.cosmo.domain.hub_clearance import (
    HUB_CLEARANCE_LEDGER_TYPE,
    HubClearanceConflictError,
    HubClearanceIngestRequest,
    HubClearanceIngestResponse,
    clearance_hash,
    compute_transfer_allowed,
)
from orchestrator.cosmo.ledger.evidence_writer import commit_evidence_entry

#: Источник записи клиренса в provenance_json.
HUB_CLEARANCE_SOURCE = "prettyk-hub"

#: Ключ маркера Contract C в provenance_json.
HUB_CLEARANCE_TYPE_KEY = "clearance_type"


def _clearance_filter(stmt):
    """Ограничить выборку записями клиренса Contract C."""
    return (
        stmt
        .where(EvidenceLedgerEntry.type == "decision")
        .where(
            EvidenceLedgerEntry.provenance_json["source"].astext
            == HUB_CLEARANCE_SOURCE
        )
        .where(
            EvidenceLedgerEntry.provenance_json[HUB_CLEARANCE_TYPE_KEY].astext
            == HUB_CLEARANCE_LEDGER_TYPE
        )
    )


def _ordered(stmt):
    return stmt.order_by(
        EvidenceLedgerEntry.created_at.desc(),
        EvidenceLedgerEntry.id.desc(),
    )


def _row_to_response(
    row: EvidenceLedgerEntry, status: str,
) -> HubClearanceIngestResponse:
    prov = row.provenance_json or {}
    return HubClearanceIngestResponse(
        status=status,  # type: ignore[arg-type]
        evaluation_id=prov.get("evaluation_id", ""),
        release_id=prov.get("release_id", ""),
        clearance_status=prov.get("qg_clearance", "REJECTED"),
        transfer_allowed=bool(prov.get("transfer_allowed", False)),
        ledger_entry_id=row.id,
        timestamp=row.created_at.isoformat() if row.created_at else "",
    )


class HubClearanceGateManager:
    """Приём/чтение клиренсов Quality Gate и авторизация трансфера."""

    async def _find(
        self,
        session: AsyncSession,
        *,
        evaluation_id: str | None = None,
        release_id: str | None = None,
    ) -> EvidenceLedgerEntry | None:
        stmt = _clearance_filter(select(EvidenceLedgerEntry))
        if evaluation_id is not None:
            stmt = stmt.where(
                EvidenceLedgerEntry.provenance_json["evaluation_id"].astext
                == evaluation_id
            )
        if release_id is not None:
            stmt = stmt.where(
                EvidenceLedgerEntry.provenance_json["release_id"].astext
                == release_id
            )
        stmt = _ordered(stmt).limit(1)
        return (await session.execute(stmt)).scalars().first()

    async def ingest(
        self,
        session: AsyncSession,
        request: HubClearanceIngestRequest,
    ) -> HubClearanceIngestResponse:
        """Принять клиренс: дедуп/дрейф → крипто-якорь → авторизация.

        Raises:
            HubClearanceConflictError: тот же ``(evaluation_id, release_id)``,
                но другой ``run_id``/``policy_version``.
        """
        existing = await self._find(
            session,
            evaluation_id=request.evaluation_id,
            release_id=request.release_id,
        )
        if existing is not None:
            prov = existing.provenance_json or {}
            stored = {
                "run_id": prov.get("run_id"),
                "policy_version": prov.get("policy_version"),
            }
            if stored != request.clearance_identity():
                changed = sorted(
                    key for key, value in request.clearance_identity().items()
                    if stored.get(key) != value
                )
                raise HubClearanceConflictError(
                    "clearance for evaluation "
                    f"{request.evaluation_id!r} / release {request.release_id!r} "
                    "already recorded with a different immutable context "
                    f"(changed: {', '.join(changed) or 'unknown'})"
                )
            return _row_to_response(existing, "duplicate")

        # Противоречивый конверт (qualifying_context=false + положительный
        # клиренс) — не тихая перезапись, а явный reject с отказом трансфера.
        rejected = request.violates_qualifying_context()
        transfer_allowed = (
            False if rejected else compute_transfer_allowed(
                qg_clearance=request.qg_clearance,
                ok_to_transfer=request.ok_to_transfer,
                security_execution_verdict=request.security_execution_verdict,
            )
        )

        payload = request.clearance_payload()
        payload_hash = clearance_hash(payload)
        provenance = dict(payload)
        provenance.update({
            "source": HUB_CLEARANCE_SOURCE,
            "contract": "C",
            HUB_CLEARANCE_TYPE_KEY: HUB_CLEARANCE_LEDGER_TYPE,
            "clearance_hash": payload_hash,
            "transfer_allowed": transfer_allowed,
        })

        entry = EvidenceLedgerEntry(
            run_id=request.run_id,
            type="decision",
            content_ref=(
                f"hub://clearance/{request.release_id}/{request.evaluation_id}"
            ),
            content_hash=payload_hash,
            provenance_json=provenance,
        )
        await commit_evidence_entry(session, entry)

        return _row_to_response(
            entry, "rejected" if rejected else "accepted",
        )

    async def latest_for_release(
        self, session: AsyncSession, release_id: str,
    ) -> HubClearanceIngestResponse | None:
        """Актуальный (последний) клиренс релиза."""
        row = await self._find(session, release_id=release_id)
        return _row_to_response(row, "accepted") if row else None

    async def latest_for_evaluation(
        self, session: AsyncSession, evaluation_id: str,
    ) -> HubClearanceIngestResponse | None:
        """Актуальный клиренс по ID оценки."""
        row = await self._find(session, evaluation_id=evaluation_id)
        return _row_to_response(row, "accepted") if row else None

    async def is_transfer_authorized(
        self, session: AsyncSession, release_id: str,
    ) -> bool:
        """Авторизован ли трансфер релиза (fail-closed: нет клиренса → False)."""
        latest = await self.latest_for_release(session, release_id)
        return bool(latest and latest.transfer_allowed)


async def release_transfer_allowed(
    session: AsyncSession, release_id: str,
) -> bool:
    """Модульный хелпер авторизации трансфера (fail-closed).

    Точка подключения для трансфер-поверхности (``zt``/``zpe``); сама
    интеграция в маршруты трансфера — вне поверхности COS-141.
    """
    return await HubClearanceGateManager().is_transfer_authorized(
        session, release_id,
    )


__all__ = [
    "HUB_CLEARANCE_SOURCE",
    "HUB_CLEARANCE_TYPE_KEY",
    "HubClearanceGateManager",
    "release_transfer_allowed",
]
