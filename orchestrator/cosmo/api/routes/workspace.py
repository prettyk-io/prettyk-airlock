# -*- coding: utf-8 -*-
"""COS-103: Workspace API — CAS-ready чтение репозитория для Web IDE.

Пара к COS-102 DTO (``orchestrator.cosmo.domain.workspace``, канон
prettyk-ide ``src/workspace/types.ts``). Роуты:

  - GET /api/v1/repos/workspace/bootstrap — capability context:
    repo → binding приложения → ForgeAdapter (repo info + head commit);
    branch пуст → default branch из forge; authorization по
    ownership-цепочке app.domain_id → principal.
  - GET /api/v1/repos/tree — плоское рекурсивное дерево на head_sha
    (CAS-ready: клиент фиксирует голову; head_sha сверяется с веткой —
    расхождение → 409, честный CAS).
  - GET /api/v1/repos/file — blob + base_blob_sha (база черновика для
    3-way merge).
  - POST /api/v1/repos/workspace/commit — CAS-коммит (COS-107).
  - POST /api/v1/repos/workspace/run — запуск Woodpecker pipeline из IDE
    (COS-108): resolve binding → CAS → submit → WorkspaceRunRow → response.

Ресурс: repo адресуется как binding ПРИЛОЖЕНИЯ (repo_path), не как
свободный forge-путь — ghost-изоляция доменов через verify_ownership
(чужой app → 404, anti-enumeration). Path/repo/branch валидируются
guard-функциями DTO (WorkspaceContractError → 400). Forge ошибки →
честный маппинг forge_client.forge_http_error (503 not configured /
502 unreachable / 404 ghost). Никакого mock-substrate: пустое дерево
честно пусто.
"""
from __future__ import annotations

import datetime
import re
import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.cosmo.api.deps import get_db, require_principal
from orchestrator.cosmo.api.domain_guard import (
    resolve_caller_domain,
    verify_ownership,
)
from orchestrator.cosmo.api.forge_client import build_adapter, forge_http_error
from orchestrator.cosmo.api.woodpecker_client import (
    build_woodpecker,
    woodpecker_http_error,
)
from orchestrator.cosmo.db.models import (
    Application as ApplicationModel,
    RepositoryBinding as RepoBindingModel,
)
from orchestrator.cosmo.db.models_execution import WorkspaceRunRow
from orchestrator.cosmo.domain.rbac import PrincipalContext
from orchestrator.cosmo.domain.workspace import (
    StepLogsResponse,
    TreeEntry,
    WorkspaceBlobResponse,
    WorkspaceBootstrapResponse,
    WorkspaceBranchListResponse,
    WorkspaceBranchSummary,
    WorkspaceCommitListResponse,
    WorkspaceCommitSummary,
    WorkspaceCommitRequest,
    WorkspaceCommitResponse,
    WorkspaceContractError,
    WorkspaceCreateBranchRequest,
    WorkspaceDiffResponse,
    WorkspaceDraftResponse,
    WorkspaceDraftUpsertRequest,
    WorkspaceRunListResponse,
    WorkspaceRunRequest,
    WorkspaceRunResponse,
    WorkspaceRunSummary,
    WorkspaceSearchMatch,
    WorkspaceSearchResponse,
    WorkspaceTagListResponse,
    WorkspaceTagSummary,
    WorkspaceTreeResponse,
    validate_branch,
    validate_head_sha,
    validate_repo,
    validate_tree_path,
)

router = APIRouter(prefix="/api/v1/repos", tags=["workspace"])


async def _binding_for_repo(
    db: AsyncSession,
    repo: str,
    principal: PrincipalContext,
    caller_domain: str | None,
) -> tuple[ApplicationModel, RepoBindingModel]:
    """repo ("owner/repo") → (application, binding) с ownership-чеком.

    repo_path ищется среди RepositoryBinding; чужой/несуществующий →
    единый 404 (ghost, anti-enumeration — не раскрываем существование).
    """
    stmt = (
        select(RepoBindingModel)
        .where(RepoBindingModel.repo_path == repo)
        .order_by(RepoBindingModel.id)
        .limit(1)
    )
    res = await db.execute(stmt)
    binding = res.scalars().first()
    if binding is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Repository '{repo}' not found",
        )
    app = await db.get(ApplicationModel, binding.app_id)
    if app is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Repository '{repo}' not found",
        )
    if not principal.is_system_admin:
        verify_ownership(
            app.domain_id,
            resolve_caller_domain(principal, caller_domain),
            f"Repository '{repo}'",
        )
    return app, binding


def _validate_or_400(**kwargs: tuple[str, str]) -> None:
    """Guard-функции DTO при ручном вызове → WorkspaceContractError → 400."""
    from orchestrator.cosmo.domain.workspace import (
        validate_branch, validate_head_sha, validate_repo, validate_tree_path,
    )
    validators = {
        "repo": validate_repo,
        "branch": validate_branch,
        "head_sha": validate_head_sha,
        "path": validate_tree_path,
    }
    try:
        for name, value in kwargs.items():
            if value:
                validators[name](value)
    except WorkspaceContractError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc


