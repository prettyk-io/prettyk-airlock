# -*- coding: utf-8 -*-
"""
COS-052: Provider-neutral capability contract.

Каждый artifact provider (Git, Harbor/OCI, Nexus/package, MinIO/S3, Sfera)
отчитывается по единой capability matrix и выполняет операции через единый
контракт. Ключевое правило карточки:

    Каждая unsupported capability возвращает честный результат,
    а не fake success.

Два механизма честности:
  - OpResult.ok=False + OpStatus.UNSUPPORTED  — операция не поддерживается провайдером;
  - CapabilityStatus (CONFIRMED/DOCUMENTED/...) — эпистемический статус знания
    о поддержке (переиспользован из BRG-003 t1_sfera_probe).

Провайдер-specific идентификаторы (area keys, repo paths, Sfera IDs) НЕ
становятся PureK canonical identity: canonical — immutable digest +
PackageRevision / ArtifactReference (см. transfer.contract, artifact_registry).
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


# ── Capability taxonomy ─────────────────────────────────────────────────────

class ProviderCapability(str, Enum):
    """Единый набор capability, запрашиваемых у любого provider."""

    # Provisioning
    PROVISION_AREA = "provision_area"               # проектная область / namespace
    PROVISION_REPOSITORY = "provision_repository"   # repo/bucket creation
    DELETE_REPOSITORY = "delete_repository"

    # Push / Pull
    RAW_PUSH = "raw_push"                           # generic blob/file upload
    RAW_PULL = "raw_pull"                           # generic blob/file download
    OCI_PUSH = "oci_push"                           # OCI blobs + manifest upload
    OCI_PULL = "oci_pull"                           # OCI manifest/config/layers download
    GIT_BUNDLE_TRANSFER = "git_bundle_transfer"     # git bundle / source refs

    # Discovery
    EXISTS = "exists"                               # artifact/object existence check
    LIST = "list"                                   # tags/tree/objects listing
    RESOLVE_DIGEST = "resolve_digest"               # tag → immutable digest
    GET_CHECKSUM = "get_checksum"                   # provider-side checksum read

    # Promotion
    COPY_OR_PROMOTE = "copy_or_promote"             # repo-to-repo / zone promotion

    # Integrity artifacts
    SIGNATURE_REF = "signature_ref"                 # cosign/signature reference
    SBOM_REF = "sbom_ref"                           # CycloneDX SBOM reference
    ATTESTATION_REF = "attestation_ref"             # OCI attestations

    # Ops
    HEALTH = "health"                               # reachable + authenticated probe
    QUOTA_REPORT = "quota_report"                   # storage/quota reporting


class OpStatus(str, Enum):
    """Единый статус операции provider adapter."""
    OK = "ok"
    UNSUPPORTED = "unsupported"          # провайдер не умеет — НЕ fake success
    NOT_FOUND = "not_found"
    TRANSIENT_FAILURE = "transient_failure"   # сеть/5xx/timeout → retry
    VALIDATION_FAILURE = "validation_failure" # checksum/manifest/schema mismatch
    AUTH_FAILURE = "auth_failure"
    QUOTA_FAILURE = "quota_failure"
    CONFLICT = "conflict"                # idempotency conflict / already exists
    ERROR = "error"                      # прочее, без маскировки


class ErrorCategory(str, Enum):
    """Retry/error categories — маппинг в TransferFailureClass (COS-050)."""
    RETRYABLE = "retryable"              # transport/network → bounded retry
    TERMINAL = "terminal"                # validation/auth/quota → fail fast
    UNKNOWN = "unknown"                  # нет подтверждённого контракта → не ретраить молча

    def to_transfer_failure_class(self) -> str:
        """Маппинг в классификацию transfer kernel (строки из TransferFailureClass)."""
        if self == ErrorCategory.RETRYABLE:
            return "transport_failure"
        return "transport_failure" if self == ErrorCategory.UNKNOWN else "validation_failure"


# ── Результаты операций ─────────────────────────────────────────────────────

@dataclass
class OpResult:
    """Честный результат provider-операции.

    digest/signature/sbom refs возвращаются КАК ЕСТЬ от провайдера —
    без пересчёта и подмены. adapter никогда не «улучшает» ответ.
    """
    status: OpStatus
    capability: ProviderCapability
    provider_id: str
    detail: str = ""
    # Immutable reference, если операция создала/прочитала артефакт:
    digest: Optional[str] = None                 # sha256:... — как вернул провайдер
    location_ref: Optional[str] = None           # provider-specific path/URI (НЕ canonical identity)
    signature_ref: Optional[str] = None
    sbom_ref: Optional[str] = None
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.status == OpStatus.OK

    @property
    def error_category(self) -> ErrorCategory:
        if self.status in (OpStatus.TRANSIENT_FAILURE,):
            return ErrorCategory.RETRYABLE
        if self.status in (OpStatus.VALIDATION_FAILURE, OpStatus.AUTH_FAILURE,
                           OpStatus.QUOTA_FAILURE, OpStatus.UNSUPPORTED):
            return ErrorCategory.TERMINAL
        if self.status in (OpStatus.NOT_FOUND, OpStatus.CONFLICT):
            return ErrorCategory.TERMINAL
        return ErrorCategory.UNKNOWN

    @classmethod
    def unsupported(cls, capability: ProviderCapability, provider_id: str, why: str = "") -> "OpResult":
        """Честный UNSUPPORTED: провайдер не умеет операцию. Никакого fake success."""
        return cls(
            status=OpStatus.UNSUPPORTED,
            capability=capability,
            provider_id=provider_id,
            detail=why or f"{provider_id} does not support {capability.value}",
        )


# ── Capability report ───────────────────────────────────────────────────────

@dataclass
class CapabilityReport:
    """Capability matrix одного провайдера: capability → эпистемический статус.

    CONFIRMED     — проверено (live/contract test)
    DOCUMENTED    — заявлено в документации/легаси-клиенте, не проверено live
    NOT_SUPPORTED — провайдер не поддерживает; операции вернут UNSUPPORTED
    UNKNOWN       — не определено (нет подтверждённого контракта)
    BLOCKED       — нет доступа проверить
    """
    provider_id: str
    entries: dict[str, "CapabilityEntry"] = field(default_factory=dict)

    def set(self, capability: ProviderCapability, status: "CapabilityStatus",
            notes: str = "", evidence: str = "") -> None:
        self.entries[capability.value] = CapabilityEntry(
            capability=capability, status=status, notes=notes,
            doc_reference=evidence,  # поле BRG-003; наш evidence-стринг ложится сюда
        )

    def get(self, capability: ProviderCapability) -> "CapabilityEntry":
        entry = self.entries.get(capability.value)
        if entry is None:
            return CapabilityEntry(
                capability=capability, status=CapabilityStatus.UNKNOWN,
                notes="not reported by provider adapter",
            )
        return entry

    def supports(self, capability: ProviderCapability) -> bool:
        """TRUE только при CONFIRMED или DOCUMENTED. UNKNOWN/NOT_SUPPORTED — нет."""
        return self.get(capability).status in (CapabilityStatus.CONFIRMED,
                                               CapabilityStatus.DOCUMENTED)

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "capabilities": {
                cap: {"status": e.status.value, "notes": e.notes,
                      "evidence": e.doc_reference}
                for cap, e in self.entries.items()
            },
        }


# Переэкспорт эпистемического статуса из BRG-003 (единая семантика)
from orchestrator.cosmo.adapters.t1_sfera_probe import CapabilityStatus, CapabilityEntry  # noqa: E402, F401


# ── Provider contract ───────────────────────────────────────────────────────

class CapabilityProvider(ABC):
    """Provider-neutral контракт: capability report + операции с честным fallback.

    Реализации обязаны:
      - возвращать OpResult.unsupported(...) вместо fake success;
      - сохранять digest/signature/sbom refs без подмены;
      - маппить ошибки в OpStatus (не глотать и не маскировать).
    """

    @property
    @abstractmethod
    def provider_id(self) -> str:
        """Стабильный ID провайдера (например 'harbor', 'nexus', 'sfera')."""
        ...

    @abstractmethod
    def capability_report(self) -> CapabilityReport:
        """Матрица capabilities с эпистемическим статусом каждой."""
        ...

    def require(self, capability: ProviderCapability) -> None:
        """Guard: бросить честную ошибку, если capability не поддерживается."""
        if not self.capability_report().supports(capability):
            raise UnsupportedCapabilityError(self.provider_id, capability)

    # Обязательные ops (реализации возвращают unsupported при отсутствии):

    @abstractmethod
    async def op_health(self) -> OpResult: ...

    @abstractmethod
    async def op_push(self, ref: str, data: bytes, *,
                      media_type: str = "application/octet-stream") -> OpResult: ...

    @abstractmethod
    async def op_pull(self, ref: str) -> OpResult: ...

    @abstractmethod
    async def op_exists(self, ref: str, digest: Optional[str] = None) -> OpResult: ...


class UnsupportedCapabilityError(Exception):
    """Провайдер не поддерживает операцию. Не маскируется под успех."""

    def __init__(self, provider_id: str, capability: ProviderCapability):
        self.provider_id = provider_id
        self.capability = capability
        super().__init__(
            f"Provider '{provider_id}' does not support capability '{capability.value}'"
        )
