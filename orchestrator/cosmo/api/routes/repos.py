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

COS-154: legacy write-surface пишет честно через build_adapter().commit_changes
(тот же bulk Contents API, что /workspace/commits COS-124). CommitFileItem
= {path, content} без action → маппинг в create/update через CAS-состояние:
файл существует на ветке (read_file дал blob sha) → update, отсутствует →
create. commit_hash — реальный 40-hex sha, не c-{uuid}. Ошибки forge →
forge_http_error (503 not configured / 502 unreachable); конфликт/ref уехал →
409. Никакого fallback на фейковый sha.
"""
from __future__ import annotations

import datetime
import uuid
from typing import Optional
from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.cosmo.api.deps import get_db, require_capability, require_principal
from orchestrator.cosmo.api.forge_client import forge_http_error
from orchestrator.cosmo.adapters.forge_gitea import GiteaConflictError
from orchestrator.cosmo.api.routes.workspace import _binding_for_repo
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


def _current_blob_sha(adapter, owner: str, repo: str, path: str, ref: str) -> str | None:
    """Текущий SHA blob'а на ref. None — файла нет (create)."""
    try:
        _content, sha = adapter.read_file(owner, repo, path, ref=ref)
        return sha
    except LookupError:
        return None


def _commit_files(owner: str, name: str, branch: str, message: str,
                  files: list[CommitFileItem]) -> str:
    """Честный forge-write: {path, content} → create/update через CAS-состояние.

    Возвращает реальный 40-hex sha. Ошибки → HTTPException (400/404/409/502/503).
    Никакого fallback на фейковый sha.
    """
    if not files:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="no file changes to commit (empty files)",
        )

    from orchestrator.cosmo.api.forge_client import build_adapter
    try:
        adapter = build_adapter()
    except Exception as exc:  # noqa: BLE001
        raise forge_http_error(exc, f"commit to {owner}/{name}@{branch}") from exc

    operations: list[dict] = []
    for f in files:
        try:
            current = _current_blob_sha(adapter, owner, name, f.path, ref=branch)
        except Exception as exc:  # noqa: BLE001
            raise forge_http_error(exc, f"{f.path} in {owner}/{name}") from exc
        if current:
            operations.append({
                "path": f.path, "content": f.content,
                "action": "update", "sha": current,
            })
        else:
            operations.append({
                "path": f.path, "content": f.content, "action": "create",
            })

    try:
        result = adapter.commit_changes(owner, name, branch, message, operations)
    except GiteaConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"commit conflict on {owner}/{name}@{branch}: {exc}",
        ) from exc
    except Exception as exc:  # noqa: BLE001
        raise forge_http_error(exc, f"commit to {owner}/{name}@{branch}") from exc

    return result.get("sha", "")


@router.post("/commit", response_model=CommitResponse)
async def commit_and_push(
    body: CommitAndPushRequest,
    db: AsyncSession = Depends(get_db),
    principal: PrincipalContext = Depends(require_principal()),
    caller_domain: str | None = Header(None, alias="X-Cosmo-Domain"),
) -> CommitResponse:
    """Commit modified files and push to remote forge branch.

    COS-068: authentication required. COS-154: честный write-path — CAS-состояние
    файла (create/update) + bulk Contents API → реальный 40-hex sha.
    """
    await _binding_for_repo(db, body.repo, principal, caller_domain)
    owner, _, name = body.repo.partition("/")
    commit_hash = _commit_files(owner, name, body.branch, body.message, body.files)
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

    COS-154: identity binding первым (403 на чужой домен — без forge-запросов),
    затем честный commit (реальный sha), затем Run в PG. Commit упал → Run НЕ
    создаётся (ложная атомарность убрана).
    """
    # COS-068: domain binding — не-админ создаёт Run только в своём домене
    if not principal.is_system_admin and (body.domain_id or "") != (principal.domain_id or ""):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"domain_id '{body.domain_id}' does not match authenticated principal domain",
        )

    # COS-154: честный commit первым; Run только после успешного коммита.
    owner, _, name = body.repo.partition("/")
    commit_hash = _commit_files(owner, name, body.branch, body.message, body.files)

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
