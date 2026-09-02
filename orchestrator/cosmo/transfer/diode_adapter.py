# -*- coding: utf-8 -*-
"""COS-054: Vendor-neutral Diode Adapter — chunked delivery over a one-way link.

Абстракция над физическим one-way каналом (InfoDiode, data diode, controlled
file drop). Никакого vendor-протокола внутри адаптера — физическое устройство
подключается реализацией TransportLink.

Модель:
  - dispatch() отправляет immutable PackageRevision чанками.
  - checkpoint после каждого чанка => resume после обрыва.
  - strict one-way mode: ACK не существует, статус = "assumed in flight".
  - ack_channel mode: отдельный (не diode) control-канал для статусов.
  - Retryable failure сохраняет ту же revision; terminal failure — нет.

Инварианты:
  - Один dispatch = одна immutable revision (не мутируется при retry).
  - Chunk sequence детерминирован (index → offset → sha256).
  - Strict mode никогда не возвращает DELIVERED — только ASSUMED_DELIVERED.
  - Terminal failure закрывает delivery: повторный dispatch по той же
    revision поднимает DeliveryClosedError (требуется новая revision).
  - Retry сохраняет identity: тот же delivery_id, та же revision_key.

Transition matrix (COS-065):
  PENDING           → IN_FLIGHT           dispatch начал отправку
  IN_FLIGHT         → CHECKPOINTED        после каждого write_chunk
  CHECKPOINTED      → ASSUMED_DELIVERED   strict: все чанки + flush
  CHECKPOINTED      → DELIVERED           ack_channel: verify + ACK ok
  CHECKPOINTED      → FAILED_RETRYABLE    transport failure / нет ACK
  CHECKPOINTED      → FAILED_TERMINAL     target reject / pre-send checksum
  FAILED_RETRYABLE  → CHECKPOINTED        retry-resume с chunks_sent
  FAILED_RETRYABLE  → FAILED_TERMINAL     max_attempts исчерпан (retry())
  FAILED_TERMINAL   → (закрыто)           только новая revision
  DELIVERED         → (terminal)          повторный poll не меняет состояние
  ASSUMED_DELIVERED → ASSUMED_DELIVERED   re-dispatch идемпотентен
                      (не terminal: device-side reconciliation
                       может упасть позже)

Delivery profiles:
  strict_one_way — физически однонаправленный канал, обратной связи нет.
    Финальное состояние ASSUMED_DELIVERED, никогда DELIVERED. ack_channel
    игнорируется, даже если передан. Целостность гарантирует target-side
    import (OfflineImporter verify-then-promote), не транспорт.
  ack_channel — diode для данных + отдельный control-канал для статусов.
    DELIVERED только при явном ACK (ok=true). Явный NACK (ok=false) —
    terminal LANDING_REJECTED (новая revision). Отсутствие ACK в окне —
    retryable, тот же revision.
"""
from __future__ import annotations

import hashlib
import time
from enum import Enum
from typing import Any, Optional, Protocol

from pydantic import BaseModel, ConfigDict, Field

from orchestrator.cosmo.transfer.contract import (
    PackageRevision,
    TransferFailureClass,
    TransportProfile,
    TransferItem,
)
from orchestrator.cosmo.transfer.gateway_lease import GatewayLeaseRegistry


# ══════════════════════════════════════════════════════════════════
# Delivery mode
# ══════════════════════════════════════════════════════════════════

class AckMode(str, Enum):
    """Как адаптер узнаёт о доставке."""
    STRICT_ONE_WAY = "strict_one_way"   # ACK физически невозможен
    ACK_CHANNEL = "ack_channel"         # отдельный control-канал


class DeliveryState(str, Enum):
    """Состояние одной delivery (отправки одной revision)."""
    PENDING = "pending"
    IN_FLIGHT = "in_flight"
    CHECKPOINTED = "checkpointed"       # частично отправлено, resume возможен
    DELIVERED = "delivered"             # только через ACK channel
    ASSUMED_DELIVERED = "assumed_delivered"  # strict mode: отправлено всё, ACK нет
    FAILED_RETRYABLE = "failed_retryable"
    FAILED_TERMINAL = "failed_terminal"


