"""
COS-007: Gitea ForgeAdapter — полный порт из prettyk-dev.

Реализация ForgeAdapter для Gitea API v1.
Методы: register_domain, get_repo_info, list_repos, set_commit_status.
Webhook handler: on_push → Plan Compiler trigger.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
from dataclasses import dataclass
from typing import Any

import requests

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 30


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
class ForgeDomain:
    """Зарегистрированный домен в forge."""
    domain_id: str
    org_name: str
    token_hash: str


class GiteaForgeAdapter:
    """Адаптер Gitea API для Cosmoport."""

    def __init__(self, base_url: str, token: str):
        self._base = base_url.rstrip("/")
        self._token = token
        self._session = requests.Session()
        self._session.headers.update({
            "Authorization": f"token {token}",
            "Content-Type": "application/json",
        })
        self._domains: dict[str, ForgeDomain] = {}

    def _get(self, path: str, **kwargs: Any) -> requests.Response:
        r = self._session.get(f"{self._base}{path}", timeout=DEFAULT_TIMEOUT, **kwargs)
        return r

    def _post(self, path: str, **kwargs: Any) -> requests.Response:
        r = self._session.post(f"{self._base}{path}", timeout=DEFAULT_TIMEOUT, **kwargs)
        return r

    def _delete(self, path: str, **kwargs: Any) -> requests.Response:
        r = self._session.delete(f"{self._base}{path}", timeout=DEFAULT_TIMEOUT, **kwargs)
        return r

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

    def close(self) -> None:
        """Закрывает HTTP-сессию."""
        self._session.close()

    def __enter__(self) -> "GiteaForgeAdapter":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()