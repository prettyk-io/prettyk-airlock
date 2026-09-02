# -*- coding: utf-8 -*-
"""COS-097: opt-in smoke против живого Woodpecker v3.5.

Запускается ТОЛЬКО если поднят стенд и задан COSMO_WOODPECKER_URL —
иначе skip (unit-сеты и CI без стенда не должны падать).

Проверяет реальный контракт адаптера, не создавая мусорных pipeline'ов:
  - lookup по owner/name резолвит числовой repo_id (v3.5: маршрутизация
    только по repo_id, owner/name → 400 без lookup);
  - get_status по несуществующему number даёт честный 404 → adapter
    исключение (executor переведёт в unknown);
  - get_logs по несуществующему stepId → 404 → пустой список (канон).

Реальный submit живёт в TestPollLoopIntegration (FakeAdapter) и в бою;
здесь он только при явном COSMO_WOODPECKER_SMOKE_SUBMIT=1 + repo с
push-доступом (COSMO_WOODPECKER_SMOKE_REPO) — создаёт один pipeline.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

_orch = Path(__file__).resolve().parents[1]
if str(_orch) not in sys.path:
    sys.path.insert(0, str(_orch))

from orchestrator.cosmo.adapters.execution_woodpecker import (  # noqa: E402
    WoodpeckerAdapter,
)

_URL = os.getenv("COSMO_WOODPECKER_URL", "").strip()
_TOKEN = os.getenv("COSMO_WOODPECKER_TOKEN", "").strip()
_REPO = os.getenv("COSMO_WOODPECKER_SMOKE_REPO", "").strip()  # "owner/name"
_SUBMIT = os.getenv("COSMO_WOODPECKER_SMOKE_SUBMIT", "").strip() in ("1", "true", "yes")

pytestmark = pytest.mark.skipif(
    not _URL,
    reason="живой Woodpecker не задан (COSMO_WOODPECKER_URL) — smoke opt-in",
)


def _adapter() -> WoodpeckerAdapter:
    return WoodpeckerAdapter(base_url=_URL, token=_TOKEN or "anonymous")


class TestWoodpeckerSmoke:
    def test_lookup_resolves_numeric_repo_id(self):
        """v3.5 контракт: owner/name → числовой repo_id через /repos/lookup."""
        if not _REPO:
            pytest.skip("COSMO_WOODPECKER_SMOKE_REPO не задан")
        owner, _, name = _REPO.partition("/")
        adapter = _adapter()
        repo_id = adapter.resolve_repo_id(owner, name)
        assert isinstance(repo_id, int) and repo_id > 0

    def test_lookup_unknown_repo_raises_lookup_error(self):
        adapter = _adapter()
        with pytest.raises(LookupError):
            adapter.resolve_repo_id("cosmo", "no-such-repo-smoke-404")

    def test_status_unknown_pipeline_is_honest_error(self):
        """Несуществующий number → 404: адаптер кидает, executor → unknown."""
        if not _REPO:
            pytest.skip("COSMO_WOODPECKER_SMOKE_REPO не задан")
        owner, _, name = _REPO.partition("/")
        adapter = _adapter()
        repo_id = adapter.resolve_repo_id(owner, name)
        handle = {"repo_id": repo_id, "number": 99999999,
                  "repo_owner": owner, "repo_name": name}
        with pytest.raises(Exception):
            adapter.get_status(handle)

    def test_logs_unknown_step_is_empty_not_error(self):
        """Канон v3.5: логов по несуществующему stepId нет → пустой список."""
        if not _REPO:
            pytest.skip("COSMO_WOODPECKER_SMOKE_REPO не задан")
        owner, _, name = _REPO.partition("/")
        adapter = _adapter()
        repo_id = adapter.resolve_repo_id(owner, name)
        handle = {"repo_id": repo_id, "number": 99999999,
                  "repo_owner": owner, "repo_name": name}
        assert adapter.get_logs(handle, step=0) == []

    def test_submit_creates_one_pipeline(self):
        """Полный живой submit — только по явному флагу (мусор в стенде)."""
        if not _SUBMIT:
            pytest.skip("COSMO_WOODPECKER_SMOKE_SUBMIT не включён")
        if not _REPO:
            pytest.skip("COSMO_WOODPECKER_SMOKE_REPO не задан")
        owner, _, name = _REPO.partition("/")
        adapter = _adapter()
        handle = adapter.submit_run(owner, name, branch="main")
        assert handle.get("number"), f"submit вернул handle без number: {handle}"
        status = adapter.get_status(handle)
        assert isinstance(status, str) and status
