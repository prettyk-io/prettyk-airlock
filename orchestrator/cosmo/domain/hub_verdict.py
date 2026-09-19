# -*- coding: utf-8 -*-
"""COS-136: Contract A — DTO приёма вердиктов PrettyK Hub в Cosmoport.

Hub (Gatekeeper) — внешняя сторона, Cosmoport — приёмник. Конверт описывает
вердикт Quality Gate по конкретному прогону (``run_id``) плюс крипто-
провенанс: список finding-ов, sha256-якоря evidence и метаданные источника.

Инварианты Contract A (docs/research/2026-09-02-cross-product-contract-bridge.md §4):
  - ``idempotency_key`` — ключ повтора, replay не создаёт дубликат;
  - вердикт принимается только из закрытого набора PASS/WARN/BLOCK;
  - ``evidence_hashes`` — sha256-якоря (hex), не inline-блобы;
  - ``extra="forbid"`` — дрейф контракта ловится на границе, не игнорируется.

Провенанс-хэш (``provenance_hash``) — канонический sha256 конверта; он
запечатывается в ``evidence_ledger.content_hash`` и служит якорем записи.
Вторая ось идемпотентности — ``verdict_hash = sha256(run_id:hub_verdict)``.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

#: Закрытый набор вердиктов Quality Gate.
HubVerdict = Literal["PASS", "WARN", "BLOCK"]

#: sha256 hex, с необязательным ``sha256:``-префиксом.
_SHA256_RE = re.compile(r"^(sha256:)?[0-9a-fA-F]{64}$")


class HubVerdictContractError(ValueError):
    """Нарушение входного контракта Contract A (Hub → Cosmoport)."""


class HubVerdictIngestRequest(BaseModel):
    """Входной конверт вердикта Hub (Contract A).

    ``run_id`` адресует прогон в Cosmoport; ``box_verdict`` — вердикт
    сканера Pure Box, ``hub_verdict`` — итоговый вердикт Gatekeeper.
    """

    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(..., min_length=1, max_length=64)
    box_verdict: str = Field(..., min_length=1, max_length=16)
    hub_verdict: HubVerdict
    finding_ids: list[str] = Field(default_factory=list)
    evidence_hashes: list[str] = Field(default_factory=list)
    provenance_metadata: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str = Field(..., min_length=1, max_length=256)

    @field_validator("run_id", "idempotency_key")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("must not be blank")
        return v

    @field_validator("box_verdict")
    @classmethod
    def _box_verdict_known(cls, v: str) -> str:
        upper = v.upper()
        if upper not in ("PASS", "WARN", "BLOCK"):
            raise ValueError("box_verdict must be one of PASS/WARN/BLOCK")
        return upper

    @field_validator("hub_verdict", mode="before")
    @classmethod
    def _hub_verdict_normalize(cls, v: Any) -> Any:
        return v.upper() if isinstance(v, str) else v

    @field_validator("evidence_hashes")
    @classmethod
    def _hashes_are_sha256(cls, v: list[str]) -> list[str]:
        for h in v:
            if not _SHA256_RE.match(h):
                raise ValueError(f"evidence hash is not sha256: {h!r}")
        return v


class HubVerdictIngestResponse(BaseModel):
    """Ответ на приём вердикта: принят, id записи ledger, статус."""

    model_config = ConfigDict(extra="forbid")

    accepted: bool
    ledger_entry_id: str
    run_id: str
    status: str


def verdict_hash(run_id: str, hub_verdict: str) -> str:
    """sha256(run_id:hub_verdict) — вторая ось идемпотентности."""
    raw = f"{run_id}:{hub_verdict.upper()}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def provenance_hash(payload: dict[str, Any]) -> str:
    """Канонический sha256 конверта (sort_keys, compact) — якорь ledger."""
    canonical = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
