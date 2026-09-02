"""Cosmoport 2.0 — Pipelines & Bricks REST API endpoints.

CRUD operations for PipelineBrick and PipelinePlan, plus Plan Compilation.
"""
from __future__ import annotations

import datetime
import uuid
from typing import Optional
from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select, delete
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.cosmo.api.deps import get_current_principal, get_db, require_capability, require_principal
from orchestrator.cosmo.api.domain_guard import resolve_caller_domain, verify_ownership
from orchestrator.cosmo.domain.rbac import Action, PrincipalContext
from orchestrator.cosmo.db.models import (
    PipelineBrick as BrickModel,
    PipelinePlan as PlanModel,
    PlanBrick as PlanBrickModel,
    Application as ApplicationModel,
    Batch as BatchModel,
    RepositoryBinding as RepoBindingModel,
)
from orchestrator.cosmo.domain.pipeline_brick import (
    PipelineBrick,
    BrickDefinition,
    BrickType,
    BrickOverride,
)
from orchestrator.cosmo.domain.run_model import Batch
from orchestrator.cosmo.compiler.plan_compiler import PlanCompiler

router = APIRouter(tags=["pipelines"])


# ── Schemas ────────────────────────────────────────────────────────────

class PipelinePlanSchema(BaseModel):
    id: str
    app_id: str
    level: str = "app"
    scope_id: str
    compiled_at: datetime.datetime
    compiled_hash: str
    brick_ids: list[str] = Field(default_factory=list)


class CreatePlanRequest(BaseModel):
    id: str = Field(..., min_length=1)
    app_id: str = Field(..., min_length=1)
    level: str = Field(default="app")
    scope_id: str = Field(default="")
    brick_ids: list[str] = Field(default_factory=list)
    compiled_hash: Optional[str] = None


class CompilePlanRequest(BaseModel):
    plan_id: str = Field(..., min_length=1)
    app_id: str = Field(..., min_length=1)
    brick_ids: list[str] = Field(..., min_length=1)
    level: str = Field(default="app")


class UpdateBrickRequest(BaseModel):
    name: Optional[str] = None
    type: Optional[BrickType] = None
    source: Optional[str] = None
    definition: Optional[BrickDefinition] = None
    depends_on: Optional[list[str]] = None
    gates: Optional[list[str]] = None


def _to_brick_schema(model: BrickModel) -> PipelineBrick:
    return PipelineBrick(
        id=model.id,
        name=model.name,
        type=model.type,  # type: ignore
        source=model.source,
        definition=BrickDefinition.model_validate(model.definition_json or {}),
        depends_on=model.depends_on or [],
        gates=model.gates or [],
    )


# ── Bricks ─────────────────────────────────────────────────────────────

@router.get("/api/v1/bricks", response_model=list[PipelineBrick])
async def list_bricks(
    brick_type: Optional[BrickType] = Query(None, alias="type", description="Filter by brick type"),
    db: AsyncSession = Depends(get_db),
    principal: PrincipalContext = Depends(require_principal()),
) -> list[PipelineBrick]:
    """List all pipeline bricks.

    COS-086: authentication required (каталог был анонимным read'ом).
    Brick — глобальный каталог (без domain_id), scoping не применяется.
    """
    stmt = select(BrickModel)
    if brick_type:
        stmt = stmt.where(BrickModel.type == brick_type)
    stmt = stmt.order_by(BrickModel.id)

    res = await db.execute(stmt)
    bricks = res.scalars().all()
    return [_to_brick_schema(b) for b in bricks]


