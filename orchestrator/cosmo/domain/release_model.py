"""
COS-036/COS-054: Pydantic модель Release (Космопорт).

Release — контролируемый выпуск после прохождения Gate'ов.
Связывает один или несколько Run в релизный пакет для деплоя.
COS-054: Transfer — межзонный трансфер ЗР→ЗТ→ЗПЭ с аудит-логом.
"""
from __future__ import annotations

import datetime
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

StrictModel = ConfigDict(extra="ignore")

ReleaseStatus = Literal["draft", "pending_review", "approved", "rejected", "deploying", "deployed", "rollback"]

ReleaseTrigger = Literal["scheduled", "pre_release", "emergency", "manual"]

# COS-054: зоны трансфера (строгий порядок)
ReleaseZone = Literal["zr", "zt", "zpe"]

# Строгий порядок зон
_ZONE_ORDER = ["zr", "zt", "zpe"]


def next_zone(current: ReleaseZone) -> ReleaseZone | None:
    """Следующая зона в порядке ЗР→ЗТ→ЗПЭ. None если на ЗПЭ."""
    try:
        idx = _ZONE_ORDER.index(current)
        if idx + 1 < len(_ZONE_ORDER):
            return _ZONE_ORDER[idx + 1]  # type: ignore
    except ValueError:
        pass
    return None


class ReleaseApproval(BaseModel):
    """Решение по release: кто, когда, вердикт."""
    model_config = StrictModel

    decided_by: str = Field(..., min_length=1, description="ID оператора, принявшего решение")
    decision: Literal["approved", "rejected"] = Field(..., description="Вердикт")
    comment: str = Field(default="", description="Комментарий к решению")
    decided_at: datetime.datetime = Field(
        default_factory=datetime.datetime.utcnow,
        description="Время решения",
    )
    signature: str | None = Field(
        default=None,
        description="Цифровая подпись решения",
    )


class TransferRecord(BaseModel):
    """COS-054: immutable запись о межзонном трансфере в аудит-логе."""
    model_config = StrictModel

    from_zone: ReleaseZone = Field(..., description="Исходная зона")
    to_zone: ReleaseZone = Field(..., description="Целевая зона")
    initiated_by: str = Field(..., min_length=1, description="ID оператора, инициировавшего трансфер")
    gate_check_passed: bool = Field(..., description="Все gates пройдены перед трансфером?")
    transferred_at: datetime.datetime = Field(
        default_factory=datetime.datetime.utcnow,
        description="Время трансфера",
    )
    comment: str = Field(default="", description="Комментарий к трансферу")


class Release(BaseModel):
    """Релизный пакет — связка прошедших gate прогонов."""
    model_config = StrictModel

    id: str = Field(..., min_length=1, description="Уникальный ID релиза")
    domain_id: str = Field(..., min_length=1, description="ID домена")
    plan_id: str = Field(..., min_length=1, description="ID плана")
    run_ids: list[str] = Field(
        default_factory=list,
        min_length=1,
        description="ID прогонов, входящих в релиз",
    )
    trigger: ReleaseTrigger = Field(
        default="manual",
        description="Триггер релиза",
    )
    status: ReleaseStatus = Field(
        default="draft",
        description="Статус релиза",
    )
    changelog: str = Field(
        default="",
        description="Описание изменений (commit messages, summary)",
    )
    version: str = Field(
        default="",
        description="Версия релиза (semver или метка)",
    )
    artifacts: list[str] = Field(
        default_factory=list,
        description="Ссылки на артефакты (SBOM, SARIF, image digests)",
    )
    approvals: list[ReleaseApproval] = Field(
        default_factory=list,
        description="История решений по релизу",
    )
    # COS-054: межзонный трансфер
    current_zone: ReleaseZone = Field(
        default="zr",
        description="Текущая зона релиза (ЗР → ЗТ → ЗПЭ)",
    )
    transfer_history: list[TransferRecord] = Field(
        default_factory=list,
        description="История межзонных трансферов (COS-054 audit log)",
    )

    @property
    def is_approved(self) -> bool:
        return self.status == "approved"

    @property
    def is_rejected(self) -> bool:
        return self.status == "rejected"

    @property
    def can_deploy(self) -> bool:
        return self.status == "approved"

    @property
    def can_transfer(self) -> bool:
        """COS-054: трансфер разрешён только из deployed."""
        return self.status == "deployed"

    def next_zone(self) -> ReleaseZone | None:
        """Следующая зона в порядке ЗР→ЗТ→ЗПЭ."""
        return next_zone(self.current_zone)

    @property
    def is_rejected(self) -> bool:
        return self.status == "rejected"

    @property
    def can_deploy(self) -> bool:
        return self.status == "approved"