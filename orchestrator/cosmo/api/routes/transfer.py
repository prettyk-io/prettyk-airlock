# -*- coding: utf-8 -*-
"""COS-058: Transfer API Boundary — FastAPI contract над transfer kernel.

Provider-neutral REST для принятого kernel (COS-050/COS-053):
  - POST   /api/v1/transfer/plans                          — создать TransferPlan (+items)
  - GET    /api/v1/transfer/plans/{plan_id}                — план + landing states
  - GET    /api/v1/transfer/plans/{plan_id}/items          — items плана
  - GET    /api/v1/transfer/releases/{release_id}/plans    — корреляция по release
  - GET    /api/v1/transfer/items/{item_id}                — item + landing report
  - POST   /api/v1/transfer/items/{item_id}/validate       — PreTransferValidator
  - GET    /api/v1/transfer/items/{item_id}/landing        — LandingCheckReport
  - POST   /api/v1/transfer/items/{item_id}/landing/{t}    — transition
  - GET    /api/v1/transfer/items/{item_id}/recovery       — recovery details
  - POST   /api/v1/transfer/items/{item_id}/mark_transfer_failed  — COS-074 терминал
  - POST   /api/v1/transfer/items/{item_id}/lease          — COS-074: gateway lease issue
  - DELETE /api/v1/transfer/items/{item_id}/lease          — COS-074: lease revoke
  - POST   /api/v1/transfer/items/{item_id}/dispatch       — COS-077: dispatch (lease-gate)

Единый error contract: {"error": {"code", "message", "details"}}:
  NOT_FOUND · INVALID_TRANSITION · VALIDATION_FAILURE · CHECKSUM_MISMATCH ·
  DUPLICATE_REVISION · PROVIDER_UNAVAILABLE · CONFLICT · GATEWAY_LEASE_REQUIRED.

COS-077: боевой путь живёт на durable PgTransferRegistryRepository
(in-memory TransferRegistry снят с боевого пути; остаётся test-double для
hermetic-тестов через dependency_overrides). Restarts процесса не теряют
ревизии/стейты. Lease-реестр — in-memory runtime-семантика (COS-074:
durable-требование только на transfer_failed-терминал).

Границы: без SOD-статусов, без Kafka, без физических адаптеров (V1 driver —
simulate-хук для acceptance), kernel semantics не изменяются.
"""
from __future__ import annotations

import threading
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field

from orchestrator.cosmo.api.deps import get_current_principal, require_capability
from orchestrator.cosmo.domain.rbac import Action, PrincipalContext
from orchestrator.cosmo.db.transfer_registry_repo import (
    PgTransferRegistryRepository,
    TransferRegistryRepository,
)
from orchestrator.cosmo.transfer.builder import PreTransferValidator, ValidationIssue, ValidationResult
from orchestrator.cosmo.transfer.contract import (
    ArtifactPlane,
    PackageMode,
    PackageRevision,
    TransferFailureClass,
    TransferItem,
    TransferItemStatus,
    TransferPlan,
    TransportProfile,
)
from orchestrator.cosmo.transfer.gateway_lease import (
    GatewayLeaseRegistry,
    LeaseRequiredError,
)
from orchestrator.cosmo.transfer.landing import (
    LandingCheckReport,
    LandingState,
    LandingStateError,
    LandingStateMachine,
)
from orchestrator.cosmo.transfer.registry import (
    DuplicateRevisionError,
    PlanEntry,
)

router = APIRouter(prefix="/api/v1/transfer", tags=["transfer"])


# ══════════════════════════════════════════════════════════════════
# Unified error contract
# ══════════════════════════════════════════════════════════════════

class TransferErrorCode(str, Enum):
    NOT_FOUND = "NOT_FOUND"
    INVALID_TRANSITION = "INVALID_TRANSITION"
    VALIDATION_FAILURE = "VALIDATION_FAILURE"
    CHECKSUM_MISMATCH = "CHECKSUM_MISMATCH"
    DUPLICATE_REVISION = "DUPLICATE_REVISION"
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
    CONFLICT = "CONFLICT"
    GATEWAY_LEASE_REQUIRED = "GATEWAY_LEASE_REQUIRED"


def transfer_error(
    status_code: int,
    code: TransferErrorCode,
    message: str,
    **details: Any,
) -> HTTPException:
    """Единая форма ошибки: {"error": {"code", "message", "details"}}."""
    return HTTPException(
        status_code=status_code,
        detail={"error": {"code": code.value, "message": message, "details": details}},
    )


async def transfer_error_handler(request: Any, exc: HTTPException) -> Any:
    """COS-058: разворачивает dict-detail с ключом 'error' в тело ответа.

    Строковые detail (все остальные роуты) сохраняют дефолтную форму
    {"detail": "..."} — поведение платформы не меняется.
    """
    from fastapi.responses import JSONResponse

    detail = exc.detail
    headers = getattr(exc, "headers", None)
    if isinstance(detail, dict) and "error" in detail:
        return JSONResponse(status_code=exc.status_code, content=detail, headers=headers)
    return JSONResponse(status_code=exc.status_code, content={"detail": detail}, headers=headers)


# ══════════════════════════════════════════════════════════════════
# Request / response schemas
# ══════════════════════════════════════════════════════════════════

class TransferItemIn(BaseModel):
    item_id: str = Field(..., min_length=1)
    artifact_plane: ArtifactPlane = ArtifactPlane.METADATA_ENVELOPE
    package_mode: PackageMode = PackageMode.METADATA_ENVELOPE
    transport_profile: TransportProfile = TransportProfile.DIRECT_AUTHENTICATED_API
    source_ref: str = ""
    target_ref: str = ""
    manifest: Dict[str, Any] = Field(default_factory=dict)
    payload_refs: List[str] = Field(default_factory=list)
    correlation_id: str = ""
    revision: int = Field(default=1, ge=1)
    manifest_sha256: Optional[str] = Field(
        default=None,
        description="SHA-256 manifest; если не задан — вычисляется из manifest",
    )


