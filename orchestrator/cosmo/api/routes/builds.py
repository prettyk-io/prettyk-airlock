"""
Cosmoport 2.0 — Builds REST API Endpoints.

SAN-012: Первоклассная сущность Build (Сборка).
COS-196: реальное исполнение за триггером — сборка оборачивает принятый
runs-контур (run → submit plan-batch'ей → Woodpecker pipeline → digest →
Evidence), статус честно реконсилится по прогону, артефакты — из durable
ArtifactRecord (COS-163/164), логи — из реального исполнения (или честное
«недоступно»). Второй build-механизм не создаётся.
"""
from __future__ import annotations

import asyncio
import datetime
import logging
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.cosmo.api.deps import get_db, get_current_principal, require_capability
from orchestrator.cosmo.api.domain_guard import resolve_caller_domain, verify_ownership
from orchestrator.cosmo.db.models import (
    Application as ApplicationModel,
    Batch as BatchModel,
    Build as BuildModel,
    EvidenceLedgerEntry,
    PipelinePlan as PlanModel,
    RepositoryBinding as RepoBindingModel,
    Run as RunModel,
)
from orchestrator.cosmo.db.models_execution import ExecutionHandleRow
from orchestrator.cosmo.db.models_lr import ProjectApplication as ProjectAppModel
from orchestrator.cosmo.domain.build_model import Build
from orchestrator.cosmo.domain.rbac import Action, PrincipalContext

logger = logging.getLogger("cosmo.builds")

router = APIRouter(tags=["builds"])

#: COS-196: терминальный статус прогона → статус сборки (честный маппинг).
_RUN_TO_BUILD_STATUS = {
    "succeeded": "success",
    "failed": "failed",
    "blocked": "failed",
    "cancelled": "aborted",
}

#: Терминальные статусы прогона (защита от отката build назад).
_TERMINAL_RUN_STATUSES = frozenset({"succeeded", "failed", "blocked", "cancelled"})

#: COS-196: кап логов в деталях сборки (честная граница отдачи).
_MAX_LOG_LINES = 2000
_MAX_LOG_CHARS = 120_000
#: Таймаут похода в Woodpecker за логами.
_WP_LOGS_TIMEOUT_S = 20.0


# ── Schemas ──────────────────────────────────────────────────────────────────

class TriggerBuildRequest(BaseModel):
    commit_sha: str = Field(..., min_length=7, description="Git commit SHA")
    branch: str = Field(default="main", min_length=1, description="Ветка репозитория")
    initiator_user_id: Optional[str] = Field(default=None, description="Инициатор сборки")
    meta: Dict[str, Any] = Field(default_factory=dict, description="Параметры сборки")


class CreateBuildRequest(BaseModel):
    """COS-196: контракт клиента (Control Station) — то, что шлёт UI."""
    app_id: str = Field(..., min_length=1, description="ID приложения")
    commit_sha: str = Field(..., min_length=7, description="Git commit SHA")
    branch: str = Field(default="main", min_length=1, description="Ветка репозитория")
    title: str = Field(default="", description="Название сборки")


def _to_build_schema(bm: BuildModel, *, app_name: Optional[str] = None) -> Build:
    meta = bm.meta or {}
    return Build(
        id=bm.id,
        app_id=bm.app_id,
        domain_id=bm.domain_id,
        title=bm.title or "",
        commit_sha=bm.commit_sha,
        branch=bm.branch,
        status=bm.status,  # type: ignore
        artifacts=bm.artifacts or [],
        started_at=bm.started_at,
        finished_at=bm.finished_at,
        initiator_user_id=bm.initiator_user_id,
        initiator=bm.initiator_user_id,
        app_name=app_name,
        run_id=meta.get("run_id"),
        evidence_refs=list(meta.get("evidence_refs") or []),
        build_logs=bm.build_logs or "",
        meta=meta,
    )


def _execution_service(request: Optional[Request]) -> Any | None:
    """COS-196: живой execution-контур из app.state (канон runs.py)."""
    state = getattr(getattr(request, "app", None), "state", None)
    return getattr(state, "execution_service", None)


# ── Reconcile: сборка ↔ прогон (честный статус/артефакт) ─────────────────────

async def _artifact_refs_for_run(db: AsyncSession, run_id: str) -> List[str]:
    """Canonical-ref'ы durable ArtifactRecord прогона (COS-163/164)."""
    from orchestrator.cosmo.ledger.artifact_record import (
        artifact_records_for_run_ids,
    )
    records = await artifact_records_for_run_ids(db, [run_id])
    return [record.canonical_ref() for record in records]


