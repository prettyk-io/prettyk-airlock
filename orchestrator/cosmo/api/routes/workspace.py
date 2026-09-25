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
    расхождение → 409, честный CAS) или на произвольном commit ref
    (COS-177: immutable snapshot, ref — authority, CAS не применяется).
  - GET /api/v1/repos/file — blob + base_blob_sha (база черновика для
    3-way merge); ref-режим (COS-177) — blob на коммите ref.
  - POST /api/v1/repos/workspace/commit — CAS-коммит (COS-107, legacy).
  - POST /api/v1/repos/workspace/commits — атомарный multi-file коммит
    create/update/delete одной транзакцией + pre-flight gate (COS-124).
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
import time
import uuid

from typing import Any

import yaml

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.cosmo.api.deps import get_db, require_principal
from orchestrator.cosmo.api.domain_guard import (
    resolve_caller_domain,
    verify_ownership,
)
from orchestrator.cosmo.adapters.forge_gitea import GiteaCompareLimitError
from orchestrator.cosmo.api.forge_client import build_adapter, forge_http_error
from orchestrator.cosmo.api.woodpecker_client import (
    build_woodpecker,
    woodpecker_http_error,
)
from orchestrator.cosmo.db.models import (
    Application as ApplicationModel,
    RepositoryBinding as RepoBindingModel,
)
from orchestrator.cosmo.db.models_execution import (
    TERMINAL_STORED_STATUSES,
    WorkspaceRunRow,
)
from orchestrator.cosmo.domain.rbac import PrincipalContext
from orchestrator.cosmo.domain.workspace import (
    StepLogsResponse,
    TreeEntry,
    WorkspaceBlobResponse,
    WorkspaceBootstrapResponse,
    WorkspaceBranchListResponse,
    WorkspaceBranchSummary,
    WorkspaceCommitListResponse,
    WorkspaceCommitRequest,
    WorkspaceCommitResponse,
    WorkspaceCommitSummary,
    WorkspaceCompareFile,
    WorkspaceCompareResponse,
    WorkspaceContentsCommitRequest,
    WorkspaceContentsCommitResponse,
    WorkspaceContractError,
    WorkspaceCreateBranchRequest,
    WorkspaceDiffResponse,
    WorkspaceDraftResponse,
    WorkspaceDraftUpsertRequest,
    WorkspaceFileActionResponse,
    WorkspaceFileCreateRequest,
    WorkspaceFileDeleteRequest,
    WorkspaceFileMoveRequest,
    WorkspaceGateCheckRequest,
    WorkspaceGateScanRequest,
    WorkspaceGateScanResponse,
    WorkspaceGateVerdictResponse,
    WorkspaceGateViolation,
    WorkspacePipelineListResponse,
    WorkspacePipelineSummary,
    WorkspaceRunCancelResponse,
    WorkspaceRunDetailResponse,
    WorkspaceRunListResponse,
    WorkspaceRunRequest,
    WorkspaceRunResponse,
    WorkspaceRunRerunResponse,
    WorkspaceRunStepSummary,
    WorkspaceRunSummary,
    WorkspaceSearchMatch,
    WorkspaceSearchResponse,
    WorkspaceTagListResponse,
    WorkspaceTagSummary,
    WorkspaceTreeResponse,
    validate_branch,
    validate_head_sha,
    validate_ref,
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
        validate_branch, validate_head_sha, validate_ref, validate_repo,
        validate_tree_path,
    )
    validators = {
        "repo": validate_repo,
        "branch": validate_branch,
        "head_sha": validate_head_sha,
        "ref": validate_ref,
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
    branch: str = Query("", description="Branch name (CAS mode; ignored when ref is given)"),
    head_sha: str = Query("", alias="head_sha", description="CAS head sha (CAS mode; ignored when ref is given)"),
    ref: str = Query("", description="Immutable snapshot: commit sha (full or >=7-hex prefix); ref wins over head_sha"),
    db: AsyncSession = Depends(get_db),
    principal: PrincipalContext = Depends(require_principal()),
) -> WorkspaceTreeResponse:
    """Плоское рекурсивное дерево: CAS-режим (head_sha) или snapshot (ref).

    CAS-режим (ref пуст): head_sha обязателен и сверяется с веткой:
    не совпадает → 409 (ветка уехала — re-bootstrap).
    Ref-режим (COS-177): чтение на коммите ref, CAS-сверка не выполняется
    (ref — authority, FR-004 §2); при ref+head_sha приоритет у ref.
    Несуществующий ref → 404, битый формат → 400. Пустое дерево честно пусто.
    """
    _validate_or_400(repo=repo, branch=branch, ref=ref)
    if not ref:
        # CAS-режим: пара обязательна, формат — до forge (400 раньше 5xx)
        if not branch or not head_sha:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="branch and head_sha are required when ref is not provided",
            )
        _validate_or_400(head_sha=head_sha)

    await _binding_for_repo(db, repo, principal, None)

    from orchestrator.cosmo.api.forge_client import build_adapter, forge_http_error
    what = f"tree of {repo}"
    try:
        adapter = build_adapter()
        if ref:
            # ref-режим: immutable snapshot, CAS не применяется
            owner, _, name = repo.partition("/")
            resolved_sha = adapter.resolve_ref(owner, name, ref)
            tree = adapter.get_tree_by_sha(owner, name, resolved_sha, recursive=True)
            what = f"tree of {repo}@{ref[:8]} (ref)"
        else:
            owner, name = await _check_head(adapter, repo, branch, head_sha)
            tree = adapter.get_tree(owner, name, ref=head_sha)
            what = f"tree of {repo}@{head_sha[:8]}"
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise forge_http_error(exc, what) from exc

    return WorkspaceTreeResponse(
        entries=[TreeEntry(path=e.path, kind=_entry_kind(e.type)) for e in tree],
    )