class TransferPlanIn(BaseModel):
    plan_id: str = Field(..., min_length=1)
    release_id: str = Field(..., min_length=1)
    correlation_id: str = ""
    source_zone: str = "zr"
    target_zone: str = "zt"
    items: List[TransferItemIn] = Field(default_factory=list)

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "summary": "Multi-plane plan: metadata envelope + SBOM skeleton",
                    "description": "Один release → несколько planes; "
                                   "skeleton_context не является deployable release.",
                    "value": {
                        "plan_id": "plan-rel-42-1",
                        "release_id": "rel-42",
                        "correlation_id": "corr-rel-42-transfer",
                        "source_zone": "zr",
                        "target_zone": "zt",
                        "items": [
                            {
                                "item_id": "item-rel-42-envelope",
                                "artifact_plane": "metadata_envelope",
                                "package_mode": "metadata_envelope",
                                "transport_profile": "direct_authenticated_api",
                                "source_ref": "git::gitea/acme/core@v1.2.3",
                                "target_ref": "sod-bridge://zt/inbox/core",
                                "manifest": {
                                    "release_id": "rel-42",
                                    "revision": 1,
                                    "artifact_plane": "metadata_envelope",
                                    "payload_refs": [],
                                },
                                "payload_refs": [],
                                "revision": 1,
                            },
                            {
                                "item_id": "item-rel-42-sbom",
                                "artifact_plane": "sbom",
                                "package_mode": "skeleton_context",
                                "transport_profile": "one_way_diode_relay",
                                "source_ref": "git::gitea/acme/core@v1.2.3",
                                "target_ref": "diode://zt/inbox/core-sbom",
                                "manifest": {
                                    "release_id": "rel-42",
                                    "revision": 1,
                                    "artifact_plane": "sbom",
                                    "payload_refs": ["sbom/cdx.json"],
                                },
                                "payload_refs": ["sbom/cdx.json"],
                                "revision": 1,
                            },
                        ],
                    },
                },
                {
                    "summary": "Metadata-only skeleton (не deployable)",
                    "description": "Только manifest + references: инвариант "
                                   "'metadata envelope ≠ deployable release'.",
                    "value": {
                        "plan_id": "plan-rel-42-skel",
                        "release_id": "rel-42",
                        "correlation_id": "corr-rel-42-skeleton",
                        "items": [
                            {
                                "item_id": "item-rel-42-skel",
                                "artifact_plane": "source_code",
                                "package_mode": "skeleton_context",
                                "source_ref": "git::gitea/acme/core@v1.2.3",
                                "manifest": {"release_id": "rel-42", "revision": 1},
                                "revision": 1,
                            }
                        ],
                    },
                },
            ]
        }
    }


class LandingTransitionIn(BaseModel):
    reason: str = ""
    incoming_manifest: Optional[Dict[str, Any]] = Field(
        default=None,
        description="verify: manifest фактически доставленного payload "
                    "(если не задан — берётся зарегистрированный manifest)",
    )
    simulate: Dict[str, bool] = Field(
        default_factory=dict,
        description="V1 driver hook (физические адаптеры вне scope): "
                    "capacity_failure | bootstrap_failure | reconcile_failure",
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "summary": "Verify с tampered delivery → CHECKSUM_MISMATCH",
                    "value": {
                        "reason": "post-import verification",
                        "incoming_manifest": {
                            "release_id": "rel-42",
                            "revision": 1,
                            "tag": "tampered-in-transit",
                        },
                    },
                },
                {
                    "summary": "Recoverable bootstrap failure (V1 simulate hook)",
                    "value": {
                        "reason": "target-side bootstrap service crash",
                        "simulate": {"bootstrap_failure": True},
                    },
                },
            ]
        }
    }


class PlanView(BaseModel):
    plan: TransferPlan
    landing: Dict[str, str] = Field(default_factory=dict, description="item_id → landing state")


class ItemView(BaseModel):
    item: TransferItem
    landing: LandingCheckReport


class TransitionView(BaseModel):
    item_id: str
    release_id: str
    transition: str
    state: str
    passed: bool = False
    recoverable: bool = False
    requires_new_revision: bool = False
    report: LandingCheckReport


class ValidationView(BaseModel):
    item_id: str
    passed: bool
    status: str
    issues: List[ValidationIssue] = Field(default_factory=list)
    error_codes: List[str] = Field(default_factory=list)


class RecoveryView(BaseModel):
    item_id: str
    release_id: str
    revision_key: str
    state: str
    recoverable: bool
    requires_new_revision: bool
    retry_target: Optional[str] = None
    failure_class: Optional[str] = None
    failure_detail: str = ""
    history: List[Dict[str, Any]] = Field(default_factory=list)


# ══════════════════════════════════════════════════════════════════
# COS-077: durable repository binding (battle path)
# ══════════════════════════════════════════════════════════════════

_transfer_repo: Optional[PgTransferRegistryRepository] = None
_transfer_repo_lock = threading.Lock()


def get_transfer_repository() -> PgTransferRegistryRepository:
    """Durable PgTransferRegistryRepository — ленивый singleton над sync engine.

    COS-078: URL резолвится при ПЕРВОМ вызове (не при импорте) —
    import-time capture был корнем COS-072/075 split-brain. В тестах
    dependency переопределяется на in-memory registry (hermetic-файлы)
    либо работает на тестовом PG через conftest-forced COSMO_DATABASE_URL.
    """
    global _transfer_repo
    if _transfer_repo is None:
        with _transfer_repo_lock:
            if _transfer_repo is None:
                from orchestrator.cosmo.db.session import get_sync_url

                _transfer_repo = PgTransferRegistryRepository(get_sync_url())
    return _transfer_repo


