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

    def list_commits(self, owner: str, repo: str, ref: str = "", limit: int = 10) -> list[GiteaCommit]:
        """Список коммитов живого репозитория (newest first)."""
        params: dict[str, Any] = {"limit": min(limit, 50)}
        if ref:
            params["sha"] = ref
        r = self._get(f"/api/v1/repos/{owner}/{repo}/commits", params=params)
        if r.status_code == 404:
            raise LookupError(f"Repository {owner}/{repo} not found")
        r.raise_for_status()
        commits: list[GiteaCommit] = []
        for item in r.json()[:limit]:
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

    # ── COS-116: Commit history ────────────────────────────────────────

    def list_commits(
        self,
        owner: str,
        repo: str,
        branch: str | None = None,
        path: str | None = None,
        limit: int = 30,
        page: int = 1,
    ) -> list[dict]:
        """Возвращает историю коммитов ветки (и опционально одного файла).

        Gitea API: GET /api/v1/repos/{owner}/{repo}/commits?sha=...&path=...&limit=...&page=...
        Ответ: [{sha, commit: {author, message, ...}, parents: [{sha}]}]
        """
        params: dict[str, str | int] = {"limit": min(limit, 100)}
        if page > 1:
            params["page"] = page
        if branch:
            params["sha"] = branch
        if path:
            params["path"] = path
        r = self._get(f"/api/v1/repos/{owner}/{repo}/commits", params=params)
        r.raise_for_status()
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
            for c in r.json()
        ]

    def close(self) -> None:
        """Закрывает HTTP-сессию."""
        self._session.close()

    def __enter__(self) -> "GiteaForgeAdapter":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()