async def _evidence_entry_ids(db: AsyncSession, run_id: str) -> List[str]:
    res = await db.execute(
        select(EvidenceLedgerEntry.id)
        .where(EvidenceLedgerEntry.run_id == run_id)
        .order_by(EvidenceLedgerEntry.created_at, EvidenceLedgerEntry.id)
    )
    return [row[0] for row in res.all()]


async def _failure_reason(db: AsyncSession, run_id: str, run: RunModel) -> str:
    """Честная причина провала: durable-след ручки → статус прогона."""
    res = await db.execute(
        select(ExecutionHandleRow.reason).where(
            ExecutionHandleRow.run_id == run_id,
            ExecutionHandleRow.reason.is_not(None),
        )
    )
    reasons = [str(row[0]) for row in res.all() if row[0]]
    if reasons:
        return "; ".join(reasons[:3])
    if run.status == "failed":
        return "прогон завершился с ошибкой (degraded)"
    if run.status == "blocked":
        return "прогон заблокирован (гейт/падение батча)"
    return f"прогон в статусе '{run.status}'"


async def _reconcile_build(db: AsyncSession, bm: BuildModel) -> None:
    """COS-196: честная сверка сборки с её прогоном — по факту, без выдумок.

    - run terminal → build terminal (succeeded→success; failed/blocked→failed;
      cancelled→aborted), finished_at — из прогона;
    - успех: artifacts — canonical_ref durable ArtifactRecord; пустой список
      не подменяется выдумкой (честная пометка в meta);
    - провал: артефактов нет (без фантома) + причина;
    - evidence_refs — id записей ledger по прогону (обновляются всегда).
    """
    meta = dict(bm.meta or {})
    run_id = meta.get("run_id")
    if not run_id:
        return
    dirty = False

    run = await db.get(RunModel, run_id)
    if run is None:
        if meta.get("run_error") != "linked run not found":
            meta["run_error"] = "linked run not found"
            dirty = True
    else:
        entry_ids = await _evidence_entry_ids(db, run_id)
        if entry_ids and list(meta.get("evidence_refs") or []) != entry_ids:
            meta["evidence_refs"] = entry_ids
            dirty = True

        if bm.status in ("pending", "running"):
            new_status = _RUN_TO_BUILD_STATUS.get(run.status)
            if new_status:
                bm.status = new_status
                bm.finished_at = run.finished_at or datetime.datetime.utcnow()
                if new_status == "success":
                    refs = await _artifact_refs_for_run(db, run_id)
                    bm.artifacts = refs
                    if not refs and not meta.get("artifact_note"):
                        meta["artifact_note"] = (
                            "прогон успешен, durable ArtifactRecord по digest "
                            "не найден"
                        )
                else:
                    # Без фантома: провал/отмена не оставляют артефактов.
                    bm.artifacts = []
                    meta["failure_reason"] = await _failure_reason(db, run_id, run)
                dirty = True
            elif run.status == "running" and bm.status == "pending":
                bm.status = "running"
                dirty = True

    if dirty:
        bm.meta = meta
        await db.commit()


# ── Логи исполнения (Woodpecker, честная недоступность) ──────────────────────

def _wp_logs_for_handle(handle: dict) -> str:
    """Синхронный сбор логов пайплайна из Woodpecker (вызывать в to_thread)."""
    from orchestrator.cosmo.api.woodpecker_client import build_woodpecker
    wp = build_woodpecker()
    detail = wp.get_pipeline(handle)
    parts: List[str] = []
    for step in wp._flatten_steps(detail):
        name = str(step.get("name"))
        state = str(step.get("state"))
        parts.append(f"## {name} [{state}]")
        step_id = step.get("id")
        if step_id is None:
            continue
        try:
            lines = wp.get_step_logs_by_id(handle, step_id)
        except Exception as exc:  # noqa: BLE001 — шаг без логов не роняет сбор
            parts.append(f"[логи шага недоступны: {exc}]")
            continue
        parts.extend(str(line) for line in lines)
    return "\n".join(parts)