@router.get("/file", response_model=WorkspaceBlobResponse)
async def workspace_file(
    repo: str = Query(..., description="Repository full name 'owner/repo'"),
    branch: str = Query("", description="Branch name (CAS mode; ignored when ref is given)"),
    path: str = Query(..., description="File path"),
    head_sha: str = Query("", alias="head_sha", description="CAS head sha (CAS mode; ignored when ref is given)"),
    ref: str = Query("", description="Immutable snapshot: commit sha (full or >=7-hex prefix); ref wins over head_sha"),
    db: AsyncSession = Depends(get_db),
    principal: PrincipalContext = Depends(require_principal()),
) -> WorkspaceBlobResponse:
    """Blob файла: CAS-режим (head_sha + base_blob_sha) или snapshot (ref).

    CAS-режим (ref пуст): как раньше — base_blob_sha база 3-way черновика.
    Ref-режим (COS-177): содержимое на коммите ref; sha/base_blob_sha —
    blob sha этого коммита (не головы ветки), CAS не применяется.
    """
    _validate_or_400(repo=repo, branch=branch, ref=ref, path=path)
    if not ref:
        # CAS-режим: пара обязательна, формат — до forge (400 раньше 5xx)
        if not branch or not head_sha:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="branch and head_sha are required when ref is not provided",
            )
        _validate_or_400(head_sha=head_sha)

    await _binding_for_repo(db, repo, principal, None)

    from orchestrator.cosmo.api.forge_client import build_adapter, forge_http_error
    what = f"{path} in {repo}"
    try:
        adapter = build_adapter()
        if ref:
            # ref-режим: immutable snapshot, CAS не применяется
            owner, _, name = repo.partition("/")
            resolved_sha = adapter.resolve_ref(owner, name, ref)
            content, blob_sha = adapter.read_file(owner, name, path, ref=resolved_sha)
            anchor = blob_sha or resolved_sha
            what = f"{path} in {repo}@{ref[:8]} (ref)"
        else:
            owner, name = await _check_head(adapter, repo, branch, head_sha)
            content, blob_sha = adapter.read_file(owner, name, path, ref=head_sha)
            anchor = blob_sha or head_sha
            what = f"{path} in {repo}@{head_sha[:8]}"
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise forge_http_error(exc, what) from exc

    return WorkspaceBlobResponse(
        path=path,
        content=content,
        sha=anchor,
        encoding="utf-8",
        base_blob_sha=anchor,
    )


# ── COS-107: Workspace commit (CAS через Contents API; legacy) ─────────

from orchestrator.cosmo.domain.workspace import (  # noqa: E402
    WorkspaceContentsCommitRequest,
    WorkspaceContentsCommitResponse,
)


def _current_blob_sha(adapter, owner: str, repo: str, path: str, ref: str) -> str | None:
    """Текущий SHA blob'а на ref. None — файла нет (delete или new)."""
    try:
        _content, sha = adapter.read_file(owner, repo, path, ref=ref)
        return sha
    except LookupError:
        return None


@router.post("/workspace/commit", response_model=WorkspaceContentsCommitResponse, status_code=status.HTTP_201_CREATED)
async def workspace_commit(
    body: WorkspaceContentsCommitRequest,
    caller_domain: str | None = Header(None, alias="X-Cosmo-Domain"),
    db: AsyncSession = Depends(get_db),
    principal: PrincipalContext = Depends(require_principal()),
) -> WorkspaceContentsCommitResponse:
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

    return WorkspaceContentsCommitResponse(
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

    # ── COS-127: выбор pipeline-конфига (валидация против discovery) ──
    config_file: str | None = None
    if body.pipeline_name is not None:
        try:
            discovered = _discover_pipelines(forge, owner, name, body.branch)
        except Exception as exc:  # noqa: BLE001
            raise forge_http_error(exc, f"pipelines of {body.repo}@{body.branch}") from exc
        match = next((p for p in discovered if p.name == body.pipeline_name), None)
        if match is None:
            available = ", ".join(p.name for p in discovered) or "(none)"
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"unknown pipeline {body.pipeline_name!r} in {body.repo}"
                    f"@{body.branch}; available: {available}"
                ),
            )
        config_file = match.path

    # ── Phase 2: submit to Woodpecker ──
    run_id = uuid.uuid4().hex[:12]
    woodpecker = build_woodpecker()

    try:
        handle = woodpecker.submit_run(owner, name, body.branch, config_file)
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