# COS-074: lease-реестр — runtime-семантика (in-memory по контракту карточки)
_gateway_leases = GatewayLeaseRegistry()


def get_gateway_leases() -> GatewayLeaseRegistry:
    """Доступ к lease-реестру (для тестовой изоляции)."""
    return _gateway_leases


# ══════════════════════════════════════════════════════════════════
# Internal helpers
# ══════════════════════════════════════════════════════════════════

_ITEM_STATUS_BY_LANDING: Dict[LandingState, TransferItemStatus] = {
    LandingState.RECEIVED: TransferItemStatus.RECEIVED,
    LandingState.VERIFIED: TransferItemStatus.IN_FLIGHT,
    LandingState.LANDING_APPROVED: TransferItemStatus.IN_FLIGHT,
    LandingState.IMPORTED: TransferItemStatus.IN_FLIGHT,
    LandingState.BOOTSTRAPPED: TransferItemStatus.LANDED,
    LandingState.RECONCILED: TransferItemStatus.RECONCILED,
    LandingState.REJECTED: TransferItemStatus.FAILED,
    LandingState.INCOMPLETE: TransferItemStatus.FAILED,
    LandingState.CHECKSUM_MISMATCH: TransferItemStatus.FAILED,
    LandingState.CAPACITY_FAILURE: TransferItemStatus.FAILED,
    LandingState.BOOTSTRAP_FAILURE: TransferItemStatus.FAILED,
    LandingState.RECONCILE_FAILURE: TransferItemStatus.FAILED,
    # COS-077: транспортный терминал — item не доехал, честный FAILED
    # (failure_class проставляет kernel/registry, не маппинг)
    LandingState.TRANSFER_FAILED: TransferItemStatus.FAILED,
}

_FAILURE_CLASS_BY_LANDING: Dict[LandingState, TransferFailureClass] = {
    LandingState.REJECTED: TransferFailureClass.LANDING_REJECTED,
    LandingState.INCOMPLETE: TransferFailureClass.LANDING_INCOMPLETE,
    LandingState.CHECKSUM_MISMATCH: TransferFailureClass.CHECKSUM_MISMATCH,
    LandingState.CAPACITY_FAILURE: TransferFailureClass.CAPACITY_QUOTA_FAILURE,
    LandingState.BOOTSTRAP_FAILURE: TransferFailureClass.BOOTSTRAP_FAILURE,
    LandingState.RECONCILE_FAILURE: TransferFailureClass.RECONCILE_FAILURE,
}

_RETRY_TARGET: Dict[LandingState, LandingState] = {
    LandingState.INCOMPLETE: LandingState.IMPORTED,
    LandingState.CAPACITY_FAILURE: LandingState.LANDING_APPROVED,
    LandingState.BOOTSTRAP_FAILURE: LandingState.IMPORTED,
    LandingState.RECONCILE_FAILURE: LandingState.BOOTSTRAPPED,
}


def _principal_domain(principal: PrincipalContext) -> str:
    """Домен аутентифицированного principal (identity, не спуфится)."""
    return (principal.domain_id or "").strip()


def _context_domain(principal: PrincipalContext, x_cosmo_domain: Optional[str]) -> str:
    """Домен-контекст для СОЗДАНИЯ записи.

    COS-066: только system admin может переключить контекст заголовком
    X-Cosmo-Domain; не-админ привязан к своему principal.domain_id —
    иначе подделка заголовка позволяла бы создавать записи в чужом домене.
    """
    if principal.is_system_admin:
        return (x_cosmo_domain or principal.domain_id or "default").strip()
    return _principal_domain(principal) or "default"


def _authorize_record_access(
    principal: PrincipalContext,
    record_domain_id: str,
    resource: str,
) -> None:
    """Кросс-доменный доступ → 404 (не раскрываем существование ресурса).

    COS-066 hardening: доступ не-админа определяется ТОЛЬКО principal.domain_id.
    Заголовок X-Cosmo-Domain клиентски контролируем и не может расширить
    чтение/мутацию на чужой домен (anti-spoofing). Админ — контекстный доступ.
    """
    if principal.is_system_admin:
        return
    if not record_domain_id or record_domain_id != _principal_domain(principal):
        raise transfer_error(
            status.HTTP_404_NOT_FOUND, TransferErrorCode.NOT_FOUND, f"{resource} not found",
        )


def _find_plan(registry: TransferRegistryRepository, plan_id: str) -> PlanEntry:
    entry = registry.get_plan(plan_id)
    if entry is None:
        raise transfer_error(
            status.HTTP_404_NOT_FOUND, TransferErrorCode.NOT_FOUND,
            f"Transfer plan '{plan_id}' not found",
        )
    return entry


def _find_item(
    registry: TransferRegistryRepository, item_id: str,
) -> tuple[PlanEntry, TransferItem]:
    found = registry.get_item(item_id)
    if found is None:
        raise transfer_error(
            status.HTTP_404_NOT_FOUND, TransferErrorCode.NOT_FOUND,
            f"Transfer item '{item_id}' not found",
        )
    return found


def _plan_view(entry: PlanEntry) -> PlanView:
    return PlanView(
        plan=entry.plan,
        landing={
            item.item_id: entry.landing_for(item).state.value
            for item in entry.plan.items
        },
    )


def _apply_landing_state(entry: PlanEntry, item: TransferItem, state: LandingState) -> None:
    """Синхронизация kernel item status с landing state (терминалы/отказы)."""
    mapped = _ITEM_STATUS_BY_LANDING.get(state)
    if mapped is not None:
        item.status = mapped
    if state in _FAILURE_CLASS_BY_LANDING:
        item.failure_class = _FAILURE_CLASS_BY_LANDING[state]
    item.updated_at = datetime.now(timezone.utc)
    entry.plan.compute_status()


