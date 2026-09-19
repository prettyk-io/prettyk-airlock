# -*- coding: utf-8 -*-
"""COS-141: Contract C — PrettyK Hub Quality Gate clearance (QGFCS → Control Plane).

Hub (QGFCS) возвращает Cosmoport вердикт внешней оценки релиза: клиренс
Quality Gate, готовность к трансферу и ссылки на объяснение/улики. Конверт
описывает ТОЧНЫЙ контекст (release/run/evaluation), чтобы решение нельзя было
применить к другому релизу или перезаписать «плавающим» результатом.

Инварианты Contract C
(docs/research/2026-09-02-cross-product-contract-bridge.md §6):

  - ``contract_version`` на каждом конверте (``"1.0"``);
  - ``evaluation_id`` + ``release_id`` — ключ дедупликации; ``run_id`` и
    ``policy_version`` — неизменяемый контекст (дрейф = конфликт, не тихая
    перезапись);
  - ``qualifying_context=false`` НИКОГДА не даёт ``PASS_GRANTED``/
    ``ok_to_transfer=true`` — такой конверт отвергается как противоречивый;
  - трансфер авторизуется СТРОГО при ``qg_clearance == "PASS_GRANTED"`` И
    ``ok_to_transfer is True`` И ``security_execution_verdict`` in (PASS, WARN);
    любой иной исход — отказ (fail-closed);
  - ``extra="forbid"`` — дрейф контракта ловится на входе.

Здесь DTO + чистая логика авторизации/хэша. Запись в ledger и дедупликация —
``ledger/hub_clearance_gate.py``; HTTP-поверхность — ``api/routes/hub.py``.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

#: Каноническая версия конверта Contract C.
HUB_CLEARANCE_CONTRACT_VERSION = "1.0"

#: Маркер типа записи ledger (в ``provenance_json``): ``type`` колонки
#: ограничен frozen-enum ``evidence_type``, поэтому сам маркер живёт в
#: provenance, а строка пишется как ``decision``.
HUB_CLEARANCE_LEDGER_TYPE = "QG_CLEARANCE"

#: Закрытый набор клиренсов Quality Gate.
ClearanceStatus = Literal["PASS_GRANTED", "BLOCKED", "REJECTED"]

#: Закрытый набор вердиктов security-исполнения / оценки.
SecurityVerdict = Literal["PASS", "WARN", "FAIL", "ERROR"]

#: Вердикты исполнения, при которых трансфер допустим (политика Contract C).
TRANSFER_SAFE_EXECUTION_VERDICTS = frozenset({"PASS", "WARN"})

#: Итог приёма конверта.
ClearanceIngestStatus = Literal["accepted", "duplicate", "rejected"]


class HubClearanceContextError(ValueError):
    """Противоречивый конверт Contract C (нарушен инвариант клиренса)."""


class HubClearanceConflictError(ValueError):
    """Дрейф неизменяемого контекста по ключу ``(evaluation_id, release_id)``."""


class HubClearanceIngestRequest(BaseModel):
    """Конверт клиренса Quality Gate (Contract C, Hub → Control Plane)."""

    model_config = ConfigDict(extra="forbid")

    contract_version: Literal["1.0"] = HUB_CLEARANCE_CONTRACT_VERSION
    evaluation_id: str = Field(..., min_length=1, max_length=128)
    release_id: str = Field(..., min_length=1, max_length=64)
    run_id: str = Field(..., min_length=1, max_length=64)
    evaluated_at: str = Field(..., min_length=1, max_length=64)
    policy_version: str = Field(..., min_length=1, max_length=128)
    security_execution_verdict: SecurityVerdict
    act_ref: str = Field(..., min_length=1, max_length=1024)
    qg_clearance: ClearanceStatus
    verdict: SecurityVerdict
    ready_for_transfer: bool
    qualifying_context: bool
    ok_to_transfer: bool
    evidence_refs: list[str] = Field(default_factory=list)
    explanation_ref: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator(
        "evaluation_id", "release_id", "run_id", "evaluated_at",
        "policy_version", "act_ref",
    )
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("must not be blank")
        return v

    @field_validator("evidence_refs")
    @classmethod
    def _refs_not_blank(cls, v: list[str]) -> list[str]:
        for ref in v:
            if not ref or not ref.strip():
                raise ValueError("evidence ref must not be blank")
        return v

    def violates_qualifying_context(self) -> bool:
        """``qualifying_context=false`` не может дать положительный клиренс."""
        if self.qualifying_context:
            return False
        return self.qg_clearance == "PASS_GRANTED" or self.ok_to_transfer

    def clearance_identity(self) -> dict[str, str]:
        """Неизменяемый контекст клиренса (дрейф = конфликт)."""
        return {
            "run_id": self.run_id,
            "policy_version": self.policy_version,
        }

    def clearance_payload(self) -> dict[str, Any]:
        """Канонический payload клиренса (то, что подписывается хэшем)."""
        return {
            "contract_version": self.contract_version,
            "evaluation_id": self.evaluation_id,
            "release_id": self.release_id,
            "run_id": self.run_id,
            "evaluated_at": self.evaluated_at,
            "policy_version": self.policy_version,
            "security_execution_verdict": self.security_execution_verdict,
            "act_ref": self.act_ref,
            "qg_clearance": self.qg_clearance,
            "verdict": self.verdict,
            "ready_for_transfer": self.ready_for_transfer,
            "qualifying_context": self.qualifying_context,
            "ok_to_transfer": self.ok_to_transfer,
            "evidence_refs": list(self.evidence_refs),
            "explanation_ref": self.explanation_ref,
            "metadata": dict(self.metadata),
        }


class HubClearanceIngestResponse(BaseModel):
    """Ответ на приём клиренса: итог, статус, авторизация трансфера, якорь."""

    model_config = ConfigDict(extra="forbid")

    status: ClearanceIngestStatus
    evaluation_id: str
    release_id: str
    clearance_status: ClearanceStatus
    transfer_allowed: bool
    ledger_entry_id: str
    timestamp: str


def compute_transfer_allowed(
    *,
    qg_clearance: str,
    ok_to_transfer: bool,
    security_execution_verdict: str,
) -> bool:
    """Правило авторизации трансфера (fail-closed, Contract C §6).

    ``True`` строго при совпадении всех трёх условий:
    ``qg_clearance == "PASS_GRANTED"`` И ``ok_to_transfer is True`` И
    ``security_execution_verdict in ("PASS", "WARN")``.
    """
    return (
        qg_clearance == "PASS_GRANTED"
        and ok_to_transfer is True
        and security_execution_verdict in TRANSFER_SAFE_EXECUTION_VERDICTS
    )


def clearance_hash(payload: dict[str, Any]) -> str:
    """Канонический SHA256 клиренса (sort_keys, compact) — якорь ledger."""
    canonical = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


__all__ = [
    "ClearanceIngestStatus",
    "ClearanceStatus",
    "HUB_CLEARANCE_CONTRACT_VERSION",
    "HUB_CLEARANCE_LEDGER_TYPE",
    "HubClearanceConflictError",
    "HubClearanceContextError",
    "HubClearanceIngestRequest",
    "HubClearanceIngestResponse",
    "SecurityVerdict",
    "TRANSFER_SAFE_EXECUTION_VERDICTS",
    "clearance_hash",
    "compute_transfer_allowed",
]
