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
from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

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


def validate_ref(ref: str) -> str:
    """COS-177: ref deep-link — commit SHA (полный или >=7-hex префикс).

    Отдельно от validate_head_sha: 400 называет именно ref (не head_sha),
    ref не привязан к CAS-семантике головы ветки — это authority snapshot'а.
    """
    if not ref or not _SHA_RE.match(ref):
        _reject(ref, "ref (commit sha, >=7 hex)")
    return ref


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


def validate_pipeline_name(name: str) -> str:
    """Имя пайплайна из discovery COS-118: непустое, без управляющих символов.

    Имя сверяется с результатом discovery (COS-118), а не превращается в
    свободный путь, поэтому здесь только базовая гигиена строки.
    """
    if not name or name.strip() != name:
        _reject(name, "pipeline_name")
    if len(name) > 200:
        _reject(name, "pipeline_name (too long)")
    for ch in ("\x00", "\n", "\r", "\\"):
        if ch in name:
            _reject(name, "pipeline_name")
    return name


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


# ── COS-107: Workspace Commit DTO (legacy Contents pipeline) ────────────
# Канонические имена WorkspaceCommitRequest/Response заняты COS-124;
# legacy DTO ниже переименованы в WorkspaceContents* и обслуживают
# старый CAS-роут POST /workspace/commit.

FileChangeAction = Literal["upsert", "delete"]


class WorkspaceContentsFileChange(BaseModel):
    """Одно изменение в CAS-коммите: upsert (создать/обновить) или delete."""
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


class WorkspaceContentsCommitRequest(_WorkspaceDTO):
    """CAS-коммит: набор изменений от base_blob_sha к новому дереву REPLACE."""
    repo: str
    branch: str
    message: str = Field(default="workspace commit", min_length=1)
    changes: List[WorkspaceContentsFileChange] = Field(min_length=1)
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


class WorkspaceContentsCommitResponse(_WorkspaceDTO):
    """Результат CAS-коммита: новый commit_sha + tree_sha."""
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


# ── COS-124: Atomic multi-file commit DTO ───────────────────────────────

WorkspaceFileChangeAction = Literal["create", "update", "delete"]


class WorkspaceFileChange(_WorkspaceDTO):
    """Одно файловое изменение атомарного коммита.

    create/update — content обязателен (строка, возможно пустая);
    delete — content должен быть None (контент не передаётся).
    base_blob_sha (COS-185) — optional файловая база клиента: при конфликте
    уезжает в typed 409 WORKSPACE_CONFLICT как expected_sha файлового уровня.
    """
    path: str
    content: Optional[str] = None
    action: WorkspaceFileChangeAction
    base_blob_sha: Optional[str] = Field(alias="baseBlobSha", default=None)

    @field_validator("path")
    @classmethod
    def _path_ok(cls, v: str) -> str:
        if v == "":
            _reject(v, "path (empty)")
        return validate_tree_path(v)

    @field_validator("base_blob_sha")
    @classmethod
    def _base_sha_ok(cls, v: Optional[str]) -> Optional[str]:
        if v is None or v == "":
            return None
        return validate_head_sha(v)

    @model_validator(mode="after")
    def _content_matches_action(self) -> "WorkspaceFileChange":
        if self.action in ("create", "update"):
            if self.content is None:
                raise ValueError(f"content is required for action={self.action!r}")
        elif self.content is not None:
            raise ValueError("content must be null for action='delete'")
        return self


