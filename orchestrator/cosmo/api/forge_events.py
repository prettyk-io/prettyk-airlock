# -*- coding: utf-8 -*-
"""COS-096: состояние живых forge-пушей (webhook → ПУ).

In-memory кэш последних push-событий по repo_path. ЧЕСТНАЯ ГРАНИЦА:
кэш переживает только процесс — после рестарта он пуст, и ПУ показывает
empty (не выдуманный коммит). Durable-трейл при этом ведётся отдельно —
каждое принятое событие пишется строкой в audit-таблицу
(action="commit_push"), поэтому история НЕ теряется, переживает рестарт
и читается через GET /apps/{id}/forge/last-push (fallback на audit).
"""
from __future__ import annotations

import datetime
import threading
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ForgePushEvent:
    repo_path: str
    branch: str
    head_sha: str
    pusher: str
    commit_count: int
    received_at: str = field(
        default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat()
    )


_LOCK = threading.Lock()
_LAST_BY_REPO: dict[str, ForgePushEvent] = {}


def record_push(event: ForgePushEvent) -> None:
    with _LOCK:
        _LAST_BY_REPO[event.repo_path] = event


def last_push(repo_path: str) -> dict[str, Any] | None:
    """Последний пуш репо из живого кэша. None — пусто (честно)."""
    with _LOCK:
        ev = _LAST_BY_REPO.get(repo_path)
        if ev is None:
            return None
        return {
            "repo_path": ev.repo_path,
            "branch": ev.branch,
            "head_sha": ev.head_sha,
            "pusher": ev.pusher,
            "commit_count": ev.commit_count,
            "received_at": ev.received_at,
            "source": "webhook_cache",
        }


def reset() -> None:
    """Только для тестов."""
    with _LOCK:
        _LAST_BY_REPO.clear()
