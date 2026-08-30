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

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.cosmo.api.deps import get_current_principal, get_db
from orchestrator.cosmo.api.domain_guard import verify_ownership
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
from orchestrator.cosmo.domain.rbac import PrincipalContext

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
    db: AsyncSession = Depends(get_db),
) -> List[Project]:
    """Список проектов с фильтрацией."""
    stmt = select(ProjectModel).order_by(ProjectModel.created_at.desc())
    if search:
        stmt = stmt.where(ProjectModel.name.ilike(f"%{search}%"))
    if owner_team:
        stmt = stmt.where(ProjectModel.owner_team == owner_team)
    stmt = stmt.offset(offset).limit(limit)
    res = await db.execute(stmt)
    return [_to_project_schema(p) for p in res.scalars().all()]


@router.post("/api/v1/projects", response_model=Project, status_code=status.HTTP_201_CREATED)
async def create_project(
    body: CreateProjectRequest,
    principal: PrincipalContext = Depends(get_current_principal),
    db: AsyncSession = Depends(get_db),
) -> Project:
    """Создать новый проект."""
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
async def get_project(project_id: str, db: AsyncSession = Depends(get_db)) -> Project:
    pm = await db.get(ProjectModel, project_id)
    if not pm:
        raise HTTPException(status_code=404, detail=f"Project '{project_id}' not found")
    return _to_project_schema(pm)


@router.put("/api/v1/projects/{project_id}", response_model=Project)
async def update_project(
    project_id: str,
    body: UpdateProjectRequest,
    principal: PrincipalContext = Depends(get_current_principal),
    db: AsyncSession = Depends(get_db),
) -> Project:
    pm = await db.get(ProjectModel, project_id)
    if not pm:
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
    db: AsyncSession = Depends(get_db),
):
    pm = await db.get(ProjectModel, project_id)
    if not pm:
        raise HTTPException(status_code=404, detail=f"Project '{project_id}' not found")

    app_ids = pm.application_ids or []
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
    db: AsyncSession = Depends(get_db),
):
    pm = await db.get(ProjectModel, project_id)
    if not pm:
        raise HTTPException(status_code=404, detail=f"Project '{project_id}' not found")

    app = await db.get(ApplicationModel, body.app_id)
    if not app:
        raise HTTPException(status_code=404, detail=f"Application '{body.app_id}' not found")

    current_ids = list(pm.application_ids or [])
    if body.app_id not in current_ids:
        current_ids.append(body.app_id)
        pm.application_ids = current_ids
        await db.commit()

    return {"status": "added", "app_id": body.app_id, "project_id": project_id}


# ── Project Graph & Team Endpoints ────────────────────────────────────────

@router.get("/api/v1/projects/{project_id}/graph")
async def get_project_graph(project_id: str, db: AsyncSession = Depends(get_db)):
    pm = await db.get(ProjectModel, project_id)
    if not pm:
        raise HTTPException(status_code=404, detail=f"Project '{project_id}' not found")
    return {"project_id": project_id, "nodes": pm.application_ids or [], "edges": pm.graph_edges or []}


@router.get("/api/v1/projects/{project_id}/team")
async def get_project_team(project_id: str, db: AsyncSession = Depends(get_db)):
    pm = await db.get(ProjectModel, project_id)
    if not pm:
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
async def list_kits_tags(db: AsyncSession = Depends(get_db)) -> List[KitsTag]:
    res = await db.execute(select(KitsTagModel).order_by(KitsTagModel.label))
    tags = res.scalars().all()
    return [KitsTag(id=t.id, label=t.label, color=t.color, description=t.description) for t in tags]


@kits_router.post("/api/v1/kits", response_model=KitsTag, status_code=status.HTTP_201_CREATED)
async def create_kits_tag(body: CreateKitTagRequest, db: AsyncSession = Depends(get_db)) -> KitsTag:
    existing = await db.get(KitsTagModel, body.id)
    if existing:
        raise HTTPException(status_code=409, detail=f"KITS tag '{body.id}' already exists")

    tag = KitsTagModel(id=body.id, label=body.label, color=body.color, description=body.description)
    db.add(tag)
    await db.commit()
    await db.refresh(tag)
    return KitsTag(id=tag.id, label=tag.label, color=tag.color, description=tag.description)


@kits_router.get("/api/v1/kits/tags", response_model=List[KitsTag])
async def list_kits_tags_alias(db: AsyncSession = Depends(get_db)) -> List[KitsTag]:
    """NX-LUNA-03: Eдиный alias для /api/v1/kits/tags → /api/v1/kits."""
    res = await db.execute(select(KitsTagModel).order_by(KitsTagModel.label))
    tags = res.scalars().all()
    return [KitsTag(id=t.id, label=t.label, color=t.color, description=t.description) for t in tags]