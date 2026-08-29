"""COS-012: User Preferences REST API — server-side persistence.

GET  /api/v1/preferences → текущие настройки (theme, domain, env)
PUT  /api/v1/preferences → обновить настройки

Без БД — in-memory dict с сессионным ключом.
Фронтенд НЕ использует localStorage — всё через этот API.
"""
from __future__ import annotations

import threading
from typing import Literal
from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/v1/preferences", tags=["preferences"])

ThemeMode = Literal["light", "dark"]


class Preferences(BaseModel):
    theme: ThemeMode = Field(default="light", description="Тема: light / dark")
    domain: str = Field(default="all", description="Выбранный domain ID")
    env: str = Field(default="stage", description="Выбранный env: dev/test/stage/prod")
    nav: str = Field(default="domains", description="Активный раздел навигации")


class UpdatePreferences(BaseModel):
    theme: ThemeMode | None = None
    domain: str | None = None
    env: str | None = None
    nav: str | None = None


# In-memory store: session_token → Preferences
_store: dict[str, Preferences] = {}
_lock = threading.Lock()


def _session_key(request: Request) -> str:
    """Вычислить ключ сессии из кук или client IP."""
    cookie = request.cookies.get("cosmo_session")
    if cookie:
        return f"cookie:{cookie}"
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return f"ip:{forwarded.split(',')[0].strip()}"
    client = request.client
    if client:
        return f"ip:{client.host}"
    return "default"


@router.get("", response_model=Preferences)
async def get_preferences(request: Request) -> Preferences:
    """Получить текущие настройки пользователя (с дефолтами)."""
    key = _session_key(request)
    with _lock:
        prefs = _store.get(key)
        if prefs is None:
            prefs = Preferences()
            _store[key] = prefs
        return prefs


@router.put("", response_model=Preferences)
async def update_preferences(
    body: UpdatePreferences,
    request: Request,
) -> Preferences:
    """Обновить настройки (частичное обновление — только переданные поля)."""
    key = _session_key(request)
    with _lock:
        prefs = _store.get(key, Preferences())

    update = body.model_dump(exclude_none=True)
    merged = prefs.model_copy(update=update)

    with _lock:
        _store[key] = merged
    return merged


def reset_store() -> None:
    """Сбросить in-memory store (для тестов)."""
    with _lock:
        _store.clear()