def _entry_kind(gitea_type: str) -> str:
    """Gitea tree type → types.ts kind ('tree'→'directory', 'blob'→'file')."""
    return "directory" if gitea_type == "tree" else "file"


async def _check_head(
    adapter, repo: str, branch: str, head_sha: str,
) -> tuple[str, str]:
    """CAS: head_sha должен быть sha головы branch (полным или префиксом).

    Returns (owner, name); branch moved → 409 (честный конфликт CAS,
    не тихое чтение чужой головы).
    """
    owner, _, name = repo.partition("/")
    head = adapter.get_commit(owner, name, branch)
    if head.sha and head_sha.lower() not in (head.sha.lower(), head.sha[: len(head_sha)].lower()):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"head_sha {head_sha} does not match {branch} head "
                f"{head.sha} in {repo} (branch moved; re-bootstrap)"
            ),
        )
    return owner, name


@router.get("/workspace/bootstrap", response_model=WorkspaceBootstrapResponse)
async def workspace_bootstrap(
    repo: str = Query(..., description="Repository full name 'owner/repo'"),
    branch: str = Query("", description="Branch; empty → default"),
    db: AsyncSession = Depends(get_db),
    principal: PrincipalContext = Depends(require_principal()),
    x_cosmo_domain: str | None = Header(None, alias="X-Cosmo-Domain"),
) -> WorkspaceBootstrapResponse:
    """Открыть workspace: capabilities + authorization + head_sha.

    capabilities — read|draft|commit|run при ownership, read-only при
    админском cross-domain чтении (честно: видим, но не пишем в чужой).
    branch пуст → default branch из forge (get_repo_info).
    """
    _validate_or_400(repo=repo, branch=branch)

    app, binding = await _binding_for_repo(db, repo, principal, x_cosmo_domain)

    resolved_branch = branch or binding.default_branch or "main"
    owner, _, name = repo.partition("/")

    from orchestrator.cosmo.api.forge_client import build_adapter, forge_http_error
    try:
        adapter = build_adapter()
        info = adapter.get_repo_info(owner, name)
        if not branch and info.default_branch:
            resolved_branch = info.default_branch
        head = adapter.get_commit(owner, name, resolved_branch)
    except Exception as exc:  # noqa: BLE001 — нормализация forge ошибок
        raise forge_http_error(exc, f"head of {repo}@{resolved_branch}") from exc

    allowed = principal.is_system_admin or app.domain_id == (principal.domain_id or "")
    return WorkspaceBootstrapResponse(
        repo=repo,
        branch=resolved_branch,
        head_sha=head.sha,
        capabilities=["read", "draft", "commit", "run"] if allowed else ["read"],
        authorization="allow" if allowed else "deny",
    )


@router.get("/tree", response_model=WorkspaceTreeResponse)
async def workspace_tree(
    repo: str = Query(..., description="Repository full name 'owner/repo'"),
    branch: str = Query(..., description="Branch name"),
    head_sha: str = Query(..., alias="head_sha", description="CAS head sha"),
    db: AsyncSession = Depends(get_db),
    principal: PrincipalContext = Depends(require_principal()),
) -> WorkspaceTreeResponse:
    """Плоское рекурсивное дерево на head_sha (CAS-ready).

    head_sha обязателен и сверяется с веткой: не совпадает → 409
    (ветка уехала — re-bootstrap). Пустое дерево честно пусто.
    """
    _validate_or_400(repo=repo, branch=branch, head_sha=head_sha)

    await _binding_for_repo(db, repo, principal, None)

    from orchestrator.cosmo.api.forge_client import build_adapter, forge_http_error
    try:
        adapter = build_adapter()
        owner, name = await _check_head(adapter, repo, branch, head_sha)
        tree = adapter.get_tree(owner, name, ref=head_sha)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise forge_http_error(exc, f"tree of {repo}@{head_sha[:8]}") from exc

    return WorkspaceTreeResponse(
        entries=[TreeEntry(path=e.path, kind=_entry_kind(e.type)) for e in tree],
    )


@router.get("/file", response_model=WorkspaceBlobResponse)
async def workspace_file(
    repo: str = Query(..., description="Repository full name 'owner/repo'"),
    branch: str = Query(..., description="Branch name"),
    path: str = Query(..., description="File path"),
    head_sha: str = Query(..., alias="head_sha", description="CAS head sha"),
    db: AsyncSession = Depends(get_db),
    principal: PrincipalContext = Depends(require_principal()),
) -> WorkspaceBlobResponse:
    """Blob файла на head_sha + base_blob_sha (база CAS-записи, 3-way)."""
    _validate_or_400(repo=repo, branch=branch, head_sha=head_sha, path=path)

    await _binding_for_repo(db, repo, principal, None)

    from orchestrator.cosmo.api.forge_client import build_adapter, forge_http_error
    try:
        adapter = build_adapter()
        owner, name = await _check_head(adapter, repo, branch, head_sha)
        content, blob_sha = adapter.read_file(owner, name, path, ref=head_sha)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise forge_http_error(exc, f"{path} in {repo}@{head_sha[:8]}") from exc

    return WorkspaceBlobResponse(
        path=path,
        content=content,
        sha=blob_sha or head_sha,
        encoding="utf-8",
        base_blob_sha=blob_sha or head_sha,
    )


