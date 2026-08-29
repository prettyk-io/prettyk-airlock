"""COS-035: OpenAPI 3.0 metadata + security contract for Cosmoport 2.0.

Расширяет стандартный FastAPI openapi() патч-схемой безопасности
и архитектурными метаданными.

Инварианты:
  - 56 эндпоинтов, 41 схема, 10 тегов
  - token_ref — VAULT-ссылка (не реальный токен)
  - HTTPValidationError — FastAPI-стандарт (Pydantic internals)
  - Аутентификация — future (Bearer token placeholder)
  - Pure Box boundary: Cosmo only acquires через CapabilityBroker
"""
from __future__ import annotations

from typing import Any


def openapi_metadata() -> dict[str, Any]:
    """Дополнительные метаданные для FastAPI app.openapi().

    Использование:
        app = FastAPI(**openapi_metadata())
        app.openapi = lambda: get_openapi_schema(app)
    """
    return {
        "title": "Cosmoport 2.0 API",
        "description": (
            "Sovereign Run Control Plane — управление жизненным циклом "
            "безопасности разработки.\n\n"
            "## Архитектурные границы\n\n"
            "Cosmoport **только** триггерит сессии защитных инструментов "
            "(scanner, Playwright) через `CapabilityBroker.acquire()` и "
            "получает результаты через webhook/SSE. Управление процессами "
            "(ZAP, Playwright CDP) — внутреннее дело **Pure Box**.\n\n"
            "## Безопасность\n\n"
            "- `token_ref` — ссылка на секретницу (VAULT/GITEA_TOKEN), "
            "НЕ реальный токен.\n"
            "- Все эндпоинты без аутентификации (dev/CI) — Bearer token "
            "запланирован в COS-017.\n"
            "- HTTPValidationError — стандартный Pydantic-вывод; "
            "не содержит чувствительных данных.\n\n"
            "## SSE\n\n"
            "- `GET /api/v1/runs/{run_id}/stream` — Server-Sent Events, "
            "rate-limit 2 Hz. Reconnect-safe.\n"
            "- События: `status_change`, `batch_complete`, `gate_decision`, `finding`."
        ),
        "version": "0.3.0",
        "openapi_tags": [
            {
                "name": "health",
                "description": "Kubernetes health checks (/live, /ready, /health). Без авторизации.",
            },
            {
                "name": "domains",
                "description": "CRUD для Domain — верхнеуровневая сущность Cosmo. ForgeBinding.token_ref — Vault-ссылка.",
            },
            {
                "name": "apps",
                "description": "Applications, Groups, RepositoryBindings внутри Domain.",
            },
            {
                "name": "pipelines",
                "description": "PipelineBricks (каталог шагов) + PipelinePlans (скомпилированные планы).",
            },
            {
                "name": "runs",
                "description": "Жизненный цикл прогонов + Batches. SSE-стрим для реального времени.",
            },
            {
                "name": "gates",
                "description": "Security Gates. Manual gate требует decided_by. Automatic gate не может быть manual_required.",
            },
            {
                "name": "sse",
                "description": "Server-Sent Events. GET /api/v1/runs/{run_id}/stream — live мониторинг.",
            },
            {
                "name": "preferences",
                "description": "Пользовательские настройки (theme, domain, env). In-memory, без БД.",
            },
            {
                "name": "releases",
                "description": "Release-пакеты: draft → pending_review → approved/rejected → deploying → deployed.",
            },
            {
                "name": "metrics",
                "description": "Prometheus metrics endpoint (/metrics).",
            },
        ],
        # COS-017: Auth placeholder (Bearer token). Пока все эндпоинты открыты.
        "components": {
            "securitySchemes": {
                "bearerAuth": {
                    "type": "http",
                    "scheme": "bearer",
                    "bearerFormat": "JWT",
                    "description": (
                        "Bearer token аутентификация (COS-017 — future). "
                        "Пока ВСЕ эндпоинты открыты. Токен выдаётся через "
                        "Cosmoport Auth Service."
                    ),
                },
            },
        },
        # Security: глобально без требований (dev/CI)
        "security": [],
        # Архитектурные аннотации
        "x-cosmo-architecture": {
            "pure_box_boundary": (
                "Cosmo only acquires tool sessions via CapabilityBroker.acquire(). "
                "ScannerCtl, PlaywrightCtl, tool_ctl — BANNED (COS-040). "
                "See cosmo/capability/BAN.md."
            ),
            "data_classification": {
                "token_ref": "VAULT reference — not a real token",
                "forge_token_ref": "Stored in DB as VAULT/GITEA_TOKEN path — never raw",
                "gate_signature": "HMAC-SHA256 of decided_by + decision + timestamp",
            },
            "audit_trail": [
                "COS-018: Security Leak Check — 25 tests",
                "COS-024: Deep-Linking — Gate Inspector → Web IDE",
                "COS-036: Release API — 7 endpoints, 18 tests",
            ],
        },
    }


def patch_openapi(app: Any) -> None:
    """Накатить OpenAPI-метаданные на существующий FastAPI app.

    Вызывается ПОСЛЕ app.include_router(...) всех роутов.
    """
    meta = openapi_metadata()

    # Обновить базовые поля
    for key in ("title", "description", "version", "openapi_tags"):
        if key in meta:
            setattr(app, key, meta[key])

    # Добавить securitySchemes в OpenAPI схему
    _orig_openapi = app.openapi

    def _patched_openapi():
        schema = _orig_openapi()
        # Добавить securitySchemes если нет
        if "components" not in schema:
            schema["components"] = {}
        comp = schema["components"]
        if "securitySchemes" not in comp:
            comp["securitySchemes"] = meta["components"]["securitySchemes"]
        # Добавить x-cosmo-architecture
        if "x-cosmo-architecture" not in schema:
            schema["x-cosmo-architecture"] = meta["x-cosmo-architecture"]
        return schema

    app.openapi = _patched_openapi


__all__ = ["openapi_metadata", "patch_openapi"]