def _persist_state(registry: Any, entry: PlanEntry, item: TransferItem,
                   sm: LandingStateMachine) -> None:
    """COS-077: durable-персист состояния после мутации в API-слое.

    PG-репозиторий сохраняет landing state + item + plan; in-memory
    test-double (hermetic-тесты) методов save_* не имеет — для него
    персист является no-op (мутации живых объектов уже видны).
    """
    save_landing = getattr(registry, "save_landing_state", None)
    if save_landing is not None:
        save_landing(item.item_id, sm)
    save_item = getattr(registry, "save_item", None)
    if save_item is not None:
        save_item(item)
    save_plan = getattr(registry, "save_plan", None)
    if save_plan is not None:
        save_plan(entry.plan)


def _transition_view(
    item: TransferItem, sm: LandingStateMachine, transition: str,
) -> TransitionView:
    report = sm.check_report()
    return TransitionView(
        item_id=item.item_id,
        release_id=item.release_id,
        transition=transition,
        state=sm.state.value,
        passed=sm.state == LandingState.RECONCILED,
        recoverable=sm.is_recoverable(),
        requires_new_revision=sm.requires_new_revision(),
        report=report,
    )


# ══════════════════════════════════════════════════════════════════
# Endpoints
# ══════════════════════════════════════════════════════════════════

@router.post(
    "/plans",
    status_code=status.HTTP_201_CREATED,
    response_model=PlanView,
    responses={
        409: {"description": "Duplicate plan_id / item_id (CONFLICT)"},
        403: {"description": "release:transfer capability required"},
    },
)
async def create_transfer_plan(
    body: TransferPlanIn,
    principal: PrincipalContext = Depends(require_capability(Action.RELEASE_TRANSFER)),
    x_cosmo_domain: Optional[str] = Header(None, alias="X-Cosmo-Domain"),
    registry: TransferRegistryRepository = Depends(get_transfer_repository),
) -> PlanView:
    """Создать TransferPlan с TransferItems (по одному на artifact plane).

    manifest_sha256 вычисляется детерминированно, если не передан явно.
    COS-077: запись регистрируется в durable-репозитории (PG на боевом пути).
    """
    items: List[TransferItem] = []
    for it in body.items:
        sha = it.manifest_sha256 or PackageRevision.compute_manifest_sha256(it.manifest)
        revision = PackageRevision(
            release_id=body.release_id,
            revision=it.revision,
            manifest_sha256=sha,
        )
        items.append(TransferItem(
            item_id=it.item_id,
            release_id=body.release_id,
            transfer_plan_id=body.plan_id,
            correlation_id=it.correlation_id or body.correlation_id,
            artifact_plane=it.artifact_plane,
            package_mode=it.package_mode,
            transport_profile=it.transport_profile,
            source_ref=it.source_ref,
            target_ref=it.target_ref,
            manifest=it.manifest,
            payload_refs=list(it.payload_refs),
            package_revision=revision,
        ))

    plan = TransferPlan(
        plan_id=body.plan_id,
        release_id=body.release_id,
        correlation_id=body.correlation_id,
        source_zone=body.source_zone,
        target_zone=body.target_zone,
        items=items,
    )
    plan.compute_status()

    try:
        entry = registry.register_plan(plan, domain_id=_context_domain(principal, x_cosmo_domain))
    except ValueError as exc:
        raise transfer_error(
            status.HTTP_409_CONFLICT, TransferErrorCode.CONFLICT, str(exc),
        ) from exc
    return _plan_view(entry)


@router.get(
    "/plans/{plan_id}",
    response_model=PlanView,
    responses={404: {"description": "Plan not found or foreign domain (NOT_FOUND)"}},
)
async def get_transfer_plan(
    plan_id: str,
    principal: PrincipalContext = Depends(get_current_principal),
    registry: TransferRegistryRepository = Depends(get_transfer_repository),
) -> PlanView:
    """Получить TransferPlan с текущими landing states items."""
    entry = _find_plan(registry, plan_id)
    _authorize_record_access(principal, entry.domain_id, "Transfer plan")
    return _plan_view(entry)


@router.get(
    "/plans/{plan_id}/items",
    response_model=List[TransferItem],
    responses={404: {"description": "Plan not found or foreign domain (NOT_FOUND)"}},
)
async def list_transfer_plan_items(
    plan_id: str,
    principal: PrincipalContext = Depends(get_current_principal),
    registry: TransferRegistryRepository = Depends(get_transfer_repository),
) -> List[TransferItem]:
    """Список TransferItems плана (kernel schema)."""
    entry = _find_plan(registry, plan_id)
    _authorize_record_access(principal, entry.domain_id, "Transfer plan")
    return list(entry.plan.items)


@router.get(
    "/releases/{release_id}/plans",
    response_model=List[PlanView],
)
async def list_plans_for_release(
    release_id: str,
    principal: PrincipalContext = Depends(get_current_principal),
    registry: TransferRegistryRepository = Depends(get_transfer_repository),
) -> List[PlanView]:
    """Корреляция: все планы release_id (release_id + correlation_id preserved).

    COS-066: не-admin видит только планы своего principal.domain_id —
    заголовок X-Cosmo-Domain клиентски контролируем и фильтр не расширяет.
    """
    caller = _principal_domain(principal)
    entries = registry.plans_for_release(release_id)
    if not principal.is_system_admin:
        entries = [e for e in entries if e.domain_id == caller]
    return [_plan_view(e) for e in entries]


@router.get(
    "/items/{item_id}",
    response_model=ItemView,
    responses={404: {"description": "Item not found or foreign domain (NOT_FOUND)"}},
)
async def get_transfer_item(
    item_id: str,
    principal: PrincipalContext = Depends(get_current_principal),
    registry: TransferRegistryRepository = Depends(get_transfer_repository),
) -> ItemView:
    """TransferItem + детальный LandingCheckReport (не boolean)."""
    entry, item = _find_item(registry, item_id)
    _authorize_record_access(principal, entry.domain_id, "Transfer item")
    return ItemView(item=item, landing=entry.landing_for(item).check_report())