# ── COS-133: Workspace Run Lifecycle (detail / cancel / rerun) ─────────

# Woodpecker отдаёт "success"/"failure"; исторические строки COS-112 писали
# "succeeded"/"failed". Оба варианта — terminal, иначе detail-роут
# перезапишет завершённый прогон статусом из Woodpecker.
_TERMINAL_RUN_STATUSES = frozenset(TERMINAL_STORED_STATUSES | {"succeeded", "failed"})


def _iso_from_epoch(value: Any) -> str | None:
    """Unix-секунды Woodpecker → ISO-8601; строки — as-is; None/0 — None."""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        if value <= 0:
            return None
        return datetime.datetime.utcfromtimestamp(value).isoformat() + "Z"
    return str(value)


def _duration_ms(started: Any, finished: Any) -> int | None:
    """Длительность (сек) → мс; None если тайминги неполные."""
    if isinstance(started, (int, float)) and isinstance(finished, (int, float)):
        if started > 0 and finished >= started:
            return int((finished - started) * 1000)
    return None


def _step_summaries(detail: dict) -> list[WorkspaceRunStepSummary]:
    """workflows[].steps[] (v3.5) → плоский список WorkspaceRunStepSummary."""
    out: list[WorkspaceRunStepSummary] = []
    for wf in detail.get("workflows") or []:
        for st in wf.get("steps") or []:
            name = st.get("name") or f"workflow-{wf.get('name')}/step"
            raw_exit = st.get("exit_code")
            out.append(WorkspaceRunStepSummary(
                name=str(name),
                status=str(st.get("state") or "pending"),
                exit_code=raw_exit if isinstance(raw_exit, int) else None,
                duration_ms=_duration_ms(st.get("started"), st.get("finished")),
                started_at=_iso_from_epoch(st.get("started")),
                finished_at=_iso_from_epoch(st.get("finished")),
            ))
    return out


async def _run_row_for_domain(
    db: AsyncSession,
    run_id: str,
    principal: PrincipalContext,
    caller_domain: str | None,
) -> WorkspaceRunRow:
    """run_id → WorkspaceRunRow с ownership-чеком (чужой домен → 404 ghost)."""
    row = await db.get(WorkspaceRunRow, run_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Run '{run_id}' not found",
        )
    await _binding_for_repo(
        db, f"{row.repo_owner}/{row.repo_name}", principal, caller_domain,
    )
    return row


def _run_handle(row: WorkspaceRunRow) -> dict:
    """WorkspaceRunRow → handle адаптера (числовой repo_id + number)."""
    if row.wp_number is None or row.repo_id is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Pipeline not created for run '{row.run_id}'",
        )
    return {
        "number": row.wp_number,
        "repo_id": row.repo_id,
        "repo_owner": row.repo_owner,
        "repo_name": row.repo_name,
    }


@router.get(
    "/workspace/runs/{run_id}",
    response_model=WorkspaceRunDetailResponse,
)
async def workspace_run_detail(
    run_id: str,
    x_cosmo_domain: str | None = Header(None, alias="X-Cosmo-Domain"),
    db: AsyncSession = Depends(get_db),
    principal: PrincipalContext = Depends(require_principal()),
) -> WorkspaceRunDetailResponse:
    """Детали запуска: опрос Woodpecker + синхронизация статуса в БД.

    Статус пишется обратно в WorkspaceRunRow только для незавершённых
    прогонов (running/pending/blocked); терминальный статус — источник
    истины в БД, Woodpecker повторно не перезаписывает.
    """
    caller_domain = resolve_caller_domain(principal, x_cosmo_domain)
    row = await _run_row_for_domain(db, run_id, principal, caller_domain)
    handle = _run_handle(row)

    wp = build_woodpecker()
    try:
        detail = wp.get_pipeline_detail(handle)
    except Exception as exc:
        raise woodpecker_http_error(exc, f"run {run_id}")

    raw_status = str(detail.get("status") or row.status)
    if row.status not in _TERMINAL_RUN_STATUSES and raw_status != row.status:
        row.status = raw_status
        row.updated_at = datetime.datetime.utcnow()
        await db.commit()

    return WorkspaceRunDetailResponse(
        run_id=row.run_id,
        repo=f"{row.repo_owner}/{row.repo_name}",
        branch=row.branch,
        commit_sha=row.commit_sha,
        status=row.status,
        pipeline_number=row.wp_number,
        original_run_id=row.original_run_id,
        duration_ms=_duration_ms(detail.get("started"), detail.get("finished")),
        started_at=_iso_from_epoch(detail.get("started")),
        finished_at=_iso_from_epoch(detail.get("finished")),
        steps=_step_summaries(detail),
    )


