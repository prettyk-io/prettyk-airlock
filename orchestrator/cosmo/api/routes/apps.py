"""Cosmoport 2.0 — Applications & Groups REST API endpoints.

CRUD operations for Application (Level 0..3), RepositoryBinding, and Groups.
"""
from __future__ import annotations

import os
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
    principal: PrincipalContext = Depends(require_principal()),
    db: AsyncSession = Depends(get_db),
) -> list[Application]:
    """List applications with optional filtering.

    COS-083: authentication required; не-админ видит только приложения
    своего домена (клиентский фильтр не может расширить выборку),
    админ фильтрует свободно или видит все.
    """
    stmt = select(ApplicationModel).options(selectinload(ApplicationModel.repo_bindings))
    if not principal.is_system_admin:
        caller = resolve_caller_domain(principal, domain_id)
        stmt = stmt.where(ApplicationModel.domain_id == caller)
    elif domain_id:
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
    principal: PrincipalContext = Depends(require_capability(Action.BRICK_MANAGE, domain_binding="identity")),
) -> Application:
    """Create a new application with repository binding."""
    # Check domain exists
    domain = await db.get(DomainModel, body.domain_id)
    if domain is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Domain '{body.domain_id}' not found",
        )

    # COS-067: domain binding — не-админ создаёт только в своём домене
    if not principal.is_system_admin and body.domain_id != principal.domain_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"domain_id '{body.domain_id}' does not match authenticated principal domain",
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
    caller_domain: str | None = Header(None, alias="X-Cosmo-Domain"),
    principal: PrincipalContext = Depends(require_principal()),
    db: AsyncSession = Depends(get_db),
) -> Application:
    """Get application details by ID.

    COS-083: authentication + единый резолв домена; чужое приложение —
    404 ghost (не раскрываем существование).
    """
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
    verify_ownership(
        app_model.domain_id,
        resolve_caller_domain(principal, caller_domain),
        f"Application '{app_id}'",
    )
    return _to_app_schema(app_model)


@router.put("/api/v1/apps/{app_id}", response_model=Application)
async def update_application(
    app_id: str,
    body: UpdateApplicationRequest,
    caller_domain: str | None = Header(None, alias="X-Cosmo-Domain"),
    db: AsyncSession = Depends(get_db),
    principal: PrincipalContext = Depends(require_capability(Action.BRICK_MANAGE, domain_binding="identity")),
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

    # COS-067/COS-083: domain binding — ownership по единому резолву для не-админа
    if not principal.is_system_admin:
        verify_ownership(
            app_model.domain_id,
            resolve_caller_domain(principal, caller_domain),
            f"Application '{app_id}'",
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
    caller_domain: str | None = Header(None, alias="X-Cosmo-Domain"),
    db: AsyncSession = Depends(get_db),
    principal: PrincipalContext = Depends(require_capability(Action.BRICK_MANAGE, domain_binding="identity")),
) -> RepositoryBinding:
    """Update or create the repository binding for an application.

    COS-083: мутация требует capability brick:manage + ownership по единому
    резолву (было — полностью без guard'ов, adjacent hole из COS-068).
    """
    app_model = await db.get(ApplicationModel, app_id)
    if app_model is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Application '{app_id}' not found",
        )
    verify_ownership(
        app_model.domain_id,
        resolve_caller_domain(principal, caller_domain),
        f"Application '{app_id}'",
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
    caller_domain: str | None = Header(None, alias="X-Cosmo-Domain"),
    db: AsyncSession = Depends(get_db),
    principal: PrincipalContext = Depends(require_capability(Action.BRICK_MANAGE, domain_binding="identity")),
) -> None:
    """Delete application and its repo bindings."""
    app_model = await db.get(ApplicationModel, app_id)
    if app_model is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Application '{app_id}' not found",
        )
    # COS-067/COS-083: domain binding — ownership по единому резолву для не-админа
    if not principal.is_system_admin:
        verify_ownership(
            app_model.domain_id,
            resolve_caller_domain(principal, caller_domain),
            f"Application '{app_id}'",
        )
    # Delete repo bindings first
    await db.execute(delete(RepoBindingModel).where(RepoBindingModel.app_id == app_id))
    await db.delete(app_model)
    await db.commit()


# ── Groups ─────────────────────────────────────────────────────────────

