# -*- coding: utf-8 -*-
"""COS-145/COS-146: авторизация межзонного трансфера и идемпотентный replay.

Межзонный трансфер (ЗР → ЗТ → ЗПЭ) — необратимая операция с высоким риском:
после неё релиз попадает в контур, где откат стоит дорого. Поэтому решение
о допуске собирается из **двух независимых крипто-свидетельств**:

  1. **Quality Gate Hub clearance** (Contract C, COS-141) — вердикт внешнего
     контура оценки качества: ``PASS_GRANTED`` + ``ok_to_transfer`` +
     исполнение ``PASS``/``WARN``;
  2. **SBOM/Grype attestation** (PK-C-003.6, COS-138) — supply-chain
     вердикт: ``PASS`` (то есть ``critical_count == 0``).

Отсутствие любого из свидетельств — это **отказ**, а не «нет данных, значит
не блокируем»: авторизация fail-closed. Причина отказа всегда перечисляется
в ``reasons`` — решение должно быть объяснимым, а не молчаливым.

``TransferTransition`` — вердикт CAS-проверки перехода (COS-146):
``PROCEED`` (переход допустим), ``REPLAY`` (переход уже выполнен — отдаём
идемпотентный ответ) и ``CONFLICT`` (клиент ожидал другую текущую зону —
оптимистичная блокировка не сошлась).
"""
from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

#: Action в audit trail для решения об авторизации трансфера (COS-145).
TRANSFER_AUTHORIZATION_AUDIT_ACTION = "release_transfer_authorization"

#: Action в audit trail для попытки обхода авторизации (COS-145).
TRANSFER_BYPASS_AUDIT_ACTION = "BYPASS_ATTEMPT"

#: Resource type в audit trail.
TRANSFER_AUTHORIZATION_RESOURCE_TYPE = "release"

#: Клиренс Quality Gate, разрешающий трансфер (COS-141).
CLEARANCE_AUTHORIZED_STATUS = "PASS_GRANTED"

#: Вердикт SBOM-аттестации, разрешающий трансфер (``critical_count == 0``).
SBOM_AUTHORIZED_VERDICT = "PASS"

#: Маркер отсутствия свидетельства (клиренс/SBOM не поступали).
STATUS_MISSING = "MISSING"

#: Маркер сбоя чтения свидетельства (fail-closed).
STATUS_CHECK_FAILED = "CHECK_FAILED"

#: Статус идемпотентного повтора уже выполненного перехода (COS-146).
TRANSFER_REPLAY_STATUS = "duplicate_success"


class TransferTransition(str, Enum):
    """COS-146: вердикт CAS-проверки перехода между зонами."""

    #: Переход не выполнялся — можно продвигать.
    PROCEED = "proceed"
    #: Переход уже зафиксирован — идемпотентный ответ без записи и уведомлений.
    REPLAY = "duplicate_success"
    #: Ожидаемое клиентом состояние не совпало с фактическим (гонка/устаревший клиент).
    CONFLICT = "conflict"


class TransferAuthorizationDecision(BaseModel):
    """COS-145: решение о допустимости межзонного трансфера (fail-closed)."""

    model_config = ConfigDict(extra="forbid")

    authorized: bool = Field(..., description="Разрешён ли трансфер")
    release_id: str = Field(..., min_length=1)
    target_zone: str = Field(..., min_length=1, description="Зона, в которую направлен трансфер")
    clearance_status: str = Field(
        ..., description="Статус клиренса Quality Gate Hub (PASS_GRANTED | BLOCKED | REJECTED | MISSING | CHECK_FAILED)",
    )
    sbom_attestation_status: str = Field(
        ..., description="Вердикт SBOM-аттестации (PASS | BLOCK | MISSING | CHECK_FAILED)",
    )
    reasons: list[str] = Field(
        default_factory=list, description="Причины отказа (пусто — трансфер разрешён)",
    )
    checked_at: str = Field(..., min_length=1, description="ISO-8601 время решения")

    @field_validator(
        "release_id", "target_zone", "clearance_status",
        "sbom_attestation_status", "checked_at",
    )
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("field must not be blank")
        return value


class TransferReplayResponse(BaseModel):
    """COS-146: идемпотентный ответ на повтор уже выполненного перехода.

    Возвращается вместо повторной записи в ``transfer_history``: переход
    уже зафиксирован, дублей в истории нет, уведомления не переэмитятся.
    """

    model_config = ConfigDict(extra="forbid")

    status: Literal["duplicate_success"] = TRANSFER_REPLAY_STATUS
    release_id: str = Field(..., min_length=1)
    current_zone: str = Field(..., min_length=1)
    transfer_history_count: int = Field(..., ge=0)

    @field_validator("release_id", "current_zone")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("field must not be blank")
        return value


__all__ = [
    "CLEARANCE_AUTHORIZED_STATUS",
    "SBOM_AUTHORIZED_VERDICT",
    "STATUS_CHECK_FAILED",
    "STATUS_MISSING",
    "TRANSFER_AUTHORIZATION_AUDIT_ACTION",
    "TRANSFER_AUTHORIZATION_RESOURCE_TYPE",
    "TRANSFER_BYPASS_AUDIT_ACTION",
    "TRANSFER_REPLAY_STATUS",
    "TransferAuthorizationDecision",
    "TransferReplayResponse",
    "TransferTransition",
]