@router.post(
    "/workspace/runs/{run_id}/cancel",
    response_model=WorkspaceRunCancelResponse,
)
async def workspace_run_cancel(
    run_id: str,
    x_cosmo_domain: str | None = Header(None, alias="X-Cosmo-Domain"),
    db: AsyncSession = Depends(get_db),
    principal: PrincipalContext = Depends(require_principal()),
) -> WorkspaceRunCancelResponse:
    """Отмена активного запуска; терминальный прогон → 400."""
    caller_domain = resolve_caller_domain(principal, x_cosmo_domain)
    row = await _run_row_for_domain(db, run_id, principal, caller_domain)

    if row.status in _TERMINAL_RUN_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Run '{run_id}' already finished (status={row.status})",
        )
    handle = _run_handle(row)

    wp = build_woodpecker()
    try:
        wp.cancel_pipeline(handle)
    except Exception as exc:
        raise woodpecker_http_error(exc, f"run {run_id}")

    row.status = "killed"
    row.updated_at = datetime.datetime.utcnow()
    await db.commit()

    return WorkspaceRunCancelResponse(
        run_id=run_id, status="killed", cancelled=True,
    )


@router.post(
    "/workspace/runs/{run_id}/rerun",
    response_model=WorkspaceRunRerunResponse,
    status_code=status.HTTP_201_CREATED,
)
async def workspace_run_rerun(
    run_id: str,
    x_cosmo_domain: str | None = Header(None, alias="X-Cosmo-Domain"),
    db: AsyncSession = Depends(get_db),
    principal: PrincipalContext = Depends(require_principal()),
) -> WorkspaceRunRerunResponse:
    """Повторный запуск пайплайна: новый WorkspaceRunRow со связью с исходным."""
    caller_domain = resolve_caller_domain(principal, x_cosmo_domain)
    row = await _run_row_for_domain(db, run_id, principal, caller_domain)
    handle = _run_handle(row)

    wp = build_woodpecker()
    try:
        result = wp.rerun_pipeline(handle)
    except Exception as exc:
        raise woodpecker_http_error(exc, f"run {run_id}")

    new_run_id = uuid.uuid4().hex[:12]
    new_number = result.get("number")
    new_pipeline_id = result.get("job_id")
    repo_id = result.get("repo_id") or row.repo_id
    tracking_url = _build_tracking_url(
        wp._base if hasattr(wp, "_base") else "",
        row.repo_owner, row.repo_name, new_number or 0,
    )

    new_row = WorkspaceRunRow(
        run_id=new_run_id,
        repo_owner=row.repo_owner,
        repo_name=row.repo_name,
        branch=row.branch,
        commit_sha=row.commit_sha,
        repo_id=repo_id,
        wp_number=new_number,
        wp_pipeline_id=new_pipeline_id,
        status="running",
        tracking_url=tracking_url,
        original_run_id=row.run_id,
        created_at=datetime.datetime.utcnow(),
        updated_at=datetime.datetime.utcnow(),
    )
    db.add(new_row)
    await db.commit()

    return WorkspaceRunRerunResponse(
        run_id=new_run_id,
        original_run_id=row.run_id,
        pipeline_number=new_number or 0,
        pipeline_id=new_pipeline_id,
        status="running",
        tracking_url=tracking_url,
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
        commits = adapter.list_commits_history(owner, name, branch=branch, path=path, limit=limit, page=page)
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


# ─ COS-124: Atomic multi-file commit ────────────────────────────────────


@router.post(
    "/workspace/commits",
    response_model=WorkspaceCommitResponse,
    status_code=status.HTTP_201_CREATED,
)
async def workspace_commits_create(
    body: WorkspaceCommitRequest,
    caller_domain: str | None = Header(None, alias="X-Cosmo-Domain"),
    db: AsyncSession = Depends(get_db),
    principal: PrincipalContext = Depends(require_principal()),
) -> WorkspaceCommitResponse:
    """Атомарный multi-file коммит (COS-124).

    Порядок:
      1. Pre-flight quality gate: секреты/запрещённые паттерны → 422 с
         violations, коммит в forge не летит;
      2. Ghost-check binding приложения → 404;
      3. Ветка должна существовать → 404;
      4. CAS-состояние файлов: create только для отсутствующих, update/delete
         только для существующих → 409 (конкурентный коммит);
      5. Bulk Contents API одной транзакцией → sha/htmlUrl/authoredAt/filesChanged.
    """
    # 1. Pre-flight gate (только реально записываемое содержимое).
    from orchestrator.cosmo.domain.gate_verdict import scan_file, compute_verdict

    all_violations = []
    for ch in body.file_changes:
        if ch.action in ("create", "update") and ch.content is not None:
            all_violations.extend(scan_file(ch.path, ch.content))

    if compute_verdict(all_violations) == "BLOCK":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "verdict": "BLOCK",
                "message": "commit blocked by quality gate: secrets detected",
                "violations": [
                    WorkspaceGateViolation(
                        path=v.path,
                        rule_id=v.rule_id,
                        severity=v.severity,
                        message=v.message,
                        line_number=v.line_number,
                        snippet=v.snippet,
                    ).model_dump(by_alias=True, mode="json")
                    for v in all_violations
                ],
            },
        )

    # 2. Ownership / ghost 404.
    await _binding_for_repo(db, body.repo, principal, caller_domain)
    owner, _, name = body.repo.partition("/")

    from orchestrator.cosmo.api.forge_client import build_adapter, forge_http_error
    from orchestrator.cosmo.adapters.forge_gitea import GiteaConflictError

    try:
        adapter = build_adapter()
    except Exception as exc:  # noqa: BLE001
        raise forge_http_error(exc, f"workspace commits in {body.repo}") from exc

    # 3. Ветка должна существовать (иначе честный 404).
    try:
        parent = adapter.get_commit(owner, name, body.branch)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise forge_http_error(exc, f"branch {body.branch} of {body.repo}") from exc

    # 4. CAS-состояние каждого файла → сборка операций с blob sha.
    def _safe_current_sha(path: str) -> str | None:
        try:
            return _current_blob_sha(adapter, owner, name, path, ref=parent.sha)
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001
            raise forge_http_error(exc, f"{path} in {body.repo}") from exc

    operations: list[dict] = []
    for ch in body.file_changes:
        current = _safe_current_sha(ch.path)

        if ch.action == "create":
            if current:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"create conflict on {ch.path}: file already exists "
                           f"at {body.branch} (concurrent commit; refresh workspace)",
                )
            operations.append({
                "path": ch.path, "content": ch.content, "action": "create",
            })
            continue

        if not current:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"{ch.action} conflict on {ch.path}: file does not exist "
                       f"at {body.branch} (concurrent commit; refresh workspace)",
            )
        operations.append({
            "path": ch.path,
            "content": ch.content if ch.action == "update" else None,
            "action": ch.action,
            "sha": current,
        })

    # 5. Одна атомарная операция в forge.
    try:
        result = adapter.commit_changes(
            owner, name, body.branch, body.message, operations,
            author_name=body.author_name,
            author_email=body.author_email,
        )
    except HTTPException:
        raise
    except GiteaConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"commit conflict on {body.repo}@{body.branch}: {exc}",
        ) from exc
    except Exception as exc:  # noqa: BLE001
        raise forge_http_error(exc, f"commit to {body.repo}@{body.branch}") from exc

    # Audit trail — soft; коммит не роняем.
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
                "commit_sha": result.get("sha", ""),
                "file_count": len(body.file_changes),
                "atomic": True,
            },
        )
    except Exception:
        pass

    return WorkspaceCommitResponse(**result)