# ── COS-107: Workspace commit (CAS через git Tree API) ─────────────────

from orchestrator.cosmo.domain.workspace import (  # noqa: E402
    FileChange,
    WorkspaceCommitRequest,
    WorkspaceCommitResponse,
)


def _current_blob_sha(adapter, owner: str, repo: str, path: str, ref: str) -> str | None:
    """Текущий SHA blob'а на ref. None — файла нет (delete или new)."""
    try:
        _content, sha = adapter.read_file(owner, repo, path, ref=ref)
        return sha
    except LookupError:
        return None


@router.post("/workspace/commit", response_model=WorkspaceCommitResponse, status_code=status.HTTP_201_CREATED)
async def workspace_commit(
    body: WorkspaceCommitRequest,
    caller_domain: str | None = Header(None, alias="X-Cosmo-Domain"),
    db: AsyncSession = Depends(get_db),
    principal: PrincipalContext = Depends(require_principal()),
) -> WorkspaceCommitResponse:
    """CAS-коммит в живой Gitea через git tree API.

    changes — список {path, content, base_blob_sha?, action: 'upsert'|'delete'}.
    base_blob_sha не совпадает с текущим blob → 409 (CAS conflict — файл
    изменился после последнего чтения в IDE). expected_head_sha не
    совпадает с HEAD ветки → 409 (ветка уехала — re-bootstrap).
    Автор коммита — principal.user_id + forge-учётка адаптера.
    """
    owner, _, name = body.repo.partition("/")
    app, binding = await _binding_for_repo(db, body.repo, principal, caller_domain)

    from orchestrator.cosmo.api.forge_client import build_adapter, forge_http_error
    try:
        adapter = build_adapter()
        parent = adapter.get_commit(owner, name, body.branch)
    except Exception as exc:  # noqa: BLE001
        raise forge_http_error(exc, f"HEAD of {body.repo}@{body.branch}") from exc

    # ── CAS: expected_head_sha match ──
    if body.expected_head_sha:
        exp = body.expected_head_sha.lower()
        actual = parent.sha.lower()
        if exp not in (actual, actual[:len(exp)]):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"expected_head_sha {body.expected_head_sha} does not match "
                        f"{body.branch} HEAD {parent.sha[:8]} (branch moved; re-bootstrap)",
            )

    # ── CAS: base_blob_sha per file ──
    import base64 as _b64

    changes_for_adapter: list[dict] = []
    has_upserts = False
    for ch in body.changes:
        if ch.action == "delete":
            current_sha = None
            try:
                current_sha = _current_blob_sha(adapter, owner, name, ch.path, ref=parent.sha)
            except Exception as exc:  # noqa: BLE001
                raise forge_http_error(exc, f"{ch.path} in {body.repo}") from exc
            if not current_sha:
                continue  # файла нет — delete идемпотентен, пропускаем
            changes_for_adapter.append({
                "path": ch.path,
                "action": "delete",
                "sha": current_sha,
            })
            has_upserts = True  # delete считается изменением
            continue

        has_upserts = True
        current_sha = None
        try:
            current_sha = _current_blob_sha(adapter, owner, name, ch.path, ref=parent.sha)
        except Exception as exc:  # noqa: BLE001
            raise forge_http_error(exc, f"{ch.path} in {body.repo}") from exc

        if ch.base_blob_sha and current_sha:
            if ch.base_blob_sha != current_sha:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"CAS conflict on {ch.path}: base_blob_sha "
                           f"{ch.base_blob_sha[:8]} != current {current_sha[:8]}",
                )
        elif not current_sha and ch.base_blob_sha:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"CAS conflict on {ch.path}: base_blob_sha provided "
                       f"but file does not exist (was deleted or renamed)",
            )

        entry = {
            "path": ch.path,
            "action": "upsert",
            "content": _b64.b64encode(ch.content.encode("utf-8")).decode("ascii"),
        }
        if current_sha:
            entry["sha"] = current_sha  # update существующего файла
        changes_for_adapter.append(entry)

    if not has_upserts:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="no file changes to commit (empty effective commit)",
        )

    try:
        commit = adapter.create_commit(
            owner, name, body.branch, body.message,
            changes_for_adapter, parent.sha,
        )
    except Exception as exc:  # noqa: BLE001
        raise forge_http_error(exc, f"commit to {body.repo}@{body.branch}") from exc

    # ── Audit trail ──
    try:
        from orchestrator.cosmo.api.routes.audit import record_system_event
        record_system_event(
            user_id=principal.user_id,
            action="commit_push",
            resource_type="repo",
            resource_id=body.repo,
            status="success",
            details={
                "branch": body.branch,
                "commit_sha": commit.sha,
                "tree_sha": "",  # fill later if needed
                "file_count": len(body.changes),
            },
        )
    except Exception:
        pass  # audit — soft; коммит не роняем

    return WorkspaceCommitResponse(
        commit_sha=commit.sha,
        branch=body.branch,
        tree_sha=getattr(commit, "tree_sha", commit.sha),
    )


# ── COS-108: Workspace Run ──────────────────────────────────────────────