@router.post(
    "/items/{item_id}/validate",
    response_model=ValidationView,
    responses={
        200: {"description": "Validation passed; item status → validated"},
        422: {
            "description": "VALIDATION_FAILURE — detailed issues, не boolean",
            "content": {
                "application/json": {
                    "examples": {
                        "validation-failure": {
                            "summary": "full_package без payload_refs и source_ref",
                            "value": {"error": {"code": "VALIDATION_FAILURE", "message": "Pre-transfer validation failed for item 'item-rel-42-bin'", "details": {"item_id": "item-rel-42-bin", "issues": [{"code": "FULL_PACKAGE_NO_PAYLOAD", "message": "full_package mode requires non-empty payload_refs", "failure_class": "validation_failure"}, {"code": "SOURCE_REF_MISSING", "message": "source_ref is required for non-metadata transfers", "failure_class": "validation_failure"}], "error_codes": ["FULL_PACKAGE_NO_PAYLOAD", "SOURCE_REF_MISSING"], "item_status": "draft"}}},
                        },
                    }
                }
            },
        },
        404: {"description": "Item not found or foreign domain (NOT_FOUND)"},
    },
)
async def validate_transfer_item(
    item_id: str,
    principal: PrincipalContext = Depends(require_capability(Action.RELEASE_TRANSFER)),
    registry: TransferRegistryRepository = Depends(get_transfer_repository),
) -> ValidationView:
    """Запустить PreTransferValidator: identity, completeness, readiness, idempotency."""
    entry, item = _find_item(registry, item_id)
    _authorize_record_access(principal, entry.domain_id, "Transfer item")
    result: ValidationResult = PreTransferValidator.validate(item)
    if result.passed:
        item.status = TransferItemStatus.VALIDATED
        item.readiness = True
        item.updated_at = datetime.now(timezone.utc)
        entry.plan.compute_status()
        _persist_state(registry, entry, item, entry.landing_for(item))
        return ValidationView(
            item_id=item.item_id, passed=True, status=item.status.value,
            issues=[], error_codes=[],
        )
    # Failure — детальный отчёт в теле ошибки, статус item не меняем
    raise transfer_error(
        status.HTTP_422_UNPROCESSABLE_ENTITY,
        TransferErrorCode.VALIDATION_FAILURE,
        f"Pre-transfer validation failed for item '{item.item_id}'",
        item_id=item.item_id,
        issues=[issue.model_dump(mode="json") for issue in result.issues],
        error_codes=result.error_codes,
        item_status=item.status.value,
    )


@router.get(
    "/items/{item_id}/landing",
    response_model=LandingCheckReport,
    responses={404: {"description": "Item not found or foreign domain (NOT_FOUND)"}},
)
async def get_landing_report(
    item_id: str,
    principal: PrincipalContext = Depends(get_current_principal),
    registry: TransferRegistryRepository = Depends(get_transfer_repository),
) -> LandingCheckReport:
    """Детальный LandingCheckReport: state, checks, failure_class, reasons."""
    entry, item = _find_item(registry, item_id)
    _authorize_record_access(principal, entry.domain_id, "Transfer item")
    return entry.landing_for(item).check_report()