@router.post("/api/v1/bricks", response_model=PipelineBrick, status_code=status.HTTP_201_CREATED)
async def create_brick(
    body: PipelineBrick,
    db: AsyncSession = Depends(get_db),
    principal: PrincipalContext = Depends(require_capability(Action.BRICK_MANAGE, domain_binding="identity")),
) -> PipelineBrick:
    """Register a new pipeline brick.

    COS-086: была анонимная запись — теперь capability brick:manage.
    """
    existing = await db.get(BrickModel, body.id)
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Brick with id '{body.id}' already exists",
        )

    db_brick = BrickModel(
        id=body.id,
        name=body.name,
        type=body.type,
        source=body.source,
        definition_json=body.definition.model_dump(),
        depends_on=body.depends_on,
        gates=body.gates,
    )
    db.add(db_brick)
    await db.commit()
    await db.refresh(db_brick)
    return _to_brick_schema(db_brick)


@router.get("/api/v1/bricks/{brick_id}", response_model=PipelineBrick)
async def get_brick(
    brick_id: str,
    db: AsyncSession = Depends(get_db),
    principal: PrincipalContext = Depends(require_principal()),
) -> PipelineBrick:
    """Get brick details by ID.

    COS-086: authentication required (был анонимным read'ом).
    """
    b = await db.get(BrickModel, brick_id)
    if b is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Brick '{brick_id}' not found",
        )
    return _to_brick_schema(b)


@router.put("/api/v1/bricks/{brick_id}", response_model=PipelineBrick)
async def update_brick(
    brick_id: str,
    body: UpdateBrickRequest,
    db: AsyncSession = Depends(get_db),
    principal: PrincipalContext = Depends(require_capability(Action.BRICK_MANAGE, domain_binding="identity")),
) -> PipelineBrick:
    """Update pipeline brick.

    COS-086: была анонимная запись — теперь capability brick:manage.
    """
    b = await db.get(BrickModel, brick_id)
    if b is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Brick '{brick_id}' not found",
        )

    if body.name is not None:
        b.name = body.name
    if body.type is not None:
        b.type = body.type
    if body.source is not None:
        b.source = body.source
    if body.definition is not None:
        b.definition_json = body.definition.model_dump()
    if body.depends_on is not None:
        b.depends_on = body.depends_on
    if body.gates is not None:
        b.gates = body.gates

    await db.commit()
    await db.refresh(b)
    return _to_brick_schema(b)


@router.delete("/api/v1/bricks/{brick_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_brick(
    brick_id: str,
    db: AsyncSession = Depends(get_db),
    principal: PrincipalContext = Depends(require_capability(Action.BRICK_MANAGE, domain_binding="identity")),
) -> None:
    """Delete pipeline brick.

    COS-086: была анонимная запись — теперь capability brick:manage.
    """
    b = await db.get(BrickModel, brick_id)
    if b is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Brick '{brick_id}' not found",
        )
    await db.delete(b)
    await db.commit()


# ── Plans ──────────────────────────────────────────────────────────────

@router.get("/api/v1/plans", response_model=list[PipelinePlanSchema])
async def list_plans(
    app_id: Optional[str] = Query(None, description="Filter by app ID"),
    caller_domain: str | None = Header(None, alias="X-Cosmo-Domain"),
    db: AsyncSession = Depends(get_db),
    principal: PrincipalContext = Depends(require_principal()),
) -> list[PipelinePlanSchema]:
    """List compiled pipeline plans.

    COS-086: authentication required + доменный scoping для не-админа —
    план якорится к домену через plan.app_id → Application.domain_id.
    """
    stmt = select(PlanModel).options(selectinload(PlanModel.bricks))
    if app_id:
        stmt = stmt.where(PlanModel.app_id == app_id)
    stmt = stmt.order_by(PlanModel.compiled_at.desc())

    res = await db.execute(stmt)
    plans = res.scalars().all()

    if not principal.is_system_admin and plans:
        caller = resolve_caller_domain(principal, caller_domain)
        app_ids = {p.app_id for p in plans}
        dom_res = await db.execute(
            select(ApplicationModel.id, ApplicationModel.domain_id).where(
                ApplicationModel.id.in_(app_ids)
            )
        )
        app_domain = {row[0]: row[1] for row in dom_res.all()}
        plans = [p for p in plans if app_domain.get(p.app_id) == caller]

    return [
        PipelinePlanSchema(
            id=p.id,
            app_id=p.app_id,
            level=p.level,
            scope_id=p.scope_id,
            compiled_at=p.compiled_at,
            compiled_hash=p.compiled_hash,
            brick_ids=[pb.brick_id for pb in p.bricks],
        )
        for p in plans
    ]


