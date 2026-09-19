# -*- coding: utf-8 -*-
"""COS-138: PK-C-003.6 — DTO SBOM (Syft) и Grype-скана релизного бандла.

Cosmoport принимает от supply-chain контура два внешних отчёта:

  - **Syft SBOM** — инвентарь пакетов артефакта (SPDX-JSON или CycloneDX-JSON);
  - **Grype scan** — уязвимости найденных пакетов с разбивкой по severity.

Оба отчёта обязаны адресовать один и тот же артефакт (``artifact_digest``):
рассинхрон digest'ов означает, что SBOM и скан описывают разные образы, —
такой конверт отклоняется (422), а не «доверяется на слово».

Инварианты:
  - ``artifact_digest`` — sha256 hex (опционально с ``sha256:``-префиксом);
  - ``extra="ignore"`` на вложенных отчётах: Syft/Grype — внешние инструменты,
    их формат богаче нашего контракта; жёсткий ``forbid`` сломал бы приём
    легитимных отчётов, а не дрейф контракта;
  - ``sbom_content_hash`` — канонический sha256 содержимого SBOM
    (sort_keys, compact), якорь записи в evidence ledger.

Гейт-вердикт (``gate_verdict``) и клиренс (``clearance``) — производные от
числа critical-уязвимостей; см. ``ledger/sbom_gate.py``.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

#: Формат SBOM, который принимает Cosmoport.
SbomFormat = Literal["spdx-json", "cyclonedx-json"]

#: Закрытый набор severity Grype.
GrypeSeverity = Literal["critical", "high", "medium", "low", "negligible"]

#: Итоговый вердикт supply-chain гейта.
SbomGateVerdict = Literal["PASS", "BLOCK"]

#: Клиренс релиза по итогам аттестации.
SbomClearance = Literal["CLEARED", "DENIED"]

#: sha256 hex, с необязательным ``sha256:``-префиксом.
_SHA256_RE = re.compile(r"^(sha256:)?[0-9a-fA-F]{64}$")


class SbomContractError(ValueError):
    """Нарушение входного контракта SBOM/Grype (Cosmoport)."""


def normalize_digest(digest: str) -> str:
    """Привести digest к канонической форме: lowercase hex без префикса."""
    return digest.split(":", 1)[1].lower() if ":" in digest else digest.lower()


def is_sha256(digest: str) -> bool:
    """Является ли строка sha256-хэшем (с префиксом или без)."""
    return bool(_SHA256_RE.match(digest or ""))


class SbomPackage(BaseModel):
    """Пакет из SBOM Syft."""

    model_config = ConfigDict(extra="ignore")

    name: str = Field(..., min_length=1)
    version: str = ""
    type: str = ""
    purl: str | None = None
    license: str | None = None

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("package name must not be blank")
        return v


class SbomReport(BaseModel):
    """Syft SBOM: инвентарь пакетов артефакта."""

    model_config = ConfigDict(extra="ignore")

    format: SbomFormat
    syft_version: str = ""
    artifact_digest: str
    packages_count: int = Field(default=0, ge=0)
    packages: list[SbomPackage] = Field(default_factory=list)

    @field_validator("artifact_digest")
    @classmethod
    def _digest_is_sha256(cls, v: str) -> str:
        if not is_sha256(v):
            raise ValueError(f"artifact_digest is not sha256: {v!r}")
        return v


class GrypeFinding(BaseModel):
    """Найденная Grype уязвимость."""

    model_config = ConfigDict(extra="ignore")

    id: str = Field(..., min_length=1)
    severity: GrypeSeverity
    package_name: str = Field(..., min_length=1)
    installed_version: str = ""
    fixed_version: str | None = None


class GrypeScanReport(BaseModel):
    """Grype scan: уязвимости пакетов артефакта с разбивкой по severity."""

    model_config = ConfigDict(extra="ignore")

    scanner_version: str = ""
    artifact_digest: str
    critical_count: int = Field(default=0, ge=0)
    high_count: int = Field(default=0, ge=0)
    medium_count: int = Field(default=0, ge=0)
    low_count: int = Field(default=0, ge=0)
    findings: list[GrypeFinding] = Field(default_factory=list)

    @field_validator("artifact_digest")
    @classmethod
    def _digest_is_sha256(cls, v: str) -> str:
        if not is_sha256(v):
            raise ValueError(f"artifact_digest is not sha256: {v!r}")
        return v


class ReleaseSbomAttachRequest(BaseModel):
    """Конверт привязки SBOM + Grype к релизному бандлу.

    ``artifact_digest`` — digest артефакта, под который аттестуется релиз;
    он обязан совпасть с digest'ами обоих отчётов (и, если релиз фиксирует
    digest своих артефактов, — с ним).
    """

    model_config = ConfigDict(extra="ignore")

    sbom: SbomReport
    vulnerabilities: GrypeScanReport
    artifact_digest: str

    @field_validator("artifact_digest")
    @classmethod
    def _digest_is_sha256(cls, v: str) -> str:
        if not is_sha256(v):
            raise ValueError(f"artifact_digest is not sha256: {v!r}")
        return v


class ReleaseSbomAttestationResponse(BaseModel):
    """Результат аттестации SBOM релиза (ответ attach/read)."""

    model_config = ConfigDict(extra="forbid")

    accepted: bool
    release_id: str
    artifact_digest: str
    sbom_digest: str
    clearance: SbomClearance
    gate_verdict: SbomGateVerdict


def sbom_content_hash(sbom: SbomReport) -> str:
    """Канонический sha256 содержимого SBOM (sort_keys, compact) — якорь ledger."""
    payload: dict[str, Any] = sbom.model_dump(mode="json")
    canonical = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