@router.post(
    "/items/{item_id}/landing/{transition}",
    response_model=TransitionView,
    responses={
        200: {
            "description": "Transition applied (успех ИЛИ first-class landing failure: "
                           "capacity/bootstrap/reconcile failure с recovery info)",
            "content": {
                "application/json": {
                    "examples": {
                        "successful-landing": {
                            "summary": "Successful landing (reconciled)",
                            "value": {
                                "item_id": "item-rel-42-envelope",
                                "release_id": "rel-42",
                                "transition": "reconcile",
                                "state": "reconciled",
                                "passed": True,
                                "recoverable": False,
                                "requires_new_revision": False,
                                "report": {
                                    "item_id": "item-rel-42-envelope",
                                    "release_id": "rel-42",
                                    "revision_key": "rel-42:1",
                                    "state": "reconciled",
                                    "passed": True,
                                    "checks": [
                                        {"check": "received", "passed": True, "detail": ""},
                                        {"check": "verified", "passed": True, "detail": ""},
                                        {"check": "landing_approved", "passed": True, "detail": ""},
                                        {"check": "imported", "passed": True, "detail": ""},
                                        {"check": "bootstrapped", "passed": True, "detail": ""},
                                        {"check": "reconciled", "passed": True, "detail": ""},
                                    ],
                                    "failure_class": None,
                                    "reasons": [],
                                },
                            },
                        },
                        "recoverable-bootstrap-failure": {
                            "summary": "Recoverable bootstrap failure (retry без новой revision)",
                            "value": {
                                "item_id": "item-rel-42-envelope",
                                "release_id": "rel-42",
                                "transition": "bootstrap",
                                "state": "bootstrap_failure",
                                "passed": False,
                                "recoverable": True,
                                "requires_new_revision": False,
                                "report": {
                                    "item_id": "item-rel-42-envelope",
                                    "release_id": "rel-42",
                                    "revision_key": "rel-42:1",
                                    "state": "bootstrap_failure",
                                    "passed": False,
                                    "checks": [],
                                    "failure_class": "bootstrap_failure",
                                    "reasons": ["target-side bootstrap service crash"],
                                },
                            },
                        },
                    }
                }
            },
        },
        409: {
            "description": "INVALID_TRANSITION (stable, без смены состояния) · "
                           "CHECKSUM_MISMATCH · DUPLICATE_REVISION",
            "content": {
                "application/json": {
                    "examples": {
                        "invalid-transition": {
                            "summary": "Bootstrap до verified + landing_approved",
                            "value": {"error": {"code": "INVALID_TRANSITION", "message": "Invalid landing transition for 'item-rel-42-envelope': received → bootstrapped", "details": {"item_id": "item-rel-42-envelope", "from_state": "received", "to_state": "bootstrapped"}}},
                        },
                        "checksum-mismatch": {
                            "summary": "Post-import checksum verification failed",
                            "value": {"error": {"code": "CHECKSUM_MISMATCH", "message": "Checksum mismatch for item 'item-rel-42-envelope': expected 3f79bb7b435b05…, computed 9d4e1e23bd5b7c…", "details": {"expected_sha256": "3f79bb7b435b0532164daea6b234c4d9ab7b435b0532164daea6b234c4d9ab7b", "computed_sha256": "9d4e1e23bd5b7cd147a9a25b1f9d9e0f9d4e1e23bd5b7cd147a9a25b1f9d9e0f", "state": "checksum_mismatch", "requires_new_revision": True}}},
                        },
                        "duplicate-revision": {
                            "summary": "Та же package revision уже получена другим item",
                            "value": {"error": {"code": "DUPLICATE_REVISION", "message": "Package revision 'rel-42:1' already received by item 'item-rel-42-envelope'", "details": {"revision_key": "rel-42:1", "existing_item_id": "item-rel-42-envelope", "incoming_item_id": "item-rel-42-sbom"}}},
                        },
                    }
                }
            },
        },
        404: {
            "description": "NOT_FOUND — неизвестный transition ИЛИ item не найден / чужой домен",
            "content": {
                "application/json": {
                    "examples": {
                        "unknown-transition": {
                            "summary": "Transition вне.allowed-набора",
                            "value": {"error": {"code": "NOT_FOUND", "message": "Unknown landing transition 'teleport'", "details": {"allowed": ["receive", "verify", "approve_landing", "import", "bootstrap", "reconcile", "retry"]}}},
                        },
                    }
                }
            },
        },
        422: {"description": "VALIDATION_FAILURE — item без package_revision"},
        503: {"description": "PROVIDER_UNAVAILABLE — transport provider seam упал"},
    },
)
async def landing_transition(
    item_id: str,
    transition: str,
    body: Optional[LandingTransitionIn] = None,
    principal: PrincipalContext = Depends(require_capability(Action.RELEASE_TRANSFER)),
    registry: TransferRegistryRepository = Depends(get_transfer_repository),
) -> TransitionView:
    """Запросить landing transition: receive · verify · approve_landing ·
    import · bootstrap · reconcile · retry · mark_transfer_failed.

    Инварианты kernel: bootstrap невозможен до verified + landing_approved;
    post-import checksum verification обязательна; invalid transition не меняет state.
    COS-074: mark_transfer_failed — честный транспортный терминал (NOT_RECEIVED →
    TRANSFER_FAILED), идемпотентен; после RECEIVED — 409 (target что-то получил).
    COS-077: после каждой успешной мутации состояние персистится в durable
    репозиторий (restart-survival).
    """
    entry, item = _find_item(registry, item_id)
    _authorize_record_access(principal, entry.domain_id, "Transfer item")
    sm: LandingStateMachine = entry.landing_for(item)
    payload = body or LandingTransitionIn()
    reason = payload.reason

    try:
        if transition == "receive":
            # Кросс-item duplicate revision → отдельная ошибка (не invalid transition)
            if item.revision_key:
                try:
                    registry.register_received_revision(item.revision_key, item.item_id)
                except DuplicateRevisionError as exc:
                    raise transfer_error(
                        status.HTTP_409_CONFLICT,
                        TransferErrorCode.DUPLICATE_REVISION,
                        str(exc),
                        revision_key=exc.revision_key,
                        existing_item_id=exc.existing_item_id,
                        incoming_item_id=exc.incoming_item_id,
                    ) from exc
            new_state = sm.transition(LandingState.RECEIVED, reason=reason or "package received")

        elif transition == "verify":
            if item.package_revision is None:
                raise transfer_error(
                    status.HTTP_422_UNPROCESSABLE_ENTITY,
                    TransferErrorCode.VALIDATION_FAILURE,
                    f"Item '{item.item_id}' has no package_revision; verification impossible",
                )
            incoming = payload.incoming_manifest if payload.incoming_manifest is not None else item.manifest
            computed = PackageRevision.compute_manifest_sha256(incoming)
            expected = item.package_revision.manifest_sha256
            if computed != expected:
                # Post-import checksum verification обязательна — состояние фиксируется
                sm.transition(LandingState.CHECKSUM_MISMATCH,
                              reason=reason or "checksum mismatch on verification")
                _apply_landing_state(entry, item, LandingState.CHECKSUM_MISMATCH)
                # COS-077: состояние легитимно изменилось — персист ДО ошибки
                _persist_state(registry, entry, item, sm)
                raise transfer_error(
                    status.HTTP_409_CONFLICT,
                    TransferErrorCode.CHECKSUM_MISMATCH,
                    f"Checksum mismatch for item '{item.item_id}': "
                    f"expected {expected[:12]}…, computed {computed[:12]}…",
                    expected_sha256=expected,
                    computed_sha256=computed,
                    state=LandingState.CHECKSUM_MISMATCH.value,
                    requires_new_revision=True,
                )
            new_state = sm.transition(LandingState.VERIFIED, reason=reason or "checksum verified")

        elif transition == "approve_landing":
            new_state = sm.transition(LandingState.LANDING_APPROVED,
                                      reason=reason or "landing approved")

        elif transition == "import":
            target = (
                LandingState.CAPACITY_FAILURE
                if payload.simulate.get("capacity_failure")
                else LandingState.IMPORTED
            )
            new_state = sm.transition(target, reason=reason or "import executed")

        elif transition == "bootstrap":
            target = (
                LandingState.BOOTSTRAP_FAILURE
                if payload.simulate.get("bootstrap_failure")
                else LandingState.BOOTSTRAPPED
            )
            new_state = sm.transition(target, reason=reason or "bootstrap executed")

        elif transition == "reconcile":
            target = (
                LandingState.RECONCILE_FAILURE
                if payload.simulate.get("reconcile_failure")
                else LandingState.RECONCILED
            )
            new_state = sm.transition(target, reason=reason or "reconcile executed")

        elif transition == "retry":
            target = _RETRY_TARGET.get(sm.state)
            if target is None:
                raise LandingStateError(item.item_id, sm.state, target or LandingState.NOT_RECEIVED)
            item.retry_count += 1
            new_state = sm.transition(target, reason=reason or "retry scheduled")

        elif transition == "mark_transfer_failed":
            # COS-074: честный транспортный терминал. Kernel-переход (в обоих
            # бэкендах) идемпотентен для TRANSFER_FAILED и поднимает
            # LandingStateError после RECEIVED — «транспортный провал» лгать
            # не может.
            prev_state = sm.state
            new_state = registry.record_transfer_failed(
                item.item_id,
                failure_class=TransferFailureClass.TRANSPORT_FAILURE,
                detail=reason or "transfer failed on the wire",
            )
            if prev_state is not LandingState.TRANSFER_FAILED:
                # COS-077: kernel-запись проставила failure fields в БД
                # (минуя in-memory item) — зеркалим, чтобы save_item не
                # перетёр их пустым payload. Повторный вызов — no-op без
                # зеркалирования (идемпотентность честная).
                item.failure_class = TransferFailureClass.TRANSPORT_FAILURE
                item.failure_detail = reason or "transfer failed on the wire"
            # COS-077: PG-репозиторий мутирует только БД; SM в entry может
            # остаться stale. Подтягиваем DB-truth (in-memory — тот же объект).
            _refresh_landing = getattr(registry, "get_landing_state", None)
            if _refresh_landing is not None:
                fresh_sm = _refresh_landing(item.item_id)
                if fresh_sm is not None:
                    entry.landing[item.item_id] = fresh_sm
                    sm = fresh_sm

        else:
            raise transfer_error(
                status.HTTP_404_NOT_FOUND,
                TransferErrorCode.NOT_FOUND,
                f"Unknown landing transition '{transition}'",
                allowed=["receive", "verify", "approve_landing", "import",
                         "bootstrap", "reconcile", "retry", "mark_transfer_failed"],
            )

    except LandingStateError as exc:
        # Стабильная ошибка без смены состояния
        raise transfer_error(
            status.HTTP_409_CONFLICT,
            TransferErrorCode.INVALID_TRANSITION,
            str(exc),
            item_id=exc.item_id,
            from_state=exc.from_state.value,
            to_state=exc.to_state.value,
        ) from exc

    _apply_landing_state(entry, item, new_state)
    _persist_state(registry, entry, item, sm)
    return _transition_view(item, sm, transition)


