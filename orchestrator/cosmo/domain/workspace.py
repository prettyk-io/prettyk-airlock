# -*- coding: utf-8 -*-
"""COS-102: Pydantic v2 DTO Web IDE workspace-контракта (CAS-ready).

Канонический FE-контракт: prettyk-ide ``src/workspace/types.ts`` (camelCase:
``headSha``). Здесь snake_case-поля + camelCase-алиасы (``to_camel``):
``model_dump(by_alias=True)`` даёт ровно ключи TS-интерфейсов,
``model_validate_json`` принимает TS-пейлоады напрямую.

Ригидность: ``extra="forbid"`` — незнакомое поле в запросе это ошибка
контракта, а не тихий игнор (драйф FE/BE ловится на границе).

CAS: ``head_sha`` обязателен в tree/blob-запросах — без него операция
не адресуемая (ветка могла уехать); blob-ответ несёт ``base_blob_sha``
(sha blob'а, на котором строится черновик — база для 3-way merge).

Path traversal: repo/path/branch валидируются на уровне Pydantic —
``..``, абсолютные пути, backslash, двойные слэши, NUL — reject до
того, как что-либо дошло до ForgeAdapter (COS-103).
"""
from __future__ import annotations

import re
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

# ── Literals (зеркало types.ts) ────────────────────────────────────────

WorkspaceCapability = Literal["read", "draft", "commit", "run"]
WorkspaceAuthorization = Literal["allow", "deny"]
TreeEntryKind = Literal["file", "directory"]
TreeEntryStatus = Literal["M", "U", "D"]
BlobEncoding = Literal["utf-8"]

# ── Валидация имён/путей (traversal guard) ─────────────────────────────

# repo: "owner/repo" (Gitea full_name); сегменты без traversal-символов
_REPO_SEGMENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
# branch: git ref без спецсимволов; без ведущего "-" (option injection)
_BRANCH_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]*$")
# head_sha: git sha (7..64 hex — допускаем сокращённые и sha256-репо)
_SHA_RE = re.compile(r"^[0-9a-fA-F]{7,64}$")


class WorkspaceContractError(ValueError):
    """Нарушение workspace-контракта (traversal / кривое имя)."""


def _reject(value: str, what: str) -> None:
    raise WorkspaceContractError(f"invalid {what}: {value!r}")


def validate_repo(repo: str) -> str:
    """repo = "owner/repo": два сегмента, без traversal."""
    if not repo or repo.strip() != repo:
        _reject(repo, "repo")
    parts = repo.split("/")
    if len(parts) != 2:
        _reject(repo, "repo (expected 'owner/repo')")
    for part in parts:
        if not _REPO_SEGMENT_RE.match(part):
            _reject(repo, "repo segment")
    return repo


def validate_branch(branch: str) -> str:
    if not branch or branch.strip() != branch:
        _reject(branch, "branch")
    if branch.startswith("/") or branch.endswith("/"):
        _reject(branch, "branch (leading/trailing slash)")
    if ".." in branch or "\\" in branch or "\x00" in branch:
        _reject(branch, "branch")
    for part in branch.split("/"):
        if part in ("", ".", ".."):
            _reject(branch, "branch segment")
    if not _BRANCH_RE.match(branch):
        _reject(branch, "branch")
    return branch


def validate_head_sha(sha: str) -> str:
    if not sha or not _SHA_RE.match(sha):
        _reject(sha, "head_sha")
    return sha


def validate_tree_path(path: str) -> str:
    """Путь файла/каталога в репо: относительный, без traversal.

    Пустая строка валидна только там, где поле опционально; для blob
    path обязателен (см. WorkspaceBlobRequest).
    """
    if "\x00" in path:
        _reject(path, "path (NUL)")
    if path.strip() != path:
        _reject(path, "path (whitespace edges)")
    if path.startswith("/") or path.startswith("\\"):
        _reject(path, "path (absolute)")
    if "\\" in path or ":" in path:
        _reject(path, "path (backslash / drive letter)")
    if path == "":
        return path
    for part in path.split("/"):
        if part in ("", ".", ".."):
            _reject(path, "path segment")
    return path


# ── Базовая конфигурация DTO ───────────────────────────────────────────

class _WorkspaceDTO(BaseModel):
    model_config = ConfigDict(
        extra="forbid",          # ригидность: незнакомое поле = ошибка
        populate_by_name=True,   # принимать и snake_case, и алиасы
    )


# Алиасы контракта types.ts (camelCase) задаются явно:
#   head_sha → headSha, base_blob_sha → baseBlobSha (см. Field(alias=...)).

# ── Requests ───────────────────────────────────────────────────────────

