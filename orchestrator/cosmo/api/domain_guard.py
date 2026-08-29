"""COS-061: Domain Boundary Guard — multi-tenancy isolation.

Заголовок X-Cosmo-Domain или query-параметр domain_id задают контекст домена.
Все запросы валидируются: ресурс принадлежит этому домену.
Перекрёстный доступ → HTTP 404 (не 403 — не раскрываем существование ресурса).
"""
from __future__ import annotations

from typing import Optional

from fastapi import Depends, Header, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.cosmo.api.deps import get_db


async def require_domain(
    x_cosmo_domain: Optional[str] = Header(None, alias="X-Cosmo-Domain"),
    domain_id: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
) -> str:
    """FastAPI dependency: требует domain_id из заголовка или query.

    Если не указан → 400.
    Если домен не существует → 404.
    """
    raw = x_cosmo_domain or domain_id
    if not raw or not raw.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="X-Cosmo-Domain header or domain_id query parameter required",
        )
    domain = raw.strip()

    from orchestrator.cosmo.db.models import Domain as DomainModel
    result = await db.execute(select(DomainModel.id).where(DomainModel.id == domain))
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Domain {domain} not found")
    return domain


def verify_ownership(
    resource_domain_id: Optional[str],
    caller_domain_id: str,
    resource_name: str = "Resource",
) -> None:
    """Проверяет, что ресурс принадлежит домену вызывающего.

    Если resource_domain_id != caller_domain_id → HTTP 404.
    Если resource_domain_id is None → 404 (реусрс не существет или не привязан к домену).
    """
    if not resource_domain_id or resource_domain_id != caller_domain_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"{resource_name} not found")