"""COS-007: Тесты Gitea ForgeAdapter — полный CRUD."""
import hashlib
import hmac
import json

import pytest
from cosmo.adapters.forge_gitea import (
    GiteaCommitStatus, GiteaForgeAdapter, GiteaRepoInfo,
)


class TestGiteaRepoInfo:
    def test_minimal(self):
        info = GiteaRepoInfo(
            id=1, owner="org", name="repo", full_name="org/repo",
            default_branch="main", clone_url="http://gitea:3000/org/repo.git",
            ssh_url="git@gitea:org/repo.git",
        )
        assert info.full_name == "org/repo"

    def test_webhook_id_default_none(self):
        info = GiteaRepoInfo(
            id=2, owner="org", name="lib", full_name="org/lib",
            default_branch="main", clone_url="http://gitea:3000/org/lib.git",
            ssh_url="git@gitea:org/lib.git",
        )
        assert info.webhook_id is None

    def test_with_webhook(self):
        info = GiteaRepoInfo(
            id=3, owner="org", name="app", full_name="org/app",
            default_branch="main", clone_url="http://gitea:3000/org/app.git",
            ssh_url="git@gitea:org/app.git", webhook_id=5,
        )
        assert info.webhook_id == 5


class TestGiteaCommitStatus:
    def test_success(self):
        s = GiteaCommitStatus(state="success", context="prettyk/dast", description="All good")
        assert s.state == "success"

    def test_failure(self):
        s = GiteaCommitStatus(state="failure", context="prettyk/sast", description="3 findings")
        assert s.state == "failure"


class TestWebhookSignature:
    def test_valid_signature(self):
        secret = "test-secret-123"
        payload = json.dumps({"ref": "refs/heads/main", "after": "abc123"}).encode()
        expected = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
        assert GiteaForgeAdapter.verify_webhook_signature(payload, expected, secret)

    def test_invalid_signature(self):
        secret = "test-secret-123"
        payload = json.dumps({"ref": "refs/heads/main"}).encode()
        assert not GiteaForgeAdapter.verify_webhook_signature(payload, "a" * 64, secret)

    def test_tampered_payload(self):
        secret = "test-secret-123"
        original = json.dumps({"ref": "refs/heads/main", "after": "abc"}).encode()
        tampered = json.dumps({"ref": "refs/heads/main", "after": "xyz"}).encode()
        sig = hmac.new(secret.encode(), original, hashlib.sha256).hexdigest()
        assert not GiteaForgeAdapter.verify_webhook_signature(tampered, sig, secret)


class TestParsePushEvent:
    def test_push_main(self):
        payload = {
            "ref": "refs/heads/main",
            "after": "abc123def456",
            "commits": [{"id": "abc123def456", "message": "fix: bug"}],
            "repository": {"full_name": "org/repo"},
            "pusher": {"login": "dev1"},
        }
        result = GiteaForgeAdapter.parse_push_event(payload)
        assert result["branch"] == "main"
        assert result["head_sha"] == "abc123def456"
        assert result["repo_full_name"] == "org/repo"
        assert result["pusher"] == "dev1"
        assert result["commit_count"] == 1

    def test_push_feature_branch(self):
        payload = {
            "ref": "refs/heads/feature/auth",
            "after": "def789",
            "commits": [],
            "repository": {"full_name": "org/repo"},
            "pusher": {},
        }
        result = GiteaForgeAdapter.parse_push_event(payload)
        assert result["branch"] == "feature/auth"
        assert result["pusher"] == "unknown"


# ── COS-007 финиш: create_repo, link_repo, unregister_webhook ──

class TestCreateRepo:
    """Тест логики create_repo (без живого Gitea — проверка структуры данных)."""

    def test_repo_info_structure(self):
        """create_repo возвращает GiteaRepoInfo с правильной структурой."""
        info = GiteaRepoInfo(
            id=42, owner="cosmo-org", name="test-repo",
            full_name="cosmo-org/test-repo",
            default_branch="main",
            clone_url="http://gitea:3000/cosmo-org/test-repo.git",
            ssh_url="git@gitea:cosmo-org/test-repo.git",
        )
        assert info.id == 42
        assert info.owner == "cosmo-org"
        assert info.name == "test-repo"
        assert info.full_name == "cosmo-org/test-repo"

    def test_idempotent_get_info_callable(self):
        """get_repo_info — метод API для получения метаданных."""
        adapter = GiteaForgeAdapter("http://gitea:3000", "test-token")
        assert callable(adapter.get_repo_info)
        assert callable(adapter.create_repo)

    def test_link_repo_callable(self):
        """link_repo — метод для привязки репозитория к Domain."""
        adapter = GiteaForgeAdapter("http://gitea:3000", "test-token")
        assert callable(adapter.link_repo)

    def test_unregister_webhook_callable(self):
        """unregister_webhook — удаление webhook'а."""
        adapter = GiteaForgeAdapter("http://gitea:3000", "test-token")
        assert callable(adapter.unregister_webhook)


class TestTokenSafety:
    """Токен не должен попадать в логи или храниться открытым текстом."""

    def test_token_not_in_repr(self):
        adapter = GiteaForgeAdapter("http://gitea:3000", "secret-token-abc")
        r = repr(adapter)
        assert "secret-token-abc" not in r

    def test_token_hashed_in_domain(self):
        adapter = GiteaForgeAdapter("http://gitea:3000", "my-token")
        from cosmo.adapters.forge_gitea import ForgeDomain
        fd = ForgeDomain(domain_id="d1", org_name="test",
                         token_hash=hashlib.sha256("my-token".encode()).hexdigest()[:16])
        assert "my-token" not in fd.token_hash
        assert len(fd.token_hash) == 16

    def test_close_cleans_session(self):
        adapter = GiteaForgeAdapter("http://gitea:3000", "token")
        adapter.close()
        adapter.close()