class WorkspaceBootstrapRequest(_WorkspaceDTO):
    """Открыть workspace репозитория. branch пуст → default branch."""
    repo: str
    branch: str = Field(default="")

    @field_validator("repo")
    @classmethod
    def _repo_ok(cls, v: str) -> str:
        return validate_repo(v)

    @field_validator("branch")
    @classmethod
    def _branch_ok(cls, v: str) -> str:
        return v if v == "" else validate_branch(v)


class WorkspaceTreeRequest(_WorkspaceDTO):
    """Дерево репо на ЗАФИКСИРОВАННОМ head_sha (CAS-ready чтение)."""
    repo: str
    branch: str
    head_sha: str = Field(alias="headSha")

    @field_validator("repo")
    @classmethod
    def _repo_ok(cls, v: str) -> str:
        return validate_repo(v)

    @field_validator("branch")
    @classmethod
    def _branch_ok(cls, v: str) -> str:
        return validate_branch(v)

    @field_validator("head_sha")
    @classmethod
    def _sha_ok(cls, v: str) -> str:
        return validate_head_sha(v)


class WorkspaceBlobRequest(_WorkspaceDTO):
    """Чтение файла на head_sha; path обязателен и traversal-guarded."""
    repo: str
    branch: str
    path: str
    head_sha: str = Field(alias="headSha")

    @field_validator("repo")
    @classmethod
    def _repo_ok(cls, v: str) -> str:
        return validate_repo(v)

    @field_validator("branch")
    @classmethod
    def _branch_ok(cls, v: str) -> str:
        return validate_branch(v)

    @field_validator("path")
    @classmethod
    def _path_ok(cls, v: str) -> str:
        if v == "":
            _reject(v, "path (empty)")
        return validate_tree_path(v)

    @field_validator("head_sha")
    @classmethod
    def _sha_ok(cls, v: str) -> str:
        return validate_head_sha(v)


# ── Responses ──────────────────────────────────────────────────────────

class TreeEntry(BaseModel):
    """Элемент дерева; status — рабочая дельта против head_sha (CAS)."""
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    path: str
    kind: TreeEntryKind
    status: Optional[TreeEntryStatus] = None

    @field_validator("path")
    @classmethod
    def _path_ok(cls, v: str) -> str:
        if v == "":
            _reject(v, "entry path (empty)")
        return validate_tree_path(v)


class WorkspaceBootstrapResponse(_WorkspaceDTO):
    """Capability context воркспейса: что IDE можно делать с репо."""
    repo: str
    branch: str
    head_sha: str = Field(alias="headSha")
    capabilities: List[WorkspaceCapability] = Field(default_factory=list)
    authorization: WorkspaceAuthorization

    @field_validator("repo")
    @classmethod
    def _repo_ok(cls, v: str) -> str:
        return validate_repo(v)

    @field_validator("branch")
    @classmethod
    def _branch_ok(cls, v: str) -> str:
        return validate_branch(v)

    @field_validator("head_sha")
    @classmethod
    def _sha_ok(cls, v: str) -> str:
        return validate_head_sha(v)


class WorkspaceTreeResponse(_WorkspaceDTO):
    """Плоское дерево (рекурсивно) на head_sha."""
    entries: List[TreeEntry] = Field(default_factory=list)


class WorkspaceBlobResponse(_WorkspaceDTO):
    """Файл + sha + база для CAS-записи (base_blob_sha)."""
    path: str
    content: str
    sha: str
    encoding: BlobEncoding = "utf-8"
    base_blob_sha: str = Field(alias="baseBlobSha")

    @field_validator("path")
    @classmethod
    def _path_ok(cls, v: str) -> str:
        if v == "":
            _reject(v, "path (empty)")
        return validate_tree_path(v)

    @field_validator("sha")
    @classmethod
    def _sha_ok(cls, v: str) -> str:
        return validate_head_sha(v)

    @field_validator("base_blob_sha")
    @classmethod
    def _base_sha_ok(cls, v: str) -> str:
        return validate_head_sha(v)


# ── COS-107: Workspace Commit DTO ──────────────────────────────────────

FileChangeAction = Literal["upsert", "delete"]


class FileChange(BaseModel):
    """Одно изменение в коммите: upsert (создать/обновить) или delete."""
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    path: str
    content: str = Field(default="")
    base_blob_sha: Optional[str] = Field(alias="baseBlobSha", default=None)
    action: FileChangeAction = "upsert"

    @field_validator("path")
    @classmethod
    def _path_ok(cls, v: str) -> str:
        if v == "":
            _reject(v, "path (empty)")
        return validate_tree_path(v)

    @field_validator("base_blob_sha")
    @classmethod
    def _sha_ok(cls, v: Optional[str]) -> Optional[str]:
        if v is None or v == "":
            return None
        return validate_head_sha(v)