def _build_tracking_url(base_url: str, repo_owner: str, repo_name: str,
                        number: int) -> str | None:
    """Собрать ссылку на Woodpecker UI для прогона."""
    try:
        return f"{base_url.rstrip('/')}/repos/{repo_owner}/{repo_name}/pipeline/{number}"
    except Exception:
        return None


@router.post(
    "/workspace/run",
    response_model=WorkspaceRunResponse,
    status_code=status.HTTP_201_CREATED,
)
async def workspace_run(
    body: WorkspaceRunRequest,
    db: AsyncSession = Depends(get_db),
    principal: PrincipalContext = Depends(require_principal()),
    x_cosmo_domain: str | None = Header(None, alias="X-Cosmo-Domain"),
) -> WorkspaceRunResponse:
    """Запустить Woodpecker pipeline из Web IDE.

    Двухфазный запуск:
      1. Compile — resolve repo binding → verify ownership → CAS head check
      2. Execute — WoodpeckerAdapter.submit_run → persist handle → response

    Возвращает run_id для последующего SSE-подключения (COS-109).
    """
    # ── Phase 1: resolve + validate ──
    caller_domain = resolve_caller_domain(principal, x_cosmo_domain)
    app, binding = await _binding_for_repo(db, body.repo, principal, caller_domain)

    # CAS: commit_sha should be HEAD of the branch (or ancestor)
    owner, _, name = body.repo.partition("/")
    forge = build_adapter()
    try:
        head = forge.get_commit(owner, name, body.branch)
    except Exception as exc:
        raise forge_http_error(exc, f"repo {body.repo} branch {body.branch}")

    if head.sha and body.commit_sha.lower() not in (
        head.sha.lower(),
        head.sha[:len(body.commit_sha)].lower(),
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"commit_sha {body.commit_sha} does not match {body.branch} head "
                f"{head.sha} in {body.repo} (branch moved; re-commit)"
            ),
        )

    # ── Phase 2: submit to Woodpecker ──
    run_id = uuid.uuid4().hex[:12]
    woodpecker = build_woodpecker()

    try:
        handle = woodpecker.submit_run(owner, name, body.branch)
    except Exception as exc:
        raise woodpecker_http_error(exc, f"repo {body.repo}")

    wp_number = handle.get("number")
    wp_pipeline_id = handle.get("job_id")
    repo_id = handle.get("repo_id")

    tracking_url = _build_tracking_url(
        woodpecker._base if hasattr(woodpecker, "_base") else "",
        owner, name, wp_number or 0,
    )

    # Persist tracking record for COS-109 SSE
    run_row = WorkspaceRunRow(
        run_id=run_id,
        repo_owner=owner,
        repo_name=name,
        branch=body.branch,
        commit_sha=body.commit_sha,
        repo_id=repo_id,
        wp_number=wp_number,
        wp_pipeline_id=wp_pipeline_id,
        status="running",
        tracking_url=tracking_url,
        created_at=datetime.datetime.utcnow(),
        updated_at=datetime.datetime.utcnow(),
    )
    db.add(run_row)
    await db.commit()

    return WorkspaceRunResponse(
        run_id=run_id,
        pipeline_number=wp_number or 0,
        pipeline_id=wp_pipeline_id,
        status="running",
        tracking_url=tracking_url,
    )


# ── COS-112: Workspace Run History ─────────────────────────────────────


@router.get("/workspace/runs", response_model=WorkspaceRunListResponse)
async def workspace_list_runs(
    repo: str = Query(..., min_length=1),
    branch: str | None = Query(None),
    status_filter: str | None = Query(None, alias="status"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    principal: PrincipalContext = Depends(require_principal()),
    x_cosmo_domain: str | None = Header(None, alias="X-Cosmo-Domain"),
) -> WorkspaceRunListResponse:
    """История запусков workspace по репозиторию/ветке.

    GET /api/v1/repos/workspace/runs?repo=owner/name&branch=main&status=running&limit=20&offset=0
    """
    # Validate repo format (traversal guard)
    try:
        validate_repo(repo)
    except WorkspaceContractError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))

    caller_domain = resolve_caller_domain(principal, x_cosmo_domain)
    await _binding_for_repo(db, repo, principal, caller_domain)

    owner, _, name = repo.partition("/")

    base = select(WorkspaceRunRow).where(
        WorkspaceRunRow.repo_owner == owner,
        WorkspaceRunRow.repo_name == name,
    )
    count_base = select(func.count()).select_from(WorkspaceRunRow).where(
        WorkspaceRunRow.repo_owner == owner,
        WorkspaceRunRow.repo_name == name,
    )

    if branch is not None:
        base = base.where(WorkspaceRunRow.branch == branch)
        count_base = count_base.where(WorkspaceRunRow.branch == branch)
    if status_filter is not None:
        base = base.where(WorkspaceRunRow.status == status_filter)
        count_base = count_base.where(WorkspaceRunRow.status == status_filter)

    total_res = await db.execute(count_base)
    total = total_res.scalar() or 0

    rows_res = await db.execute(
        base.order_by(WorkspaceRunRow.created_at.desc())
        .limit(limit)
        .offset(offset),
    )
    rows = rows_res.scalars().all()

    runs = [
        WorkspaceRunSummary(
            run_id=r.run_id,
            repo_owner=r.repo_owner,
            repo_name=r.repo_name,
            branch=r.branch,
            commit_sha=r.commit_sha,
            pipeline_number=r.wp_number,
            status=r.status,
            tracking_url=r.tracking_url,
            created_at=r.created_at.isoformat() if r.created_at else "",
        )
        for r in rows
    ]

    return WorkspaceRunListResponse(
        runs=runs, total=total, limit=limit, offset=offset,
    )