@router.post("/api/v1/plans", response_model=PipelinePlanSchema, status_code=status.HTTP_201_CREATED)
async def create_plan(
    body: CreatePlanRequest,
    caller_domain: str | None = Header(None, alias="X-Cosmo-Domain"),
    db: AsyncSession = Depends(get_db),
    principal: PrincipalContext = Depends(require_capability(Action.PIPELINE_CONFIGURE, domain_binding="identity")),
) -> PipelinePlanSchema:
    """Create a pipeline plan with explicit brick associations.

    COS-086: была анонимная запись — теперь capability pipeline:configure
    + ghost-404 для приложения чужого домена (единый резолв, как в compile).
    """
    app = await db.get(ApplicationModel, body.app_id)
    if app is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Application '{body.app_id}' not found",
        )

    if not principal.is_system_admin:
        verify_ownership(
            app.domain_id,
            resolve_caller_domain(principal, caller_domain),
            f"Application '{body.app_id}'",
        )

    existing = await db.get(PlanModel, body.id)
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Plan '{body.id}' already exists",
        )

    scope_id = body.scope_id or body.app_id
    compiled_hash = body.compiled_hash or uuid.uuid4().hex

    plan = PlanModel(
        id=body.id,
        app_id=body.app_id,
        level=body.level,
        scope_id=scope_id,
        compiled_at=datetime.datetime.utcnow(),
        compiled_hash=compiled_hash,
    )
    db.add(plan)
    await db.flush()

    for idx, brick_id in enumerate(body.brick_ids):
        pb = PlanBrickModel(
            id=f"pb-{uuid.uuid4().hex[:12]}",
            plan_id=body.id,
            brick_id=brick_id,
            sort_order=idx,
        )
        db.add(pb)

    await db.commit()

    return PipelinePlanSchema(
        id=plan.id,
        app_id=plan.app_id,
        level=plan.level,
        scope_id=plan.scope_id,
        compiled_at=plan.compiled_at,
        compiled_hash=plan.compiled_hash,
        brick_ids=body.brick_ids,
    )


async def _compile_and_persist(
    db: AsyncSession,
    *,
    plan_id: str,
    app_id: str,
    level: str,
    brick_ids: list[str],
    app: ApplicationModel,
) -> PipelinePlanSchema:
    """COS-096: общая компиляция + персист (compile и compile-from-source)."""
    existing = await db.get(PlanModel, plan_id)
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Plan '{plan_id}' already exists",
        )

    # Fetch bricks
    stmt = select(BrickModel).where(BrickModel.id.in_(brick_ids))
    res = await db.execute(stmt)
    db_bricks = res.scalars().all()
    if len(db_bricks) != len(brick_ids):
        found_ids = {b.id for b in db_bricks}
        missing = set(brick_ids) - found_ids
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Bricks not found: {sorted(missing)}",
        )

    brick_schemas = [_to_brick_schema(b) for b in db_bricks]

    compiler = PlanCompiler()
    cycles = compiler.detect_cycles(brick_schemas)
    if cycles:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cycle detected in brick dependencies: {cycles}",
        )

    batches = compiler.compile(brick_schemas, plan_id=plan_id)
    compiled_hash = compiler.compile_hash(batches, brick_schemas)

    plan = PlanModel(
        id=plan_id,
        app_id=app_id,
        level=level,
        scope_id=app_id,
        compiled_at=datetime.datetime.utcnow(),
        compiled_hash=compiled_hash,
    )
    db.add(plan)
    await db.flush()

    # Add plan bricks
    for idx, bid in enumerate(brick_ids):
        pb = PlanBrickModel(
            id=f"pb-{uuid.uuid4().hex[:12]}",
            plan_id=plan_id,
            brick_id=bid,
            sort_order=idx,
        )
        db.add(pb)

    # Add generated batches to DB
    for b in batches:
        db_batch = BatchModel(
            id=b.id,
            plan_id=plan_id,
            type=b.type,
            status=b.status,
            bricks_refs=b.bricks,
            artifacts=b.artifacts,
            evidence_refs=b.evidence,
        )
        db.add(db_batch)

    # Update app pipeline_plan_id
    app.pipeline_plan_id = plan_id

    await db.commit()

    return PipelinePlanSchema(
        id=plan.id,
        app_id=plan.app_id,
        level=plan.level,
        scope_id=plan.scope_id,
        compiled_at=plan.compiled_at,
        compiled_hash=plan.compiled_hash,
        brick_ids=brick_ids,
    )