async def _collect_run_logs(db: AsyncSession, run_id: str) -> tuple[str, Optional[str]]:
    """COS-196: реальные логи исполнения сборки (или честная причина).

    Возвращает ``(text, error)``: ``text="" + error=None`` — исполнение ещё
    не оставило логов (не выдумываем); ``text="" + error`` — логи недоступны
    (WP недоступен/отверг), причина честно отдаётся наружу.
    """
    res = await db.execute(
        select(ExecutionHandleRow)
        .where(ExecutionHandleRow.run_id == run_id)
        .order_by(ExecutionHandleRow.created_at)
    )
    rows = list(res.scalars().all())
    handles = [
        r.as_handle_dict() for r in rows
        if r.wp_number is not None and r.repo_id is not None
    ]
    if not handles:
        return "", None

    texts: List[str] = []
    errors: List[str] = []
    for handle in handles:
        try:
            text = await asyncio.wait_for(
                asyncio.to_thread(_wp_logs_for_handle, handle),
                timeout=_WP_LOGS_TIMEOUT_S,
            )
        except Exception as exc:  # noqa: BLE001 — честная недоступность
            errors.append(f"pipeline #{handle.get('number')}: {exc}")
            continue
        if text:
            texts.append(text)

    if not texts:
        return "", ("; ".join(errors) if errors else None)

    joined = "\n".join(texts)
    lines = joined.splitlines()
    if len(lines) > _MAX_LOG_LINES:
        joined = (
            f"[... логи обрезаны: показаны последние {_MAX_LOG_LINES} строк ...]\n"
            + "\n".join(lines[-_MAX_LOG_LINES:])
        )
    if len(joined) > _MAX_LOG_CHARS:
        joined = joined[-_MAX_LOG_CHARS:]
    return joined, ("; ".join(errors) if errors else None)


# ── Вспомогательные резолвы ──────────────────────────────────────────────────

async def _project_app_ids(db: AsyncSession, project_id: str) -> List[str]:
    res = await db.execute(
        select(ProjectAppModel.app_id).where(
            ProjectAppModel.project_id == project_id
        )
    )
    return [row[0] for row in res.all()]


async def _resolve_build_plan(
    db: AsyncSession, app: ApplicationModel,
) -> tuple[Optional[str], List[str], List[str]]:
    """COS-196: план сборки приложения (pipeline_plan_id → latest) + батчи.

    Возвращает ``(plan_id, batch_ids, batch_statuses)``.
    """
    plan: Optional[PlanModel] = None
    plan_id = getattr(app, "pipeline_plan_id", None)
    if plan_id:
        plan = await db.get(PlanModel, plan_id)
    if plan is None:
        res = await db.execute(
            select(PlanModel)
            .where(PlanModel.app_id == app.id)
            .order_by(PlanModel.compiled_at.desc())
            .limit(1)
        )
        plan = res.scalars().first()
    if plan is None:
        return None, [], []
    res = await db.execute(
        select(BatchModel.id, BatchModel.status)
        .where(BatchModel.plan_id == plan.id)
        .order_by(BatchModel.id)
    )
    rows = res.all()
    return plan.id, [row[0] for row in rows], [str(row[1]) for row in rows]


async def _repo_path_for_app(db: AsyncSession, app_id: str) -> tuple[str, str]:
    """(repo_path, default_branch) приложения — из binding (COS-096)."""
    res = await db.execute(
        select(RepoBindingModel)
        .where(RepoBindingModel.app_id == app_id)
        .order_by(RepoBindingModel.id)
        .limit(1)
    )
    binding = res.scalars().first()
    if binding is None:
        return "", "main"
    return binding.repo_path or "", binding.default_branch or "main"


