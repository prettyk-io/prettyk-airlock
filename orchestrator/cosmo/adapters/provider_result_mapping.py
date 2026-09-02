# -*- coding: utf-8 -*-
"""
COS-060: Provider operation result → transfer kernel normalization.

Мост между capability-контрактом провайдеров (COS-052 OpResult) и принятыми
моделями transfer kernel (COS-050/COS-053). Kernel модели НЕ меняются —
только читаются enums.

Семантика маппинга (честная):
  OK                 → DISPATCHED (провайдер принял артефакт; RECEIVED/LANDED —
                       про target landing, за пределами provider op);
  TRANSIENT_FAILURE  → RETRY_SCHEDULED + TRANSPORT_FAILURE (retryable);
  VALIDATION_FAILURE → FAILED + VALIDATION_FAILURE;
  AUTH_FAILURE       → FAILED + TRANSPORT_FAILURE (доступ/канал, не payload);
  QUOTA_FAILURE      → FAILED + CAPACITY_QUOTA_FAILURE;
  CONFLICT           → FAILED + IDEMPOTENCY_CONFLICT;
  NOT_FOUND          → FAILED + PACKAGE_NOT_READY (источник не готов/отсутствует);
  UNSUPPORTED        → FAILED + failure_class=None (kernel не имеет класса
                       UNSUPPORTED — не искажаем семантику kernel, причина в detail);
  ERROR              → FAILED + TRANSPORT_FAILURE + detail (не маскировать).

Known gap (зафиксирован в capability-evidence doc): kernel не имеет
класса UNSUPPORTED/CONFIGURATION_FAILURE — пока failure_class=None + detail.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from orchestrator.cosmo.adapters.provider_capability import OpResult, OpStatus
from orchestrator.cosmo.transfer.contract import TransferFailureClass, TransferItemStatus


@dataclass
class TransferOpOutcome:
    """Нормализованный исход provider-операции для transfer item lifecycle."""
    item_status: TransferItemStatus
    failure_class: Optional[TransferFailureClass]
    detail: str = ""
    digest: Optional[str] = None          # server digest без подмены
    location_ref: Optional[str] = None    # provider-specific ref (НЕ canonical)

    @property
    def ok(self) -> bool:
        return self.item_status == TransferItemStatus.DISPATCHED

    @property
    def retryable(self) -> bool:
        return self.item_status == TransferItemStatus.RETRY_SCHEDULED


_MAPPING: dict[OpStatus, tuple[TransferItemStatus, Optional[TransferFailureClass]]] = {
    OpStatus.OK: (TransferItemStatus.DISPATCHED, None),
    OpStatus.TRANSIENT_FAILURE: (TransferItemStatus.RETRY_SCHEDULED, TransferFailureClass.TRANSPORT_FAILURE),
    OpStatus.VALIDATION_FAILURE: (TransferItemStatus.FAILED, TransferFailureClass.VALIDATION_FAILURE),
    OpStatus.AUTH_FAILURE: (TransferItemStatus.FAILED, TransferFailureClass.TRANSPORT_FAILURE),
    OpStatus.QUOTA_FAILURE: (TransferItemStatus.FAILED, TransferFailureClass.CAPACITY_QUOTA_FAILURE),
    OpStatus.CONFLICT: (TransferItemStatus.FAILED, TransferFailureClass.IDEMPOTENCY_CONFLICT),
    OpStatus.NOT_FOUND: (TransferItemStatus.FAILED, TransferFailureClass.PACKAGE_NOT_READY),
    OpStatus.UNSUPPORTED: (TransferItemStatus.FAILED, None),
    OpStatus.ERROR: (TransferItemStatus.FAILED, TransferFailureClass.TRANSPORT_FAILURE),
}


def to_transfer_outcome(result: OpResult) -> TransferOpOutcome:
    """Нормализовать OpResult для downstream transfer kernel.

    Обрабатывает ВСЕ OpStatus исчерпывающе: неизвестный статус (будущие
    версии контракта) → FAILED + TRANSPORT_FAILURE + detail — не падаем
    и не маскируем.
    """
    try:
        item_status, failure_class = _MAPPING[result.status]
    except KeyError:
        return TransferOpOutcome(
            item_status=TransferItemStatus.FAILED,
            failure_class=TransferFailureClass.TRANSPORT_FAILURE,
            detail=f"unmapped provider op status: {result.status!r}",
        )

    detail = result.detail
    if result.status == OpStatus.UNSUPPORTED:
        detail = (detail or "provider capability unsupported") + \
                 " [no kernel failure class for UNSUPPORTED — see COS-060 evidence doc]"

    return TransferOpOutcome(
        item_status=item_status,
        failure_class=failure_class,
        detail=detail,
        digest=result.digest,
        location_ref=result.location_ref,
    )
