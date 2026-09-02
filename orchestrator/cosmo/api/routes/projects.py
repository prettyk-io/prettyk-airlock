"""
LR-001 / LR-005: Projects & KITS REST API.

  GET/POST      /api/v1/projects
  GET/PUT       /api/v1/projects/{id}
  GET/POST      /api/v1/projects/{id}/apps
  GET/PUT       /api/v1/projects/{id}/graph
  GET/PUT       /api/v1/projects/{id}/team

  GET           /api/v1/kits

  GET           /api/v1/apps (с фильтрами project_id, kits, level, status, search, sort, пагинация)
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Set
from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.cosmo.api.deps import get_current_principal, get_db, require_capability, require_principal
from orchestrator.cosmo.api.domain_guard import resolve_caller_domain, verify_ownership
from orchestrator.cosmo.db.models import (
    Application as ApplicationModel,
)
from orchestrator.cosmo.db.models_lr import (
    Project as ProjectModel,
    KitsTag as KitsTagModel,
    ApplicationKitTag as AppKitTagModel,
    ProjectTeam as ProjectTeamModel,
)
from orchestrator.cosmo.domain.project_model import (
    Project,
    ProjectMetadata,
    ProjectTeam,
    KitsTag,
)
from orchestrator.cosmo.domain.rbac import Action, PrincipalContext

router = APIRouter(tags=["projects"])


# ── Schemas ──────────────────────────────────────────────────────────────────

class CreateProjectRequest(BaseModel):
    id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    description: Optional[str] = None
    owner_team: str = Field(default="core_platform")
    criticality: str = Field(default="category_2")
    sla_tier: str = Field(default="gold")
    deployment_model: str = Field(default="microservices")
    git_repo_root: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class UpdateProjectRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    owner_team: Optional[str] = None
    criticality: Optional[str] = None
    sla_tier: Optional[str] = None


class AddAppToProjectRequest(BaseModel):
    app_id: str = Field(..., min_length=1)


class CreateKitTagRequest(BaseModel):
    id: str = Field(..., min_length=1)
    label: str = Field(..., min_length=1)
    color: str = Field(default="#1E88E5")
    description: Optional[str] = None


class ApplicationListItem(BaseModel):
    id: str
    domain_id: str
    level: int
    name: str = ""
    kits_tags: List[str] = Field(default_factory=list)
    projects: List[str] = Field(default_factory=list)


# ── Helpers ─────────────────────────────────────────────────────────────────

async def _caller_domain_app_ids(db: AsyncSession, caller_domain: str) -> Set[str]:
    """COS-083: id приложений домена caller'а.

    Project не имеет собственного domain_id (LR-001, миграции заморожены),
    поэтому доменная видимость проекта выводится из его приложений.
    """
    res = await db.execute(select(ApplicationModel.id).where(ApplicationModel.domain_id == caller_domain))
    return {row[0] for row in res.all()}


def _to_project_schema(pm: ProjectModel) -> Project:
    return Project(
        id=pm.id,
        name=pm.name,
        description=pm.description,
        owner_team=pm.owner_team,
        metadata=ProjectMetadata(
            criticality=pm.criticality,  # type: ignore
            sla_tier=pm.sla_tier,        # type: ignore
            deployment_model=pm.deployment_model,  # type: ignore
            git_repo_root=pm.git_repo_root or "",
            custom_fields=pm.custom_metadata or {},
        ),
        application_ids=pm.application_ids or [],
        graph_edges=pm.graph_edges or [],
        kits_tags=pm.kits_tag_ids or [],
        created_at=pm.created_at,
        updated_at=pm.updated_at,
    )


# ── Project Endpoints ───────────────────────────────────────────────────────

@router.get("/api/v1/projects", response_model=List[Project])
async def list_projects(
    search: Optional[str] = Query(None, description="Поиск по имени"),
    owner_team: Optional[str] = Query(None, description="Фильтр по команде владельца"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    caller_domain: str | None = Header(None, alias="X-Cosmo-Domain"),
    db: AsyncSession = Depends(get_db),
    principal: PrincipalContext = Depends(require_principal()),
) -> List[Project]:
    """Список проектов с фильтрацией.

    COS-068: authentication required (было — анонимный листинг).
    COS-083: доменный scoping — не-админ видит только проекты, у которых
    есть хотя бы одно приложение его домена; application_ids в payload
    отфильтрованы до приложений своего домена (без утечки чужих привязок).
    """
    stmt = select(ProjectModel).order_by(ProjectModel.created_at.desc())
    if search:
        stmt = stmt.where(ProjectModel.name.ilike(f"%{search}%"))
    if owner_team:
        stmt = stmt.where(ProjectModel.owner_team == owner_team)
    res = await db.execute(stmt)
    projects = list(res.scalars().all())

    if not principal.is_system_admin:
        caller = resolve_caller_domain(principal, caller_domain)
        visible_ids = await _caller_domain_app_ids(db, caller)
        scoped: list[Project] = []
        for p in projects:
            own = sorted(set(p.application_ids or []) & visible_ids)
            if not own:
                continue
            schema = _to_project_schema(p)
            schema.application_ids = own
            scoped.append(schema)
        return scoped[offset:offset + limit]

    projects = projects[offset:offset + limit]
    return [_to_project_schema(p) for p in projects]


@router.post("/api/v1/projects", response_model=Project, status_code=status.HTTP_201_CREATED)
async def create_project(
    body: CreateProjectRequest,
    principal: PrincipalContext = Depends(require_capability(Action.PROJECT_WRITE, domain_binding="identity")),
    db: AsyncSession = Depends(get_db),
) -> Project:
    """Создать новый проект.

    COS-083: write требует capability project:write (не просто principal).
    """
    existing = await db.get(ProjectModel, body.id)
    if existing:
        raise HTTPException(status_code=409, detail=f"Project '{body.id}' already exists")

    pm = ProjectModel(
        id=body.id,
        name=body.name,
        description=body.description,
        owner_team=body.owner_team,
        criticality=body.criticality,
        sla_tier=body.sla_tier,
        deployment_model=body.deployment_model,
        git_repo_root=body.git_repo_root,
        metadata=body.metadata,
    )
    db.add(pm)
    await db.commit()
    await db.refresh(pm)
    return _to_project_schema(pm)


@router.get("/api/v1/projects/{project_id}", response_model=Project)
async def get_project(
    project_id: str,
    caller_domain: str | None = Header(None, alias="X-Cosmo-Domain"),
    db: AsyncSession = Depends(get_db),
    principal: PrincipalContext = Depends(require_principal()),
) -> Project:
    """COS-068: authentication required. COS-083: доменный scoping для не-админа."""
    pm = await db.get(ProjectModel, project_id)
    if not pm:
        raise HTTPException(status_code=404, detail=f"Project '{project_id}' not found")

    schema = _to_project_schema(pm)
    if not principal.is_system_admin:
        caller = resolve_caller_domain(principal, caller_domain)
        visible_ids = await _caller_domain_app_ids(db, caller)
        own = sorted(set(pm.application_ids or []) & visible_ids)
        if not own:
            # ghost: чужой (или пустой в чужих доменах) проект не раскрываем
            raise HTTPException(status_code=404, detail=f"Project '{project_id}' not found")
        schema.application_ids = own
    return schema


@router.put("/api/v1/projects/{project_id}", response_model=Project)
async def update_project(
    project_id: str,
    body: UpdateProjectRequest,
    caller_domain: str | None = Header(None, alias="X-Cosmo-Domain"),
    principal: PrincipalContext = Depends(require_capability(Action.PROJECT_WRITE, domain_binding="identity")),
    db: AsyncSession = Depends(get_db),
) -> Project:
    """COS-083: write требует capability project:write + доменная видимость."""
    pm = await db.get(ProjectModel, project_id)
    if not pm:
        raise HTTPException(status_code=404, detail=f"Project '{project_id}' not found")

    if not principal.is_system_admin:
        caller = resolve_caller_domain(principal, caller_domain)
        visible_ids = await _caller_domain_app_ids(db, caller)
        if not (set(pm.application_ids or []) & visible_ids):
            raise HTTPException(status_code=404, detail=f"Project '{project_id}' not found")

    if body.name is not None:
        pm.name = body.name
    if body.description is not None:
        pm.description = body.description
    if body.owner_team is not None:
        pm.owner_team = body.owner_team
    if body.criticality is not None:
        pm.criticality = body.criticality
    if body.sla_tier is not None:
        pm.sla_tier = body.sla_tier

    await db.commit()
    await db.refresh(pm)
    return _to_project_schema(pm)


# ── Project-Apps Endpoints ──────────────────────────────────────────────────

@router.get("/api/v1/projects/{project_id}/apps")
async def list_project_apps(
    project_id: str,
    caller_domain: str | None = Header(None, alias="X-Cosmo-Domain"),
    db: AsyncSession = Depends(get_db),
    principal: PrincipalContext = Depends(require_principal()),
):
    """COS-068: authentication required. COS-083: не-админ видит только apps своего домена."""
    pm = await db.get(ProjectModel, project_id)
    if not pm:
        raise HTTPException(status_code=404, detail=f"Project '{project_id}' not found")

    app_ids = pm.application_ids or []
    if not app_ids:
        return []

    caller_domain_ids: Set[str] | None = None
    if not principal.is_system_admin:
        caller = resolve_caller_domain(principal, caller_domain)
        caller_domain_ids = await _caller_domain_app_ids(db, caller)
        app_ids = [a for a in app_ids if a in caller_domain_ids]
        if not app_ids:
            return []

    stmt = select(ApplicationModel).where(ApplicationModel.id.in_(app_ids))
    res = await db.execute(stmt)
    apps = res.scalars().all()

    # Get KITS tags for each app
    tag_to_apps: dict[str, list[str]] = {}
    for a in apps:
        tag_stmt = select(AppKitTagModel).where(AppKitTagModel.app_id == a.id)
        tag_res = await db.execute(tag_stmt)
        for akt in tag_res.scalars().all():
            tag_to_apps.setdefault(a.id, []).append(akt.tag_id)

    return [
        ApplicationListItem(
            id=a.id,
            domain_id=getattr(a, "domain_id", "default"),
            level=getattr(a, "level", 0),
            name=getattr(a, "name", ""),
            kits_tags=tag_to_apps.get(a.id, []),
            projects=[project_id],
        )
        for a in apps
    ]


@router.post("/api/v1/projects/{project_id}/apps")
async def add_app_to_project(
    project_id: str,
    body: AddAppToProjectRequest,
    caller_domain: str | None = Header(None, alias="X-Cosmo-Domain"),
    db: AsyncSession = Depends(get_db),
    principal: PrincipalContext = Depends(require_capability(Action.PROJECT_WRITE, domain_binding="identity")),
):
    """COS-068: authentication required. COS-083: capability project:write +
    единый резолв домена — чужое приложение не раскрываем (404 ghost)."""
    pm = await db.get(ProjectModel, project_id)
    if not pm:
        raise HTTPException(status_code=404, detail=f"Project '{project_id}' not found")

    app = await db.get(ApplicationModel, body.app_id)
    if not app:
        raise HTTPException(status_code=404, detail=f"Application '{body.app_id}' not found")

    verify_ownership(
        getattr(app, "domain_id", None),
        resolve_caller_domain(principal, caller_domain),
        f"Application '{body.app_id}'",
    )

    current_ids = list(pm.application_ids or [])
    if body.app_id not in current_ids:
        current_ids.append(body.app_id)
        pm.application_ids = current_ids
        await db.commit()

    return {"status": "added", "app_id": body.app_id, "project_id": project_id}


# ── Project Graph & Team Endpoints ────────────────────────────────────────

@router.get("/api/v1/projects/{project_id}/graph")
async def get_project_graph(
    project_id: str,
    caller_domain: str | None = Header(None, alias="X-Cosmo-Domain"),
    db: AsyncSession = Depends(get_db),
    principal: PrincipalContext = Depends(require_principal()),
):
    """COS-068: authentication required. COS-083: доменный scoping узлов."""
    pm = await db.get(ProjectModel, project_id)
    if not pm:
        raise HTTPException(status_code=404, detail=f"Project '{project_id}' not found")

    nodes = pm.application_ids or []
    if not principal.is_system_admin and nodes:
        caller = resolve_caller_domain(principal, caller_domain)
        visible_ids = await _caller_domain_app_ids(db, caller)
        nodes = [a for a in nodes if a in visible_ids]
    return {"project_id": project_id, "nodes": nodes, "edges": pm.graph_edges or []}


@router.get("/api/v1/projects/{project_id}/team")
async def get_project_team(
    project_id: str,
    caller_domain: str | None = Header(None, alias="X-Cosmo-Domain"),
    db: AsyncSession = Depends(get_db),
    principal: PrincipalContext = Depends(require_principal()),
):
    """COS-068: authentication required (состав команды был публичен).

    COS-086: доменный якорь ProjectTeam через резолв-контракт —
    ProjectTeam не имеет собственного domain_id (миграции заморожены),
    видимость выводится из приложений проекта: не-админ получает ghost-404,
    если у проекта нет ни одного приложения его домена.
    """
    pm = await db.get(ProjectModel, project_id)
    if not pm:
        raise HTTPException(status_code=404, detail=f"Project '{project_id}' not found")

    if not principal.is_system_admin:
        caller = resolve_caller_domain(principal, caller_domain)
        visible_ids = await _caller_domain_app_ids(db, caller)
        if not (set(pm.application_ids or []) & visible_ids):
            raise HTTPException(status_code=404, detail=f"Project '{project_id}' not found")

    team_stmt = select(ProjectTeamModel).where(ProjectTeamModel.project_id == project_id)
    team_res = await db.execute(team_stmt)
    team = team_res.scalar_one_or_none()

    if not team:
        return ProjectTeam(project_id=project_id)

    return ProjectTeam(
        project_id=team.project_id,
        inherited_members=team.inherited_members or [],
        local_additions=team.local_additions or [],
        local_exclusions=team.local_exclusions or [],
        role_overrides=team.role_overrides or [],
    )


# ── KITS Tags Endpoints ──────────────────────────────────────────────────────

kits_router = APIRouter(tags=["kits"])


@kits_router.get("/api/v1/kits", response_model=List[KitsTag])
async def list_kits_tags(
    db: AsyncSession = Depends(get_db),
    principal: PrincipalContext = Depends(require_principal()),
) -> List[KitsTag]:
    """COS-068: authentication required."""
    res = await db.execute(select(KitsTagModel).order_by(KitsTagModel.label))
    tags = res.scalars().all()
    return [KitsTag(id=t.id, label=t.label, color=t.color, description=t.description) for t in tags]


@kits_router.post("/api/v1/kits", response_model=KitsTag, status_code=status.HTTP_201_CREATED)
async def create_kits_tag(
    body: CreateKitTagRequest,
    db: AsyncSession = Depends(get_db),
    principal: PrincipalContext = Depends(require_capability(Action.PROJECT_WRITE, domain_binding="identity")),
) -> KitsTag:
    """COS-068: authentication required (мутация справочника была анонимной).
    COS-083: write требует capability project:write."""
    existing = await db.get(KitsTagModel, body.id)
    if existing:
        raise HTTPException(status_code=409, detail=f"KITS tag '{body.id}' already exists")

    tag = KitsTagModel(id=body.id, label=body.label, color=body.color, description=body.description)
    db.add(tag)
    await db.commit()
    await db.refresh(tag)
    return KitsTag(id=tag.id, label=tag.label, color=tag.color, description=tag.description)


@kits_router.get("/api/v1/kits/tags", response_model=List[KitsTag])
async def list_kits_tags_alias(
    db: AsyncSession = Depends(get_db),
    principal: PrincipalContext = Depends(require_principal()),
) -> List[KitsTag]:
    """NX-LUNA-03: Eдиный alias для /api/v1/kits/tags → /api/v1/kits.

    COS-068: authentication required.
    """
    res = await db.execute(select(KitsTagModel).order_by(KitsTagModel.label))
    tags = res.scalars().all()
    return [KitsTag(id=t.id, label=t.label, color=t.color, description=t.description) for t in tags]