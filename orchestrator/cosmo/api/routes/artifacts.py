"""COS-066: Artifact Retention API — плановая очистка, статус хранилища.

COS-142 (PK-C-003.4): + canonical tag / bundle manifest digest-pin —
верификация манифеста и чтение подтверждённого манифеста по ``bundle_id``.
COS-147/148 (PK-C-003.4): + attestation bundle релиза (provenance-конверт) и
офлайн-верификация целостности airgap-пакета.
COS-152: read-поверхности (manifest / attestation / airgap) читают актуальный
якорь из ``evidence_ledger`` (latest wins) — единственный источник истины,
рестарт cosmo-api не теряет GET-ответы.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.cosmo.api.deps import (
    get_db,
    require_principal,
    require_system_admin,
)
from orchestrator.cosmo.domain.airgap_bundle import (
    AirgapVerifyRequest,
    AirgapVerifyResponse,
)
from orchestrator.cosmo.domain.artifact_manifest import (
    ArtifactBundleManifest,
    ManifestVerificationResult,
)
from orchestrator.cosmo.domain.evidence_attestation import (
    EvidenceAttestationBundle,
)
from orchestrator.cosmo.domain.rbac import PrincipalContext
from orchestrator.cosmo.ledger.airgap_verifier import (
    AirgapBundleVerifier,
    latest_airgap_status,
)
from orchestrator.cosmo.ledger.artifact_store import ArtifactStore
from orchestrator.cosmo.ledger.attestation_packager import (
    AttestationBundlePackager,
    AttestationEvidenceError,
    latest_attestation_bundle,
)
from orchestrator.cosmo.ledger.manifest_verifier import (
    BundleManifestVerifier,
    latest_manifest,
)
from orchestrator.cosmo.ledger.retention import ArtifactRetentionManager, RetentionPolicy

router = APIRouter(prefix="/api/v1/artifacts", tags=["artifacts"])

# In-memory store (dev) — replace with DB/MinIO backend in production
_store = ArtifactStore()

# Default policy
_manager = ArtifactRetentionManager(_store)

# COS-142: верификатор манифестов бандла (stateless; чтение — из ledger)
_manifest_verifier = BundleManifestVerifier()

# COS-147: упаковщик attestation bundle релиза (stateless; чтение — из ledger)
_attestation_packager = AttestationBundlePackager()

# COS-148: офлайн-верификатор целостности airgap-пакетов (stateless)
_airgap_verifier = AirgapBundleVerifier()


# ── Schemas ────────────────────────────────────────────────────────────

class CleanupRequest(BaseModel):
    run_ids: list[str] = Field(default_factory=list, description="ID прогонов для проверки")
    dry_run: bool = Field(default=False, description="Если True — только отчёт без удаления")
    max_age_days: int = Field(default=90, ge=1, description="Максимальный возраст артефакта (дни)")
    keep_min_runs: int = Field(default=5, ge=1, description="Минимум последних прогонов для защиты")


class RetentionStatus(BaseModel):
    total_runs: int
    total_artifacts: int
    total_size_bytes: int
    total_size_mb: float
    policy: dict
    protected_run_ids: list[str]
    candidates_count: int
    candidates_freed_mb: float


class AttestationBundleRequest(BaseModel):
    """COS-147: запрос сборки attestation bundle релиза."""

    release_id: str = Field(..., min_length=1, description="ID релиза")


# ── Endpoints ───────────────────────────────────────────────────────────

@router.post("/cleanup")
async def trigger_cleanup(
    body: CleanupRequest,
    principal: PrincipalContext = Depends(require_system_admin()),
):
    """COS-066: запустить плановую очистку артефактов.

    COS-068: system-admin only — деструктивная операция (удаление
    артефактов прогонов) была доступна анонимно.
    """
    run_ids = body.run_ids or _list_all_run_dirs()

    policy = RetentionPolicy(
        max_age_days=body.max_age_days,
        keep_min_runs=body.keep_min_runs,
    )
    _manager.set_policy(policy)

    result = _manager.purge_expired(run_ids, dry_run=body.dry_run)
    return result


@router.get("/retention/status", response_model=RetentionStatus)
async def retention_status(
    principal: PrincipalContext = Depends(require_principal()),
):
    """COS-066: сводка хранилища — место, кандидаты, защищённые прогоны.

    COS-068: authentication required.
    """
    run_ids = _list_all_run_dirs()
    plan = _manager.evaluate_cleanup(run_ids)

    return RetentionStatus(
        total_runs=len(run_ids),
        total_artifacts=len(plan.candidates) + len(plan.protected),
        total_size_bytes=plan.total_candidates_bytes + plan.total_protected_bytes,
        total_size_mb=(plan.total_candidates_bytes + plan.total_protected_bytes) / (1024 * 1024),
        policy={
            "max_age_days": _manager.policy.max_age_days,
            "keep_min_runs": _manager.policy.keep_min_runs,
            "protected_tags": _manager.policy.protected_tags,
        },
        protected_run_ids=sorted(_manager._protected_run_ids),
        candidates_count=len(plan.candidates),
        candidates_freed_mb=plan.total_candidates_mb,
    )


# ── COS-142: bundle manifest (PK-C-003.4) ───────────────────────────────

@router.post("/manifest/verify", response_model=ManifestVerificationResult)
async def verify_artifact_manifest(
    body: ArtifactBundleManifest,
    principal: PrincipalContext = Depends(require_principal()),
    session: AsyncSession = Depends(get_db),
):
    """COS-142: верифицировать манифест бандла, посчитать digest-pin, зафиксировать.

    Расхождение формата (невалидный tag/digest, тег ``latest``) — 422 от
    валидаторов DTO. Семантический вердикт (mismatch ``expected_digest_pin``,
    отсутствующий прогон для якоря) возвращается как ``valid=false`` с
    ``errors`` — это расчёт, а не ошибка запроса.
    """
    return await _manifest_verifier.verify(session, body)


@router.get("/manifest/{bundle_id}", response_model=ArtifactBundleManifest)
async def read_artifact_manifest(
    bundle_id: str,
    principal: PrincipalContext = Depends(require_principal()),
    session: AsyncSession = Depends(get_db),
):
    """COS-142/COS-152: прочитать подтверждённый манифест из ledger.

    Источник истины — ``evidence_ledger`` (latest wins по ``bundle_id``);
    in-memory реестра нет, ответ переживает рестарт cosmo-api. 404, если
    манифест не якорён (non-durable edge: верификация без ``run_id``).
    """
    manifest = await latest_manifest(session, bundle_id)
    if manifest is None:
        raise HTTPException(
            status_code=404,
            detail=f"verified manifest '{bundle_id}' not found",
        )
    return manifest


# ── COS-147: release attestation bundle ─────────────────────────────────

@router.post("/attestation/bundle", response_model=EvidenceAttestationBundle)
async def build_attestation_bundle(
    body: AttestationBundleRequest,
    principal: PrincipalContext = Depends(require_principal()),
    session: AsyncSession = Depends(get_db),
):
    """COS-147: собрать и зафиксировать полный attestation bundle релиза.

    Агрегирует манифест бандла (COS-142), аттестацию SBOM (COS-138) и клиренс
    Quality Gate (COS-141), считает канонический root-хэш, валидирует
    непрерывность цепочки свидетельств и пишет конверт в evidence ledger.
    Непрерывность нарушена → ``verified=false`` (вердикт, не ошибка запроса).
    """
    try:
        return await _attestation_packager.build(session, body.release_id)
    except AttestationEvidenceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))


@router.get("/attestation/{release_id}", response_model=EvidenceAttestationBundle)
async def read_attestation_bundle(
    release_id: str,
    principal: PrincipalContext = Depends(require_principal()),
    session: AsyncSession = Depends(get_db),
):
    """COS-147/COS-152: актуальный attestation bundle релиза из ledger.

    Источник истины — ``evidence_ledger`` (latest wins по ``release_id``);
    in-memory реестра нет, ответ переживает рестарт cosmo-api. 404, если
    конверт для релиза не собран.
    """
    bundle = await latest_attestation_bundle(session, release_id)
    if bundle is None:
        raise HTTPException(
            status_code=404,
            detail=f"attestation bundle for release '{release_id}' not found",
        )
    return bundle


# ── COS-148: airgap bundle integrity ────────────────────────────────────

@router.post("/airgap/verify", response_model=AirgapVerifyResponse)
async def verify_airgap_bundle(
    body: AirgapVerifyRequest,
    principal: PrincipalContext = Depends(require_principal()),
    session: AsyncSession = Depends(get_db),
):
    """COS-148: автономная офлайн-проверка целостности airgap-пакета.

    Сверяет манифест с наблюдаемыми чексуммами архива (missing / corrupted /
    unregistered) и ``package_digest_pin``; сетевых вызовов нет. Вердикт
    фиксируется в evidence ledger при наличии локального релиза пакета.
    """
    return await _airgap_verifier.verify(session, body)


@router.get("/airgap/{package_id}", response_model=AirgapVerifyResponse)
async def read_airgap_status(
    package_id: str,
    principal: PrincipalContext = Depends(require_principal()),
    session: AsyncSession = Depends(get_db),
):
    """COS-148/COS-152: статус проверки airgap-пакета из ledger.

    Источник истины — ``evidence_ledger`` (latest wins по ``package_id``);
    in-memory реестра нет, ответ переживает рестарт cosmo-api. 404, если
    пакет не якорён (non-durable edge: у пакета не было локального релиза).
    """
    result = await latest_airgap_status(session, package_id)
    if result is None:
        raise HTTPException(
            status_code=404,
            detail=f"airgap package '{package_id}' has not been verified",
        )
    return result


# ── Helpers ────────────────────────────────────────────────────────────

def _list_all_run_dirs() -> list[str]:
    """List all run directories in the artifact store."""
    run_ids: list[str] = []
    if _store._base.is_dir():
        for entry in _store._base.iterdir():
            if entry.is_dir():
                run_ids.append(entry.name)
    return sorted(run_ids)


# ── Test helpers ────────────────────────────────────────────────────────

def _reset_retention_state() -> None:
    """Сбросить состояние менеджера (для тестов)."""
    global _store, _manager
    _store = ArtifactStore()
    _manager = ArtifactRetentionManager(_store)