# ── COS-120: Workspace File Actions & Mutator API ────────────────────────


@router.post("/workspace/files", status_code=status.HTTP_201_CREATED)
async def workspace_file_create(
    body: WorkspaceFileCreateRequest,
    caller_domain: str | None = Header(None, alias="X-Cosmo-Domain"),
    db: AsyncSession = Depends(get_db),
    principal: PrincipalContext = Depends(require_principal()),
) -> WorkspaceFileActionResponse:
    """Создаёт файл в репозитории (409 если существует, 400 traversal)."""
    await _binding_for_repo(db, body.repo, principal, caller_domain)
    owner, _, name = body.repo.partition("/")

    from orchestrator.cosmo.api.forge_client import build_adapter, forge_http_error
    try:
        adapter = build_adapter()
        result = adapter.create_file(
            owner, name, body.path, body.content,
            branch=body.base_branch or "",
            message=body.message,
            is_base64=body.is_base64,
        )
    except Exception as exc:  # noqa: BLE001
        raise forge_http_error(exc, f"create file {body.path} in {body.repo}") from exc

    return WorkspaceFileActionResponse(**result)


@router.delete("/workspace/files", status_code=status.HTTP_200_OK)
async def workspace_file_delete(
    body: WorkspaceFileDeleteRequest,
    caller_domain: str | None = Header(None, alias="X-Cosmo-Domain"),
    db: AsyncSession = Depends(get_db),
    principal: PrincipalContext = Depends(require_principal()),
) -> WorkspaceFileActionResponse:
    """Удаляет файл из репозитория (404 если не найден)."""
    await _binding_for_repo(db, body.repo, principal, caller_domain)
    owner, _, name = body.repo.partition("/")

    from orchestrator.cosmo.api.forge_client import build_adapter, forge_http_error
    try:
        adapter = build_adapter()
        result = adapter.delete_file(
            owner, name, body.path,
            branch=body.branch or "",
            message=body.message,
        )
    except Exception as exc:  # noqa: BLE001
        raise forge_http_error(exc, f"delete file {body.path} in {body.repo}") from exc

    return WorkspaceFileActionResponse(**result)