class WorkspaceCommitRequest(_WorkspaceDTO):
    """Атомарный multi-file коммит: create/update/delete одним запросом."""
    repo: str
    branch: str
    message: str = Field(min_length=1, max_length=500)
    author_name: Optional[str] = Field(alias="authorName", default=None)
    author_email: Optional[str] = Field(alias="authorEmail", default=None)
    file_changes: List[WorkspaceFileChange] = Field(alias="fileChanges", min_length=1)
    # COS-181: явная optimistic concurrency по голове ветки (полный sha или
    # >=7-hex префикс). Расхождение → typed 409 WORKSPACE_CONFLICT до записей.
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
    """Результат атомарного коммита: sha, ссылка, дата, число файлов."""
    sha: str
    html_url: str = Field(alias="htmlUrl")
    authored_at: datetime = Field(alias="authoredAt")
    files_changed: int = Field(alias="filesChanged")

    @field_validator("sha")
    @classmethod
    def _sha_ok(cls, v: str) -> str:
        return validate_head_sha(v)


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
    """Запрос на запуск Woodpecker pipeline из IDE.

    pipeline_name — имя пайплайна из discovery (COS-118). Если задано,
    Woodpecker запускает именно этот конфиг; None → default-поведение.
    """
    repo: str
    branch: str = Field(min_length=1)
    commit_sha: str = Field(alias="commitSha")
    pipeline_name: Optional[str] = Field(alias="pipelineName", default=None)

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

    @field_validator("pipeline_name")
    @classmethod
    def _pipeline_name_ok(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        return validate_pipeline_name(v)


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


# ── COS-133: Workspace Run Lifecycle DTO ────────────────────────────────


class WorkspaceRunStepSummary(_WorkspaceDTO):
    """Один шаг пайплайна в детализации запуска."""
    name: str
    status: str  # pending / running / success / failure / killed / ...
    exit_code: int | None = None
    duration_ms: int | None = None
    started_at: str | None = None
    finished_at: str | None = None


class WorkspaceRunDetailResponse(_WorkspaceDTO):
    """Детальная информация по запуску: статус, тайминги, шаги."""
    run_id: str
    repo: str  # owner/name
    branch: str
    commit_sha: str
    status: str
    pipeline_number: int | None = None
    original_run_id: str | None = None
    duration_ms: int | None = None
    started_at: str | None = None
    finished_at: str | None = None
    steps: list[WorkspaceRunStepSummary] = Field(default_factory=list)


class WorkspaceRunCancelResponse(_WorkspaceDTO):
    """Результат отмены запуска."""
    run_id: str
    status: str  # killed
    cancelled: bool = True


class WorkspaceRunRerunResponse(_WorkspaceDTO):
    """Результат перезапуска: новый run_id + связь с исходным запуском."""
    run_id: str
    original_run_id: str
    pipeline_number: int
    pipeline_id: int | None = None
    status: str
    tracking_url: str | None = None


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


# ── COS-118: Workspace Pipeline Discovery DTO ───────────────────────────────


class WorkspacePipelineSummary(_WorkspaceDTO):
    """Один пайплайн: имя, путь, формат, шаги."""
    name: str
    path: str
    format: str  # "yaml" | "yml" | "invalid"
    is_default: bool = Field(alias="isDefault", default=False)
    step_names: list[str] = Field(alias="stepNames", default_factory=list)


class WorkspacePipelineListResponse(_WorkspaceDTO):
    """Список пайплайнов репозитория."""
    pipelines: list[WorkspacePipelineSummary]
    default_pipeline: str | None = Field(alias="defaultPipeline", default=None)


# ── COS-120: Workspace File Actions & Mutator DTO ───────────────────────────


class WorkspaceFileCreateRequest(_WorkspaceDTO):
    """Создание файла."""
    repo: str
    path: str
    content: str
    message: str = Field(default="Create file via Web IDE")
    base_branch: str = Field(alias="baseBranch", default="")
    is_base64: bool = Field(alias="isBase64", default=False)

    @field_validator("repo")
    @classmethod
    def _repo_ok(cls, v: str) -> str:
        return validate_repo(v)

    @field_validator("path")
    @classmethod
    def _path_ok(cls, v: str) -> str:
        return validate_tree_path(v)


class WorkspaceFileDeleteRequest(_WorkspaceDTO):
    """Удаление файла."""
    repo: str
    path: str
    message: str = Field(default="Delete file via Web IDE")
    branch: str = Field(default="")
    last_commit_sha: str | None = Field(alias="lastCommitSha", default=None)

    @field_validator("repo")
    @classmethod
    def _repo_ok(cls, v: str) -> str:
        return validate_repo(v)

    @field_validator("path")
    @classmethod
    def _path_ok(cls, v: str) -> str:
        return validate_tree_path(v)


class WorkspaceFileMoveRequest(_WorkspaceDTO):
    """Перемещение / переименование файла."""
    repo: str
    source_path: str = Field(alias="sourcePath")
    target_path: str = Field(alias="targetPath")
    message: str = Field(default="Move file via Web IDE")
    branch: str = Field(default="")

    @field_validator("repo")
    @classmethod
    def _repo_ok(cls, v: str) -> str:
        return validate_repo(v)

    @field_validator("source_path", "target_path")
    @classmethod
    def _path_ok(cls, v: str) -> str:
        return validate_tree_path(v)


class WorkspaceFileActionResponse(_WorkspaceDTO):
    """Результат файловой операции."""
    commit_sha: str = Field(alias="commitSha")
    path: str
    status: str  # "created" | "deleted" | "moved"


# ── COS-123: Pre-flight Quality Gate DTO ─────────────────────────────────────


class WorkspaceGateFileChange(_WorkspaceDTO):
    """Один файл для проверки: путь + содержимое (draft/head/blob)."""
    path: str
    content: str


class WorkspaceGateCheckRequest(_WorkspaceDTO):
    """Запрос на пре-флайт проверку перед коммитом."""
    repo: str
    branch: str = ""
    files: list[WorkspaceGateFileChange]

    @field_validator("repo")
    @classmethod
    def _repo_ok(cls, v: str) -> str:
        return validate_repo(v)


class WorkspaceGateViolation(_WorkspaceDTO):
    """Одно нарушение quality gate."""
    path: str
    rule_id: str = Field(alias="ruleId")
    severity: str  # "BLOCK" | "WARN"
    message: str
    line_number: int = Field(alias="lineNumber", default=0)
    snippet: str = ""


class WorkspaceGateVerdictResponse(_WorkspaceDTO):
    """Результат пре-флайт проверки."""
    verdict: str  # "PASS" | "WARN" | "BLOCK"
    violations: list[WorkspaceGateViolation] = []
    summary: dict = {}  # {"total": N, "block": N, "warn": N}


# ── COS-125: Workspace Compare (tree snapshot diff) DTO ──────────────────────

CompareFileStatus = Literal["added", "modified", "deleted", "renamed"]


class WorkspaceCompareFile(_WorkspaceDTO):
    """Один файл в сравнении двух Git tree snapshot-ов."""
    path: str
    old_path: Optional[str] = Field(alias="oldPath", default=None)
    status: CompareFileStatus
    additions: int = 0
    deletions: int = 0
    patch: Optional[str] = None
    is_binary: bool = Field(alias="isBinary", default=False)
    truncated: bool = False  # blob превысил лимит — контент не читался

    @field_validator("path")
    @classmethod
    def _path_ok(cls, v: str) -> str:
        return validate_tree_path(v)

    @field_validator("old_path")
    @classmethod
    def _old_path_ok(cls, v: Optional[str]) -> Optional[str]:
        return None if v is None else validate_tree_path(v)


class WorkspaceCompareResponse(_WorkspaceDTO):
    """Результат сравнения двух Git tree snapshot-ов.

    base/head — разрешённые commit SHA (не исходные ref-строки).
    """
    base: str
    head: str
    files: list[WorkspaceCompareFile]
    total_additions: int = Field(alias="totalAdditions")
    total_deletions: int = Field(alias="totalDeletions")
    files_changed: int = Field(alias="filesChanged")


# ── COS-132: Full repository security scan & SARIF export DTO ────────────────

GateScanExportFormat = Literal["json", "sarif"]


class WorkspaceGateScanRequest(_WorkspaceDTO):
    """Запрос полного скана дерева репозитория/ветки."""
    repo: str
    ref: Optional[str] = None  # пусто → default branch binding'а
    max_files: int = Field(alias="maxFiles", default=1000, ge=1, le=1000)
    export_format: GateScanExportFormat = Field(
        alias="exportFormat", default="json",
    )

    @field_validator("repo")
    @classmethod
    def _repo_ok(cls, v: str) -> str:
        return validate_repo(v)

    @field_validator("ref")
    @classmethod
    def _ref_ok(cls, v: Optional[str]) -> Optional[str]:
        if v is None or v == "":
            return None
        return validate_branch(v)


class WorkspaceGateScanResponse(_WorkspaceDTO):
    """Агрегированный результат полного скана дерева."""
    scanned_files: int = Field(alias="scannedFiles")
    clean_files: int = Field(alias="cleanFiles")
    block_violations: int = Field(alias="blockViolations")
    warn_violations: int = Field(alias="warnViolations")
    verdict: str  # "PASS" | "WARN" | "BLOCK"
    duration_ms: int = Field(alias="durationMs")
    violations: list[WorkspaceGateViolation] = []