# ══════════════════════════════════════════════════════════════════
# Chunk model
# ══════════════════════════════════════════════════════════════════

class ChunkRef(BaseModel):
    """Ссылка на один чанк payload."""
    model_config = ConfigDict(extra="ignore")
    index: int
    offset: int
    size: int
    sha256: str
    file_name: str


class DeliveryCheckpoint(BaseModel):
    """Checkpoint доставки: сколько чанков ушло, что осталось."""
    model_config = ConfigDict(extra="ignore")
    delivery_id: str
    revision_key: str
    item_id: str
    manifest_sha256: str = ""
    ack_mode: AckMode = AckMode.STRICT_ONE_WAY
    chunks_total: int = 0
    chunks_sent: int = 0
    last_chunk_index: int = -1
    state: DeliveryState = DeliveryState.PENDING
    failure_class: Optional[TransferFailureClass] = None
    failure_detail: str = ""
    attempts: int = 0
    created_at: str = ""
    updated_at: str = ""

    @property
    def is_terminal(self) -> bool:
        return self.state in (
            DeliveryState.DELIVERED,
            DeliveryState.FAILED_TERMINAL,
        )

    @property
    def is_retryable(self) -> bool:
        return self.state == DeliveryState.FAILED_RETRYABLE

    @property
    def recovery_requirement(self) -> str:
        """Observability: что нужно для recovery ("none"|"resume_same_revision"|"new_revision")."""
        if self.state in (DeliveryState.DELIVERED, DeliveryState.ASSUMED_DELIVERED):
            return "none"
        if self.state == DeliveryState.FAILED_TERMINAL:
            return "new_revision"
        return "resume_same_revision"

    @property
    def progress(self) -> float:
        if self.chunks_total == 0:
            return 0.0
        return self.chunks_sent / self.chunks_total


# ══════════════════════════════════════════════════════════════════
# Transport link seam — vendor device implements this
# ══════════════════════════════════════════════════════════════════

class TransportLink(Protocol):
    """Шов под физический канал. Vendor-реализация живёт снаружи.

    write_chunk: бросает TransportError при обрыве канала.
    verify_target: optional hook на target-стороне (если есть обратный
      канал) — проверяет целостность принятого.
    """

    def write_chunk(self, chunk: bytes, ref: ChunkRef) -> None: ...

    def flush(self) -> None:
        """Финализация: дожать буферы устройства."""
        ...

class TransportError(Exception):
    """Обрыв/ошибка физического канала — retryable."""

class TargetRejectError(Exception):
    """Target явно отверг пакет (через ACK channel) — terminal."""


class DeliveryClosedError(Exception):
    """Повторный dispatch/retry по закрытой (terminal/delivered) delivery.

    Terminal failure требует новой revision (rebuild) — identity
    delivery/revision не переиспользуется.
    """


class CheckpointCorruptedError(Exception):
    """Восстановленный checkpoint невалиден (schema/state mismatch).

    Silent success невозможен: corrupt checkpoint обязан упасть явно.
    """

class TargetVerifyHook(Protocol):
    """Hook проверки на target-стороне (при наличии ACK channel)."""

    def __call__(self, revision_key: str, expected_sha256: str) -> bool: ...

class AckChannel(Protocol):
    """Отдельный control/ACK канал (не diode)."""

    def send_ack(self, revision_key: str, ok: bool, detail: str = "") -> None: ...

    def poll_status(self, revision_key: str) -> Optional[dict[str, Any]]: ...


# ══════════════════════════════════════════════════════════════════
# Dispatch result / status
# ══════════════════════════════════════════════════════════════════