# ── COS-112: Step Logs REST API (отдельный роутер) ─────────────────────

run_log_router = APIRouter(prefix="/api/v1/runs", tags=["workspace"])


@run_log_router.get("/{run_id}/steps/{step_id}/logs")
async def workspace_step_logs(
    run_id: str,
    step_id: int,
    offset: int = Query(0, ge=0),
    limit: int = Query(1000, ge=1, le=5000),
    tail: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    principal: PrincipalContext = Depends(require_principal()),
) -> StepLogsResponse:
    """Постраничное чтение логов завершённого шага (не-SSE).

    GET /api/v1/runs/{run_id}/steps/{step_id}/logs?offset=0&limit=1000&tail=0

    tail > 0 — возвращает последние N строк, игнорируя offset.
    """
    row = await db.get(WorkspaceRunRow, run_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Run '{run_id}' not found",
        )

    if row.wp_number is None or row.repo_id is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Pipeline not created for run '{run_id}'",
        )

    handle = {
        "number": row.wp_number,
        "repo_id": row.repo_id,
        "repo_owner": row.repo_owner,
        "repo_name": row.repo_name,
    }

    wp = build_woodpecker()
    try:
        all_lines = wp.get_step_logs_by_id(handle, step_id)
    except Exception as exc:
        raise woodpecker_http_error(exc, f"run {run_id} step {step_id}")

    total_lines = len(all_lines)
    step_name: str | None = None
    try:
        detail = wp.get_pipeline(handle)
        for step in wp._flatten_steps(detail):
            if step.get("id") == step_id:
                step_name = str(step.get("name"))
                break
    except Exception:
        pass

    if tail > 0:
        lines = all_lines[-tail:] if tail < total_lines else all_lines
        has_more = False
    else:
        lines = all_lines[offset:offset + limit]
        has_more = (offset + limit) < total_lines

    return StepLogsResponse(
        run_id=run_id,
        step_id=step_id,
        step_name=step_name,
        total_lines=total_lines,
        lines=lines,
        has_more=has_more,
    )


# ── COS-110: Workspace Drafts & 3-way Diff ──────────────────────────────


@router.put("/workspace/draft", status_code=status.HTTP_201_CREATED)
async def workspace_draft_upsert(
    body: WorkspaceDraftUpsertRequest,
    caller_domain: str | None = Header(None, alias="X-Cosmo-Domain"),
    db: AsyncSession = Depends(get_db),
    principal: PrincipalContext = Depends(require_principal()),
) -> WorkspaceDraftResponse:
    """Атомарно сохраняет черновик файла в Valkey (TTL 7d)."""
    app, _binding = await _binding_for_repo(db, body.repo, principal, caller_domain)
    owner, _, name = body.repo.partition("/")

    from orchestrator.cosmo.infra.valkey_drafts import save_draft, ValkeyUnreachableError
    try:
        data = save_draft(
            domain=app.domain_id,
            user_id=principal.user_id,
            owner=owner,
            repo=name,
            branch=body.branch,
            path=body.path,
            content=body.content,
            base_blob_sha=body.base_blob_sha,
        )
    except ValkeyUnreachableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc

    return WorkspaceDraftResponse(
        path=body.path,
        content=data["content"],
        base_blob_sha=data.get("base_blob_sha"),
        updated_at=data.get("updated_at"),
    )


@router.get("/workspace/draft")
async def workspace_draft_get(
    repo: str = Query(..., description="owner/repo"),
    branch: str = Query(...),
    path: str = Query(...),
    caller_domain: str | None = Header(None, alias="X-Cosmo-Domain"),
    db: AsyncSession = Depends(get_db),
    principal: PrincipalContext = Depends(require_principal()),
) -> WorkspaceDraftResponse:
    """Читает черновик файла из Valkey."""
    _validate_or_400(repo=repo, branch=branch, path=path)
    app, _binding = await _binding_for_repo(db, repo, principal, caller_domain)
    owner, _, name = repo.partition("/")

    from orchestrator.cosmo.infra.valkey_drafts import load_draft, ValkeyUnreachableError
    try:
        data = load_draft(
            domain=app.domain_id,
            user_id=principal.user_id,
            owner=owner,
            repo=name,
            branch=branch,
            path=path,
        )
    except ValkeyUnreachableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc

    if data is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No draft for {repo}/{path}",
        )

    return WorkspaceDraftResponse(
        path=path,
        content=data["content"],
        base_blob_sha=data.get("base_blob_sha"),
        updated_at=data.get("updated_at"),
    )


