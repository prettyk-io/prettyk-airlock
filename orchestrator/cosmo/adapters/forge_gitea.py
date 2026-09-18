"""
COS-007: Gitea ForgeAdapter — полный порт из prettyk-dev.

Реализация ForgeAdapter для Gitea API v1.
Методы: register_domain, get_repo_info, list_repos, set_commit_status.
Webhook handler: on_push → Plan Compiler trigger.

COS-096 (live forge cycle): чтение живого source (read_file, list_commits),
идемпотентный ensure_webhook (reuse по URL + retry на транзиенты),
basic-auth поддержка (dev-стенд без API-токена).
"""
from __future__ import annotations

import base64
import difflib
import hashlib
import hmac
import logging
import time
from dataclasses import dataclass
from typing import Any

import requests

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 30
# COS-096: транзиентные коды/ошибки для retry (edge/gitea мигает — не фейл).
_TRANSIENT_STATUSES = {502, 503, 504}
_RETRY_ATTEMPTS = 3
_RETRY_BACKOFF_S = 0.5


@dataclass
class GiteaRepoInfo:
    """Информация о репозитории Gitea."""
    id: int
    owner: str
    name: str
    full_name: str
    default_branch: str
    clone_url: str
    ssh_url: str
    webhook_id: int | None = None


@dataclass
class GiteaCommitStatus:
    """Статус коммита (аналог GitHub Status API)."""
    state: str
    context: str
    description: str = ""
    target_url: str = ""


@dataclass
class GiteaCommit:
    """Коммит из живого репозитория (COS-096)."""
    sha: str
    message: str
    author: str
    timestamp: str


@dataclass
class GiteaTreeEntry:
    """Element git-dereva (COS-103 workspace API)."""
    path: str
    type: str  # "blob" | "tree" | "commit" | "submodule"
    sha: str
    size: int | None = None


# ── COS-125: Compare двух tree snapshot-ов ─────────────────────────────

_MAX_COMPARE_FILES = 500
_MAX_COMPARE_BLOB_BYTES = 2 * 1024 * 1024  # 2 MiB на текстовый blob


@dataclass
class _SnapshotChange:
    """Внутреннее представление различия snapshot-ов (до чтения блобов)."""
    status: str  # added | modified | deleted | renamed
    path: str
    old_path: str | None = None
    base_sha: str | None = None
    head_sha: str | None = None


@dataclass
class GiteaCompareFile:
    """Один файл в результате сравнения ref-ов."""
    path: str
    status: str  # added | modified | deleted | renamed
    old_path: str | None = None
    additions: int = 0
    deletions: int = 0
    patch: str | None = None
    is_binary: bool = False
    truncated: bool = False


@dataclass
class GiteaCompareResult:
    """Полный результат сравнения: разрешённые SHA + файлы."""
    base_sha: str
    head_sha: str
    files: list[GiteaCompareFile]


class GiteaCompareLimitError(RuntimeError):
    """Сравнение затронуло больше файлов, чем разрешено лимитом."""


def _is_binary_bytes(data: bytes) -> bool:
    """Бинарность по NUL-байту в начале содержимого."""
    return b"\x00" in data[:8192]


def _decode_text(data: bytes) -> str | None:
    """bytes → utf-8 str либо None, если контент бинарный/не декодируется."""
    if _is_binary_bytes(data):
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _classify_snapshots(
    base_map: dict[str, GiteaTreeEntry],
    head_map: dict[str, GiteaTreeEntry],
) -> list[_SnapshotChange]:
    """Локально сравнить два snapshot-а {path → blob entry}.

    Только в head → added; только в base → deleted; разные sha → modified;
    равные sha → не включается. Rename: удалённый и добавленный с равным
    blob sha (эвристика), иначе deleted + added.
    """
    changes: list[_SnapshotChange] = []
    deleted: list[GiteaTreeEntry] = []
    for path, bentry in base_map.items():
        hentry = head_map.get(path)
        if hentry is None:
            deleted.append(bentry)
        elif hentry.sha != bentry.sha:
            changes.append(_SnapshotChange(
                status="modified", path=path,
                base_sha=bentry.sha, head_sha=hentry.sha,
            ))

    added = [e for p, e in head_map.items() if p not in base_map]
    used_deleted: set[int] = set()
    for aentry in added:
        match = next(
            (i for i, d in enumerate(deleted)
             if i not in used_deleted and d.sha == aentry.sha),
            None,
        )
        if match is not None:
            used_deleted.add(match)
            changes.append(_SnapshotChange(
                status="renamed", path=aentry.path,
                old_path=deleted[match].path,
                base_sha=deleted[match].sha, head_sha=aentry.sha,
            ))
        else:
            changes.append(_SnapshotChange(
                status="added", path=aentry.path, head_sha=aentry.sha,
            ))

    for i, dentry in enumerate(deleted):
        if i not in used_deleted:
            changes.append(_SnapshotChange(
                status="deleted", path=dentry.path, base_sha=dentry.sha,
            ))

    changes.sort(key=lambda c: c.path)
    return changes


