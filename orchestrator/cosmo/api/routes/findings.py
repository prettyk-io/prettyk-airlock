"""COS-104: Finding Search API endpoint — GET /api/v1/findings/search."""
from __future__ import annotations

from typing import Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.cosmo.api.deps import get_db, require_principal
from orchestrator.cosmo.domain.rbac import PrincipalContext

router = APIRouter(prefix="/api/v1/findings", tags=["findings"])


@router.get("/search")
async def search_findings(
    q: Optional[str] = Query(None, description="Full-text search query"),
    severity: Optional[str] = Query(None, description="Critical|High|Medium|Low|Info"),
    cwe: Optional[str] = Query(None, description="CWE-89"),
    file: Optional[str] = Query(None, description="File path ILIKE"),
    tool: Optional[str] = Query(None, description="Source tool"),
    domain_id: Optional[str] = Query(None, description="Domain ID"),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    principal: PrincipalContext = Depends(require_principal()),
):
    """Поиск по уязвимостям с GIN-оптимизацией.

    Поддерживает: текстовый поиск (q), фильтр severity, CWE, путь к файлу,
    source tool, диапазон дат, пагинацию.

    Returns {items, total, offset, limit}.

    COS-068: authentication required + domain-scoping: не-админ ищет
    только в своём домене (клиентский domain_id игнорируется), админ
    может фильтровать любым доменом или искать глобально.
    """
    from orchestrator.cosmo.db.session import get_sync_session
    from orchestrator.cosmo.ledger.finding_search import FindingSearchEngine

    # COS-068: domain-scoping — не-админ не может расширить поиск на чужой домен
    effective_domain = (
        domain_id if principal.is_system_admin else (principal.domain_id or "__no_domain__")
    )

    # Parse severity list
    sev_list = [s.strip() for s in severity.split(",")] if severity else None
    sev_arg = sev_list if sev_list and len(sev_list) > 1 else (sev_list[0] if sev_list else None)

    result = FindingSearchEngine.search_pg(
        db_session_factory=get_sync_session,
        domain_id=effective_domain,
        severity=sev_arg,
        cwe=cwe,
        file_path=file,
        tool=tool,
        date_from=date_from,
        date_to=date_to,
        q=q,
        offset=offset,
        limit=limit,
    )
    return result