@router.post("/api/v1/plans/compile", response_model=PipelinePlanSchema, status_code=status.HTTP_201_CREATED)
async def compile_plan(
    body: CompilePlanRequest,
    caller_domain: str | None = Header(None, alias="X-Cosmo-Domain"),
    db: AsyncSession = Depends(get_db),
    principal: PrincipalContext = Depends(require_capability(Action.PIPELINE_CONFIGURE, domain_binding="identity")),
) -> PipelinePlanSchema:
    """Compile application pipeline plan using PlanCompiler and persist batches."""
    app = await db.get(ApplicationModel, body.app_id)
    if app is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Application '{body.app_id}' not found",
        )

    # COS-067/COS-083: domain binding — компиляция только для приложения
    # своего домена (единый резолв)
    if not principal.is_system_admin:
        verify_ownership(
            app.domain_id,
            resolve_caller_domain(principal, caller_domain),
            f"Application '{body.app_id}'",
        )

    return await _compile_and_persist(
        db, plan_id=body.plan_id, app_id=body.app_id,
        level=body.level, brick_ids=body.brick_ids, app=app,
    )


class CompilePlanFromSourceRequest(BaseModel):
    """COS-096: компиляция от живого дерева forge-репозитория."""
    plan_id: str = Field(..., min_length=1)
    app_id: str = Field(..., min_length=1)
    level: str = Field(default="app")
    source_path: str = Field(
        default=".cosmo/pipeline.yaml",
        description="Путь к pipeline-декларации в репозитории",
    )
    ref: str = Field(default="", description="Branch/tag/sha; пусто — default branch")


@router.post("/api/v1/plans/compile-from-source", response_model=PipelinePlanSchema, status_code=status.HTTP_201_CREATED)
async def compile_plan_from_source(
    body: CompilePlanFromSourceRequest,
    caller_domain: str | None = Header(None, alias="X-Cosmo-Domain"),
    db: AsyncSession = Depends(get_db),
    principal: PrincipalContext = Depends(require_capability(Action.PIPELINE_CONFIGURE, domain_binding="identity")),
) -> PipelinePlanSchema:
    """Compile план от ЖИВОГО source: app binding → Gitea read → bricks.

    .cosmo/pipeline.yaml в репозитории объявляет stages (name + brick);
    brick'и резолвятся в каталоге БД — незнакомый brick это честный 404
    с именем, не тихий пропуск. Forge недоступен → 502, репо/файл не
    найден → 404 (mappинг forge_client.forge_http_error).
    """
    import yaml as _yaml

    from orchestrator.cosmo.api.forge_client import build_adapter, forge_http_error

    app = await db.get(ApplicationModel, body.app_id)
    if app is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Application '{body.app_id}' not found",
        )
    if not principal.is_system_admin:
        verify_ownership(
            app.domain_id,
            resolve_caller_domain(principal, caller_domain),
            f"Application '{body.app_id}'",
        )

    stmt = (
        select(RepoBindingModel)
        .where(RepoBindingModel.app_id == body.app_id)
        .order_by(RepoBindingModel.id)
        .limit(1)
    )
    res = await db.execute(stmt)
    binding = res.scalars().first()
    if binding is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Application '{body.app_id}' has no repo binding",
        )
    owner, _, name = binding.repo_path.partition("/")

    try:
        adapter = build_adapter()
        source, _sha = adapter.read_file(owner, name, body.source_path, ref=body.ref)
    except Exception as exc:  # noqa: BLE001 — нормализуется в честный HTTP
        raise forge_http_error(exc, f"{body.source_path} in {binding.repo_path}") from exc

    try:
        decl = _yaml.safe_load(source) or {}
        stages = (decl.get("pipeline") or {}).get("stages") or []
        brick_ids: list[str] = []
        for st in stages:
            bid = (st.get("brick") or "").strip() if isinstance(st, dict) else ""
            if bid and bid not in brick_ids:
                brick_ids.append(bid)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid pipeline source in {body.source_path}: {exc}",
        ) from exc

    if not brick_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"No stages/bricks declared in {body.source_path} "
                   f"({binding.repo_path}) — nothing to compile",
        )

    return await _compile_and_persist(
        db, plan_id=body.plan_id, app_id=body.app_id,
        level=body.level, brick_ids=brick_ids, app=app,
    )


