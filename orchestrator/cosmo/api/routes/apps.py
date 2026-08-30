"""Cosmoport 2.0 — Applications & Groups REST API endpoints.

CRUD operations for Application (Level 0..3), RepositoryBinding, and Groups.
"""
from __future__ import annotations

import uuid
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select, delete
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.cosmo.api.deps import get_db, require_capability
from orchestrator.cosmo.domain.rbac import Action
from orchestrator.cosmo.db.models import (
    Application as ApplicationModel,
    RepositoryBinding as RepoBindingModel,
    Group as GroupModel,
    Domain as DomainModel,
)
from orchestrator.cosmo.domain.app_graph import Application, Group, RepositoryBinding

router = APIRouter(tags=["apps"])


# ── Schemas ────────────────────────────────────────────────────────────

class CreateApplicationRequest(BaseModel):
    id: str = Field(..., min_length=1, description="Unique app ID")
    domain_id: str = Field(..., min_length=1, description="Domain ID")
    level: int = Field(default=1, ge=0, le=3, description="0=library, 1..3=app")
    group_id: Optional[str] = Field(default=None, description="Group ID")
    repo_binding: RepositoryBinding = Field(..., description="Git repo binding")
    pipeline_plan_id: Optional[str] = Field(default=None, description="Active pipeline plan ID")


class UpdateApplicationRequest(BaseModel):
    level: Optional[int] = Field(default=None, ge=0, le=3)
    group_id: Optional[str] = None
    pipeline_plan_id: Optional[str] = None


class UpdateRepoBindingRequest(BaseModel):
    forge_id: str = Field(..., min_length=1)
    repo_path: str = Field(..., min_length=1)
    default_branch: str = Field(default="main", min_length=1)
    webhook_id: Optional[str] = None


def _to_app_schema(app_model: ApplicationModel) -> Application:
    """Helper to convert ORM Application + repo_bindings to Pydantic Application."""
    binding_model = app_model.repo_bindings[0] if app_model.repo_bindings else None
    binding = RepositoryBinding(
        forge_id=binding_model.forge_id if binding_model else "",
        repo_path=binding_model.repo_path if binding_model else "",
        default_branch=binding_model.default_branch if binding_model else "main",
        webhook_id=binding_model.webhook_id if binding_model else None,
    )
    return Application(
        id=app_model.id,
        domain_id=app_model.domain_id,
        level=app_model.level,
        group_id=app_model.group_id,
        repo_binding=binding,
        pipeline_plan_id=app_model.pipeline_plan_id,
    )


# ── Applications ────────────────────────────────────────────────────────

@router.get("/api/v1/apps", response_model=list[Application])
async def list_applications(
    domain_id: Optional[str] = Query(None, description="Filter by domain ID"),
    level: Optional[int] = Query(None, ge=0, le=3, description="Filter by level"),
    db: AsyncSession = Depends(get_db),
) -> list[Application]:
    """List applications with optional filtering."""
    stmt = select(ApplicationModel).options(selectinload(ApplicationModel.repo_bindings))
    if domain_id:
        stmt = stmt.where(ApplicationModel.domain_id == domain_id)
    if level is not None:
        stmt = stmt.where(ApplicationModel.level == level)
    stmt = stmt.order_by(ApplicationModel.id)

    result = await db.execute(stmt)
    apps = result.scalars().all()
    return [_to_app_schema(a) for a in apps]


@router.post("/api/v1/apps", response_model=Application, status_code=status.HTTP_201_CREATED)
async def create_application(
    body: CreateApplicationRequest,
    db: AsyncSession = Depends(get_db),
    _guard: None = Depends(require_capability(Action.BRICK_MANAGE)),
) -> Application:
    """Create a new application with repository binding."""
    # Check domain exists
    domain = await db.get(DomainModel, body.domain_id)
    if domain is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Domain '{body.domain_id}' not found",
        )

    # Check app doesn't exist
    existing = await db.get(ApplicationModel, body.id)
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Application with id '{body.id}' already exists",
        )

    # Check group exists if provided
    if body.group_id:
        group = await db.get(GroupModel, body.group_id)
        if group is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Group '{body.group_id}' not found",
            )

    db_app = ApplicationModel(
        id=body.id,
        domain_id=body.domain_id,
        level=body.level,
        group_id=body.group_id,
        pipeline_plan_id=body.pipeline_plan_id,
    )
    db.add(db_app)
    await db.flush()

    # Create RepoBinding
    binding_id = f"rb-{uuid.uuid4().hex[:12]}"
    db_binding = RepoBindingModel(
        id=binding_id,
        app_id=body.id,
        forge_id=body.repo_binding.forge_id,
        repo_path=body.repo_binding.repo_path,
        default_branch=body.repo_binding.default_branch,
        webhook_id=body.repo_binding.webhook_id,
    )
    db.add(db_binding)

    await db.commit()

    # Reload with relationships
    stmt = (
        select(ApplicationModel)
        .where(ApplicationModel.id == body.id)
        .options(selectinload(ApplicationModel.repo_bindings))
    )
    res = await db.execute(stmt)
    loaded = res.scalar_one()
    return _to_app_schema(loaded)