@router.delete("/workspace/draft", status_code=status.HTTP_204_NO_CONTENT)
async def workspace_draft_delete(
    repo: str = Query(..., description="owner/repo"),
    branch: str = Query(...),
    path: str = Query(...),
    caller_domain: str | None = Header(None, alias="X-Cosmo-Domain"),
    db: AsyncSession = Depends(get_db),
    principal: PrincipalContext = Depends(require_principal()),
):
    """Удаляет черновик файла (после коммита или сброса)."""
    _validate_or_400(repo=repo, branch=branch, path=path)
    app, _binding = await _binding_for_repo(db, repo, principal, caller_domain)
    owner, _, name = repo.partition("/")

    from orchestrator.cosmo.infra.valkey_drafts import delete_draft, ValkeyUnreachableError
    try:
        existed = delete_draft(
            domain=app.domain_id,
            user_id=principal.user_id,
            owner=owner,
            repo=name,
            branch=branch,
            path=path,
        )
    except ValkeyUnreachableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc

    if not existed:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No draft for {repo}/{path}",
        )

    return None  # 204 — тело не отправляется


@router.get("/workspace/diff")
async def workspace_diff(
    repo: str = Query(..., description="owner/repo"),
    branch: str = Query(...),
    path: str = Query(...),
    base_blob_sha: str | None = Query(None, alias="baseBlobSha"),
    caller_domain: str | None = Header(None, alias="X-Cosmo-Domain"),
    db: AsyncSession = Depends(get_db),
    principal: PrincipalContext = Depends(require_principal()),
) -> WorkspaceDiffResponse:
    """Вычисляет 3-way diff: base (blob коммита) vs draft (Valkey) vs head (ветка).

    Monaco Diff Editor: left = base/head, right = draft.
    has_conflict = True, если head изменился относительно base (кто-то
    закоммитил в этот файл, пока пользователь редактировал черновик).
    """
    _validate_or_400(repo=repo, branch=branch, path=path)
    app, _binding = await _binding_for_repo(db, repo, principal, caller_domain)
    owner, _, name = repo.partition("/")

    # ── Draft из Valkey ──
    from orchestrator.cosmo.infra.valkey_drafts import load_draft, ValkeyUnreachableError
    try:
        draft_data = load_draft(
            domain=app.domain_id,
            user_id=principal.user_id,
            owner=owner,
            repo=name,
            branch=branch,
            path=path,
        )
    except ValkeyUnreachableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc

    draft_content = draft_data["content"] if draft_data else None

    # ── Base и head из Gitea ──
    from orchestrator.cosmo.api.forge_client import build_adapter, forge_http_error

    base_content: str | None = None
    head_content: str | None = None
    has_conflict = False

    try:
        adapter = build_adapter()

        # Base: blob по base_blob_sha (из запроса или из черновика)
        resolved_base_sha = base_blob_sha or (draft_data.get("base_blob_sha") if draft_data else None)
        if resolved_base_sha:
            try:
                raw_base, _ = adapter.read_file(owner, name, path, ref=resolved_base_sha)
                base_content = raw_base
            except Exception:  # noqa: BLE001
                pass  # blob мог быть удалён/перезаписан — base_content остаётся None

        # Head: текущий файл в ветке
        try:
            raw_head, _ = adapter.read_file(owner, name, path, ref=branch)
            head_content = raw_head
        except Exception:  # noqa: BLE001
            pass  # файла нет в head — head_content остаётся None

    except Exception as exc:  # noqa: BLE001
        raise forge_http_error(exc, f"{repo} {path}") from exc

    # ── Conflict detection ──
    if base_content is not None and head_content is not None:
        has_conflict = base_content != head_content

    # ── Line counts ──
    additions = deletions = 0
    if draft_content:
        additions = len(draft_content.splitlines())
    if base_content and draft_content:
        # Diff-lite: lines in base but not in draft ≈ deletions
        base_lines = set(base_content.splitlines())
        draft_lines = set(draft_content.splitlines())
        deletions = len(base_lines - draft_lines)
        additions = len(draft_lines - base_lines)

    return WorkspaceDiffResponse(
        path=path,
        base_content=base_content,
        draft_content=draft_content,
        head_content=head_content,
        has_conflict=has_conflict,
        additions=additions,
        deletions=deletions,
    )


# ── COS-113: Workspace Branches & Tags ──────────────────────────────────


@router.get("/workspace/branches")
async def workspace_branches_list(
    repo: str = Query(..., description="owner/repo"),
    caller_domain: str | None = Header(None, alias="X-Cosmo-Domain"),
    db: AsyncSession = Depends(get_db),
    principal: PrincipalContext = Depends(require_principal()),
) -> WorkspaceBranchListResponse:
    """Список веток репозитория с SHA головы и флагами default/protected."""
    _validate_or_400(repo=repo)
    await _binding_for_repo(db, repo, principal, caller_domain)
    owner, _, name = repo.partition("/")

    from orchestrator.cosmo.api.forge_client import build_adapter, forge_http_error
    try:
        adapter = build_adapter()
        branches = adapter.list_branches(owner, name)
    except Exception as exc:  # noqa: BLE001
        raise forge_http_error(exc, f"branches of {repo}") from exc

    default = next((b["name"] for b in branches if b.get("is_default")), branches[0]["name"] if branches else "")
    summaries = [
        WorkspaceBranchSummary(
            name=b["name"], sha=b["sha"],
            is_default=b.get("is_default", False),
            is_protected=b.get("is_protected", False),
        )
        for b in branches
    ]
    return WorkspaceBranchListResponse(branches=summaries, default_branch=default)