class WorkspaceCommitRequest(_WorkspaceDTO):
    """CAS-коммит: набор изменений от base_blob_sha к новому дереву REPLACE."""
    repo: str
    branch: str
    message: str = Field(default="workspace commit", min_length=1)
    changes: List[FileChange] = Field(min_length=1)
    expected_head_sha: Optional[str] = Field(alias="expectedHeadSha", default=None)

    @field_validator("repo")
    @classmethod
    def _repo_ok(cls, v: str) -> str:
        return validate_repo(v)

    @field_validator("branch")
    @classmethod
    def _branch_ok(cls, v: str) -> str:
        return validate_branch(v)

    @field_validator("expected_head_sha")
    @classmethod
    def _sha_ok(cls, v: Optional[str]) -> Optional[str]:
        if v is None or v == "":
            return None
        return validate_head_sha(v)


class WorkspaceCommitResponse(_WorkspaceDTO):
    """Результат коммита: новый commit_sha + tree_sha."""
    commit_sha: str = Field(alias="commitSha")
    branch: str
    tree_sha: str = Field(alias="treeSha")

    @field_validator("commit_sha")
    @classmethod
    def _sha_ok(cls, v: str) -> str:
        return validate_head_sha(v)

    @field_validator("tree_sha")
    @classmethod
    def _treesha_ok(cls, v: str) -> str:
        return validate_head_sha(v)

    @field_validator("branch")
    @classmethod
    def _branch_ok(cls, v: str) -> str:
        return validate_branch(v)


# ── COS-110: Workspace Draft DTO ────────────────────────────────────────



class WorkspaceDraftUpsertRequest(_WorkspaceDTO):
    """Сохранение черновика файла (upsert)."""
    repo: str
    branch: str
    path: str
    content: str
    base_blob_sha: Optional[str] = Field(alias="baseBlobSha", default=None)

    @field_validator("repo")
    @classmethod
    def _repo_ok(cls, v: str) -> str:
        return validate_repo(v)

    @field_validator("branch")
    @classmethod
    def _branch_ok(cls, v: str) -> str:
        return validate_branch(v)

    @field_validator("path")
    @classmethod
    def _path_ok(cls, v: str) -> str:
        if not v or not v.strip():
            _reject(v, "path (empty)")
        return validate_tree_path(v)

    @field_validator("base_blob_sha")
    @classmethod
    def _sha_ok(cls, v: Optional[str]) -> Optional[str]:
        if v is None or v == "":
            return None
        return validate_head_sha(v)


class WorkspaceDraftResponse(_WorkspaceDTO):
    """Текущий черновик файла."""
    path: str
    content: str
    base_blob_sha: Optional[str] = Field(alias="baseBlobSha")
    updated_at: Optional[str] = Field(alias="updatedAt", default=None)

    @field_validator("path")
    @classmethod
    def _path_ok(cls, v: str) -> str:
        return validate_tree_path(v)


class WorkspaceDiffResponse(_WorkspaceDTO):
    """3-way diff: base (blob из коммита) vs draft (Valkey) vs head (ветка)."""
    path: str
    base_content: Optional[str] = Field(alias="baseContent")
    draft_content: Optional[str] = Field(alias="draftContent")
    head_content: Optional[str] = Field(alias="headContent")
    has_conflict: bool = Field(alias="hasConflict")
    additions: int = 0
    deletions: int = 0

    @field_validator("path")
    @classmethod
    def _path_ok(cls, v: str) -> str:
        return validate_tree_path(v)


# ── COS-108: Workspace Run DTO ──────────────────────────────────────────

class WorkspaceRunRequest(_WorkspaceDTO):
    """Запрос на запуск Woodpecker pipeline из IDE."""
    repo: str
    branch: str = Field(min_length=1)
    commit_sha: str = Field(alias="commitSha")

    @field_validator("repo")
    @classmethod
    def _repo_ok(cls, v: str) -> str:
        return validate_repo(v)

    @field_validator("branch")
    @classmethod
    def _branch_ok(cls, v: str) -> str:
        return validate_branch(v)

    @field_validator("commit_sha")
    @classmethod
    def _sha_ok(cls, v: str) -> str:
        return validate_head_sha(v)


class WorkspaceRunResponse(_WorkspaceDTO):
    """Результат запуска: run_id для SSE-подключения."""
    run_id: str
    pipeline_number: int
    pipeline_id: int | None = None
    status: str
    tracking_url: str | None = None