@router.get("/api/v1/groups", response_model=list[Group])
async def list_groups(
    domain_id: Optional[str] = Query(None, description="Filter by domain ID"),
    principal: PrincipalContext = Depends(require_principal()),
    db: AsyncSession = Depends(get_db),
) -> list[Group]:
    """List application groups.

    COS-083: authentication required; не-админ видит только группы своего
    домена (клиентский фильтр не может расширить выборку).
    """
    stmt = select(GroupModel)
    if not principal.is_system_admin:
        caller = resolve_caller_domain(principal, domain_id)
        stmt = stmt.where(GroupModel.domain_id == caller)
    elif domain_id:
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
    principal: PrincipalContext = Depends(require_capability(Action.BRICK_MANAGE, domain_binding="identity")),
) -> Group:
    """Create a new group.

    COS-083: write требует capability brick:manage; не-админ создаёт
    группу только в своём домене (было — полностью анонимная запись).
    """
    domain = await db.get(DomainModel, body.domain_id)
    if domain is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Domain '{body.domain_id}' not found",
        )

    # COS-067/COS-083: domain binding — не-админ создаёт только в своём домене
    if not principal.is_system_admin and body.domain_id != principal.domain_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"domain_id '{body.domain_id}' does not match authenticated principal domain",
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
    caller_domain: str | None = Header(None, alias="X-Cosmo-Domain"),
    principal: PrincipalContext = Depends(require_principal()),
    db: AsyncSession = Depends(get_db),
) -> Group:
    """Get group details by ID. COS-083: доменный scoping для не-админа."""
    g = await db.get(GroupModel, group_id)
    if g is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Group '{group_id}' not found",
        )
    if not principal.is_system_admin:
        verify_ownership(
            g.domain_id,
            resolve_caller_domain(principal, caller_domain),
            f"Group '{group_id}'",
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
    caller_domain: str | None = Header(None, alias="X-Cosmo-Domain"),
    db: AsyncSession = Depends(get_db),
    principal: PrincipalContext = Depends(require_capability(Action.BRICK_MANAGE, domain_binding="identity")),
) -> None:
    """Delete a group. COS-083: мутация требует capability + ownership не-админа."""
    g = await db.get(GroupModel, group_id)
    if g is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Group '{group_id}' not found",
        )
    if not principal.is_system_admin:
        verify_ownership(
            g.domain_id,
            resolve_caller_domain(principal, caller_domain),
            f"Group '{group_id}'",
        )
    await db.delete(g)
    await db.commit()


# ── SAN-014: Lifecycle Config Endpoints ───────────────────────────────

