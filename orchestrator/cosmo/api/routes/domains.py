"""Cosmoport 2.0 — Domain REST API endpoints.

CRUD operations for Domain (КИТС) and domain AppGraph.
"""
from __future__ import annotations

from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select, delete
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.cosmo.api.deps import get_db, require_principal, require_system_admin
from orchestrator.cosmo.db.models import (
    Domain as DomainModel,
    Application as ApplicationModel,
    Group as GroupModel,
    RepositoryBinding as RepoBindingModel,
)
from orchestrator.cosmo.domain.domain_model import Domain, DomainQuota, ForgeBinding
from orchestrator.cosmo.domain.app_graph import AppGraph, Application, Group, RepositoryBinding
from orchestrator.cosmo.domain.rbac import PrincipalContext

router = APIRouter(prefix="/api/v1/domains", tags=["domains"])


class UpdateDomainRequest(BaseModel):
    """Payload for updating domain fields."""
    label: Optional[str] = None
    forge_binding: Optional[ForgeBinding] = None
    rbac_config: Optional[dict] = None
    quota: Optional[DomainQuota] = None


def _db_to_domain(db_d: DomainModel) -> Domain:
    """Convert SQLAlchemy Domain model to Pydantic Domain schema."""
    return Domain(
        id=db_d.id,
        label=db_d.label,
        forge_binding=ForgeBinding(
            forge_type=db_d.forge_type,  # type: ignore
            url=db_d.forge_url,
            token_ref=db_d.forge_token_ref,
        ),
        rbac_config=db_d.rbac_config or {},
        quota=DomainQuota(
            max_runs=db_d.quota_max_runs,
            max_storage_gb=db_d.quota_max_storage_gb,
            max_cpu=db_d.quota_max_cpu,
        ),
    )


@router.get("", response_model=list[Domain])
async def list_domains(
    db: AsyncSession = Depends(get_db),
    principal: PrincipalContext = Depends(require_principal()),
) -> list[Domain]:
    """List all registered domains.

    COS-068: authentication required. Список доменов нужен любому
    аутентифицированному UI (выбор контекста), секреты не раскрываются.
    """
    stmt = select(DomainModel).order_by(DomainModel.id)
    result = await db.execute(stmt)
    domains = result.scalars().all()
    return [_db_to_domain(d) for d in domains]


@router.post("", response_model=Domain, status_code=status.HTTP_201_CREATED)
async def create_domain(
    body: Domain,
    db: AsyncSession = Depends(get_db),
    principal: PrincipalContext = Depends(require_system_admin()),
) -> Domain:
    """Create a new domain.

    COS-068: system-admin only — домен несёт forge-токены и RBAC-конфиг.
    """
    existing = await db.get(DomainModel, body.id)
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Domain with id '{body.id}' already exists",
        )

    db_domain = DomainModel(
        id=body.id,
        label=body.label,
        forge_type=body.forge_binding.forge_type,
        forge_url=body.forge_binding.url,
        forge_token_ref=body.forge_binding.token_ref,
        rbac_config=body.rbac_config,
        quota_max_runs=body.quota.max_runs,
        quota_max_storage_gb=body.quota.max_storage_gb,
        quota_max_cpu=body.quota.max_cpu,
    )
    db.add(db_domain)
    await db.commit()
    return _db_to_domain(db_domain)


@router.get("/{domain_id}", response_model=Domain)
async def get_domain(
    domain_id: str,
    db: AsyncSession = Depends(get_db),
    principal: PrincipalContext = Depends(require_principal()),
) -> Domain:
    """Get domain by unique ID.

    COS-068: authentication required.
    """
    db_domain = await db.get(DomainModel, domain_id)
    if db_domain is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Domain '{domain_id}' not found",
        )
    return _db_to_domain(db_domain)


@router.put("/{domain_id}", response_model=Domain)
async def update_domain(
    domain_id: str,
    body: UpdateDomainRequest,
    db: AsyncSession = Depends(get_db),
    principal: PrincipalContext = Depends(require_system_admin()),
) -> Domain:
    """Update domain configuration.

    COS-068: system-admin only (forge-токены, rbac_config, квоты).
    """
    db_domain = await db.get(DomainModel, domain_id)
    if db_domain is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Domain '{domain_id}' not found",
        )

    if body.label is not None:
        db_domain.label = body.label.strip()
    if body.forge_binding is not None:
        db_domain.forge_type = body.forge_binding.forge_type
        db_domain.forge_url = body.forge_binding.url
        db_domain.forge_token_ref = body.forge_binding.token_ref
    if body.rbac_config is not None:
        db_domain.rbac_config = body.rbac_config
    if body.quota is not None:
        db_domain.quota_max_runs = body.quota.max_runs
        db_domain.quota_max_storage_gb = body.quota.max_storage_gb
        db_domain.quota_max_cpu = body.quota.max_cpu

    await db.commit()
    await db.refresh(db_domain)
    return _db_to_domain(db_domain)


@router.delete("/{domain_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_domain(
    domain_id: str,
    db: AsyncSession = Depends(get_db),
    principal: PrincipalContext = Depends(require_system_admin()),
) -> None:
    """Delete domain and its dependencies.

    COS-068: system-admin only (деструктивная операция уровня платформы).
    """
    db_domain = await db.get(DomainModel, domain_id)
    if db_domain is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Domain '{domain_id}' not found",
        )
    await db.delete(db_domain)
    await db.commit()


@router.get("/{domain_id}/graph", response_model=AppGraph)
async def get_domain_app_graph(
    domain_id: str,
    db: AsyncSession = Depends(get_db),
    principal: PrincipalContext = Depends(require_principal()),
) -> AppGraph:
    """Get complete AppGraph for a domain (groups + apps + libraries).

    COS-068: authentication required.
    """
    db_domain = await db.get(DomainModel, domain_id)
    if db_domain is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Domain '{domain_id}' not found",
        )

    # Fetch groups
    grp_stmt = select(GroupModel).where(GroupModel.domain_id == domain_id)
    grp_result = await db.execute(grp_stmt)
    db_groups = grp_result.scalars().all()
    groups = [
        Group(
            id=g.id,
            domain_id=g.domain_id,
            parent_group_id=g.parent_group_id,
            level=g.level,
            name=g.name,
        )
        for g in db_groups
    ]

    # Fetch apps with repo bindings
    app_stmt = (
        select(ApplicationModel)
        .where(ApplicationModel.domain_id == domain_id)
        .options(selectinload(ApplicationModel.repo_bindings))
    )
    app_result = await db.execute(app_stmt)
    db_apps = app_result.scalars().all()

    apps_list: list[Application] = []
    libs_list: list[Application] = []

    for a in db_apps:
        first_binding = a.repo_bindings[0] if a.repo_bindings else None
        binding = RepositoryBinding(
            forge_id=first_binding.forge_id if first_binding else db_domain.forge_type,
            repo_path=first_binding.repo_path if first_binding else "",
            default_branch=first_binding.default_branch if first_binding else "main",
            webhook_id=first_binding.webhook_id if first_binding else None,
        )
        app_schema = Application(
            id=a.id,
            domain_id=a.domain_id,
            level=a.level,
            group_id=a.group_id,
            repo_binding=binding,
            pipeline_plan_id=a.pipeline_plan_id,
        )
        if a.level == 0:
            libs_list.append(app_schema)
        else:
            apps_list.append(app_schema)

    return AppGraph(
        domain=domain_id,
        groups=groups,
        apps=apps_list,
        libraries=libs_list,
    )