@router.get(
    "/items/{item_id}/recovery",
    response_model=RecoveryView,
    responses={404: {"description": "Item not found or foreign domain (NOT_FOUND)"}},
)
async def get_recovery_details(
    item_id: str,
    principal: PrincipalContext = Depends(get_current_principal),
    registry: TransferRegistryRepository = Depends(get_transfer_repository),
) -> RecoveryView:
    """Recovery details: recoverable / requires_new_revision / retry_target / history."""
    entry, item = _find_item(registry, item_id)
    _authorize_record_access(principal, entry.domain_id, "Transfer item")
    sm = entry.landing_for(item)
    retry_target = _RETRY_TARGET.get(sm.state)
    return RecoveryView(
        item_id=item.item_id,
        release_id=item.release_id,
        revision_key=item.revision_key,
        state=sm.state.value,
        recoverable=sm.is_recoverable(),
        requires_new_revision=sm.requires_new_revision(),
        retry_target=retry_target.value if retry_target else None,
        failure_class=item.failure_class.value if item.failure_class else None,
        failure_detail=item.failure_detail,
        history=sm.history,
    )


# ══════════════════════════════════════════════════════════════════
# COS-074/COS-077: gateway lease + dispatch (offline semantics)
# ══════════════════════════════════════════════════════════════════

class LeaseIn(BaseModel):
    """Запрос gateway lease на отправку revision."""
    ttl_seconds: int = Field(..., gt=0, le=86400)
    gateway_id: str = Field(default="gateway-default", min_length=1)


class LeaseView(BaseModel):
    lease_id: str
    revision_key: str
    item_id: str
    gateway_id: str
    issued_at: datetime
    ttl_seconds: int
    expires_at: datetime
    state: str


class RevokeView(BaseModel):
    item_id: str
    revision_key: str
    revoked: bool


class DispatchIn(BaseModel):
    """V1 driver hook: физические адаптеры вне scope, dispatch фиксирует
    readiness и lease-семантику (kernel DiodeAdapter остаётся вне API)."""
    simulate: Dict[str, bool] = Field(
        default_factory=dict,
        description="simulate.transport_failure → record_transfer_retryable",
    )


class DispatchView(BaseModel):
    item_id: str
    release_id: str
    revision_key: str
    transport_profile: str
    state: str
    lease_id: Optional[str] = None
    retry_count: int = 0


def _lease_violation(exc: LeaseRequiredError) -> HTTPException:
    """COS-077: lease-нарушение → 423 LOCKED по error contract.

    Reason из kernel (no lease issued / lease revoked / lease expired) —
    в details; код единый GATEWAY_LEASE_REQUIRED.
    """
    return transfer_error(
        status.HTTP_423_LOCKED,
        TransferErrorCode.GATEWAY_LEASE_REQUIRED,
        f"Gateway lease violation for revision '{exc.revision_key}': {exc.reason}",
        revision_key=exc.revision_key,
        reason=exc.reason,
    )