class DispatchResult(BaseModel):
    model_config = ConfigDict(extra="ignore")
    delivery_id: str
    revision_key: str
    state: DeliveryState = DeliveryState.PENDING
    chunks_total: int = 0
    chunks_sent: int = 0
    failure_class: Optional[TransferFailureClass] = None
    failure_detail: str = ""
    same_revision: bool = True   # retry сохранил revision?
    # COS-065 observability
    last_chunk_index: int = -1   # индекс последнего отправленного чанка
    attempts: int = 0            # число попыток доставки
    recovery_requirement: str = "resume_same_revision"

    @property
    def ok(self) -> bool:
        return self.state in (DeliveryState.DELIVERED, DeliveryState.ASSUMED_DELIVERED)


# ══════════════════════════════════════════════════════════════════
# DiodeAdapter
# ══════════════════════════════════════════════════════════════════

class DiodeAdapter:
    """Vendor-neutral адаптер отправки через one-way канал.

    - chunked dispatch с checkpoint после каждого чанка;
    - resume продолжает с последнего неотправленного чанка;
    - strict one-way: ASSUMED_DELIVERED после flush, никакого DELIVERED;
    - ack_channel: DELIVERED только после явного ACK/target verify.
    """

    def __init__(
        self,
        link: TransportLink,
        chunk_size: int = 65536,
        ack_mode: AckMode = AckMode.STRICT_ONE_WAY,
        ack_channel: Optional[AckChannel] = None,
        target_verify: Optional[TargetVerifyHook] = None,
        max_attempts: int = 3,
        clock: Any = None,
        gateway_leases: Optional[GatewayLeaseRegistry] = None,
    ):
        if ack_mode is AckMode.ACK_CHANNEL and ack_channel is None:
            raise ValueError("ack_channel required when ack_mode=ACK_CHANNEL")
        self._link = link
        self._chunk_size = chunk_size
        self._ack_mode = ack_mode
        self._ack = ack_channel
        self._target_verify = target_verify
        self._max_attempts = max_attempts
        self._clock = clock or (lambda: time.time())
        self._checkpoints: dict[str, DeliveryCheckpoint] = {}
        # COS-074: опциональный lease-реестр; enforced только для
        # CONTROLLED_GATEWAY_RELAY (см. _require_gateway_lease).
        self._gateway_leases = gateway_leases

    def _require_gateway_lease(self, item: TransferItem, revision_key: str) -> None:
        """COS-074: dispatch по CONTROLLED_GATEWAY_RELAY требует активный lease.

        Нет реестра → проверка не enforced (обратная совместимость).
        Оффлайн без grant'а — raises LeaseRequiredError ДО любых мутаций:
        чанки не пишутся, checkpoint не создаётся, attempts не растут.
        """
        if self._gateway_leases is None:
            return
        try:
            profile = TransportProfile(item.transport_profile)
        except ValueError:
            return  # неизвестный профиль — lease-политика не применяется
        if profile is not TransportProfile.CONTROLLED_GATEWAY_RELAY:
            return
        self._gateway_leases.validate(revision_key)

    # ── chunking ──

    def make_chunks(self, file_name: str, payload: bytes) -> list[ChunkRef]:
        chunks: list[ChunkRef] = []
        offset = 0
        index = 0
        while offset < len(payload) or (offset == 0 and len(payload) == 0):
            piece = payload[offset:offset + self._chunk_size]
            chunks.append(ChunkRef(
                index=index,
                offset=offset,
                size=len(piece),
                sha256=hashlib.sha256(piece).hexdigest(),
                file_name=file_name,
            ))
            index += 1
            offset += self._chunk_size
            if len(piece) < self._chunk_size and len(payload) > 0:
                break
            if len(payload) == 0:
                break
        return chunks

    # ── checkpoint storage ──

    def _save_checkpoint(self, cp: DeliveryCheckpoint) -> None:
        cp.updated_at = str(self._clock())
        self._checkpoints[cp.delivery_id] = cp

    def get_checkpoint(self, delivery_id: str) -> Optional[DeliveryCheckpoint]:
        return self._checkpoints.get(delivery_id)

    def restore_checkpoint(self, data: dict) -> DeliveryCheckpoint:
        """Восстановить checkpoint из persistent store после crash.

        Строгая валидация: schema/state mismatch → CheckpointCorruptedError
        (silent success невозможен). Duplicate delivery_id с другим
        содержимым → CheckpointCorruptedError (детерминированный отказ).
        """
        from pydantic import ValidationError as _VE

        if not isinstance(data, dict):
            raise CheckpointCorruptedError("checkpoint payload must be a dict")
        for key in ("delivery_id", "revision_key", "item_id"):
            if not str(data.get(key, "")).strip():
                raise CheckpointCorruptedError("missing required field: " + key)
        def _coerce(enum_cls, value, field):
            """enum из value или enum-инстанса (model_dump mode='python')."""
            if isinstance(value, Enum):
                return value
            try:
                return enum_cls(str(value))
            except ValueError as exc:
                raise CheckpointCorruptedError(
                    "invalid %s value: %r" % (field, value)) from exc

        try:
            state = _coerce(DeliveryState, data.get("state", ""), "state")
            ack_mode = _coerce(
                AckMode, data.get("ack_mode", AckMode.STRICT_ONE_WAY), "ack_mode")
        except CheckpointCorruptedError:
            raise

        chunks_total = data.get("chunks_total", 0)
        chunks_sent = data.get("chunks_sent", 0)
        last_index = data.get("last_chunk_index", -1)
        if not isinstance(chunks_total, int) or chunks_total < 0:
            raise CheckpointCorruptedError("chunks_total must be non-negative int")
        if not isinstance(chunks_sent, int) or not (0 <= chunks_sent <= chunks_total):
            raise CheckpointCorruptedError("chunks_sent out of range")
        if not isinstance(last_index, int) or not (-1 <= last_index < max(chunks_total, 1)):
            raise CheckpointCorruptedError("last_chunk_index out of range")

        existing = self._checkpoints.get(str(data["delivery_id"]))
        if existing is not None:
            fresh = DeliveryCheckpoint(**data)
            if existing.model_dump() != fresh.model_dump():
                raise CheckpointCorruptedError(
                    "duplicate checkpoint restore with different content: "
                    + str(data["delivery_id"]))
            return existing

        try:
            cp = DeliveryCheckpoint(**data)
        except _VE as exc:
            raise CheckpointCorruptedError("schema validation failed: %s" % exc)
        cp.state = state
        cp.ack_mode = ack_mode
        self._checkpoints[cp.delivery_id] = cp
        return cp

    # ── dispatch / resume ──

    def dispatch(
        self,
        item: TransferItem,
        payload: bytes,
        file_name: str = "payload.bin",
    ) -> DispatchResult:
        """Отправить immutable revision. При retry — та же revision_key.

        ValueError если item не ready (нет revision) — immutable contract.
        """
        if item.package_revision is None:
            raise ValueError("item has no package_revision — build first")
        revision = item.package_revision

        # COS-074: gateway lease gate — до checkpoint/chunks/attempts.
        self._require_gateway_lease(item, revision.revision_key)

        # Terminal delivery закрыта навсегда: identity не переиспользуется
        for cp in self._checkpoints.values():
            if cp.revision_key == revision.revision_key and cp.is_terminal:
                raise DeliveryClosedError(
                    f"delivery '{cp.delivery_id}' for revision "
                    f"'{revision.revision_key}' is {cp.state.value}; "
                    "terminal failure requires a new package revision "
                    "(PackageBuilder.rebuild_with_revision)")

        # Идемпотентный resume: существующий checkpoint => та же delivery
        existing = None
        for cp in self._checkpoints.values():
            if cp.revision_key == revision.revision_key and not cp.is_terminal:
                existing = cp
                break

        if existing is not None:
            return self._resume(existing, payload, file_name)

        delivery_id = f"dl-{revision.revision_key}"
        chunks = self.make_chunks(file_name, payload)
        cp = DeliveryCheckpoint(
            delivery_id=delivery_id,
            revision_key=revision.revision_key,
            item_id=item.item_id,
            manifest_sha256=revision.manifest_sha256,
            ack_mode=self._ack_mode,
            chunks_total=len(chunks),
            chunks_sent=0,
            state=DeliveryState.PENDING,
            created_at=str(self._clock()),
        )
        self._save_checkpoint(cp)
        return self._resume(cp, payload, file_name)

    def _resume(
        self,
        cp: DeliveryCheckpoint,
        payload: bytes,
        file_name: str,
    ) -> DispatchResult:
        """Продолжить/выполнить отправку с последнего неотправленного чанка."""
        cp.attempts += 1
        chunks = self.make_chunks(file_name, payload)
        cp.chunks_total = len(chunks)

        if cp.state == DeliveryState.PENDING:
            cp.state = DeliveryState.IN_FLIGHT
        self._save_checkpoint(cp)

        try:
            while cp.chunks_sent < len(chunks):
                ref = chunks[cp.chunks_sent]
                piece = payload[ref.offset:ref.offset + ref.size]
                # целостность чанка перед отправкой
                if hashlib.sha256(piece).hexdigest() != ref.sha256:
                    cp.state = DeliveryState.FAILED_TERMINAL
                    cp.failure_class = TransferFailureClass.CHECKSUM_MISMATCH
                    cp.failure_detail = f"chunk {ref.index} corrupted before send"
                    self._save_checkpoint(cp)
                    return self._result(cp, same_revision=True)

                self._link.write_chunk(piece, ref)
                cp.chunks_sent += 1
                cp.last_chunk_index = ref.index
                cp.state = DeliveryState.CHECKPOINTED
                self._save_checkpoint(cp)  # checkpoint после каждого чанка

            self._link.flush()
        except TransportError as exc:
            # retryable: канал упал, revision не трогаем.
            # capacity-ошибка канала — отдельный класс, но тоже retryable.
            msg = str(exc)
            cp.state = DeliveryState.FAILED_RETRYABLE
            if "capacity" in msg.lower():
                cp.failure_class = TransferFailureClass.CAPACITY_QUOTA_FAILURE
            else:
                cp.failure_class = TransferFailureClass.TRANSPORT_FAILURE
            cp.failure_detail = msg
            self._save_checkpoint(cp)
            return self._result(cp, same_revision=True)
        except TargetRejectError as exc:
            cp.state = DeliveryState.FAILED_TERMINAL
            cp.failure_class = TransferFailureClass.LANDING_REJECTED
            cp.failure_detail = str(exc)
            self._save_checkpoint(cp)
            return self._result(cp, same_revision=False)

        # payload ушёл целиком
        if self._ack_mode is AckMode.STRICT_ONE_WAY:
            # ACK физически невозможен — честный статус, не DELIVERED
            cp.state = DeliveryState.ASSUMED_DELIVERED
            self._save_checkpoint(cp)
            return self._result(cp, same_revision=True)

        # ACK channel: верификация target
        revision_sha = ""
        if self._target_verify is not None:
            try:
                verified = self._target_verify(cp.revision_key, cp.manifest_sha256)
            except TransportError as exc:
                cp.state = DeliveryState.FAILED_RETRYABLE
                cp.failure_class = TransferFailureClass.TRANSPORT_FAILURE
                cp.failure_detail = f"target verify failed: {exc}"
                self._save_checkpoint(cp)
                return self._result(cp, same_revision=True)
            if not verified:
                cp.state = DeliveryState.FAILED_TERMINAL
                cp.failure_class = TransferFailureClass.CHECKSUM_MISMATCH
                cp.failure_detail = "target verification hook returned False"
                self._save_checkpoint(cp)
                return self._result(cp, same_revision=False)

        # explicit ACK: ok=true → DELIVERED; ok=false → terminal reject;
        # отсутствие ACK — retryable (тот же revision).
        status = self._ack.poll_status(cp.revision_key) if self._ack else None
        if status is not None and status.get("ok"):
            cp.state = DeliveryState.DELIVERED
            self._save_checkpoint(cp)
            return self._result(cp, same_revision=True)
        if status is not None and status.get("ok") is False:
            # Явный отказ target — terminal, требуется новая revision.
            cp.state = DeliveryState.FAILED_TERMINAL
            cp.failure_class = TransferFailureClass.LANDING_REJECTED
            cp.failure_detail = status.get("detail") or "target rejected via ack channel"
            self._save_checkpoint(cp)
            return self._result(cp, same_revision=False)

        cp.state = DeliveryState.FAILED_RETRYABLE
        cp.failure_class = TransferFailureClass.TRANSPORT_FAILURE
        cp.failure_detail = "ACK not received within window"
        self._save_checkpoint(cp)
        return self._result(cp, same_revision=True)

    # ── retry / status ──

    def retry(self, item: TransferItem, payload: bytes, file_name: str = "payload.bin") -> DispatchResult:
        """Повторная доставка. Та же revision, тот же delivery_id.

        max_attempts исчерпан → FAILED_TERMINAL (identity сохранена,
        но требуется новая revision или ручное вмешательство).
        """
        if item.package_revision is None:
            raise ValueError("item has no package_revision — build first")
        rk = item.package_revision.revision_key
        cp = next((c for c in self._checkpoints.values() if c.revision_key == rk), None)
        if cp is not None and cp.is_terminal:
            raise DeliveryClosedError(
                f"delivery '{cp.delivery_id}' is {cp.state.value}; "
                "terminal failure requires a new package revision")
        if cp is not None and cp.attempts >= self._max_attempts:
            cp.state = DeliveryState.FAILED_TERMINAL
            cp.failure_class = cp.failure_class or TransferFailureClass.TRANSPORT_FAILURE
            cp.failure_detail = f"max attempts ({self._max_attempts}) exhausted"
            self._save_checkpoint(cp)
            return self._result(cp, same_revision=True)
        return self.dispatch(item, payload, file_name)

    def poll_status(self, delivery_id: str) -> Optional[DeliveryCheckpoint]:
        cp = self._checkpoints.get(delivery_id)
        if cp is None or cp.is_terminal:
            return cp
        # ACK channel: подтянуть свежий статус
        if self._ack_mode is AckMode.ACK_CHANNEL and self._ack is not None:
            status = self._ack.poll_status(cp.revision_key)
            if status is not None and status.get("ok"):
                cp.state = DeliveryState.DELIVERED
                self._save_checkpoint(cp)
            elif status is not None and status.get("ok") is False:
                cp.state = DeliveryState.FAILED_TERMINAL
                cp.failure_class = TransferFailureClass.LANDING_REJECTED
                cp.failure_detail = status.get("detail") or "target rejected via ack channel"
                self._save_checkpoint(cp)
        return cp

    def list_active(self) -> list[DeliveryCheckpoint]:
        """Активные (не terminal) доставки — для recovery на старте."""
        return [
            cp for cp in self._checkpoints.values()
            if not cp.is_terminal
        ]

    # ── helpers ──

    def _result(self, cp: DeliveryCheckpoint, same_revision: bool) -> DispatchResult:
        return DispatchResult(
            delivery_id=cp.delivery_id,
            revision_key=cp.revision_key,
            state=cp.state,
            chunks_total=cp.chunks_total,
            chunks_sent=cp.chunks_sent,
            failure_class=cp.failure_class,
            failure_detail=cp.failure_detail,
            same_revision=same_revision,
            last_chunk_index=cp.last_chunk_index,
            attempts=cp.attempts,
            recovery_requirement=cp.recovery_requirement,
        )
