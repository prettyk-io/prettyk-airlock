# -*- coding: utf-8 -*-
"""COS-129: GiteaForgeAdapter — унификация list_commits.

Регрессия: второй `list_commits` (COS-116, dict) затенял канонический
(COS-096, GiteaCommit) → `get_commit(ref=...)`, `get_tree(ref=...)` и
`routes/apps.py` падали с TypeError против живого Gitea. COS-129 разводит
проекции: `list_commits` → GiteaCommit, `list_commits_history` → dict.

Юниты на фейковой сессии — без живого Gitea.

Запуск:  pytest .../test_forge_gitea_commits_unified.py -q
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path
from typing import Optional

import pytest
import requests

_orch = Path(__file__).resolve().parents[1]
if str(_orch) not in sys.path:
    sys.path.insert(0, str(_orch))

from orchestrator.cosmo.adapters.forge_gitea import (
    GiteaCommit,
    GiteaForgeAdapter,
    GiteaTreeEntry,
)

SHA = "a" * 40
SHA2 = "b" * 40


def _commit_json(sha: str = SHA, message: str = "feat: add login\n\nbody") -> dict:
    return {
        "sha": sha,
        "author": {"login": "max"},
        "commit": {
            "message": message,
            "author": {
                "name": "Max Dev", "email": "max@o.l",
                "date": "2026-09-18T10:00:00Z",
            },
        },
        "parents": [{"sha": "p" * 40}],
    }


class _Resp:
    def __init__(self, status_code: int = 200, payload=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else []

    def json(self):
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")


class _Session:
    """Записывает вызовы; поведение задаёт routes(method, url, kwargs)."""

    headers: dict = {}

    def __init__(self, routes):
        self.calls: list[tuple[str, str, dict]] = []
        self._routes = routes

    def request(self, method: str, url: str, **kw):
        self.calls.append((method, url, kw))
        return self._routes(method, url, kw)


def _routes(commits=None, commit_status: int = 200, tree=None):
    commits = commits if commits is not None else [_commit_json()]
    tree = tree if tree is not None else [
        {"path": "src/app.py", "type": "blob", "sha": "blob1", "size": 10},
    ]

    def handler(method: str, url: str, kw: dict):
        if url.endswith("/commits"):
            if commit_status >= 400:
                return _Resp(commit_status, [])
            return _Resp(200, commits)
        if "/git/trees/" in url:
            return _Resp(200, {"tree": tree})
        return _Resp(404, {})

    return handler


def _adapter(handler) -> GiteaForgeAdapter:
    a = GiteaForgeAdapter(base_url="http://forge.local", token="t")
    a._session = _Session(handler)
    return a


# ══════════════════════════════════════════════════════════════════════
# Регрессия shadowing: get_commit / get_tree с ref=
# ══════════════════════════════════════════════════════════════════════

class TestShadowingRegression:
    def test_get_commit_with_ref_no_typeerror(self):
        """До COS-129: TypeError unexpected keyword 'ref'."""
        a = _adapter(_routes())
        c = a.get_commit("org", "app", ref="main")
        assert isinstance(c, GiteaCommit)
        assert c.sha == SHA

    def test_get_commit_without_ref_uses_default_branch(self):
        commits = [_commit_json()]
        a = _adapter(_routes(commits=commits))
        # get_repo_info → GET /repos/{owner}/{repo}
        a.get_repo_info = lambda owner, repo: type(
            "Info", (), {"default_branch": "main"},
        )()
        c = a.get_commit("org", "app")
        assert c.sha == SHA

    def test_get_tree_with_ref_no_typeerror(self):
        a = _adapter(_routes())
        entries = a.get_tree("org", "app", ref="main")
        assert len(entries) == 1
        assert isinstance(entries[0], GiteaTreeEntry)
        assert entries[0].path == "src/app.py"

    def test_single_list_commits_definition_accepts_ref(self):
        """Один метод с именем list_commits, и он принимает ref=."""
        params = inspect.signature(GiteaForgeAdapter.list_commits).parameters
        assert "ref" in params
        assert "branch" in params
        assert "list_commits_history" in dir(GiteaForgeAdapter)


# ══════════════════════════════════════════════════════════════════════
# Каноническая проекция: list_commits → GiteaCommit
# ══════════════════════════════════════════════════════════════════════

class TestListCommitsCanonical:
    def test_returns_gitea_commit(self):
        a = _adapter(_routes())
        out = a.list_commits("org", "app", ref="main", limit=5)
        assert len(out) == 1
        assert isinstance(out[0], GiteaCommit)
        assert out[0].sha == SHA
        assert out[0].message == "feat: add login"  # первая строка
        assert out[0].author == "max"
        assert out[0].timestamp == "2026-09-18T10:00:00Z"

    def test_branch_alias_equals_ref(self):
        handler = _routes()
        a = _adapter(handler)
        a.list_commits("org", "app", branch="feat/x")
        _, _, kw = a._session.calls[0]
        assert kw["params"]["sha"] == "feat/x"

    def test_ref_wins_over_branch(self):
        a = _adapter(_routes())
        a.list_commits("org", "app", ref="main", branch="other")
        assert a._session.calls[0][2]["params"]["sha"] == "main"

    def test_no_ref_omits_sha_param(self):
        a = _adapter(_routes())
        a.list_commits("org", "app")
        assert "sha" not in a._session.calls[0][2]["params"]

    def test_limit_capped_100(self):
        a = _adapter(_routes())
        a.list_commits("org", "app", limit=500)
        assert a._session.calls[0][2]["params"]["limit"] == 100

    def test_page_forwarded(self):
        a = _adapter(_routes())
        a.list_commits("org", "app", page=3)
        assert a._session.calls[0][2]["params"]["page"] == 3

    def test_404_lookup_error(self):
        a = _adapter(_routes(commit_status=404))
        with pytest.raises(LookupError):
            a.list_commits("org", "app", ref="main")

    def test_consumer_shape_for_apps_route(self):
        """apps.py строит recent из c.sha/message/author/timestamp."""
        a = _adapter(_routes())
        c = a.list_commits("org", "app", ref="main", limit=5)[0]
        row = {"sha": c.sha, "message": c.message,
               "author": c.author, "timestamp": c.timestamp}
        assert row["sha"] == SHA and row["author"] == "max"


# ══════════════════════════════════════════════════════════════════════
# History-проекция: list_commits_history → dict
# ══════════════════════════════════════════════════════════════════════

class TestListCommitsHistory:
    def test_returns_dict_with_full_fields(self):
        a = _adapter(_routes())
        out = a.list_commits_history("org", "app", branch="main", limit=5)
        assert len(out) == 1
        row = out[0]
        assert isinstance(row, dict)
        assert row["sha"] == SHA
        assert row["short_sha"] == SHA[:8]
        assert row["message"] == "feat: add login\n\nbody"  # полное сообщение
        assert row["author_name"] == "Max Dev"
        assert row["author_email"] == "max@o.l"
        assert row["committed_at"] == "2026-09-18T10:00:00Z"
        assert row["parent_shas"] == ["p" * 40]

    def test_branch_path_page_forwarded(self):
        a = _adapter(_routes())
        a.list_commits_history(
            "org", "app", branch="feat/x", path="src/main.py", limit=2, page=2,
        )
        params = a._session.calls[0][2]["params"]
        assert params["sha"] == "feat/x"
        assert params["path"] == "src/main.py"
        assert params["limit"] == 2
        assert params["page"] == 2

    def test_empty_filters_omit_params(self):
        a = _adapter(_routes())
        a.list_commits_history("org", "app")
        params = a._session.calls[0][2]["params"]
        assert "sha" not in params and "path" not in params and "page" not in params

    def test_404_lookup_error(self):
        a = _adapter(_routes(commit_status=404))
        with pytest.raises(LookupError):
            a.list_commits_history("org", "app")


# ══════════════════════════════════════════════════════════════════════
# resolve_ref (COS-125) идёт через history-проекцию
# ══════════════════════════════════════════════════════════════════════

class TestResolveRef:
    def test_resolve_ref_returns_sha(self):
        a = _adapter(_routes())
        assert a.resolve_ref("org", "app", "main") == SHA

    def test_resolve_ref_uses_history_projection(self, monkeypatch):
        a = _adapter(_routes())
        seen = {}

        def _hist(owner, repo, branch=None, path=None, limit=30, page=1):
            seen.update(branch=branch, limit=limit)
            return [{"sha": SHA}]

        monkeypatch.setattr(a, "list_commits_history", _hist)
        assert a.resolve_ref("org", "app", "main") == SHA
        assert seen == {"branch": "main", "limit": 1}

    def test_empty_ref_value_error(self):
        a = _adapter(_routes())
        with pytest.raises(ValueError):
            a.resolve_ref("org", "app", "")

    def test_unknown_ref_lookup_error(self, monkeypatch):
        a = _adapter(_routes())
        monkeypatch.setattr(a, "list_commits_history", lambda *a, **k: [])
        with pytest.raises(LookupError):
            a.resolve_ref("org", "app", "ghost")