@router.post(
    "/items/{item_id}/lease",
    response_model=LeaseView,
    responses={
        200: {"description": "Lease issued (previous active lease on the same revision revoked)"},
        404: {"description": "Item not found or foreign domain (NOT_FOUND)"},
        422: {"description": "Item без package_revision"},
    },
)
async def issue_gateway_lease(
    item_id: str,
    body: LeaseIn,
    principal: PrincipalContext = Depends(require_capability(Action.RELEASE_TRANSFER)),
    registry: TransferRegistryRepository = Depends(get_transfer_repository),
) -> LeaseView:
    """Выдать gateway lease (single-active на revision_key; новый issue
    отзывает предыдущий — kernel инвариант COS-074)."""
    entry, item = _find_item(registry, item_id)
    _authorize_record_access(principal, entry.domain_id, "Transfer item")
    if item.package_revision is None:
        raise transfer_error(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            TransferErrorCode.VALIDATION_FAILURE,
            f"Item '{item.item_id}' has no package_revision; lease is meaningless",
        )
    lease = get_gateway_leases().issue(
        item.revision_key, item.item_id, body.gateway_id, body.ttl_seconds,
    )
    return LeaseView(
        lease_id=lease.lease_id,
        revision_key=lease.revision_key,
        item_id=lease.item_id,
        gateway_id=lease.gateway_id,
        issued_at=lease.issued_at,
        ttl_seconds=lease.ttl_seconds,
        expires_at=lease.expires_at,
        state=lease.state.value,
    )


@router.delete(
    "/items/{item_id}/lease",
    response_model=RevokeView,
    responses={404: {"description": "Item not found or foreign domain (NOT_FOUND)"}},
)
async def revoke_gateway_lease(
    item_id: str,
    principal: PrincipalContext = Depends(require_capability(Action.RELEASE_TRANSFER)),
    registry: TransferRegistryRepository = Depends(get_transfer_repository),
) -> RevokeView:
    """Отозвать активный lease (идемпотентно: revoked=False если не было)."""
    entry, item = _find_item(registry, item_id)
    _authorize_record_access(principal, entry.domain_id, "Transfer item")
    revision_key = item.revision_key
    revoked = bool(revision_key) and get_gateway_leases().revoke(revision_key)
    return RevokeView(item_id=item.item_id, revision_key=revision_key, revoked=revoked)


@router.post(
    "/items/{item_id}/dispatch",
    response_model=DispatchView,
    responses={
        200: {"description": "Dispatch accepted (item status → dispatched)"},
        409: {"description": "CONFLICT — item уже в полёте/терминальном статусе"},
        404: {"description": "Item not found or foreign domain (NOT_FOUND)"},
        422: {"description": "Item без package_revision"},
        423: {"description": "GATEWAY_LEASE_REQUIRED — нет активного lease "
                             "(missing/expired/revoked) для CONTROLLED_GATEWAY_RELAY"},
    },
)
async def dispatch_transfer_item(
    item_id: str,
    body: Optional[DispatchIn] = None,
    principal: PrincipalContext = Depends(require_capability(Action.RELEASE_TRANSFER)),
    registry: TransferRegistryRepository = Depends(get_transfer_repository),
) -> DispatchView:
    """Dispatch item'а в транспорт.

    COS-074 parity: для CONTROLLED_GATEWAY_RELAY требуется активный lease —
    отказ ДО любых мутаций (status/attempts не растут). Остальные профили
    dispatch без lease (прямой authenticated API / one-way diode без grant).
    """
    entry, item = _find_item(registry, item_id)
    _authorize_record_access(principal, entry.domain_id, "Transfer item")
    if item.package_revision is None:
        raise transfer_error(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            TransferErrorCode.VALIDATION_FAILURE,
            f"Item '{item.item_id}' has no package_revision; dispatch impossible",
        )
    if item.status not in (TransferItemStatus.DRAFT, TransferItemStatus.VALIDATED):
        raise transfer_error(
            status.HTTP_409_CONFLICT,
            TransferErrorCode.CONFLICT,
            f"Item '{item.item_id}' is not dispatchable from status "
            f"'{item.status.value}'",
            item_status=item.status.value,
        )

    revision_key = item.revision_key
    lease_id: Optional[str] = None
    if item.transport_profile is TransportProfile.CONTROLLED_GATEWAY_RELAY:
        try:
            lease = get_gateway_leases().validate(revision_key)
        except LeaseRequiredError as exc:
            raise _lease_violation(exc) from exc
        lease_id = lease.lease_id

    # simulate-хук: честный retryable transport failure (runtime-лог kernel)
    payload = body or DispatchIn()
    if payload.simulate.get("transport_failure"):
        retry_count = registry.record_transfer_retryable(
            item.item_id,
            failure_class=TransferFailureClass.TRANSPORT_FAILURE,
            detail="simulated transport failure on dispatch",
        )
        # зеркалим kernel-мутации в in-memory item (save_item не перетирает)
        item.retry_count = retry_count
        item.failure_class = TransferFailureClass.TRANSPORT_FAILURE
        item.failure_detail = "simulated transport failure on dispatch"
        item.updated_at = datetime.now(timezone.utc)
        entry.plan.compute_status()
        sm = entry.landing_for(item)
        _persist_state(registry, entry, item, sm)
        return DispatchView(
            item_id=item.item_id,
            release_id=item.release_id,
            revision_key=revision_key,
            transport_profile=item.transport_profile.value,
            state="transport_failed_retryable",
            lease_id=lease_id,
            retry_count=retry_count,
        )

    item.status = TransferItemStatus.DISPATCHED
    item.updated_at = datetime.now(timezone.utc)
    entry.plan.compute_status()
    _persist_state(registry, entry, item, entry.landing_for(item))
    return DispatchView(
        item_id=item.item_id,
        release_id=item.release_id,
        revision_key=revision_key,
        transport_profile=item.transport_profile.value,
        state=TransferItemStatus.DISPATCHED.value,
        lease_id=lease_id,
        retry_count=item.retry_count,
    )
