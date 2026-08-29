# -*- coding: utf-8 -*-
"""COS-104: Finding Search & GIN Query Engine.

FindingSearchEngine:
  - filter(findings, **criteria) — фильтрация in-memory (тестопригодно)
  - search_pg(db_factory, **criteria) — PostgreSQL JSONB GIN-accelerated query
  - Пагинация: offset/limit
"""
from __future__ import annotations

from typing import Any, Optional


class FindingSearchEngine:
    """High-performance finding filter engine.

    Поддерживаемые фильтры:
      - severity: str | list[str] — Critical|High|Medium|Low|Info
      - cwe: str — точный CWE (CWE-89)
      - cwe_ids: list[str] — несколько CWE (array containment)
      - file_path: str — ILIKE подстрока
      - tool: str — source_tool (sonarqube, zap, etc.)
      - date_from / date_to: str — ISO date range (detected_at)
      - q: str — полнотекстовый поиск по title + description + message
      - offset: int = 0, limit: int = 50
    """

    @staticmethod
    def filter(
        findings: list[dict[str, Any]],
        *,
        severity: Optional[str | list[str]] = None,
        cwe: Optional[str] = None,
        cwe_ids: Optional[list[str]] = None,
        file_path: Optional[str] = None,
        tool: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        q: Optional[str] = None,
        offset: int = 0,
        limit: int = 50,
    ) -> dict[str, Any]:
        """Filter findings in-memory. Returns {items, total, offset, limit}."""
        # Normalize cwe_ids from cwe param
        all_cwe = set(cwe_ids or [])
        if cwe:
            all_cwe.add(cwe)

        severities = None
        if severity:
            if isinstance(severity, list):
                severities = set(severity)
            else:
                severities = {severity}

        query_lower = q.lower() if q else None

        matched: list[dict[str, Any]] = []

        for f in findings:
            # Severity filter
            if severities is not None:
                f_sev = f.get("severity", "")
                if f_sev not in severities:
                    continue

            # CWE filter (check cwe_ids field)
            if all_cwe:
                f_cwe_list = f.get("cwe_ids", [])
                if isinstance(f_cwe_list, str):
                    f_cwe_list = [f_cwe_list]
                if not any(c in f_cwe_list for c in all_cwe):
                    continue

            # File path filter (ILIKE)
            if file_path:
                fp = f.get("file_path") or f.get("artifactLocation", {}).get("uri", "")
                if file_path.lower() not in fp.lower():
                    continue

            # Tool filter
            if tool:
                f_tool = f.get("source_tool") or f.get("tool", "")
                if tool.lower() not in f_tool.lower():
                    continue

            # Date range filter
            if date_from or date_to:
                det = f.get("detected_at") or f.get("created_at", "")
                if isinstance(det, str) and det:
                    if date_from and det < date_from:
                        continue
                    if date_to and det > date_to:
                        continue

            # Full-text search on title + description + message
            if query_lower:
                title = (f.get("title") or f.get("rule_name") or "").lower()
                desc = (f.get("description") or f.get("message") or "").lower()
                if query_lower not in title and query_lower not in desc:
                    continue

            matched.append(f)

        total = len(matched)
        items = matched[offset:offset + limit]

        return {
            "items": items,
            "total": total,
            "offset": offset,
            "limit": limit,
        }

    @staticmethod
    def search_pg(
        db_session_factory: Any,
        *,
        domain_id: Optional[str] = None,
        severity: Optional[str | list[str]] = None,
        cwe: Optional[str] = None,
        file_path: Optional[str] = None,
        tool: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        q: Optional[str] = None,
        offset: int = 0,
        limit: int = 50,
    ) -> dict[str, Any]:
        """Query PostgreSQL runs.findings_refs via JSONB operators (GIN-accelerated).

        Returns {items, total, offset, limit}.
        """
        from orchestrator.cosmo.db.models import Run as RunModel
        from sqlalchemy import cast, String

        s = db_session_factory()
        try:
            all_findings: list[dict[str, Any]] = []

            # Base query: all runs with findings
            query = s.query(RunModel)
            if domain_id:
                query = query.filter(RunModel.domain_id == domain_id)

            # JSONB containment for CWE: findings_refs @> [{"cwe_ids": ["CWE-89"]}]
            # This leverages the GIN index on findings_refs
            if cwe:
                pattern = cast(f'[{{"cwe_ids": ["{cwe}"]}}]', type_=String)
                query = query.filter(RunModel.findings_refs.contains([{"cwe_ids": [cwe]}]))

            runs = query.order_by(RunModel.created_at.desc()).all()

            # Extract findings from runs
            for run in runs:
                findings = run.findings_refs or []
                for f in findings:
                    if isinstance(f, dict):
                        f["_run_id"] = run.id
                        f["_plan_id"] = run.plan_id
                        f["_detected_at"] = str(run.finished_at or run.created_at)
                        all_findings.append(f)

        finally:
            s.close()

        # In-memory filtering for the rest
        return FindingSearchEngine.filter(
            all_findings,
            severity=severity,
            cwe=cwe,
            file_path=file_path,
            tool=tool,
            date_from=date_from,
            date_to=date_to,
            q=q,
            offset=offset,
            limit=limit,
        )