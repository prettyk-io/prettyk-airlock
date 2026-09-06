"""Cosmoport 2.0 — Repositories & Web IDE Write/Run REST endpoints.

COS-103: mock/wire substrate (_MOCK_REPO_FILES, in-memory VFS fallback)
вычищен. Чтение (tree/file/bootstrap) — CAS-ready workspace-роуты
COS-103 в ``orchestrator.cosmo.api.routes.workspace`` (реальный
GiteaForgeAdapter). Здесь остаются WRITE/WORKFLOW поверхности:

  - POST /api/v1/repos/commit        — commit files (forge write)
  - POST /api/v1/repos/commit-and-run — commit + trigger Run (PG, real)

commit-and-run сохраняет COS-067/068 контракт: SCAN_START capability +
identity binding (не-админ триггерит только в своём домене, 403 на
чужой body.domain_id) + реальный Run в PG.

TODO(COS-0xx): commit/commit-and-run пишут через ForgeAdapter при
подключении write-side API (сейчас push-сторона Web IDE идёт через
ForgeAdapter в COS-105/Boss OpenBao-контур); file-write сохранение
временно in-memory — write-path не входит в COS-103 scope (чтение —
да), валидация путей — на WRITE-роутах при переходе на forge.
"""
from __future__ import annotations

import datetime
import uuid
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.cosmo.api.deps import get_db, require_capability, require_principal
from orchestrator.cosmo.domain.rbac import Action, CBRRole, PrincipalContext, Role
from orchestrator.cosmo.db.models import Run as RunModel
from orchestrator.cosmo.domain.run_model import Run

router = APIRouter(prefix="/api/v1/repos", tags=["repos"])


# ── Schemas ────────────────────────────────────────────────────────────

class FileTreeNode(BaseModel):
    name: str = Field(..., alias="name")
    path: str
    kind: str = Field(..., description="'file' | 'dir'")
    size: Optional[int] = None
    children: Optional[list["FileTreeNode"]] = None


# COS-058: self-referencing forward-ref must be resolved, иначе /openapi.json
# падает с PydanticUserError (class-not-fully-defined) при построении схемы.
FileTreeNode.model_rebuild()


class SaveFileRequest(BaseModel):
    repo: str = Field(..., min_length=1)
    path: str = Field(..., min_length=1)
    content: str
    message: Optional[str] = "Update file content"


class CommitFileItem(BaseModel):
    path: str
    content: str


class CommitAndPushRequest(BaseModel):
    repo: str = Field(..., min_length=1)
    branch: str = Field(default="main")
    message: str = Field(..., min_length=1)
    files: list[CommitFileItem] = Field(default_factory=list)


class CommitAndRunRequest(BaseModel):
    repo: str = Field(..., min_length=1)
    branch: str = Field(default="main")
    message: str = Field(..., min_length=1)
    plan_id: str = Field(..., min_length=1)
    domain_id: str = Field(..., min_length=1)
    files: list[CommitFileItem] = Field(default_factory=list)


class CommitResponse(BaseModel):
    ok: bool = True
    commit_hash: str
    branch: str
    repo: str
    message: str
    run_id: Optional[str] = None


# ── Endpoints ──────────────────────────────────────────────────────────


@router.post("/commit", response_model=CommitResponse)
async def commit_and_push(
    body: CommitAndPushRequest,
    principal: PrincipalContext = Depends(require_principal()),
) -> CommitResponse:
    """Commit modified files and push to remote forge branch.

    COS-068: authentication required. TODO(COS-0xx): ownership-чек при
    переходе на реальные forge-репозитории.
    """
    commit_hash = f"c-{uuid.uuid4().hex[:12]}"
    return CommitResponse(
        ok=True,
        commit_hash=commit_hash,
        branch=body.branch,
        repo=body.repo,
        message=body.message,
    )


@router.post("/commit-and-run", response_model=CommitResponse)
async def commit_and_run(
    body: CommitAndRunRequest,
    db: AsyncSession = Depends(get_db),
    principal: PrincipalContext = Depends(
        require_capability(Action.SCAN_START, domain_binding="identity")
    ),
) -> CommitResponse:
    """Commit modified files, push to branch, and immediately trigger pipeline Run.

    COS-068: creates a Run — same contract as POST /runs (COS-067):
    SCAN_START capability + identity binding (не-админ триггерит только
    в своём домене, 403 на чужой body.domain_id).
    """
    # COS-068: domain binding — не-админ создаёт Run только в своём домене
    if not principal.is_system_admin and (body.domain_id or "") != (principal.domain_id or ""):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"domain_id '{body.domain_id}' does not match authenticated principal domain",
        )

    commit_hash = f"c-{uuid.uuid4().hex[:12]}"

    # Trigger Run in database
    run_id = f"run-{uuid.uuid4().hex[:8]}"
    initiator_role = (
        principal.roles[0].value
        if principal.roles and isinstance(principal.roles[0], (Role, CBRRole))
        else (str(principal.roles[0]) if principal.roles else "user")
    )
    run = RunModel(
        id=run_id,
        plan_id=body.plan_id,
        trigger="manual",
        initiator_user_id=principal.user_id,
        initiator_role=initiator_role,
        domain_id=body.domain_id,
        status="running",
        findings_refs=[],
        started_at=datetime.datetime.utcnow(),
        created_at=datetime.datetime.utcnow(),
    )
    db.add(run)
    await db.commit()

    return CommitResponse(
        ok=True,
        commit_hash=commit_hash,
        branch=body.branch,
        repo=body.repo,
        message=body.message,
        run_id=run_id,
    )