async def _create_and_trigger_build(
    db: AsyncSession,
    *,
    app: ApplicationModel,
    commit_sha: str,
    branch: str,
    title: str,
    initiator_user_id: str,
    request: Optional[Request],
    extra_meta: Optional[Dict[str, Any]] = None,
) -> Build:
    """COS-196: сборка = запись + прогон принятого runs-контура.

    Второй механизм не создаётся: исполнение — submit plan-batch'ей через
    ``execution_service.submit_run`` (канон COS-097). Executor выключен →
    честный провал на старте (запись с причиной, без run'а и фантома;
    «вечный running» исключён). Плана/батчей нет → честный 400.
    """
    plan_id, batch_ids, batch_statuses = await _resolve_build_plan(db, app)
    if not plan_id or not batch_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Application '{app.id}' has no compiled build plan — "
                f"сначала скомпилируйте план сборки"
            ),
        )
    # COS-196: план уже исполнялся (resubmit-guard COS-097 не поднимет его
    # батчи повторно) — сборка залипла бы в running. Честно: новый билд =
    # новый скомпилированный план.
    if any(s != "pending" for s in batch_statuses):
        states = ", ".join(sorted(set(batch_statuses)))
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Plan '{plan_id}' уже исполнялся (батчи: {states}) — "
                f"скомпилируйте новый план сборки"
            ),
        )

    now = datetime.datetime.utcnow()
    build_id = f"bld-{uuid.uuid4().hex[:8]}"
    repo_path, default_branch = await _repo_path_for_app(db, app.id)
    effective_branch = branch or default_branch or "main"

    exec_service = _execution_service(request)
    if exec_service is None:
        # Честный провал на старте: сборка-запись есть, причина видна,
        # прогон не создаётся (нечего исполнять) — фантома нет.
        bm = BuildModel(
            id=build_id,
            app_id=app.id,
            domain_id=app.domain_id,
            title=title or f"Build {app.id}@{commit_sha[:8]}",
            commit_sha=commit_sha,
            branch=effective_branch,
            status="failed",
            artifacts=[],
            build_logs="",
            initiator_user_id=initiator_user_id or "system",
            meta={
                "plan_id": plan_id,
                "repo": repo_path,
                "batch_ids": batch_ids,
                "source": "build-api",
                "failure_reason": (
                    "execution disabled: живой контур выключен "
                    "(COSMO_EXECUTOR_ENABLED) — сборка не запущена"
                ),
            },
            started_at=now,
            finished_at=now,
        )
        db.add(bm)
        await db.commit()
        await db.refresh(bm)
        logger.warning("COS-196 build %s not started: execution disabled", build_id)
        return _to_build_schema(bm)

    run_id = f"run-bld-{uuid.uuid4().hex[:10]}"

    run = RunModel(
        id=run_id,
        plan_id=plan_id,
        trigger="manual",
        initiator_user_id=initiator_user_id or "system",
        initiator_role="developer",
        domain_id=app.domain_id,
        status="running",
        findings_refs=[],
        started_at=now,
        created_at=now,
    )
    db.add(run)

    meta: Dict[str, Any] = {
        "run_id": run_id,
        "plan_id": plan_id,
        "repo": repo_path,
        "batch_ids": batch_ids,
        "source": "build-api",
    }
    if extra_meta:
        meta.update(extra_meta)

    bm = BuildModel(
        id=build_id,
        app_id=app.id,
        domain_id=app.domain_id,
        title=title or f"Build {app.id}@{commit_sha[:8]}",
        commit_sha=commit_sha,
        branch=effective_branch,
        status="running",
        artifacts=[],
        build_logs="",
        initiator_user_id=initiator_user_id or "system",
        meta=meta,
        started_at=now,
        finished_at=None,
    )
    db.add(bm)
    await db.commit()
    await db.refresh(bm)

    # Живой цикл: run → running → submit plan-batch'ей (канон COS-097).
    try:
        await exec_service.submit_run(run_id)
    except Exception as exc:  # noqa: BLE001 — fire-and-forget, след в логах
        logger.warning("Build %s submit_run failed: %s", build_id, exc)

    logger.info("COS-196 build %s triggered: app=%s run=%s plan=%s",
                build_id, app.id, run_id, plan_id)
    return _to_build_schema(bm)


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.get("/api/v1/builds", response_model=List[Build])
async def list_builds(
    app_id: Optional[str] = Query(None, description="Фильтр по приложению"),
    project_id: Optional[str] = Query(None, description="Фильтр по проекту (LR-001)"),
    status_f: Optional[str] = Query(None, alias="status", description="Фильтр по статусу"),
    branch: Optional[str] = Query(None, description="Фильтр по ветке"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    caller_domain: str | None = Header(None, alias="X-Cosmo-Domain"),
    principal: PrincipalContext = Depends(get_current_principal),
    db: AsyncSession = Depends(get_db),
) -> List[Build]:
    """COS-196: сводный реестр сборок (клиентская поверхность Control Station).

    Живой ответ вместо 404/405: фильтры app_id/project_id/status/branch.
    Видимость: не-админ — свой домен (единый резолв COS-067/083); админ —
    сводная картина по КИТС (паттерн projects.py). Активные сборки сверяются
    с прогоном (bounded, best-effort).
    """
    stmt = select(BuildModel)
    if not principal.is_system_admin:
        caller = resolve_caller_domain(principal, caller_domain)
        stmt = stmt.where(BuildModel.domain_id == caller)
    if app_id:
        stmt = stmt.where(BuildModel.app_id == app_id)
    if project_id:
        stmt = stmt.where(
            BuildModel.app_id.in_(await _project_app_ids(db, project_id))
        )
    if status_f:
        stmt = stmt.where(BuildModel.status == status_f)
    if branch:
        stmt = stmt.where(BuildModel.branch == branch)
    # COS-083 unit-стиль: прямой вызов хендлера даёт дефолты FastAPI — Query.
    lim = int(limit) if isinstance(limit, (int, str)) and not hasattr(limit, "default") else 50
    off = int(offset) if isinstance(offset, (int, str)) and not hasattr(offset, "default") else 0
    stmt = stmt.order_by(BuildModel.created_at.desc()).offset(off).limit(lim)

    res = await db.execute(stmt)
    builds = list(res.scalars().all())

    for bm in builds:
        if bm.status in ("pending", "running"):
            try:
                await _reconcile_build(db, bm)
            except Exception as exc:  # noqa: BLE001 — реестр не роняем
                logger.warning("Build reconcile failed for %s: %s", bm.id, exc)

    return [_to_build_schema(b) for b in builds]


@router.post("/api/v1/builds", response_model=Build, status_code=status.HTTP_201_CREATED)
async def create_build(
    body: CreateBuildRequest,
    request: Request,
    caller_domain: str | None = Header(None, alias="X-Cosmo-Domain"),
    principal: PrincipalContext = Depends(require_capability(Action.BUILD_RUN, domain_binding="identity")),
    db: AsyncSession = Depends(get_db),
) -> Build:
    """COS-196: запуск сборки из клиента (Control Station) — реальное исполнение.

    Принимает то, что шлёт UI: ``{app_id, title, branch, commit_sha}``.
    """
    app = await db.get(ApplicationModel, body.app_id)
    if not app:
        raise HTTPException(status_code=404, detail=f"Application '{body.app_id}' not found")
    if not principal.is_system_admin:
        verify_ownership(app.domain_id, resolve_caller_domain(principal, caller_domain), f"Application '{body.app_id}'")
    return await _create_and_trigger_build(
        db,
        app=app,
        commit_sha=body.commit_sha,
        branch=body.branch,
        title=body.title,
        initiator_user_id=principal.user_id,
        request=request,
    )


@router.get("/api/v1/apps/{app_id}/builds", response_model=List[Build])
async def list_app_builds(
    app_id: str,
    branch: Optional[str] = Query(None, description="Фильтр по ветке"),
    status_f: Optional[str] = Query(None, alias="status", description="Фильтр по статусу"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    caller_domain: str | None = Header(None, alias="X-Cosmo-Domain"),
    principal: PrincipalContext = Depends(get_current_principal),
    db: AsyncSession = Depends(get_db),
) -> List[Build]:
    """Список сборок конкретного приложения (SAN-012 + честный статус COS-196)."""
    app = await db.get(ApplicationModel, app_id)
    if not app:
        raise HTTPException(status_code=404, detail=f"Application '{app_id}' not found")

    # COS-083: единый резолв домена caller'а (админ — context switch по заголовку)
    if not principal.is_system_admin:
        verify_ownership(app.domain_id, resolve_caller_domain(principal, caller_domain), f"Application '{app_id}'")

    stmt = select(BuildModel).where(BuildModel.app_id == app_id).order_by(BuildModel.created_at.desc())
    if branch:
        stmt = stmt.where(BuildModel.branch == branch)
    if status_f:
        stmt = stmt.where(BuildModel.status == status_f)

    lim = int(limit) if isinstance(limit, (int, str)) and not hasattr(limit, "default") else 50
    off = int(offset) if isinstance(offset, (int, str)) and not hasattr(offset, "default") else 0
    stmt = stmt.offset(off).limit(lim)
    res = await db.execute(stmt)
    builds = list(res.scalars().all())

    for bm in builds:
        if bm.status in ("pending", "running"):
            try:
                await _reconcile_build(db, bm)
            except Exception as exc:  # noqa: BLE001 — список не роняем
                logger.warning("Build reconcile failed for %s: %s", bm.id, exc)

    return [_to_build_schema(b) for b in builds]


@router.post("/api/v1/apps/{app_id}/builds", response_model=Build, status_code=status.HTTP_201_CREATED)
async def trigger_app_build(
    app_id: str,
    body: TriggerBuildRequest,
    request: Request,
    caller_domain: str | None = Header(None, alias="X-Cosmo-Domain"),
    principal: PrincipalContext = Depends(require_capability(Action.BUILD_RUN, domain_binding="identity")),
    db: AsyncSession = Depends(get_db),
) -> Build:
    """SAN-012 + COS-196: запуск сборки приложения — реальное исполнение.

    COS-083: write требует capability build:run (не просто principal).
    COS-196: за триггером — реальный прогон (runs-контур), не заглушка.
    """
    app = await db.get(ApplicationModel, app_id)
    if not app:
        raise HTTPException(status_code=404, detail=f"Application '{app_id}' not found")

    # COS-083: единый резолв домена caller'а; COS-032: admin обходит проверку
    if not principal.is_system_admin:
        verify_ownership(app.domain_id, resolve_caller_domain(principal, caller_domain), f"Application '{app_id}'")

    return await _create_and_trigger_build(
        db,
        app=app,
        commit_sha=body.commit_sha,
        branch=body.branch,
        title="",
        initiator_user_id=body.initiator_user_id or principal.user_id,
        request=request,
        extra_meta=dict(body.meta or {}),
    )


@router.get("/api/v1/builds/{build_id}", response_model=Build)
async def get_build_details(
    build_id: str,
    caller_domain: str | None = Header(None, alias="X-Cosmo-Domain"),
    principal: PrincipalContext = Depends(get_current_principal),
    db: AsyncSession = Depends(get_db),
) -> Build:
    """COS-196: детали сборки — честный статус, реальные логи, digest, evidence."""
    bm = await db.get(BuildModel, build_id)
    if not bm:
        raise HTTPException(status_code=404, detail=f"Build '{build_id}' not found")

    # COS-032: system admin обходит доменную проверку (как runs cancel/compile).
    if not principal.is_system_admin:
        verify_ownership(bm.domain_id, resolve_caller_domain(principal, caller_domain), f"Build '{build_id}'")

    try:
        await _reconcile_build(db, bm)
    except Exception as exc:  # noqa: BLE001 — детали не роняем
        logger.warning("Build reconcile failed for %s: %s", build_id, exc)

    meta = dict(bm.meta or {})
    run_id = meta.get("run_id")
    dirty = False
    if run_id:
        text, err = await _collect_run_logs(db, run_id)
        if text and bm.build_logs != text:
            bm.build_logs = text
            dirty = True
        if err:
            if meta.get("logs_error") != err:
                meta["logs_error"] = err
                dirty = True
        elif meta.pop("logs_error", None) is not None:
            dirty = True
        if dirty:
            bm.meta = meta
            await db.commit()

    return _to_build_schema(bm)


@router.post("/api/v1/builds/{build_id}/abort", response_model=Build)
async def abort_build(
    build_id: str,
    request: Request,
    caller_domain: str | None = Header(None, alias="X-Cosmo-Domain"),
    principal: PrincipalContext = Depends(require_capability(Action.BUILD_RUN, domain_binding="identity")),
    db: AsyncSession = Depends(get_db),
) -> Build:
    """COS-196: прерывание сборки = отмена её прогона (канон runs cancel).

    COS-083: write требует capability build:run.
    """
    bm = await db.get(BuildModel, build_id)
    if not bm:
        raise HTTPException(status_code=404, detail=f"Build '{build_id}' not found")

    # COS-032: system admin обходит доменную проверку.
    if not principal.is_system_admin:
        verify_ownership(bm.domain_id, resolve_caller_domain(principal, caller_domain), f"Build '{build_id}'")

    if bm.status not in ("pending", "running"):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot abort build in status '{bm.status}'",
        )

    meta = dict(bm.meta or {})
    run_id = meta.get("run_id")
    if run_id:
        run = await db.get(RunModel, run_id)
        if run is not None and run.status not in _TERMINAL_RUN_STATUSES:
            run.status = "cancelled"
            run.finished_at = datetime.datetime.utcnow()
        exec_service = _execution_service(request)
        if exec_service is not None:
            try:
                await exec_service.cancel_run(run_id)
            except Exception as exc:  # noqa: BLE001 — отмена PG всё равно фиксируется
                logger.warning("Build %s cancel_run failed: %s", build_id, exc)

    bm.status = "aborted"
    bm.finished_at = datetime.datetime.utcnow()
    bm.build_logs = (bm.build_logs or "") + "\n[ABORTED] Build cancelled by operator.\n"
    await db.commit()
    await db.refresh(bm)
    return _to_build_schema(bm)
