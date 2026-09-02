# -*- coding: utf-8 -*-
"""COS-050: Transfer Kernel Contract — provider-neutral, PureK-owned.

TransferItem — единица передачи по одному artifact plane.
TransferPlan — группировка нескольких TransferItem под общим release identity.

Ключевые инварианты:
  - Package revision immutable: одна и та же revision = один и тот же manifest+checksum.
  - Metadata envelope ≠ deployable release (skeleton/context mode required).
  - Один release может иметь несколько TransferItem по разным planes.
  - Idempotency: повторная доставка той же revision не создаёт duplicate.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

Strict = ConfigDict(extra="ignore")


# ══════════════════════════════════════════════════════════════════
# Enums
# ══════════════════════════════════════════════════════════════════

class ArtifactPlane(str, Enum):
    """Plane передачи: каждый plane — независимый TransferItem."""
    METADATA_ENVELOPE = "metadata_envelope"
    SOURCE_CODE = "source_code"
    OCI_IMAGE = "oci_image"
    NEXUS_PACKAGE = "nexus_package"
    EVIDENCE = "evidence"
    SBOM = "sbom"


class PackageMode(str, Enum):
    """Что именно передаём: только метаданные или полный payload."""
    METADATA_ENVELOPE = "metadata_envelope"   # только manifest + references
    FULL_PACKAGE = "full_package"             # manifest + все artifacts inline
    SKELETON_CONTEXT = "skeleton_context"     # landing context без deployable payload


class TransportProfile(str, Enum):
    """Способ пересечения границы. Меняет канал, не меняет contract."""
    DIRECT_AUTHENTICATED_API = "direct_authenticated_api"
    IMMUTABLE_OFFLINE_IMPORT = "immutable_offline_import"
    CONTROLLED_GATEWAY_RELAY = "controlled_gateway_relay"
    ONE_WAY_DIODE_RELAY = "one_way_diode_relay"
    SOD_BRIDGE = "sod_bridge"


class TransferItemStatus(str, Enum):
    """Статус одного TransferItem."""
    DRAFT = "draft"
    VALIDATED = "validated"
    DISPATCHED = "dispatched"
    IN_FLIGHT = "in_flight"
    RECEIVED = "received"
    LANDED = "landed"
    RECONCILED = "reconciled"
    FAILED = "failed"
    RETRY_SCHEDULED = "retry_scheduled"
    CANCELLED = "cancelled"


class TransferPlanStatus(str, Enum):
    """Статус всего плана."""
    DRAFT = "draft"
    ACTIVE = "active"
    PARTIALLY_COMPLETE = "partially_complete"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


# ══════════════════════════════════════════════════════════════════
# Failure Classification
# ══════════════════════════════════════════════════════════════════

class TransferFailureClass(str, Enum):
    """Явная классификация отказов — transport ≠ validation ≠ landing ≠ bootstrap."""
    TRANSPORT_FAILURE = "transport_failure"           # сеть, gateway, diode
    VALIDATION_FAILURE = "validation_failure"         # checksum, manifest, schema
    LANDING_REJECTED = "landing_rejected"             # target preflight отказал
    LANDING_INCOMPLETE = "landing_incomplete"         # partial import
    CHECKSUM_MISMATCH = "checksum_mismatch"           # post-import verification
    CAPACITY_QUOTA_FAILURE = "capacity_quota_failure" # target нет места / квота
    BOOTSTRAP_FAILURE = "bootstrap_failure"           # target-side bootstrap упал
    RECONCILE_FAILURE = "reconcile_failure"           # target reconcile не прошёл
    IDEMPOTENCY_CONFLICT = "idempotency_conflict"     # та же revision, другой checksum
    PACKAGE_NOT_READY = "package_not_ready"           # package не прошёл preflight


# ══════════════════════════════════════════════════════════════════
# Package Revision (immutable)
# ══════════════════════════════════════════════════════════════════

class PackageRevision(BaseModel):
    """Immutable идентификатор пакета: (release_id, revision, checksum).

    Повторная доставка той же revision не создаёт duplicate landing.
    Если checksum меняется при той же revision — IDEMPOTENCY_CONFLICT.
    """
    model_config = Strict
    release_id: str = Field(..., min_length=1)
    revision: int = Field(..., ge=1, description="Monotonically increasing revision")
    manifest_sha256: str = Field(..., min_length=64, max_length=64)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def revision_key(self) -> str:
        """Уникальный ключ для idempotency: {release_id}:{revision}."""
        return f"{self.release_id}:{self.revision}"

    @staticmethod
    def compute_manifest_sha256(manifest: dict[str, Any]) -> str:
        """Deterministic SHA-256 от canonical JSON manifest."""
        canonical = json.dumps(manifest, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ══════════════════════════════════════════════════════════════════
# TransferItem
# ══════════════════════════════════════════════════════════════════

class TransferItem(BaseModel):
    """Одна единица передачи по одному artifact plane.

    Каждый TransferItem независим: свой transport, свой status, свой recovery.
    Общее с планом: release_id, correlation_id, package_revision.
    """
    model_config = Strict
    item_id: str = Field(..., min_length=1, description="Unique item ID")
    release_id: str = Field(..., min_length=1)
    transfer_plan_id: str = Field(..., min_length=1)
    correlation_id: str = Field(default="")

    # Plane & payload
    artifact_plane: ArtifactPlane = ArtifactPlane.METADATA_ENVELOPE
    package_mode: PackageMode = PackageMode.METADATA_ENVELOPE
    transport_profile: TransportProfile = TransportProfile.DIRECT_AUTHENTICATED_API

    # References
    source_ref: str = Field(default="", description="Source location (URI, registry, path)")
    target_ref: str = Field(default="", description="Target location (expected)")
    manifest: dict[str, Any] = Field(default_factory=dict)
    payload_refs: list[str] = Field(default_factory=list, description="Refs to payload objects (not inline)")

    # Immutable revision
    package_revision: Optional[PackageRevision] = None

    # State
    status: TransferItemStatus = TransferItemStatus.DRAFT
    failure_class: Optional[TransferFailureClass] = None
    failure_detail: str = ""
    retry_count: int = 0
    readiness: bool = False

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def is_deployable(self) -> bool:
        """Metadata-only и skeleton/context — не deployable. Только full_package."""
        return self.package_mode == PackageMode.FULL_PACKAGE

    @property
    def revision_key(self) -> str:
        if self.package_revision:
            return self.package_revision.revision_key
        return ""


# ══════════════════════════════════════════════════════════════════
# TransferPlan
# ══════════════════════════════════════════════════════════════════

class TransferPlan(BaseModel):
    """Группировка нескольких TransferItem под общим release identity.

    Один release → один план → несколько TransferItem (по одному на plane).
    Plan не атомарен: один item failed ≠ остальные потеряны.
    """
    model_config = Strict
    plan_id: str = Field(..., min_length=1)
    release_id: str = Field(..., min_length=1)
    correlation_id: str = Field(default="")
    source_zone: str = Field(default="zr")
    target_zone: str = Field(default="zt")
    items: list[TransferItem] = Field(default_factory=list)
    status: TransferPlanStatus = TransferPlanStatus.DRAFT
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def add_item(self, item: TransferItem) -> None:
        """Добавить TransferItem в план."""
        if item.release_id != self.release_id:
            raise ValueError(
                f"Item release_id '{item.release_id}' ≠ plan release_id '{self.release_id}'"
            )
        self.items.append(item)
        self._recompute_status()

    def _recompute_status(self) -> None:
        if not self.items:
            self.status = TransferPlanStatus.DRAFT
            return
        statuses = {i.status for i in self.items}
        if all(s == TransferItemStatus.RECONCILED for s in statuses):
            self.status = TransferPlanStatus.COMPLETED
        elif any(s == TransferItemStatus.FAILED for s in statuses) and any(
            s in (TransferItemStatus.RECONCILED, TransferItemStatus.LANDED) for s in statuses
        ):
            self.status = TransferPlanStatus.PARTIALLY_COMPLETE
        elif all(s == TransferItemStatus.FAILED for s in statuses):
            self.status = TransferPlanStatus.FAILED
        elif any(s != TransferItemStatus.DRAFT for s in statuses):
            self.status = TransferPlanStatus.ACTIVE

    def compute_status(self) -> TransferPlanStatus:
        self._recompute_status()
        return self.status

    @property
    def completed_items(self) -> list[TransferItem]:
        return [i for i in self.items if i.status == TransferItemStatus.RECONCILED]

    @property
    def failed_items(self) -> list[TransferItem]:
        return [i for i in self.items if i.status == TransferItemStatus.FAILED]

    @property
    def pending_items(self) -> list[TransferItem]:
        return [i for i in self.items if i.status not in (
            TransferItemStatus.RECONCILED, TransferItemStatus.FAILED,
            TransferItemStatus.CANCELLED,
        )]


# ══════════════════════════════════════════════════════════════════
# SODTransferAdapter seam (без SOD-specific статусов в core)
# ══════════════════════════════════════════════════════════════════

class SODTransferAdapter:
    """Optional seam для интеграции с внешним СОД.

    Реализация адаптера НЕ принадлежит PureK core. Этот класс —
    только интерфейсный шов: PureK вызывает адаптер, адаптер
    маппит на СОД-specific semantics. Никакие СОД статусы
    не протекают в TransferItem / TransferPlan.
    """

    def dispatch(self, item: TransferItem) -> TransferItemStatus:
        """Отправить item через СОД. Возвращает новый статус."""
        raise NotImplementedError("SOD adapter must be provided by customer integration")

    def check_status(self, item: TransferItem) -> TransferItemStatus:
        """Poll статус у СОД."""
        raise NotImplementedError("SOD adapter must be provided by customer integration")

    def cancel(self, item: TransferItem) -> bool:
        raise NotImplementedError("SOD adapter must be provided by customer integration")