@router.get("/api/v1/apps/{app_id}", response_model=Application)
async def get_application(
    app_id: str,
    db: AsyncSession = Depends(get_db),
) -> Application:
    """Get application details by ID."""
    stmt = (
        select(ApplicationModel)
        .where(ApplicationModel.id == app_id)
        .options(selectinload(ApplicationModel.repo_bindings))
    )
    res = await db.execute(stmt)
    app_model = res.scalar_one_or_none()
    if app_model is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Application '{app_id}' not found",
        )
    return _to_app_schema(app_model)


@router.put("/api/v1/apps/{app_id}", response_model=Application)
async def update_application(
    app_id: str,
    body: UpdateApplicationRequest,
    db: AsyncSession = Depends(get_db),
    _guard: None = Depends(require_capability(Action.BRICK_MANAGE)),
) -> Application:
    """Update application attributes."""
    stmt = (
        select(ApplicationModel)
        .where(ApplicationModel.id == app_id)
        .options(selectinload(ApplicationModel.repo_bindings))
    )
    res = await db.execute(stmt)
    app_model = res.scalar_one_or_none()
    if app_model is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Application '{app_id}' not found",
        )

    if body.level is not None:
        app_model.level = body.level
    if body.group_id is not None:
        if body.group_id != "":
            group = await db.get(GroupModel, body.group_id)
            if group is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Group '{body.group_id}' not found",
                )
            app_model.group_id = body.group_id
        else:
            app_model.group_id = None
    if body.pipeline_plan_id is not None:
        app_model.pipeline_plan_id = body.pipeline_plan_id if body.pipeline_plan_id != "" else None

    await db.commit()
    await db.refresh(app_model)
    return _to_app_schema(app_model)


@router.put("/api/v1/apps/{app_id}/repo-binding", response_model=RepositoryBinding)
async def update_repo_binding(
    app_id: str,
    body: UpdateRepoBindingRequest,
    db: AsyncSession = Depends(get_db),
) -> RepositoryBinding:
    """Update or create the repository binding for an application."""
    app_model = await db.get(ApplicationModel, app_id)
    if app_model is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Application '{app_id}' not found",
        )

    stmt = select(RepoBindingModel).where(RepoBindingModel.app_id == app_id)
    res = await db.execute(stmt)
    binding = res.scalar_one_or_none()

    if binding is None:
        binding = RepoBindingModel(
            id=f"rb-{uuid.uuid4().hex[:12]}",
            app_id=app_id,
            forge_id=body.forge_id,
            repo_path=body.repo_path,
            default_branch=body.default_branch,
            webhook_id=body.webhook_id,
        )
        db.add(binding)
    else:
        binding.forge_id = body.forge_id
        binding.repo_path = body.repo_path
        binding.default_branch = body.default_branch
        if body.webhook_id is not None:
            binding.webhook_id = body.webhook_id

    await db.commit()
    await db.refresh(binding)
    return RepositoryBinding(
        forge_id=binding.forge_id,
        repo_path=binding.repo_path,
        default_branch=binding.default_branch,
        webhook_id=binding.webhook_id,
    )


@router.delete("/api/v1/apps/{app_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_application(
    app_id: str,
    db: AsyncSession = Depends(get_db),
    _guard: None = Depends(require_capability(Action.BRICK_MANAGE)),
) -> None:
    """Delete application and its repo bindings."""
    app_model = await db.get(ApplicationModel, app_id)
    if app_model is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Application '{app_id}' not found",
        )
    # Delete repo bindings first
    await db.execute(delete(RepoBindingModel).where(RepoBindingModel.app_id == app_id))
    await db.delete(app_model)
    await db.commit()