@router.get("/api/v1/apps/{app_id}/lc-config")
async def get_lifecycle_config(
    app_id: str,
    caller_domain: str | None = Header(None, alias="X-Cosmo-Domain"),
    principal: PrincipalContext = Depends(require_principal()),
    db: AsyncSession = Depends(get_db),
):
    """Get 8-step lifecycle configuration for an application.

    COS-083: authentication + доменный scoping для не-админа.
    """
    from orchestrator.cosmo.control_plane.lifecycle_resolver import (
        LifecycleResolver, LCStepConfig, CANONICAL_8_STEPS,
        BuildBatch, StaticScanBatch, DeployBatch,
    )
    app_model = await db.get(ApplicationModel, app_id)
    if app_model is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Application '{app_id}' not found",
        )
    if not principal.is_system_admin:
        verify_ownership(
            app_model.domain_id,
            resolve_caller_domain(principal, caller_domain),
            f"Application '{app_id}'",
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
async def update_lifecycle_config(
    app_id: str,
    body: dict,
    caller_domain: str | None = Header(None, alias="X-Cosmo-Domain"),
    principal: PrincipalContext = Depends(require_capability(Action.BRICK_MANAGE, domain_binding="identity")),
    db: AsyncSession = Depends(get_db),
):
    """Update lifecycle config overrides for an application.

    Body: {"overrides": {"build": {"step_enabled": false}, ...}}
    Required steps cannot be disabled.

    COS-083: мутация требует capability + доменный scoping не-админа
    (было — полностью анонимная запись).
    """
    from orchestrator.cosmo.control_plane.lifecycle_resolver import (
        LifecycleResolver, CANONICAL_8_STEPS,
    )
    app_model = await db.get(ApplicationModel, app_id)
    if app_model is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Application '{app_id}' not found",
        )
    if not principal.is_system_admin:
        verify_ownership(
            app_model.domain_id,
            resolve_caller_domain(principal, caller_domain),
            f"Application '{app_id}'",
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


# ── COS-096: Live forge surface (ПУ видит коммиты) ─────────────────────

class ForgeLastPushResponse(BaseModel):
    """Честный статус forge-привязки приложения."""
    app_id: str
    repo_path: str
    bound: bool = True
    last_push: Optional[dict] = Field(
        default=None,
        description="Последний принятый webhook'ом push; null — пушей не было",
    )
    recent_commits: list[dict] = Field(
        default_factory=list,
        description="Живые коммиты из Gitea (новые впереди); пусто если forge недоступен",
    )
    forge_unreachable: Optional[str] = Field(
        default=None,
        description="Честная причина, почему живые коммиты не показаны",
    )


@router.get("/api/v1/apps/{app_id}/forge/last-push", response_model=ForgeLastPushResponse)
async def get_app_forge_last_push(
    app_id: str,
    db: AsyncSession = Depends(get_db),
    principal: PrincipalContext = Depends(require_principal()),
) -> ForgeLastPushResponse:
    """Forge-статус приложения: последний webhook-пуш + живые коммиты Gitea.

    Пусто = пусто: без пушей last_push=None (никаких выдуманных коммитов).
    Gitea недоступен → forge_unreachable с причиной, recent_commits=[],
    но last_push из кэша всё равно показывается.
    """
    from orchestrator.cosmo.api import forge_events
    from orchestrator.cosmo.api.forge_client import build_adapter, forge_http_error

    app_model = await db.get(ApplicationModel, app_id)
    if app_model is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Application '{app_id}' not found",
        )
    stmt = (
        select(RepoBindingModel)
        .where(RepoBindingModel.app_id == app_id)
        .order_by(RepoBindingModel.id)
        .limit(1)
    )
    res = await db.execute(stmt)
    binding = res.scalars().first()
    if binding is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Application '{app_id}' has no repo binding",
        )

    repo_path = binding.repo_path
    last = forge_events.last_push(repo_path)

    recent: list[dict] = []
    unreachable: Optional[str] = None
    try:
        adapter = build_adapter()
        owner, _, name = repo_path.partition("/")
        ref = binding.default_branch or "main"
        commits = adapter.list_commits(owner, name, ref=ref, limit=5)
        recent = [
            {"sha": c.sha, "message": c.message, "author": c.author, "timestamp": c.timestamp}
            for c in commits
        ]
    except Exception as exc:  # noqa: BLE001 — честная деградация, не фейл
        err = forge_http_error(exc, f"commits for {repo_path}")
        unreachable = err.detail

    return ForgeLastPushResponse(
        app_id=app_id,
        repo_path=repo_path,
        bound=True,
        last_push=last,
        recent_commits=recent,
        forge_unreachable=unreachable,
    )


@router.post("/api/v1/apps/{app_id}/forge/webhook-setup", status_code=status.HTTP_200_OK)
async def setup_app_forge_webhook(
    app_id: str,
    db: AsyncSession = Depends(get_db),
    principal: PrincipalContext = Depends(
        require_capability(Action.PIPELINE_CONFIGURE, domain_binding="identity")
    ),
) -> dict:
    """Идемпотентный setup webhook живого Gitea для привязанного репо.

    Reuse существующего hook по URL (без дублей); секрет ротируется, если
    изменился. Возвращает {webhook_id, created}.
    """
    from orchestrator.cosmo.api.forge_client import (
        build_adapter, forge_http_error, webhook_secret,
    )

    app_model = await db.get(ApplicationModel, app_id)
    if app_model is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Application '{app_id}' not found",
        )
    stmt = (
        select(RepoBindingModel)
        .where(RepoBindingModel.app_id == app_id)
        .order_by(RepoBindingModel.id)
        .limit(1)
    )
    res = await db.execute(stmt)
    binding = res.scalars().first()
    if binding is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Application '{app_id}' has no repo binding",
        )

    owner, _, name = binding.repo_path.partition("/")
    hook_url = f"{os.getenv('PK_PUBLIC_API_URL', 'http://cosmo-api:8100').rstrip('/')}/api/v1/webhooks/gitea"
    try:
        adapter = build_adapter()
        hook_id, created = adapter.ensure_webhook(
            owner, name, hook_url, webhook_secret(),
        )
    except Exception as exc:  # noqa: BLE001
        raise forge_http_error(exc, f"webhook setup for {binding.repo_path}") from exc

    binding.webhook_id = str(hook_id)
    await db.commit()
    return {
        "app_id": app_id,
        "repo_path": binding.repo_path,
        "webhook_id": hook_id,
        "created": created,
        "url": hook_url,
    }