# ── COS-112: Workspace Run History & Step Logs DTO ──────────────────────


class WorkspaceRunSummary(_WorkspaceDTO):
    """Один прогон в истории запусков workspace."""
    run_id: str
    repo_owner: str
    repo_name: str
    branch: str
    commit_sha: str
    pipeline_number: int | None = None
    status: str  # pending / running / succeeded / failed
    tracking_url: str | None = None
    created_at: str  # ISO-8601 строка (сериализация datetime)


class WorkspaceRunListResponse(_WorkspaceDTO):
    """Пагинированный список прогонов."""
    runs: list[WorkspaceRunSummary]
    total: int  # всего записей по фильтру
    limit: int
    offset: int


class StepLogsResponse(_WorkspaceDTO):
    """Постраничный ответ с логами одного шага."""
    run_id: str
    step_id: int
    step_name: str | None = None
    total_lines: int
    lines: list[str]
    has_more: bool = False  # True если есть ещё строки за offset+limit


# ── COS-114: Workspace Search DTO ───────────────────────────────────────


class WorkspaceSearchMatch(_WorkspaceDTO):
    """Одно вхождение поиска в файле."""
    path: str
    line_number: int = Field(alias="lineNumber")
    line_content: str = Field(alias="lineContent")
    match_start: int = Field(alias="matchStart")
    match_end: int = Field(alias="matchEnd")


class WorkspaceSearchResponse(_WorkspaceDTO):
    """Результат поиска по кодовой базе."""
    query: str
    matches: list[WorkspaceSearchMatch]
    total_matches: int = Field(alias="totalMatches")
    scanned_files: int = Field(alias="scannedFiles")
    has_more: bool = Field(alias="hasMore", default=False)


# ── COS-113: Workspace Branches & Tags DTO ──────────────────────────────


class BranchNameValidator:
    """Git ref name validation — rejects special chars and traversal."""
    _RE = re.compile(r"^(?![-.])[A-Za-z0-9][A-Za-z0-9._/-]*[A-Za-z0-9]$|^[A-Za-z0-9]$")


def validate_branch_name(v: str) -> str:
    if not v or not BranchNameValidator._RE.match(v):
        raise WorkspaceContractError(f"invalid branch name: {v!r}")
    return v


class WorkspaceBranchSummary(_WorkspaceDTO):
    """Одна ветка: имя, SHA головы, флаги."""
    name: str
    sha: str  # HEAD commit sha
    is_default: bool = Field(alias="isDefault", default=False)
    is_protected: bool = Field(alias="isProtected", default=False)

    @field_validator("name")
    @classmethod
    def _name_ok(cls, v: str) -> str:
        return validate_branch_name(v)


class WorkspaceBranchListResponse(_WorkspaceDTO):
    """Список веток."""
    branches: list[WorkspaceBranchSummary]
    default_branch: str = Field(alias="defaultBranch")


class WorkspaceCreateBranchRequest(_WorkspaceDTO):
    """Создание ветки от существующей (база) или HEAD."""
    repo: str
    base_branch: str = Field(alias="baseBranch")  # от какой ветки создать
    new_branch: str = Field(alias="newBranch")     # имя новой ветки

    @field_validator("repo")
    @classmethod
    def _repo_ok(cls, v: str) -> str:
        return validate_repo(v)

    @field_validator("base_branch", "new_branch")
    @classmethod
    def _branch_ok(cls, v: str) -> str:
        return validate_branch(v)


class WorkspaceTagSummary(_WorkspaceDTO):
    """Один тег: имя, SHA коммита."""
    name: str
    sha: str

    @field_validator("name")
    @classmethod
    def _name_ok(cls, v: str) -> str:
        if not v or not v.strip():
            raise WorkspaceContractError(f"invalid tag name: {v!r}")
        return v.strip()


class WorkspaceTagListResponse(_WorkspaceDTO):
    """Список тегов."""
    tags: list[WorkspaceTagSummary]


# ── COS-116: Workspace Commits History ──────────────────────────────────


class WorkspaceCommitSummary(_WorkspaceDTO):
    """Один коммит: SHA, автор, сообщение, родительские хэши."""
    sha: str
    short_sha: str = Field(alias="shortSha")
    message: str
    author_name: str = Field(alias="authorName")
    author_email: str = Field(alias="authorEmail")
    committed_at: str = Field(alias="committedAt")  # ISO-8601
    parent_shas: list[str] = Field(alias="parentShas", default_factory=list)


class WorkspaceCommitListResponse(_WorkspaceDTO):
    """Пагинированный список коммитов."""
    commits: list[WorkspaceCommitSummary]
    total: int
    has_more: bool = Field(alias="hasMore")