@router.get("/api/v1/plans/{plan_id}", response_model=PipelinePlanSchema)
async def get_plan(
    plan_id: str,
    caller_domain: str | None = Header(None, alias="X-Cosmo-Domain"),
    db: AsyncSession = Depends(get_db),
    principal: PrincipalContext = Depends(require_principal()),
) -> PipelinePlanSchema:
    """Get pipeline plan details.

    COS-086: authentication required + ghost-404 чужого плана для не-админа
    (якорь plan.app_id → Application.domain_id, единый резолв).
    """
    stmt = (
        select(PlanModel)
        .where(PlanModel.id == plan_id)
        .options(selectinload(PlanModel.bricks))
    )
    res = await db.execute(stmt)
    plan = res.scalar_one_or_none()
    if plan is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Plan '{plan_id}' not found",
        )

    if not principal.is_system_admin:
        app = await db.get(ApplicationModel, plan.app_id)
        verify_ownership(
            getattr(app, "domain_id", None),
            resolve_caller_domain(principal, caller_domain),
            f"Plan '{plan_id}'",
        )

    # Sort bricks by sort_order
    sorted_bricks = sorted(plan.bricks, key=lambda pb: pb.sort_order)
    return PipelinePlanSchema(
        id=plan.id,
        app_id=plan.app_id,
        level=plan.level,
        scope_id=plan.scope_id,
        compiled_at=plan.compiled_at,
        compiled_hash=plan.compiled_hash,
        brick_ids=[pb.brick_id for pb in sorted_bricks],
    )


@router.delete("/api/v1/plans/{plan_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_plan(
    plan_id: str,
    caller_domain: str | None = Header(None, alias="X-Cosmo-Domain"),
    db: AsyncSession = Depends(get_db),
    principal: PrincipalContext = Depends(require_capability(Action.PIPELINE_CONFIGURE, domain_binding="identity")),
) -> None:
    """Delete a pipeline plan.

    COS-086: была анонимная запись — теперь capability pipeline:configure
    + ghost-404 чужого плана для не-админа (единый резолв).
    """
    plan = await db.get(PlanModel, plan_id)
    if plan is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Plan '{plan_id}' not found",
        )

    if not principal.is_system_admin:
        app = await db.get(ApplicationModel, plan.app_id)
        verify_ownership(
            getattr(app, "domain_id", None),
            resolve_caller_domain(principal, caller_domain),
            f"Plan '{plan_id}'",
        )

    # Delete associated plan_bricks
    await db.execute(delete(PlanBrickModel).where(PlanBrickModel.plan_id == plan_id))
    await db.delete(plan)
    await db.commit()
