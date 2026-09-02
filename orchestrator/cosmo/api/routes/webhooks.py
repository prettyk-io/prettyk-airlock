# -*- coding: utf-8 -*-
"""COS-096: приём webhook'ов Gitea (live forge cycle).

POST /api/v1/webhooks/gitea — forge callback. Аутентификация НЕ по bearer
(Gitea не наш пользователь), а по HMAC-SHA256 подписи (X-Gitea-Signature)
с общим секретом PK_GITEA_WEBHOOK_SECRET — ровно тем, которым adapter
регистрирует hook (ensure_webhook). Неверная подпись → 401, тело не
доверяем.

Семантика:
  - push привязанного репо (repo_bindings.repo_path == full_name):
    in-memory кэш (ПУ видит сразу) + audit-запись (existing audit surface)
    → 200;
  - push непривязанного репо: честный 202 {"bound": false} — событие не
    теряется в тишине, но и не изображает привязку;
  - битая подпись → 401; мусорный payload → 400.

ЧЕСТНАЯ ГРАНИЦА (COS-096): audit и кэш — in-memory поверхности приложения,
переживают только процесс. После рестарта last-push пуст до следующего
пуша; durable-трейл (audit-таблица в БД) — follow-up вне миграционного
freeze. Ничего не изображаем: пусто = пусто.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.cosmo.adapters.forge_gitea import GiteaForgeAdapter
from orchestrator.cosmo.api import forge_events
from orchestrator.cosmo.api.forge_client import webhook_secret
from orchestrator.cosmo.api.deps import get_db
from orchestrator.cosmo.api.routes.audit import record_system_event
from orchestrator.cosmo.db.models import RepositoryBinding as RepoBindingModel

logger = logging.getLogger("cosmo.forge.webhook")

router = APIRouter(prefix="/api/v1/webhooks", tags=["webhooks"])


def _signature_valid(raw: bytes, signature: str, secret: str) -> bool:
    return GiteaForgeAdapter.verify_webhook_signature(raw, signature.strip(), secret)


@router.post("/gitea", status_code=status.HTTP_200_OK)
async def gitea_webhook(
    request: Request,
    x_gitea_signature: str = Header(default=""),
    x_gitea_event: str = Header(default="push"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Gitea push webhook: signature verify → bind check → ПУ + audit."""
    raw = await request.body()
    sig = x_gitea_signature or ""
    secret = webhook_secret()

    if not sig or not _signature_valid(raw, sig, secret):
        logger.warning("Gitea webhook rejected: invalid or missing signature")
        record_system_event(
            user_id="forge:gitea",
            action="webhook_rejected",
            resource_type="repo",
            resource_id="unknown",
            status="blocked",
            details={"reason": "invalid signature"},
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid webhook signature",
        )

    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="webhook payload is not valid JSON",
        )

    if x_gitea_event != "push":
        # Честно принимаем и игнорируем нерелевантные события (ping и др.)
        return {"handled": False, "reason": f"event '{x_gitea_event}' ignored"}

    parsed = GiteaForgeAdapter.parse_push_event(payload)
    repo_path = parsed.get("repo_full_name", "")
    if not repo_path:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="push payload missing repository.full_name",
        )

    # Привязка: repo_path в repo_bindings?
    stmt = select(RepoBindingModel).where(RepoBindingModel.repo_path == repo_path)
    res = await db.execute(stmt)
    binding = res.scalars().first()

    event = forge_events.ForgePushEvent(
        repo_path=repo_path,
        branch=parsed.get("branch", ""),
        head_sha=parsed.get("head_sha", ""),
        pusher=parsed.get("pusher", "unknown"),
        commit_count=parsed.get("commit_count", 0),
    )

    if binding is None:
        logger.info("Gitea push for UNBOUND repo %s (sha=%s)", repo_path, event.head_sha[:8])
        record_system_event(
            user_id=f"forge:gitea:{event.pusher}",
            action="webhook_unbound_push",
            resource_type="repo",
            resource_id=repo_path,
            status="success",
            details={"branch": event.branch, "head_sha": event.head_sha},
        )
        return {"handled": True, "bound": False, "repo": repo_path}

    # ПУ surface: in-memory кэш + audit-запись
    forge_events.record_push(event)
    record_system_event(
        user_id=f"forge:gitea:{event.pusher}",
        action="commit_push",
        resource_type="repo",
        resource_id=repo_path,
        status="success",
        details={
            "branch": event.branch,
            "head_sha": event.head_sha,
            "commit_count": event.commit_count,
        },
    )

    logger.info(
        "Gitea push accepted: %s@%s (%d commit(s) by %s)",
        repo_path, event.branch, event.commit_count, event.pusher,
    )
    return {
        "handled": True,
        "bound": True,
        "repo": repo_path,
        "branch": event.branch,
        "head_sha": event.head_sha,
    }
