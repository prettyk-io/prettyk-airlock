# -*- coding: utf-8 -*-
"""COS-139: Contract B — Control Plane → PrettyK Hub evaluation.

Cosmoport (Control Plane) инициирует внешнюю QG-оценку релиза в PrettyK Hub
(он же QGFCS): отправляет конверт с точным контекстом релиза/сборки/дайджеста
и обязательным фактом security-исполнения (Studio PASS + Act + Evidence).

Инварианты Contract B
(docs/research/2026-09-02-cross-product-contract-bridge.md §5):

  - ``contract_version`` на каждом конверте (``"1.0"``);
  - оценивается ТОЧНЫЙ контекст release/build/digest, а не «последний по
    проекту»: ``release_id``, ``run_id``, ``build_id``, ``artifact_digest``
    immutable и обязательны;
  - отсутствующий/проваленный обязательный факт исполнения НЕ превращается
    в warning/PASS (``security_execution.verdict`` обязан быть ``PASS``);
  - ``qualifying_context=False`` не может привести к положительному
    clearance для production-профилей — отправка запрещена на границе;
  - ``extra="forbid"`` — дрейф контракта ловится на входе, не игнорируется.

Здесь только DTO/валидация конверта. Транспорт — ``adapters/hub_client.py``,
оркестрация (идемпотентность, аудит) — ``control_plane/hub_dispatcher.py``.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

#: Каноническая версия конверта Contract B.
HUB_EVALUATION_CONTRACT_VERSION = "1.0"

#: Маркер Contract B в ``provenance_json`` ledger-записи (COS-153): колонка
#: ``type`` ограничена frozen-enum ``evidence_type``, поэтому тип строки —
#: ``decision``, а идентичность dispatch-якоря фиксируется в provenance.
HUB_EVALUATION_LEDGER_TYPE = "HUB_EVALUATION_DISPATCH"

#: Зоны доставки Cosmoport (``zpe`` — контур промышленной эксплуатации).
HubEvaluationZone = Literal["zr", "zt", "zpe"]

#: Вердикт security-исполнения (Studio) — закрытый набор, как в Contract A.
HubExecutionVerdict = Literal["PASS", "WARN", "BLOCK"]

#: Зоны, трактуемые как production-контур (положительный clearance требует
#: ``qualifying_context=True``).
PRODUCTION_ZONES = frozenset({"zpe"})

#: Базовые имена production-профилей релиза (до ``@``-версии).
_PRODUCTION_PROFILE_TOKENS = frozenset({"prod", "production"})

#: sha256 hex, с необязательным ``sha256:``-префиксом.
_SHA256_RE = re.compile(r"^(sha256:)?[0-9a-fA-F]{64}$")


class HubEvaluationContextError(ValueError):
    """Нарушение обязательного контекста Contract B (отправка запрещена)."""


def normalize_artifact_digest(raw: str) -> str:
    """Каноническая форма дайджеста артефакта: ``sha256:<64hex>``."""
    return raw if raw.lower().startswith("sha256:") else f"sha256:{raw}"


def is_production_context(release_profile: str, target_zone: str) -> bool:
    """Production-контекст: production-профиль ИЛИ production-зона (``zpe``).

    Профиль сравнивается по базовому токену до ``@`` (например
    ``production@1`` → ``production``); ``ordinary@1`` production-профилем
    не является.
    """
    base = release_profile.strip().lower().split("@", 1)[0]
    if base in _PRODUCTION_PROFILE_TOKENS:
        return True
    return target_zone.strip().lower() in PRODUCTION_ZONES


class HubSecurityExecution(BaseModel):
    """Факт security-исполнения (Studio), приложенный к оценке.

    ``act_ref`` и ``evidence_refs`` — immutable object references
    (``artifact://...``), не inline-блобы и не сырые секреты.
    """

    model_config = ConfigDict(extra="forbid")

    studio_run_id: str = Field(..., min_length=1, max_length=128)
    verdict: HubExecutionVerdict
    act_ref: str = Field(..., min_length=1, max_length=1024)
    evidence_refs: list[str] = Field(..., min_length=1)

    @field_validator("studio_run_id", "act_ref")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("must not be blank")
        return v

    @field_validator("verdict", mode="before")
    @classmethod
    def _verdict_normalize(cls, v: Any) -> Any:
        return v.upper() if isinstance(v, str) else v

    @field_validator("evidence_refs")
    @classmethod
    def _refs_not_blank(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("evidence_refs must not be empty")
        for ref in v:
            if not ref or not ref.strip():
                raise ValueError("evidence ref must not be blank")
        return v


class HubEvaluationRequest(BaseModel):
    """Конверт запроса оценки релиза (Contract B, Control Plane → Hub)."""

    model_config = ConfigDict(extra="forbid")

    contract_version: Literal["1.0"] = HUB_EVALUATION_CONTRACT_VERSION
    request_id: str = Field(..., min_length=1, max_length=128)
    evaluation_id: str = Field(..., min_length=1, max_length=128)
    project_id: str = Field(..., min_length=1, max_length=128)
    application_ids: list[str] = Field(..., min_length=1)
    release_id: str = Field(..., min_length=1, max_length=64)
    run_id: str = Field(..., min_length=1, max_length=64)
    build_id: str = Field(..., min_length=1, max_length=128)
    artifact_digest: str = Field(..., min_length=1)
    release_profile: str = Field(..., min_length=1, max_length=64)
    target_zone: HubEvaluationZone
    qualifying_context: bool
    security_execution: HubSecurityExecution

    @field_validator(
        "request_id", "evaluation_id", "project_id", "release_id",
        "run_id", "build_id", "release_profile",
    )
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("must not be blank")
        return v

    @field_validator("application_ids")
    @classmethod
    def _apps_not_blank(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("application_ids must not be empty")
        for app in v:
            if not app or not app.strip():
                raise ValueError("application id must not be blank")
        return v

    @field_validator("artifact_digest")
    @classmethod
    def _digest_is_sha256(cls, v: str) -> str:
        if not _SHA256_RE.match(v):
            raise ValueError("artifact_digest must be sha256 hex")
        return normalize_artifact_digest(v)

    @field_validator("target_zone", mode="before")
    @classmethod
    def _zone_normalize(cls, v: Any) -> Any:
        return v.strip().lower() if isinstance(v, str) else v

    def enforce_required_context(self) -> None:
        """Проверить обязательный контекст; иначе — отказ отправки.

        Правила Contract B, которые нельзя «смягчить» до warning:
          - ``security_execution.verdict`` обязан быть ``PASS``
            (missing/failed факт ≠ PASS);
          - ``qualifying_context=True`` обязателен для production-профилей
            (``zpe`` или ``production``-профиль).
        """
        if self.security_execution.verdict != "PASS":
            raise HubEvaluationContextError(
                "security_execution.verdict must be PASS "
                f"(got {self.security_execution.verdict})"
            )
        if not self.qualifying_context and is_production_context(
            self.release_profile, self.target_zone,
        ):
            raise HubEvaluationContextError(
                "qualifying_context=False is not allowed for production "
                f"profile {self.release_profile!r} (zone {self.target_zone!r})"
            )


class HubEvaluationDispatchResponse(BaseModel):
    """Результат отправки/чтения оценки: факт, статус, время отправки."""

    model_config = ConfigDict(extra="forbid")

    dispatched: bool
    request_id: str
    evaluation_id: str
    status: str
    dispatched_at: str


def evaluation_identity(request: HubEvaluationRequest) -> dict[str, str]:
    """Immutable context identity оценки — то, что нельзя подменять повтором.

    Оценка привязана к точной четвёрке release/run/build/digest; повтор с
    тем же ``evaluation_id``, но другой identity — дрейф контракта.
    """
    return {
        "release_id": request.release_id,
        "run_id": request.run_id,
        "build_id": request.build_id,
        "artifact_digest": request.artifact_digest,
    }


def evaluation_dispatch_hash(payload: dict[str, Any]) -> str:
    """Канонический SHA256 dispatch-записи (sort_keys, compact) — якорь ledger."""
    canonical = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