@router.post("/workspace/files/move", status_code=status.HTTP_200_OK)
async def workspace_file_move(
    body: WorkspaceFileMoveRequest,
    caller_domain: str | None = Header(None, alias="X-Cosmo-Domain"),
    db: AsyncSession = Depends(get_db),
    principal: PrincipalContext = Depends(require_principal()),
) -> WorkspaceFileActionResponse:
    """Перемещает/переименовывает файл (409 target занят, 404 source не найден)."""
    await _binding_for_repo(db, body.repo, principal, caller_domain)
    owner, _, name = body.repo.partition("/")

    from orchestrator.cosmo.api.forge_client import build_adapter, forge_http_error
    try:
        adapter = build_adapter()
        result = adapter.move_file(
            owner, name, body.source_path, body.target_path,
            branch=body.branch or "",
            message=body.message,
        )
    except Exception as exc:  # noqa: BLE001
        raise forge_http_error(exc, f"move {body.source_path} → {body.target_path} in {body.repo}") from exc

    return WorkspaceFileActionResponse(**result)


# ── COS-118: Workspace Pipeline Discovery ────────────────────────────────

# Пути, сканируемые для обнаружения пайплайнов
_PIPELINE_ROOTS: tuple[str, ...] = (
    ".woodpecker.yaml",
    ".woodpecker.yml",
    ".woodpecker/.yaml",   # отсеется — не файл, но оставляем для ясности
    ".pipeline.yaml",
    ".pipeline.yml",
)
_WOODPECKER_DIR = ".woodpecker"
_WOODPECKER_EXTS = (".yaml", ".yml")


def _extract_step_names(yaml_doc: dict) -> list[str]:
    """Извлечь имена шагов из YAML-документа pipeline.

    Поддерживает:
      - Woodpecker v1 (map): pipeline: { build: {...}, test: {...} }
        → имена = ключи словаря
      - Woodpecker v2 (list): steps: [ { name: "build" }, { name: "test" } ]
        → имена = item["name"]
      - Generic: pipeline: { stages: [ { steps: [ { name } ] } ] }
    """
    if not isinstance(yaml_doc, dict):
        return []

    def _name_of(step: dict) -> str:
        return str(step.get("name", step.get("id", "?")))

    # Woodpecker v1/v2: top-level "pipeline" or "steps" key
    steps = yaml_doc.get("steps")
    if steps is None:
        steps = yaml_doc.get("pipeline")

    if isinstance(steps, dict):
        # v1: pipeline: { build: {...}, test: {...} } — keys are step names
        # But values could be config dicts → use key as name
        return list(steps.keys())
    if isinstance(steps, list):
        return [_name_of(s) for s in steps if isinstance(s, dict)]

    # Nested: pipeline: { stages: [ { steps: [...] } ] }
    pipe = yaml_doc.get("pipeline")
    if isinstance(pipe, dict):
        inner = pipe.get("steps") or pipe.get("stages")
        if isinstance(inner, list):
            return [_name_of(s) for s in inner if isinstance(s, dict)]
        if isinstance(inner, dict):
            return list(inner.keys())

    return []


def _parse_pipeline_yaml(content: str) -> tuple[str, list[str]]:
    """Парсинг YAML-файла пайплайна. Возвращает (format, step_names).

    Невалидный YAML → ("invalid", []) — толерантность, не 500.
    """
    try:
        doc = yaml.safe_load(content)
    except yaml.YAMLError:
        return "invalid", []
    if doc is None:
        return "invalid", []
    if not isinstance(doc, dict):
        return "invalid", []
    step_names = _extract_step_names(doc)
    return "yaml", step_names


def _discover_pipelines(
    adapter: Any, owner: str, name: str, branch: str,
) -> list[WorkspacePipelineSummary]:
    """COS-118/COS-127: обнаружение pipeline-конфигов репозитория.

    Возвращает список с is_default по порядку обнаружения.
    name — имя из discovery (COS-118), path — путь конфига для
    repo.config_file (COS-127). Исключения адаптера пробрасываются.
    """
    tree = adapter.get_tree(owner, name, ref=branch, recursive=True)
    head = adapter.get_commit(owner, name, branch)
    head_ref = head.sha

    # Строим индекс: path → blob entry
    blob_map: dict[str, object] = {}
    for e in tree:
        if e.type == "blob":
            blob_map[e.path] = e

    pipelines: list[WorkspacePipelineSummary] = []
    seen_names: set[str] = set()

    def _add_pipeline(pname: str, path: str, fmt: str, steps: list[str]) -> None:
        if pname in seen_names:
            return
        seen_names.add(pname)
        pipelines.append(WorkspacePipelineSummary(
            name=pname, path=path, format=fmt,
            is_default=(len(pipelines) == 0),
            step_names=steps,
        ))

    # ── Сканирование корневых файлов ──
    for root_path in (".woodpecker.yaml", ".woodpecker.yml", ".pipeline.yaml", ".pipeline.yml"):
        entry = blob_map.get(root_path)
        if entry is not None:
            try:
                content, _ = adapter.read_file(owner, name, root_path, ref=head_ref)
            except (ValueError, LookupError):
                continue
            fmt, steps = _parse_pipeline_yaml(content)
            pname = root_path.rsplit(".", 1)[0]  # ".woodpecker" / ".pipeline"
            _add_pipeline(pname, root_path, fmt, steps)

    # ── Сканирование папки .woodpecker/ ──
    for path, entry in blob_map.items():
        if path.startswith(f"{_WOODPECKER_DIR}/") and path.endswith(_WOODPECKER_EXTS):
            try:
                content, _ = adapter.read_file(owner, name, path, ref=head_ref)
            except (ValueError, LookupError):
                continue
            fmt, steps = _parse_pipeline_yaml(content)
            # Имя: "deploy" из ".woodpecker/deploy.yaml"
            base = path.rsplit("/", 1)[-1]  # "deploy.yaml"
            pname = base.rsplit(".", 1)[0]  # "deploy"
            _add_pipeline(pname, path, fmt, steps)

    return pipelines