@router.post("/workspace/branches", status_code=status.HTTP_201_CREATED)
async def workspace_branch_create(
    body: WorkspaceCreateBranchRequest,
    caller_domain: str | None = Header(None, alias="X-Cosmo-Domain"),
    db: AsyncSession = Depends(get_db),
    principal: PrincipalContext = Depends(require_principal()),
) -> WorkspaceBranchSummary:
    """Создаёт новую ветку от base_branch."""
    await _binding_for_repo(db, body.repo, principal, caller_domain)
    owner, _, name = body.repo.partition("/")

    from orchestrator.cosmo.api.forge_client import build_adapter, forge_http_error
    try:
        adapter = build_adapter()
        result = adapter.create_branch(owner, name, body.new_branch, body.base_branch)
    except Exception as exc:  # noqa: BLE001
        raise forge_http_error(exc, f"create branch {body.new_branch} in {body.repo}") from exc

    return WorkspaceBranchSummary(
        name=result["name"], sha=result["sha"],
        is_default=result.get("is_default", False),
        is_protected=result.get("is_protected", False),
    )


@router.delete("/workspace/branches", status_code=status.HTTP_204_NO_CONTENT)
async def workspace_branch_delete(
    repo: str = Query(..., description="owner/repo"),
    branch: str = Query(..., description="branch name to delete"),
    caller_domain: str | None = Header(None, alias="X-Cosmo-Domain"),
    db: AsyncSession = Depends(get_db),
    principal: PrincipalContext = Depends(require_principal()),
):
    """Удаляет ветку. 400 при попытке удалить default branch."""
    _validate_or_400(repo=repo, branch=branch)
    await _binding_for_repo(db, repo, principal, caller_domain)
    owner, _, name = repo.partition("/")

    from orchestrator.cosmo.api.forge_client import build_adapter, forge_http_error
    try:
        adapter = build_adapter()
        # Проверить, не default ли удаляем
        branches = adapter.list_branches(owner, name)
        for b in branches:
            if b["name"] == branch and b.get("is_default"):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Cannot delete default branch '{branch}' of {repo}",
                )
        existed = adapter.delete_branch(owner, name, branch)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise forge_http_error(exc, f"delete branch {branch} in {repo}") from exc

    if not existed:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Branch '{branch}' not found in {repo}",
        )
    return None


@router.get("/workspace/tags")
async def workspace_tags_list(
    repo: str = Query(..., description="owner/repo"),
    caller_domain: str | None = Header(None, alias="X-Cosmo-Domain"),
    db: AsyncSession = Depends(get_db),
    principal: PrincipalContext = Depends(require_principal()),
) -> WorkspaceTagListResponse:
    """Список тегов репозитория с SHA коммита."""
    _validate_or_400(repo=repo)
    await _binding_for_repo(db, repo, principal, caller_domain)
    owner, _, name = repo.partition("/")

    from orchestrator.cosmo.api.forge_client import build_adapter, forge_http_error
    try:
        adapter = build_adapter()
        tags = adapter.list_tags(owner, name)
    except Exception as exc:  # noqa: BLE001
        raise forge_http_error(exc, f"tags of {repo}") from exc

    summaries = [WorkspaceTagSummary(name=t["name"], sha=t["sha"]) for t in tags]
    return WorkspaceTagListResponse(tags=summaries)


# ── COS-114: Workspace Search ───────────────────────────────────────────

# Extensions to skip during code search (binary / non-text files).
_BINARY_EXTENSIONS: frozenset[str] = frozenset({
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".webp", ".svgz",
    ".mp3", ".mp4", ".mov", ".avi", ".mkv", ".webm", ".wmv", ".flv",
    ".zip", ".tar", ".gz", ".bz2", ".xz", ".7z", ".rar",
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".exe", ".dll", ".so", ".dylib", ".bin", ".dat",
    ".ttf", ".otf", ".woff", ".woff2", ".eot",
    ".pyc", ".pyo", ".class", ".o", ".obj", ".a", ".lib",
    ".db", ".sqlite", ".sqlite3",
    ".min.js", ".min.css",  # minified bundles — too large, no value in search
})


def _is_text_file(path: str) -> bool:
    """Heuristic: skip known binary extensions before reading content."""
    lower = path.lower()
    for ext in _BINARY_EXTENSIONS:
        if lower.endswith(ext):
            return False
    return True


def _compile_pattern(query: str, is_regex: bool, case_sensitive: bool) -> "re.Pattern[str]":
    """Compile search pattern with ReDoS protection (length cap + re.error)."""
    if len(query) > 1000:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Search query too long (>1000 chars)",
        )
    if is_regex:
        try:
            flags = 0 if case_sensitive else re.IGNORECASE
            return re.compile(query, flags)
        except re.error as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid regex: {exc}",
            ) from exc
    else:
        # Plain text: escape and compile as regex (^literal$ not needed — substring match)
        escaped = re.escape(query)
        flags = 0 if case_sensitive else re.IGNORECASE
        return re.compile(escaped, flags)