def _unified_patch(
    base_text: str, head_text: str, path: str, old_path: str | None = None,
) -> tuple[str | None, int, int]:
    """Локальный unified diff → (patch, additions, deletions).

    Нет различий → patch=None. Числа считаются по +/- строкам патча.
    """
    old_label = f"a/{old_path or path}"
    new_label = f"b/{path}"
    diff_lines = list(difflib.unified_diff(
        base_text.splitlines(keepends=True),
        head_text.splitlines(keepends=True),
        fromfile=old_label,
        tofile=new_label,
    ))
    additions = sum(
        1 for ln in diff_lines if ln.startswith("+") and not ln.startswith("+++")
    )
    deletions = sum(
        1 for ln in diff_lines if ln.startswith("-") and not ln.startswith("---")
    )
    patch = "".join(diff_lines) or None
    return patch, additions, deletions


class GiteaConflictError(RuntimeError):
    """Конкурентный коммит / рассинхрон ref в Gitea (bulk Contents API, COS-124)."""


@dataclass
class ForgeDomain:
    """Зарегистрированный домен в forge."""
    domain_id: str
    org_name: str
    token_hash: str


class GiteaForgeAdapter:
    """Адаптер Gitea API для Cosmoport.

    COS-096: аутентификация — API token (``Authorization: token ...``)
    ИЛИ basic auth (username/password; dev-стенд с админом cosmo).
    """

    def __init__(
        self,
        base_url: str,
        token: str = "",
        username: str = "",
        password: str = "",
    ):
        self._base = base_url.rstrip("/")
        self._token = token
        self._username = username
        self._password = password
        self._session = requests.Session()
        self._session.headers.update({"Content-Type": "application/json"})
        if token:
            self._session.headers.update({"Authorization": f"token {token}"})
        elif username and password:
            self._session.auth = (username, password)
        self._domains: dict[str, ForgeDomain] = {}

    # ── HTTP core (COS-096: retry на транзиентных ошибках) ────────────

    def _request(self, method: str, path: str, **kwargs: Any) -> requests.Response:
        """Один HTTP-вызов с retry на транзиентах (5xx/timeout).

        Не ретраит 4xx — это честные ошибки, а не мигание сети.
        """
        last_exc: Exception | None = None
        for attempt in range(1, _RETRY_ATTEMPTS + 1):
            try:
                r = self._session.request(
                    method, f"{self._base}{path}",
                    timeout=DEFAULT_TIMEOUT, **kwargs,
                )
                if r.status_code in _TRANSIENT_STATUSES and attempt < _RETRY_ATTEMPTS:
                    logger.warning(
                        "Gitea transient %d on %s %s (attempt %d/%d), retrying",
                        r.status_code, method, path, attempt, _RETRY_ATTEMPTS,
                    )
                    time.sleep(_RETRY_BACKOFF_S * attempt)
                    continue
                return r
            except (requests.ConnectionError, requests.Timeout) as exc:
                last_exc = exc
                if attempt < _RETRY_ATTEMPTS:
                    logger.warning(
                        "Gitea connection error on %s %s (attempt %d/%d): %s",
                        method, path, attempt, _RETRY_ATTEMPTS, exc,
                    )
                    time.sleep(_RETRY_BACKOFF_S * attempt)
                    continue
        raise last_exc  # type: ignore[misc]

    def _get(self, path: str, **kwargs: Any) -> requests.Response:
        return self._request("GET", path, **kwargs)

    def _post(self, path: str, **kwargs: Any) -> requests.Response:
        return self._request("POST", path, **kwargs)

    def _patch(self, path: str, **kwargs: Any) -> requests.Response:
        return self._request("PATCH", path, **kwargs)

    def _put(self, path: str, **kwargs: Any) -> requests.Response:
        return self._request("PUT", path, **kwargs)

    def _delete(self, path: str, **kwargs: Any) -> requests.Response:
        return self._request("DELETE", path, **kwargs)

    def register_domain(self, domain_id: str, org_name: str) -> ForgeDomain:
        """Регистрирует Domain как организацию в Gitea."""
        r = self._get(f"/api/v1/orgs/{org_name}")
        if r.status_code == 200:
            logger.info("Org %s already exists, reusing", org_name)
        elif r.status_code == 404:
            r = self._post(
                "/api/v1/orgs",
                json={"username": org_name, "full_name": org_name, "visibility": "private"},
            )
            if r.status_code not in (200, 201):
                raise RuntimeError(f"Failed to create org {org_name}: {r.status_code} {r.text}")
            logger.info("Created org %s", org_name)
        else:
            r.raise_for_status()

        fd = ForgeDomain(
            domain_id=domain_id,
            org_name=org_name,
            token_hash=hashlib.sha256(self._token.encode()).hexdigest()[:16],
        )
        self._domains[domain_id] = fd
        return fd

    def get_repo_info(self, owner: str, repo: str) -> GiteaRepoInfo:
        """Получает информацию о репозитории."""
        r = self._get(f"/api/v1/repos/{owner}/{repo}")
        if r.status_code == 404:
            raise LookupError(f"Repository {owner}/{repo} not found")
        r.raise_for_status()
        data = r.json()
        return GiteaRepoInfo(
            id=data["id"],
            owner=data["owner"]["login"],
            name=data["name"],
            full_name=data["full_name"],
            default_branch=data.get("default_branch", "main"),
            clone_url=data["clone_url"],
            ssh_url=data["ssh_url"],
        )

    def list_repos(self, owner: str) -> list[GiteaRepoInfo]:
        """Список всех репозиториев владельца/организации."""
        repos: list[GiteaRepoInfo] = []
        page = 1
        while True:
            r = self._get(f"/api/v1/orgs/{owner}/repos", params={"page": page, "limit": 50})
            if r.status_code == 404:
                r = self._get(f"/api/v1/users/{owner}/repos", params={"page": page, "limit": 50})
            r.raise_for_status()
            data = r.json()
            if not data:
                break
            for repo in data:
                repos.append(GiteaRepoInfo(
                    id=repo["id"],
                    owner=repo["owner"]["login"],
                    name=repo["name"],
                    full_name=repo["full_name"],
                    default_branch=repo.get("default_branch", "main"),
                    clone_url=repo["clone_url"],
                    ssh_url=repo["ssh_url"],
                ))
            if len(data) < 50:
                break
            page += 1
        return repos

    def create_repo(self, owner: str, repo_name: str, *,
                    description: str = "", private: bool = True,
                    auto_init: bool = True) -> GiteaRepoInfo:
        """Создаёт репозиторий. Идемпотентно — если существует, возвращает существующий.

        Повторный вызов с тем же owner/repo_name не создаёт дубль.
        """
        try:
            existing = self.get_repo_info(owner, repo_name)
            logger.info("Repo %s/%s already exists, reusing (id=%s)", owner, repo_name, existing.id)
            return existing
        except LookupError:
            pass

        r = self._post(
            f"/api/v1/orgs/{owner}/repos",
            json={
                "name": repo_name,
                "description": description,
                "private": private,
                "auto_init": auto_init,
            },
        )
        if r.status_code == 404:
            r = self._post(
                "/api/v1/user/repos",
                json={
                    "name": repo_name,
                    "description": description,
                    "private": private,
                    "auto_init": auto_init,
                },
            )
        r.raise_for_status()
        data = r.json()
        logger.info("Created repo %s/%s (id=%s)", owner, repo_name, data.get("id"))
        return GiteaRepoInfo(
            id=data["id"],
            owner=data["owner"]["login"],
            name=data["name"],
            full_name=data["full_name"],
            default_branch=data.get("default_branch", "main"),
            clone_url=data["clone_url"],
            ssh_url=data["ssh_url"],
        )

    def link_repo(self, owner: str, repo_name: str, domain_id: str) -> GiteaRepoInfo:
        """Привязывает существующий репозиторий к Domain. Возвращает метаданные — не создаёт."""
        info = self.get_repo_info(owner, repo_name)
        logger.info("Linked repo %s/%s to domain %s", owner, repo_name, domain_id)
        return info

    def set_commit_status(
        self, owner: str, repo: str, sha: str, status: GiteaCommitStatus,
    ) -> None:
        """Устанавливает статус коммита (CI/CD feedback)."""
        r = self._post(
            f"/api/v1/repos/{owner}/{repo}/statuses/{sha}",
            json={
                "state": status.state,
                "context": status.context,
                "description": status.description,
                "target_url": status.target_url,
            },
        )
        r.raise_for_status()
        logger.debug("Set commit status %s for %s/%s@%s", status.state, owner, repo, sha[:8])

    # ── COS-096: чтение живого pipeline source ────────────────────────

    def read_file(self, owner: str, repo: str, path: str, ref: str = "") -> tuple[str, str]:
        """Читает файл из живого репозитория. Возвращает (content, sha).

        ref — branch/tag/sha; пусто → default branch (Gitea сам резолвит).
        404 → LookupError (missing repo/файл — честный негатив).
        Бинарный контент → ValueError (pipeline source обязан быть текстом).
        """
        quoted = requests.utils.quote(path, safe="")
        params = {"ref": ref} if ref else {}
        r = self._get(f"/api/v1/repos/{owner}/{repo}/contents/{quoted}", params=params)
        if r.status_code == 404:
            raise LookupError(f"File {path} not found in {owner}/{repo} (ref={ref or 'default'})")
        r.raise_for_status()
        data = r.json()
        # Гите-квирк (1.22, пустой репо): 200 + [] вместо 404 на любой путь.
        if isinstance(data, list):
            raise LookupError(
                f"File {path} not found in {owner}/{repo} (ref={ref or 'default'}; "
                f"forge returned directory/empty-repo listing)"
            )
        if data.get("type") != "file":
            raise ValueError(f"{path} in {owner}/{repo} is not a file (type={data.get('type')})")
        import base64
        raw = base64.b64decode(data.get("content", ""))
        encoding = data.get("encoding", "")
        if encoding != "base64":
            raise ValueError(f"Unsupported content encoding: {encoding!r}")
        return raw.decode("utf-8"), data.get("sha", "")

    # ── COS-096/COS-116/COS-129: единый источник коммитов ──────────────

    def _fetch_commits(
        self, owner: str, repo: str, ref: str | None = None,
        path: str | None = None, limit: int = 30, page: int = 1,
    ) -> list[dict]:
        """GET /commits — сырой ответ Gitea (общий для обеих проекций).

        ref — branch/tag/sha (Gitea-параметр `sha`); path — фильтр по файлу;
        page > 1 добавляет пагинацию. 404 → LookupError (роут отдаёт 404).
        """
        params: dict[str, Any] = {"limit": min(limit, 100)}
        if page > 1:
            params["page"] = page
        if ref:
            params["sha"] = ref
        if path:
            params["path"] = path
        r = self._get(f"/api/v1/repos/{owner}/{repo}/commits", params=params)
        if r.status_code == 404:
            raise LookupError(f"Repository {owner}/{repo} not found")
        r.raise_for_status()
        return r.json()

    def list_commits(
        self, owner: str, repo: str, ref: str = "", branch: str | None = None,
        path: str | None = None, limit: int = 10, page: int = 1,
    ) -> list[GiteaCommit]:
        """Канонический список коммитов (newest first) → GiteaCommit.

        COS-129: единственный метод с этим именем. `ref` (COS-096) и
        `branch` (COS-116) — взаимозаменяемые алиасы Gitea-параметра `sha`.
        Потребители: get_commit/get_tree (ref=...), routes/apps.py.
        """
        resolved_ref = ref or branch or None
        items = self._fetch_commits(
            owner, repo, ref=resolved_ref, path=path, limit=limit, page=page,
        )
        commits: list[GiteaCommit] = []
        for item in items[:limit]:
            author = (item.get("author") or {}).get("login") or "unknown"
            commit_info = item.get("commit") or {}
            commits.append(GiteaCommit(
                sha=item.get("sha", ""),
                message=(commit_info.get("message") or "").split("\n", 1)[0],
                author=author,
                timestamp=commit_info.get("author", {}).get("date", ""),
            ))
        return commits

    # --- COS-103: workspace API (get_commit, get_tree) ---

    def get_commit(self, owner: str, repo: str, ref: str = "") -> GiteaCommit:
        commits = self.list_commits(owner, repo, ref=ref, limit=1)
        if not commits:
            raise LookupError(f"No commits in {owner}/{repo}")
        return commits[0]

    def get_tree(
        self, owner: str, repo: str, ref: str = "", recursive: bool = True,
    ) -> list[GiteaTreeEntry]:
        if ref:
            commit = self.get_commit(owner, repo, ref)
            tree_sha = commit.sha
        else:
            info = self.get_repo_info(owner, repo)
            commit = self.get_commit(owner, repo, info.default_branch)
            tree_sha = commit.sha
        params = {"recursive": "1"} if recursive else {}
        r = self._get(f"/api/v1/repos/{owner}/{repo}/git/trees/{tree_sha}", params=params)
        if r.status_code == 404:
            raise LookupError(f"Tree not found in {owner}/{repo}")
        r.raise_for_status()
        data = r.json()
        entries = []
        for item in data.get("tree", []):
            entries.append(GiteaTreeEntry(
                path=item.get("path", ""),
                type=item.get("type", "blob"),
                sha=item.get("sha", ""),
                size=item.get("size"),
            ))
        return entries

    def ensure_webhook(self, owner: str, repo: str, webhook_url: str, secret: str) -> tuple[int, bool]:
        """Идемпотентный setup webhook: reuse по URL, иначе create.

        Возвращает (hook_id, created). Повторный вызов с тем же URL НЕ
        создаёт дубль — существующий hook переиспользуется; если у него
        другой secret → патчится (секрет мог ротироваться).
        """
        r = self._get(f"/api/v1/repos/{owner}/{repo}/hooks", params={"limit": 50})
        r.raise_for_status()
        for hook in r.json():
            config = hook.get("config") or {}
            if config.get("url") == webhook_url:
                hook_id = hook["id"]
                if config.get("secret") and config.get("secret") != secret:
                    pr = self._patch(
                        f"/api/v1/repos/{owner}/{repo}/hooks/{hook_id}",
                        json={"config": {"url": webhook_url, "content_type": "json", "secret": secret}},
                    )
                    pr.raise_for_status()
                    logger.info("Webhook %d secret rotated for %s/%s", hook_id, owner, repo)
                logger.info("Webhook %d already exists for %s/%s, reusing", hook_id, owner, repo)
                return hook_id, False

        r = self._post(
            f"/api/v1/repos/{owner}/{repo}/hooks",
            json={
                "type": "gitea",
                "config": {
                    "url": webhook_url,
                    "content_type": "json",
                    "secret": secret,
                },
                "events": ["push"],
                "active": True,
            },
        )
        r.raise_for_status()
        hook_id = r.json()["id"]
        logger.info("Created webhook %d for %s/%s", hook_id, owner, repo)
        return hook_id, True

    def create_webhook(
        self, owner: str, repo: str, webhook_url: str, secret: str,
    ) -> int:
        """Создаёт webhook на push-события. Возвращает webhook_id."""
        r = self._post(
            f"/api/v1/repos/{owner}/{repo}/hooks",
            json={
                "type": "gitea",
                "config": {
                    "url": webhook_url,
                    "content_type": "json",
                    "secret": secret,
                },
                "events": ["push"],
                "active": True,
            },
        )
        r.raise_for_status()
        hook_id = r.json()["id"]
        logger.info("Created webhook %d for %s/%s", hook_id, owner, repo)
        return hook_id

    def unregister_webhook(
        self, owner: str, repo: str, webhook_id: int,
    ) -> bool:
        """Удаляет webhook по ID. Возвращает True если удалён, False если не найден."""
        r = self._delete(f"/api/v1/repos/{owner}/{repo}/hooks/{webhook_id}")
        if r.status_code == 404:
            logger.info("Webhook %d not found for %s/%s (already removed)", webhook_id, owner, repo)
            return False
        if r.status_code == 204:
            logger.info("Unregistered webhook %d for %s/%s", webhook_id, owner, repo)
            return True
        r.raise_for_status()
        return True

    @staticmethod
    def verify_webhook_signature(
        payload: bytes, signature: str, secret: str,
    ) -> bool:
        """Проверяет HMAC-SHA256 подпись webhook'а."""
        expected = hmac.new(
            secret.encode(), payload, hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(expected, signature)

    @staticmethod
    def parse_push_event(payload: dict) -> dict[str, Any]:
        """Разбирает push-событие в структуру для Plan Compiler."""
        ref = payload.get("ref", "")
        branch = ref.replace("refs/heads/", "") if ref.startswith("refs/heads/") else ref
        commits = payload.get("commits", [])
        return {
            "repo_full_name": payload.get("repository", {}).get("full_name", ""),
            "branch": branch,
            "head_sha": payload.get("after", ""),
            "commit_count": len(commits),
            "pusher": payload.get("pusher", {}).get("login", "unknown"),
        }

    # ── COS-107: Workspace commit через Contents API ────────────────────

    def create_commit(
        self, owner: str, repo: str, branch: str, message: str,
        changes: list[dict], parent_sha: str,
    ) -> GiteaCommit:
        """Создаёт коммит(ы) через Contents API (POST/PUT/DELETE на файл).

        Gitea 1.22.6: POST git/trees = 404. Contents API:
          - POST /contents/{path} — новый файл (без sha)
          - PUT  /contents/{path} — update (sha: file blob sha)
          - DELETE /contents/{path} — delete (sha: file blob sha)

        Множественные файлы = отдельные коммиты; возвращается SHA последнего
        (HEAD ветки после всех операций).

        Args:
            changes: [{path, action: 'upsert'|'delete',
                       content: base64 (для upsert), sha?: file blob sha}, ...]
        """
        for i, ch in enumerate(changes):
            p = ch["path"]
            content = ch.get("content", "")
            sha = ch.get("sha")
            if ch.get("action") == "delete":
                r = self._delete(
                    f"/api/v1/repos/{owner}/{repo}/contents/{requests.utils.quote(p, safe='')}",
                    json={
                        "message": message if i == 0 else f"{message} (delete {p})",
                        "branch": branch,
                        "sha": sha,
                    },
                )
                r.raise_for_status()
            elif sha:
                r = self._put(
                    f"/api/v1/repos/{owner}/{repo}/contents/{requests.utils.quote(p, safe='')}",
                    json={
                        "message": message if i == 0 else f"{message} (upsert {p})",
                        "branch": branch,
                        "content": content,
                        "sha": sha,
                    },
                )
                r.raise_for_status()
            else:
                r = self._post(
                    f"/api/v1/repos/{owner}/{repo}/contents/{requests.utils.quote(p, safe='')}",
                    json={
                        "message": message if i == 0 else f"{message} (upsert {p})",
                        "branch": branch,
                        "content": content,
                    },
                )
                r.raise_for_status()

        final = self.get_commit(owner, repo, branch)
        result = GiteaCommit(
            sha=final.sha,
            message=message.split("\n", 1)[0],
            author=final.author,
            timestamp=final.timestamp,
        )
        result.tree_sha = final.sha
        logger.info(
            "Committed on %s/%s branch=%s (%d file(s), sha=%s)",
            owner, repo, branch, len(changes), final.sha[:8],
        )
        return result

    # ── COS-124: Atomic multi-file commit (bulk Contents API) ───────────

    def commit_changes(
        self, owner: str, repo: str, branch: str, message: str,
        file_changes: list[dict],
        author_name: str | None = None,
        author_email: str | None = None,
    ) -> dict:
        """Атомарный коммит нескольких файлов одной операцией.

        Gitea 1.22.6 не имеет POST git/trees (404), зато имеет bulk
        Contents API: POST /api/v1/repos/{owner}/{repo}/contents
        (repoChangeFiles) с телом ChangeFilesOptions — одна транзакция
        create/update/delete.

        Args:
            file_changes: [{path, action: 'create'|'update'|'delete',
                            content: str|None, sha?: blob sha (update/delete)}]
        Returns:
            {sha, html_url, authored_at, files_changed}

        Raises:
            GiteaConflictError: ref уехал / состояние файла изменилось (409/422).
        """
        import base64 as _b64

        ops: list[dict] = []
        for ch in file_changes:
            action = ch["action"]
            op: dict[str, Any] = {"path": ch["path"], "operation": action}
            if action in ("create", "update"):
                content = ch.get("content") or ""
                op["content"] = _b64.b64encode(content.encode("utf-8")).decode("ascii")
            if action in ("update", "delete"):
                sha = ch.get("sha")
                if not sha:
                    raise ValueError(
                        f"sha is required for action={action!r} on {ch['path']}"
                    )
                op["sha"] = sha
            ops.append(op)

        body: dict[str, Any] = {"files": ops, "message": message, "branch": branch}
        ident: dict[str, str] = {}
        if author_name:
            ident["name"] = author_name
        if author_email:
            ident["email"] = author_email
        if ident:
            body["author"] = ident

        r = self._post(f"/api/v1/repos/{owner}/{repo}/contents", json=body)
        if r.status_code in (409, 422):
            raise GiteaConflictError(
                f"Gitea rejected bulk commit (HTTP {r.status_code}): "
                f"ref moved or file state changed"
            )
        r.raise_for_status()
        data = r.json()
        commit = data.get("commit") or {}
        files = data.get("files")
        files_changed = len(files) if files is not None else len(file_changes)
        logger.info(
            "Atomic commit on %s/%s branch=%s (%d file(s), sha=%s)",
            owner, repo, branch, len(file_changes), str(commit.get("sha", ""))[:8],
        )
        return {
            "sha": commit.get("sha", ""),
            "html_url": commit.get("html_url", ""),
            "authored_at": commit.get("created", ""),
            "files_changed": files_changed,
        }

    # ── COS-113: Branch & Tag management ─────────────────────────────────

    def list_branches(self, owner: str, repo: str) -> list[dict]:
        """Возвращает список веток с SHA головы и флагами.

        Gitea API: GET /api/v1/repos/{owner}/{repo}/branches
        Ответ: [{name, commit: {id, ...}, protected}]
        """
        r = self._get(f"/api/v1/repos/{owner}/{repo}/branches")
        r.raise_for_status()
        branches = r.json()
        # Определяем default branch через repo info
        try:
            info_r = self._get(f"/api/v1/repos/{owner}/{repo}")
            info_r.raise_for_status()
            info = info_r.json()
            default_branch = info.get("default_branch", "")
        except Exception:  # noqa: BLE001
            default_branch = branches[0]["name"] if branches else "main"

        return [
            {
                "name": b["name"],
                "sha": b["commit"]["id"],
                "is_default": b["name"] == default_branch,
                "is_protected": b.get("protected", False),
            }
            for b in branches
        ]

    def create_branch(
        self, owner: str, repo: str, new_branch: str, base_branch: str,
    ) -> dict:
        """Создаёт ветку от base_branch.

        Gitea API: POST /api/v1/repos/{owner}/{repo}/branches
        Body: {new_branch_name, old_branch_name}
        Ответ: {name, commit: {id}, ...}
        """
        r = self._post(
            f"/api/v1/repos/{owner}/{repo}/branches",
            json={"new_branch_name": new_branch, "old_branch_name": base_branch},
        )
        r.raise_for_status()
        data = r.json()
        return {
            "name": data["name"],
            "sha": data["commit"]["id"],
            "is_default": False,  # новая ветка — не default
            "is_protected": data.get("protected", False),
        }

    def delete_branch(self, owner: str, repo: str, branch_name: str) -> bool:
        """Удаляет ветку. Возвращает True если ветка существовала.

        Gitea API: DELETE /api/v1/repos/{owner}/{repo}/branches/{branch}
        """
        import requests as _requests
        r = self._delete(
            f"/api/v1/repos/{owner}/{repo}/branches/{_requests.utils.quote(branch_name, safe='')}"
        )
        if r.status_code == 404:
            return False
        r.raise_for_status()
        return True

    def list_tags(self, owner: str, repo: str) -> list[dict]:
        """Возвращает список тегов с SHA коммита.

        Gitea API: GET /api/v1/repos/{owner}/{repo}/tags
        Ответ: [{name, commit: {sha}, ...}]
        """
        r = self._get(f"/api/v1/repos/{owner}/{repo}/tags")
        r.raise_for_status()
        return [
            {"name": t["name"], "sha": t["commit"]["sha"]}
            for t in r.json()
        ]

    # ── COS-116/COS-129: Commit history (dict-проекция) ────────────────

    def list_commits_history(
        self,
        owner: str,
        repo: str,
        branch: str | None = None,
        path: str | None = None,
        limit: int = 30,
        page: int = 1,
    ) -> list[dict]:
        """История коммитов ветки (и опционально одного файла) → dict.

        COS-129: переименован из второго `list_commits`, который затенял
        канонический метод COS-096. Потребители: routes/workspace.py
        (GET /workspace/commits), resolve_ref (COS-125).

        Gitea API: GET /api/v1/repos/{owner}/{repo}/commits?sha=...&path=...&limit=...&page=...
        Ответ: [{sha, commit: {author, message, ...}, parents: [{sha}]}]
        """
        items = self._fetch_commits(
            owner, repo, ref=branch, path=path, limit=limit, page=page,
        )
        return [
            {
                "sha": c["sha"],
                "short_sha": c["sha"][:8],
                "message": c["commit"]["message"],
                "author_name": c["commit"]["author"]["name"],
                "author_email": c["commit"]["author"]["email"],
                "committed_at": c["commit"]["author"]["date"],
                "parent_shas": [p["sha"] for p in c.get("parents", [])],
            }
            for c in items
        ]

    # ── COS-120: File create / delete / move ───────────────────────────

    def create_file(
        self, owner: str, repo: str, path: str, content: str,
        branch: str, message: str, is_base64: bool = False,
    ) -> dict:
        """Создаёт файл через Gitea Contents API.

        Gitea API: POST /api/v1/repos/{owner}/{repo}/contents/{path}
        Body: {content: base64, message, branch}
        Ответ: {content: {sha, ...}, commit: {sha, ...}}
        """
        import requests as _requests
        import base64 as _b64
        encoded_path = _requests.utils.quote(path, safe="/")
        body_content = content if is_base64 else _b64.b64encode(content.encode()).decode()
        body: dict[str, str] = {"content": body_content, "message": message}
        if branch:
            body["branch"] = branch

        r = self._post(
            f"/api/v1/repos/{owner}/{repo}/contents/{encoded_path}",
            json=body,
        )
        r.raise_for_status()
        data = r.json()
        return {
            "commit_sha": data["commit"]["sha"],
            "path": path,
            "status": "created",
        }

    def delete_file(
        self, owner: str, repo: str, path: str,
        branch: str, message: str,
    ) -> dict:
        """Удаляет файл через Gitea Contents API.

        Сначала получает blob SHA файла, затем DELETE с sha.
        Gitea API: DELETE /api/v1/repos/{owner}/{repo}/contents/{path}
        Body: {message, sha: blob_sha, branch}
        """
        import requests as _requests
        encoded_path = _requests.utils.quote(path, safe="/")

        # Получаем blob SHA (sha контента, не коммита)
        params = {}
        if branch:
            params["ref"] = branch
        r_get = self._get(
            f"/api/v1/repos/{owner}/{repo}/contents/{encoded_path}",
            params=params,
        )
        r_get.raise_for_status()
        blob_sha = r_get.json()["sha"]

        body: dict[str, str] = {"message": message, "sha": blob_sha}
        if branch:
            body["branch"] = branch
        r = self._delete(
            f"/api/v1/repos/{owner}/{repo}/contents/{encoded_path}",
            json=body,
        )
        r.raise_for_status()
        data = r.json()
        return {
            "commit_sha": data["commit"]["sha"],
            "path": path,
            "status": "deleted",
        }

    def move_file(
        self, owner: str, repo: str, src: str, dst: str,
        branch: str, message: str,
    ) -> dict:
        """Перемещает/переименовывает файл: GET src → POST dst → DELETE src.

        Неатомарно (Gitea Contents API без транзакций), но сохраняет контент.
        """
        import requests as _requests
        src_enc = _requests.utils.quote(src, safe="/")
        dst_enc = _requests.utils.quote(dst, safe="/")
        params = {}
        if branch:
            params["ref"] = branch

        # 1. Получаем контент источника
        r_get = self._get(
            f"/api/v1/repos/{owner}/{repo}/contents/{src_enc}",
            params=params,
        )
        r_get.raise_for_status()
        src_data = r_get.json()
        content = src_data["content"]
        src_sha = src_data["sha"]

        # 2. Создаём файл в целевом пути
        body_create: dict[str, str] = {"content": content, "message": message}
        if branch:
            body_create["branch"] = branch
        r_create = self._post(
            f"/api/v1/repos/{owner}/{repo}/contents/{dst_enc}",
            json=body_create,
        )
        r_create.raise_for_status()

        # 3. Удаляем исходный файл
        body_del: dict[str, str] = {
            "message": f"{message} (move)",
            "sha": src_sha,
        }
        if branch:
            body_del["branch"] = branch
        r_del = self._delete(
            f"/api/v1/repos/{owner}/{repo}/contents/{src_enc}",
            json=body_del,
        )
        r_del.raise_for_status()
        data = r_del.json()
        return {
            "commit_sha": data["commit"]["sha"],
            "path": dst,
            "status": "moved",
        }

    # ── COS-125: Compare двух ref-ов (tree snapshot diff) ───────────────

    def resolve_ref(self, owner: str, repo: str, ref: str) -> str:
        """Разрешить branch/tag/commit-ref в commit SHA.

        Использует COS-116-проекцию list_commits_history (branch=...),
        не затеняя канонический list_commits. Пусто/не найдено →
        LookupError (роут честно отдаёт 404).
        """
        if not ref:
            raise ValueError("ref is required")
        commits = self.list_commits_history(owner, repo, branch=ref, limit=1)
        if not commits:
            raise LookupError(f"Ref {ref!r} not found in {owner}/{repo}")
        return commits[0]["sha"]

    def get_tree_by_sha(
        self, owner: str, repo: str, sha: str, recursive: bool = True,
    ) -> list[GiteaTreeEntry]:
        """Recursive tree по уже разрешённому commit SHA (COS-125)."""
        params = {"recursive": "1"} if recursive else {}
        r = self._get(f"/api/v1/repos/{owner}/{repo}/git/trees/{sha}", params=params)
        if r.status_code == 404:
            raise LookupError(f"Tree {sha} not found in {owner}/{repo}")
        r.raise_for_status()
        data = r.json()
        return [
            GiteaTreeEntry(
                path=item.get("path", ""),
                type=item.get("type", "blob"),
                sha=item.get("sha", ""),
                size=item.get("size"),
            )
            for item in data.get("tree", [])
        ]

    def get_blob(self, owner: str, repo: str, blob_sha: str) -> bytes:
        """Сырые bytes blob-а по SHA через Git Blobs API."""
        r = self._get(f"/api/v1/repos/{owner}/{repo}/git/blobs/{blob_sha}")
        if r.status_code == 404:
            raise LookupError(f"Blob {blob_sha} not found in {owner}/{repo}")
        r.raise_for_status()
        data = r.json()
        if data.get("encoding") != "base64":
            raise ValueError(f"Unsupported blob encoding: {data.get('encoding')!r}")
        return base64.b64decode(data.get("content", ""))

    def _blob_bytes(
        self, owner: str, repo: str, entry: GiteaTreeEntry | None,
        sha: str | None, path: str,
    ) -> tuple[bytes | None, bool]:
        """Прочитать blob изменённого файла → (bytes | None, truncated).

        Сначала git/blobs по SHA; при отказе — read_file(path, ref=sha)
        как fallback. Слишком большой blob (по tree size или факту) не
        читается: (None, True).
        """
        if not sha:
            return None, False
        if entry is not None and entry.size is not None \
                and entry.size > _MAX_COMPARE_BLOB_BYTES:
            return None, True
        try:
            data = self.get_blob(owner, repo, sha)
        except (LookupError, ValueError):
            try:
                text, _ = self.read_file(owner, repo, path, ref=sha)
                data = text.encode("utf-8")
            except (LookupError, ValueError):
                return None, False
        if len(data) > _MAX_COMPARE_BLOB_BYTES:
            return None, True
        return data, False

    def compare_refs(
        self, owner: str, repo: str, base: str, head: str,
    ) -> GiteaCompareResult:
        """Сравнить два ref-а без server-side diff (Gitea 1.22.6).

        Клиентский snapshot-compare: resolve обоих ref в SHA → recursive
        tree каждого → локальная классификация → чтение только изменённых
        блобов → unified patch через difflib. Бинарные файлы: is_binary,
        patch=None. Rename определяется по равному blob sha.

        Raises:
            GiteaCompareLimitError: изменений > _MAX_COMPARE_FILES.
        """
        base_sha = self.resolve_ref(owner, repo, base)
        head_sha = self.resolve_ref(owner, repo, head)

        base_tree = self.get_tree_by_sha(owner, repo, base_sha, recursive=True)
        head_tree = self.get_tree_by_sha(owner, repo, head_sha, recursive=True)
        base_map = {e.path: e for e in base_tree if e.type == "blob"}
        head_map = {e.path: e for e in head_tree if e.type == "blob"}

        changes = _classify_snapshots(base_map, head_map)
        if len(changes) > _MAX_COMPARE_FILES:
            raise GiteaCompareLimitError(
                f"Compare {owner}/{repo} {base}..{head} touches "
                f"{len(changes)} files (limit {_MAX_COMPARE_FILES})"
            )

        files: list[GiteaCompareFile] = []
        for ch in changes:
            if ch.status == "renamed":
                # Равный blob sha → контент не менялся.
                files.append(GiteaCompareFile(
                    path=ch.path, status="renamed", old_path=ch.old_path,
                ))
                continue

            if ch.status == "added":
                base_bytes: bytes | None = b""
                head_bytes, truncated = self._blob_bytes(
                    owner, repo, head_map.get(ch.path), ch.head_sha, ch.path,
                ) if ch.head_sha else (None, False)
            elif ch.status == "deleted":
                base_bytes, truncated = self._blob_bytes(
                    owner, repo, base_map.get(ch.path), ch.base_sha, ch.path,
                ) if ch.base_sha else (None, False)
                head_bytes = b""
            else:  # modified
                old_path = ch.old_path or ch.path
                base_bytes, trunc_b = self._blob_bytes(
                    owner, repo, base_map.get(old_path), ch.base_sha, old_path,
                ) if ch.base_sha else (None, False)
                head_bytes, trunc_h = self._blob_bytes(
                    owner, repo, head_map.get(ch.path), ch.head_sha, ch.path,
                ) if ch.head_sha else (None, False)
                truncated = trunc_b or trunc_h

            if truncated or base_bytes is None or head_bytes is None:
                files.append(GiteaCompareFile(
                    path=ch.path, status=ch.status, old_path=ch.old_path,
                    truncated=truncated,
                ))
                continue

            base_text = _decode_text(base_bytes)
            head_text = _decode_text(head_bytes)
            if base_text is None or head_text is None:
                files.append(GiteaCompareFile(
                    path=ch.path, status=ch.status, old_path=ch.old_path,
                    is_binary=True,
                ))
                continue

            patch, additions, deletions = _unified_patch(
                base_text, head_text, ch.path, ch.old_path,
            )
            files.append(GiteaCompareFile(
                path=ch.path, status=ch.status, old_path=ch.old_path,
                additions=additions, deletions=deletions, patch=patch,
            ))

        return GiteaCompareResult(
            base_sha=base_sha, head_sha=head_sha, files=files,
        )

    def close(self) -> None:
        """Закрывает HTTP-сессию."""
        self._session.close()

    def __enter__(self) -> "GiteaForgeAdapter":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()