@router.get("/workspace/pipelines", response_model=WorkspacePipelineListResponse)
async def workspace_pipelines_list(
    repo: str = Query(..., min_length=1),
    branch: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    principal: PrincipalContext = Depends(require_principal()),
    x_cosmo_domain: str | None = Header(None, alias="X-Cosmo-Domain"),
) -> WorkspacePipelineListResponse:
    """Обнаружение пайплайнов репозитория.

    GET /api/v1/repos/workspace/pipelines?repo=owner/name&branch=main
    """
    _validate_or_400(repo=repo)

    app, binding = await _binding_for_repo(db, repo, principal, x_cosmo_domain)
    owner, _, name = repo.partition("/")
    resolved_branch = branch or binding.default_branch or "main"

    try:
        adapter = build_adapter()
        pipelines = _discover_pipelines(adapter, owner, name, resolved_branch)
    except Exception as exc:  # noqa: BLE001
        raise forge_http_error(exc, f"tree of {repo}@{resolved_branch}") from exc

    return WorkspacePipelineListResponse(
        pipelines=pipelines,
        default_pipeline=pipelines[0].name if pipelines else None,
    )


# ── COS-123: Pre-flight Quality Gate ─────────────────────────────────────────


@router.post("/workspace/gate-check", response_model=WorkspaceGateVerdictResponse)
async def workspace_gate_check(
    body: WorkspaceGateCheckRequest,
    db: AsyncSession = Depends(get_db),
    principal: PrincipalContext = Depends(require_principal()),
    x_cosmo_domain: str | None = Header(None, alias="X-Cosmo-Domain"),
) -> WorkspaceGateVerdictResponse:
    """Пре-флайт проверка: сканирование файлов на секреты и запрещённые паттерны.

    POST /api/v1/repos/workspace/gate-check
    Body: { repo, branch, files: [{ path, content }] }
    Response: { verdict: "PASS"|"WARN"|"BLOCK", violations, summary }
    """
    _validate_or_400(repo=body.repo, branch=body.branch or "main")

    # Ghost-check: verify repo binding exists
    _app, _binding = await _binding_for_repo(
        db, body.repo, principal, x_cosmo_domain,
    )

    from orchestrator.cosmo.domain.gate_verdict import (
        scan_file,
        compute_verdict,
        Violation,
    )

    all_violations: list[Violation] = []
    for f in body.files:
        all_violations.extend(scan_file(f.path, f.content))

    verdict = compute_verdict(all_violations)

    return WorkspaceGateVerdictResponse(
        verdict=verdict,
        violations=[
            WorkspaceGateViolation(
                path=v.path,
                rule_id=v.rule_id,
                severity=v.severity,
                message=v.message,
                line_number=v.line_number,
                snippet=v.snippet,
            )
            for v in all_violations
        ],
        summary={
            "total": len(all_violations),
            "block": sum(1 for v in all_violations if v.severity == "BLOCK"),
            "warn": sum(1 for v in all_violations if v.severity == "WARN"),
        },
    )


# ── COS-125: Workspace Compare (tree snapshot diff) ──────────────────────────


def _validate_compare_ref(ref: str) -> None:
    """ref сравнения — branch/tag/sha. Кривой ref → 400 (не 500)."""
    from orchestrator.cosmo.domain.workspace import (
        validate_branch, validate_head_sha,
    )
    try:
        validate_branch(ref)
        return
    except WorkspaceContractError:
        pass
    try:
        validate_head_sha(ref)
    except WorkspaceContractError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"invalid ref: {ref!r}",
        ) from exc