def _search_in_content(
    path: str, content: str, pattern: "re.Pattern[str]",
    collected: int, limit: int,
) -> list[WorkspaceSearchMatch]:
    """Search one file, return matches up to remaining limit."""
    matches: list[WorkspaceSearchMatch] = []
    lines = content.split("\n")
    for line_idx, line in enumerate(lines, start=1):
        for m in pattern.finditer(line):
            matches.append(WorkspaceSearchMatch(
                path=path,
                line_number=line_idx,
                line_content=line,
                match_start=m.start(),
                match_end=m.end(),
            ))
            if len(matches) + collected >= limit:
                return matches
    return matches


@router.get("/workspace/search", response_model=WorkspaceSearchResponse)
async def workspace_search(
    repo: str = Query(..., min_length=1),
    q: str = Query(..., min_length=2),
    branch: str | None = Query(None),
    path_prefix: str | None = Query(None),
    case_sensitive: bool = Query(False, alias="caseSensitive"),
    is_regex: bool = Query(False, alias="isRegex"),
    limit: int = Query(50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    principal: PrincipalContext = Depends(require_principal()),
    x_cosmo_domain: str | None = Header(None, alias="X-Cosmo-Domain"),
) -> WorkspaceSearchResponse:
    """Полнотекстовый поиск / grep по кодовой базе репозитория.

    GET /api/v1/repos/workspace/search?repo=owner/name&q=pattern&branch=main&path_prefix=src/&is_regex=true
    """
    _validate_or_400(repo=repo)

    app, binding = await _binding_for_repo(db, repo, principal, x_cosmo_domain)
    owner, _, name = repo.partition("/")
    resolved_branch = branch or binding.default_branch or "main"

    # Compile pattern early (fail fast on invalid regex)
    pattern = _compile_pattern(q, is_regex, case_sensitive)

    try:
        adapter = build_adapter()
        tree = adapter.get_tree(owner, name, ref=resolved_branch, recursive=True)
        head = adapter.get_commit(owner, name, resolved_branch)
        head_ref = head.sha
    except Exception as exc:  # noqa: BLE001
        raise forge_http_error(exc, f"tree of {repo}@{resolved_branch}") from exc

    # Filter blobs
    blobs = [
        e for e in tree
        if e.type == "blob" and _is_text_file(e.path)
        and (path_prefix is None or e.path.startswith(path_prefix))
    ]

    all_matches: list[WorkspaceSearchMatch] = []
    scanned = 0
    has_more = False

    for entry in blobs:
        try:
            content, _sha = adapter.read_file(owner, name, entry.path, ref=head_ref)
        except (ValueError, LookupError):
            # Binary file (ValueError) or file disappeared (LookupError) — skip silently
            continue
        except Exception:
            # Transient network error — skip this file, continue search
            continue

        scanned += 1

        before = len(all_matches)
        all_matches.extend(
            _search_in_content(entry.path, content, pattern, before, limit),
        )
        if len(all_matches) >= limit:
            has_more = any(
                e.type == "blob" and _is_text_file(e.path)
                and (path_prefix is None or e.path.startswith(path_prefix))
                for e in tree[tree.index(entry) + 1:]
            )
            all_matches = all_matches[:limit]
            break

    return WorkspaceSearchResponse(
        query=q,
        matches=all_matches,
        total_matches=len(all_matches),
        scanned_files=scanned,
        has_more=has_more,
    )


# ── COS-116: Workspace Commits History & Timeline ────────────────────────


@router.get("/workspace/commits")
async def workspace_commits_list(
    repo: str = Query(..., description="owner/repo"),
    branch: str | None = Query(None, description="branch name, default HEAD"),
    path: str | None = Query(None, description="file path to filter history"),
    limit: int = Query(30, ge=1, le=100),
    offset: int = Query(0, ge=0),
    caller_domain: str | None = Header(None, alias="X-Cosmo-Domain"),
    db: AsyncSession = Depends(get_db),
    principal: PrincipalContext = Depends(require_principal()),
) -> WorkspaceCommitListResponse:
    """История коммитов ветки и таймлайн конкретного файла."""
    _validate_or_400(repo=repo, path=path)
    await _binding_for_repo(db, repo, principal, caller_domain)
    owner, _, name = repo.partition("/")

    page = (offset // limit) + 1

    from orchestrator.cosmo.api.forge_client import build_adapter, forge_http_error
    try:
        adapter = build_adapter()
        commits = adapter.list_commits(owner, name, branch=branch, path=path, limit=limit, page=page)
    except Exception as exc:  # noqa: BLE001
        raise forge_http_error(exc, f"commits of {repo}") from exc

    summaries = [
        WorkspaceCommitSummary(
            sha=c["sha"], short_sha=c["short_sha"], message=c["message"],
            author_name=c["author_name"], author_email=c["author_email"],
            committed_at=c["committed_at"], parent_shas=c["parent_shas"],
        )
        for c in commits
    ]
    return WorkspaceCommitListResponse(
        commits=summaries, total=len(summaries), has_more=len(summaries) == limit,
    )