# ── Groups ─────────────────────────────────────────────────────────────

@router.get("/api/v1/groups", response_model=list[Group])
async def list_groups(
    domain_id: Optional[str] = Query(None, description="Filter by domain ID"),
    db: AsyncSession = Depends(get_db),
) -> list[Group]:
    """List application groups."""
    stmt = select(GroupModel)
    if domain_id:
        stmt = stmt.where(GroupModel.domain_id == domain_id)
    stmt = stmt.order_by(GroupModel.id)

    res = await db.execute(stmt)
    groups = res.scalars().all()
    return [
        Group(
            id=g.id,
            domain_id=g.domain_id,
            parent_group_id=g.parent_group_id,
            level=g.level,
            name=g.name,
        )
        for g in groups
    ]


@router.post("/api/v1/groups", response_model=Group, status_code=status.HTTP_201_CREATED)
async def create_group(
    body: Group,
    db: AsyncSession = Depends(get_db),
) -> Group:
    """Create a new group."""
    domain = await db.get(DomainModel, body.domain_id)
    if domain is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Domain '{body.domain_id}' not found",
        )

    existing = await db.get(GroupModel, body.id)
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Group with id '{body.id}' already exists",
        )

    if body.parent_group_id:
        parent = await db.get(GroupModel, body.parent_group_id)
        if parent is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Parent group '{body.parent_group_id}' not found",
            )

    db_group = GroupModel(
        id=body.id,
        domain_id=body.domain_id,
        parent_group_id=body.parent_group_id,
        level=body.level,
        name=body.name,
    )
    db.add(db_group)
    await db.commit()
    await db.refresh(db_group)

    return Group(
        id=db_group.id,
        domain_id=db_group.domain_id,
        parent_group_id=db_group.parent_group_id,
        level=db_group.level,
        name=db_group.name,
    )


@router.get("/api/v1/groups/{group_id}", response_model=Group)
async def get_group(
    group_id: str,
    db: AsyncSession = Depends(get_db),
) -> Group:
    """Get group details by ID."""
    g = await db.get(GroupModel, group_id)
    if g is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Group '{group_id}' not found",
        )
    return Group(
        id=g.id,
        domain_id=g.domain_id,
        parent_group_id=g.parent_group_id,
        level=g.level,
        name=g.name,
    )


@router.delete("/api/v1/groups/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_group(
    group_id: str,
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete a group."""
    g = await db.get(GroupModel, group_id)
    if g is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Group '{group_id}' not found",
        )
    await db.delete(g)
    await db.commit()


# ── SAN-014: Lifecycle Config Endpoints ───────────────────────────────

@router.get("/api/v1/apps/{app_id}/lc-config")
async def get_lifecycle_config(app_id: str):
    """Get 8-step lifecycle configuration for an application."""
    from orchestrator.cosmo.control_plane.lifecycle_resolver import (
        LifecycleResolver, LCStepConfig, CANONICAL_8_STEPS,
        BuildBatch, StaticScanBatch, DeployBatch,
    )
    # For now, return canonical defaults + any app-level overrides
    resolver = LifecycleResolver()
    steps = resolver.resolve_as_list()
    batches = resolver.generate_batches()
    coverage = resolver.validate_required_coverage()
    return {
        "app_id": app_id,
        "steps": [s.model_dump() for s in steps],
        "batches": batches,
        "coverage": coverage,
    }


@router.put("/api/v1/apps/{app_id}/lc-config")
async def update_lifecycle_config(app_id: str, body: dict):
    """Update lifecycle config overrides for an application.

    Body: {"overrides": {"build": {"step_enabled": false}, ...}}
    Required steps cannot be disabled.
    """
    from orchestrator.cosmo.control_plane.lifecycle_resolver import (
        LifecycleResolver, CANONICAL_8_STEPS,
    )
    overrides = body.get("overrides", {})
    resolver = LifecycleResolver(app_overrides=overrides)
    steps = resolver.resolve_as_list()
    coverage = resolver.validate_required_coverage()
    return {
        "app_id": app_id,
        "overrides_applied": list(overrides.keys()),
        "steps": [s.model_dump() for s in steps],
        "coverage": coverage,
    }
