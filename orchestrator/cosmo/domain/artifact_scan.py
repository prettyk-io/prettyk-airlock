# -*- coding: utf-8 -*-
"""COS-168: PK-C-003.6 / DOCKER_AUDIT — Trivy container scan + gate (DTO).

``DOCKER_AUDIT`` профиль требует между SBOM и deploy шаг **trivy** с
``gates_required=True``. Trivy сканирует образ и отдаёт отчёт уязвимостей с
разбивкой по severity; gate-вердикт считается по канону COS-138 Grype-gate:

  - critical считается честно: ``max(заявленный critical_count, число
    findings severity='critical')`` — отчёт не может «занизить» блокер;
  - ``critical > 0`` → ``gate_verdict=BLOCK`` / ``clearance=DENIED``,
    иначе ``PASS`` / ``CLEARED``;
  - digest-сверка: ``artifact_digest`` конверта обязан совпасть с
    ``scan.artifact_digest`` и с digest'ом durable-образа (``ArtifactRecord``).

Инварианты (``extra="ignore"`` на вложенных отчётах — как COS-138: trivy —
внешний инструмент, его формат богаче контракта; ``forbid`` ломал бы приём):
  - ``artifact_digest`` — sha256 hex (опционально ``sha256:``-префикс);
  - ``trivy_scan_content_hash`` — канонический sha256 содержимого отчёта,
    якорь записи в evidence ledger.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from orchestrator.cosmo.domain.sbom_scan import is_sha256, normalize_digest

#: Закрытый набор severity (нормализуем trivy → нижний регистр).
TrivySeverity = Literal["critical", "high", "medium", "low", "negligible"]

#: Итоговый вердикт trivy-gate.
TrivyGateVerdict = Literal["PASS", "BLOCK"]

#: Клиренс образа по итогам скана.
TrivyClearance = Literal["CLEARED", "DENIED"]

_TRIVY_SEVERITIES = ("critical", "high", "medium", "low", "negligible")


class TrivyFinding(BaseModel):
    """Одна уязвимость из trivy-отчёта."""

    model_config = ConfigDict(extra="ignore")

    id: str = Field(..., min_length=1)
    severity: TrivySeverity
    package_name: str = Field(..., min_length=1)
    installed_version: str = ""
    fixed_version: str | None = None


class TrivyScanReport(BaseModel):
    """Trivy scan: уязвимости образа с разбивкой по severity."""

    model_config = ConfigDict(extra="ignore")

    scanner_version: str = ""
    artifact_digest: str
    critical_count: int = Field(default=0, ge=0)
    high_count: int = Field(default=0, ge=0)
    medium_count: int = Field(default=0, ge=0)
    low_count: int = Field(default=0, ge=0)
    findings: list[TrivyFinding] = Field(default_factory=list)

    @field_validator("artifact_digest")
    @classmethod
    def _digest_is_sha256(cls, v: str) -> str:
        if not is_sha256(v):
            raise ValueError(f"artifact_digest is not sha256: {v!r}")
        return v


class TrivyGateAttachRequest(BaseModel):
    """Конверт привязки trivy-отчёта к образу релиза.

    ``artifact_digest`` — digest образа, под который аттестуется сканирование;
    обязан совпасть с ``scan.artifact_digest`` и с digest'ом одного из
    durable ``ArtifactRecord`` прогонов релиза (рассинхрон → 422).
    """

    model_config = ConfigDict(extra="ignore")

    artifact_digest: str
    scan: TrivyScanReport

    @field_validator("artifact_digest")
    @classmethod
    def _digest_is_sha256(cls, v: str) -> str:
        if not is_sha256(v):
            raise ValueError(f"artifact_digest is not sha256: {v!r}")
        return v


class TrivyGateAttestationResponse(BaseModel):
    """Результат аттестации trivy-gate (ответ attach/read)."""

    model_config = ConfigDict(extra="forbid")

    accepted: bool
    release_id: str
    artifact_digest: str
    scan_digest: str
    clearance: TrivyClearance
    gate_verdict: TrivyGateVerdict


def trivy_scan_content_hash(scan: TrivyScanReport) -> str:
    """Канонический sha256 содержимого trivy-отчёта (sort_keys, compact)."""
    payload: dict[str, Any] = scan.model_dump(mode="json")
    canonical = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def observed_severity_count(scan: TrivyScanReport, severity: str) -> int:
    """Число findings заданного severity (независимо от заявленного числа)."""
    return sum(1 for f in scan.findings if f.severity == severity)


def resolve_normalized_digests(
    artifact_digest: str, scan_digest: str,
) -> tuple[str, str]:
    """Привести оба digest'а к канонической форме (lowercase, без префикса)."""
    return normalize_digest(artifact_digest), normalize_digest(scan_digest)