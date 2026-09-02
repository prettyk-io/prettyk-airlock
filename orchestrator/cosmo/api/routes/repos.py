"""Cosmoport 2.0 — Repositories & Web IDE File REST API endpoints.

Provides file tree inspection, file read/write, commit & push, and commit & run workflows.
"""
from __future__ import annotations

import datetime
import hashlib
import uuid
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.cosmo.api.deps import get_db, require_capability, require_principal
from orchestrator.cosmo.domain.rbac import Action, CBRRole, PrincipalContext, Role
from orchestrator.cosmo.db.models import (
    Run as RunModel,
    PipelinePlan as PlanModel,
    Domain as DomainModel,
    Application as ApplicationModel,
    RepositoryBinding as RepoBindingModel,
)
from orchestrator.cosmo.domain.run_model import Run

router = APIRouter(prefix="/api/v1/repos", tags=["repos"])


# ── In-memory virtual filesystem for IDE live sessions ─────────────────

_MOCK_REPO_FILES: dict[str, dict[str, str]] = {
    "payments/api": {
        "scenarios/auth.wire": (
            "// Wire Scenario: Authentication & Token Exchange\n"
            "navigate \"https://payments.bank.local/login\"\n"
            "fill \"#username\", \"admin\"\n"
            "fill \"#password\", \"secret123\"\n"
            "click \"button[type=submit]\"\n"
            "assert_url \"https://payments.bank.local/dashboard\"\n"
            "assert_status 200\n"
        ),
        "scenarios/payment.wire": (
            "// Wire Scenario: FastPay Settlement\n"
            "navigate \"https://payments.bank.local/transfer\"\n"
            "fill \"#amount\", \"15000\"\n"
            "fill \"#recipient\", \"RU04452597400000012345\"\n"
            "click \"#confirm-transfer\"\n"
            "assert_text \".status-badge\", \"SUCCESS\"\n"
        ),
        ".cosmo/pipeline.yaml": (
            "version: '2.0'\n"
            "pipeline:\n"
            "  name: Payments Core CI/CD\n"
            "  stages:\n"
            "    - name: build\n"
            "      brick: go_builder\n"
            "    - name: sast\n"
            "      brick: sonarqube_scanner\n"
            "    - name: dast\n"
            "      brick: zap_dast_scanner\n"
        ),
        "README.md": "# Payments API\nCore banking payments service.\n",
    },
    "cbr/wallet-api": {
        "scenarios/wallet.wire": (
            "// Digital Ruble Wallet Operations\n"
            "navigate \"https://cbr.digital-ruble.local/wallet\"\n"
            "assert_status 200\n"
        ),
        ".cosmo/pipeline.yaml": (
            "version: '2.0'\n"
            "pipeline:\n"
            "  name: Digital Ruble Pipeline\n"
            "  stages:\n"
            "    - name: static_scan\n"
            "      brick: sast_sonar\n"
            "    - name: dynamic_test\n"
            "      brick: dast_zap\n"
        ),
        "README.md": "# Digital Ruble Wallet API\nCentral Bank Digital Currency wallet service.\n",
    },
}


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


class FileContentResponse(BaseModel):
    repo: str
    path: str
    content: str
    sha: str


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

@router.get("/tree", response_model=list[FileTreeNode])
async def get_repo_tree(
    repo: str = Query(..., description="Repository full name, e.g. payments/api"),
    principal: PrincipalContext = Depends(require_principal()),
) -> list[FileTreeNode]:
    """Get recursive file tree for a repository.

    COS-068: authentication required (было — анонимный доступ).
    """
    repo_files = _MOCK_REPO_FILES.get(repo)
    if not repo_files:
        # Generate default structured tree if custom repo
        return [
            FileTreeNode(
                name="scenarios",
                path="scenarios",
                kind="dir",
                children=[
                    FileTreeNode(name="main.wire", path="scenarios/main.wire", kind="file", size=320),
                ],
            ),
            FileTreeNode(
                name=".cosmo",
                path=".cosmo",
                kind="dir",
                children=[
                    FileTreeNode(name="pipeline.yaml", path=".cosmo/pipeline.yaml", kind="file", size=240),
                ],
            ),
            FileTreeNode(name="README.md", path="README.md", kind="file", size=150),
        ]

    # Build directory hierarchy from flat paths
    dirs: dict[str, list[FileTreeNode]] = {}
    root_nodes: list[FileTreeNode] = []

    for path, content in sorted(repo_files.items()):
        parts = path.split("/")
        if len(parts) == 1:
            root_nodes.append(
                FileTreeNode(name=parts[0], path=path, kind="file", size=len(content))
            )
        else:
            dir_name = parts[0]
            if dir_name not in dirs:
                dirs[dir_name] = []
            dirs[dir_name].append(
                FileTreeNode(name=parts[-1], path=path, kind="file", size=len(content))
            )

    for dir_name, children in dirs.items():
        root_nodes.append(
            FileTreeNode(name=dir_name, path=dir_name, kind="dir", children=children)
        )

    return root_nodes


@router.get("/file", response_model=FileContentResponse)
async def get_repo_file(
    repo: str = Query(..., description="Repository identifier"),
    path: str = Query(..., description="Relative file path"),
    principal: PrincipalContext = Depends(require_principal()),
) -> FileContentResponse:
    """Get text content of a file.

    COS-068: authentication required.
    """
    repo_files = _MOCK_REPO_FILES.setdefault(repo, {})
    content = repo_files.get(path)
    if content is None:
        # Default placeholder code
        content = (
            f"# {path} in {repo}\n"
            "pipeline \"Default Pipeline\" {\n"
            "  stage \"build\" { brick \"go_build\" }\n"
            "  stage \"scan\"  { brick \"sonar_sast\" }\n"
            "}\n"
        )
        repo_files[path] = content

    sha = hashlib.sha256(content.encode()).hexdigest()
    return FileContentResponse(repo=repo, path=path, content=content, sha=sha)


@router.put("/file", response_model=FileContentResponse)
async def save_repo_file(
    body: SaveFileRequest,
    principal: PrincipalContext = Depends(require_principal()),
) -> FileContentResponse:
    """Save content of a file.

    COS-068: authentication required. TODO(COS-0xx): при переходе с
    in-memory VFS на реальные forge-репозитории добавить ownership-чек
    repo → app → domain (сейчас ресурс виртуальный, владельца нет).
    """
    repo_files = _MOCK_REPO_FILES.setdefault(body.repo, {})
    repo_files[body.path] = body.content
    sha = hashlib.sha256(body.content.encode()).hexdigest()
    return FileContentResponse(repo=body.repo, path=body.path, content=body.content, sha=sha)


@router.post("/commit", response_model=CommitResponse)
async def commit_and_push(
    body: CommitAndPushRequest,
    principal: PrincipalContext = Depends(require_principal()),
) -> CommitResponse:
    """Commit modified files and push to remote forge branch.

    COS-068: authentication required. TODO(COS-0xx): ownership-чек при
    переходе на реальные forge-репозитории.
    """
    repo_files = _MOCK_REPO_FILES.setdefault(body.repo, {})
    for item in body.files:
        repo_files[item.path] = item.content

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

    # 1. Save committed files
    repo_files = _MOCK_REPO_FILES.setdefault(body.repo, {})
    for item in body.files:
        repo_files[item.path] = item.content

    commit_hash = f"c-{uuid.uuid4().hex[:12]}"

    # 2. Trigger Run in database
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