@router.get("/workspace/compare", response_model=WorkspaceCompareResponse)
async def workspace_compare(
    repo: str = Query(..., description="owner/repo"),
    base: str = Query(..., description="Base ref (branch/tag/sha)"),
    head: str = Query(..., description="Head ref (branch/tag/sha)"),
    db: AsyncSession = Depends(get_db),
    principal: PrincipalContext = Depends(require_principal()),
    x_cosmo_domain: str | None = Header(None, alias="X-Cosmo-Domain"),
) -> WorkspaceCompareResponse:
    """Сравнение двух Git tree snapshot-ов (клиентский diff).

    GET /api/v1/repos/workspace/compare?repo=owner/name&base=main&head=feature

    base == head → 400; неизвестный ref → 404; >500 файлов → 413.
    Патчи строятся локально (difflib); бинарные файлы → isBinary=true,
    patch=null. base/head в ответе — разрешённые commit SHA.
    """
    _validate_or_400(repo=repo)
    _validate_compare_ref(base)
    _validate_compare_ref(head)
    if base == head:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="base and head must be different refs",
        )

    _app, _binding = await _binding_for_repo(db, repo, principal, x_cosmo_domain)
    owner, _, name = repo.partition("/")

    try:
        adapter = build_adapter()
        result = adapter.compare_refs(owner, name, base, head)
    except GiteaCompareLimitError as exc:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=str(exc),
        ) from exc
    except Exception as exc:  # noqa: BLE001
        raise forge_http_error(exc, f"compare {repo} {base}..{head}") from exc

    files = [
        WorkspaceCompareFile(
            path=f.path,
            old_path=f.old_path,
            status=f.status,
            additions=f.additions,
            deletions=f.deletions,
            patch=f.patch,
            is_binary=f.is_binary,
            truncated=f.truncated,
        )
        for f in result.files
    ]
    return WorkspaceCompareResponse(
        base=result.base_sha,
        head=result.head_sha,
        files=files,
        total_additions=sum(f.additions for f in files),
        total_deletions=sum(f.deletions for f in files),
        files_changed=len(files),
    )


# ── COS-132: Full repository security scan & SARIF export ────────────────────


@router.post("/workspace/gate-scan", response_model=WorkspaceGateScanResponse)
async def workspace_gate_scan(
    body: WorkspaceGateScanRequest,
    db: AsyncSession = Depends(get_db),
    principal: PrincipalContext = Depends(require_principal()),
    x_cosmo_domain: str | None = Header(None, alias="X-Cosmo-Domain"),
):
    """Полный аудит безопасности дерева репозитория/ветки.

    POST /api/v1/repos/workspace/gate-scan
    Body: { repo, ref?, maxFiles?, exportFormat? }

    ref пуст → default branch binding'а. Дерево берётся через
    resolve_ref + get_tree_by_sha (COS-125). Файлы > maxFiles → 413.
    exportFormat="sarif" → `application/sarif+json` (SARIF 2.1.0).
    """
    _validate_or_400(repo=body.repo)
    if body.ref:
        _validate_compare_ref(body.ref)

    _app, binding = await _binding_for_repo(
        db, body.repo, principal, x_cosmo_domain,
    )
    owner, _, name = body.repo.partition("/")
    resolved_ref = body.ref or binding.default_branch or "main"

    from orchestrator.cosmo.domain.gate_verdict import (
        compute_verdict,
        scan_tree,
        to_sarif,
    )

    started = time.perf_counter()
    try:
        adapter = build_adapter()
        commit_sha = adapter.resolve_ref(owner, name, resolved_ref)
        tree = adapter.get_tree_by_sha(owner, name, commit_sha, recursive=True)
    except Exception as exc:  # noqa: BLE001
        raise forge_http_error(exc, f"tree of {body.repo}@{resolved_ref}") from exc

    blob_entries = [e for e in tree if getattr(e, "type", "blob") == "blob"]
    if len(blob_entries) > body.max_files:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=(
                f"Repository {body.repo}@{resolved_ref} has "
                f"{len(blob_entries)} files (maxFiles={body.max_files})"
            ),
        )

    def _blob_loader(entry):
        """bytes blob-а: git/blobs по sha, fallback contents/{path}."""
        try:
            return adapter.get_blob(owner, name, entry.sha)
        except (LookupError, ValueError):
            try:
                text, _ = adapter.read_file(
                    owner, name, entry.path, ref=commit_sha,
                )
                return text
            except (LookupError, ValueError):
                return None

    scan = scan_tree(tree, _blob_loader)
    verdict = compute_verdict(scan.violations)
    duration_ms = int((time.perf_counter() - started) * 1000)

    if body.export_format == "sarif":
        sarif = to_sarif(scan.violations)
        sarif["runs"][0]["properties"] = {
            "repo": body.repo,
            "ref": resolved_ref,
            "commitSha": commit_sha,
            "scannedFiles": scan.scanned_files,
            "cleanFiles": scan.clean_files,
            "skippedFiles": scan.skipped_files,
            "verdict": verdict,
        }
        return JSONResponse(content=sarif, media_type="application/sarif+json")

    return WorkspaceGateScanResponse(
        scanned_files=scan.scanned_files,
        clean_files=scan.clean_files,
        block_violations=sum(
            1 for v in scan.violations if v.severity == "BLOCK"
        ),
        warn_violations=sum(
            1 for v in scan.violations if v.severity == "WARN"
        ),
        verdict=verdict,
        duration_ms=duration_ms,
        violations=[
            WorkspaceGateViolation(
                path=v.path,
                rule_id=v.rule_id,
                severity=v.severity,
                message=v.message,
                line_number=v.line_number,
                snippet=v.snippet,
            )
            for v in scan.violations
        ],
    )
