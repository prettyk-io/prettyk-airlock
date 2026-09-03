# -*- coding: utf-8 -*-
"""COS-101: Мост Findings ↔ Quality Gates.

Канонический носитель findings — ``runs.findings_refs`` (JSONB на runs):
его читают FindingSearchEngine (COS-104), runs API и этот мост. Сканеры
пишут severity в разных регистрах ("critical"/"CRITICAL"), а
GatePolicyEngine (COS-055) ожидает канон Critical|High|Medium|Low|Info —
нормализация living здесь, на границе.

Составляющие:
  - normalize_severity / normalize_finding — приведение severity к канону;
  - PgFindingsProvider — production-провайдер ``run_id → findings`` из PG
    (до COS-101 в wiring были только тестовые ``lambda: []``);
  - attach_findings — scan-сторона моста: append валидированных findings
    в runs.findings_refs (вызывается из API-эндпоинта ingest).

Fail-open контракт: provider не рейзит наружу — ошибка чтения = [] с
warning. Gate evaluation не должен ломать финализацию прогона
(parity COS-055 RCP: ошибка gate engine → fail-open).
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from sqlalchemy import select

logger = logging.getLogger("cosmo.findings_bridge")

# Канон severity GatePolicyEngine._SEVERITIES (gate_engine.py).
_SEVERITY_CANON: dict[str, str] = {
    "critical": "Critical",
    "high": "High",
    "medium": "Medium",
    "low": "Low",
    "info": "Info",
}


def normalize_severity(raw: Any) -> str:
    """Привести severity к канону gate engine (Critical/High/Medium/Low/Info).

    Unknown-значения проходят как есть: gate engine игнорирует их, но
    честнее сохранить находку, чем выбросить.
    """
    if not isinstance(raw, str):
        return ""
    return _SEVERITY_CANON.get(raw.strip().lower(), raw.strip())


def normalize_finding(finding: dict[str, Any]) -> dict[str, Any]:
    """Нормализовать один finding dict (не мутирует вход)."""
    out = dict(finding)
    out["severity"] = normalize_severity(out.get("severity"))
    return out


class PgFindingsProvider:
    """Production findings provider: run_id → findings из runs.findings_refs.

    Callable — сигнатура совпадает с RunControlPlane.set_findings_provider
    (COS-055). Поддерживает и async-вызов (ExecutionService.finalize_run).
    """

    def __init__(self, session_factory: Any) -> None:
        self._sf = session_factory

    async def __call__(self, run_id: str) -> list[dict[str, Any]]:
        if not run_id:
            return []
        try:
            from orchestrator.cosmo.db.models import Run as RunORM
            async with self._sf() as s:
                row = (await s.execute(
                    select(RunORM.findings_refs).where(RunORM.id == run_id)
                )).scalar_one_or_none()
        except Exception as exc:  # noqa: BLE001 — fail-open по контракту
            logger.warning("findings bridge read failed for run %s: %s",
                           run_id, exc)
            return []
        if not row:
            return []
        return [
            normalize_finding(f) for f in row
            if isinstance(f, dict)
        ]


async def attach_findings(
    session_factory: Any,
    run_id: str,
    findings: list[dict[str, Any]],
) -> int:
    """Append findings в runs.findings_refs. Возвращает новый total.

    Валидация: каждый finding обязан нести определяемый severity
    (critical|high|medium|low|info в любом регистре) — находка без
    severity не может участвовать в gate-политике, молча пропускать её
    нельзя. Run должен существовать.
    """
    if not findings:
        raise ValueError("findings payload is empty")

    prepared: list[dict[str, Any]] = []
    for i, f in enumerate(findings):
        if not isinstance(f, dict):
            raise ValueError(f"finding[{i}] is not an object")
        sev_raw = f.get("severity")
        sev = normalize_severity(sev_raw)
        if sev.lower() not in _SEVERITY_CANON:
            raise ValueError(
                f"finding[{i}].severity '{sev_raw}' is not one of "
                f"{sorted(_SEVERITY_CANON)}")
        prepared.append(normalize_finding(f))

    from orchestrator.cosmo.db.models import Run as RunORM
    async with session_factory() as s:
        run = await s.get(RunORM, run_id)
        if run is None:
            raise LookupError(f"Run '{run_id}' not found")
        refs = list(run.findings_refs or [])
        refs.extend(prepared)
        run.findings_refs = refs
        await s.commit()
        total = len(refs)
    logger.info("COS-101: attached %d finding(s) to run %s (total %d)",
                len(prepared), run_id, total)
    return total
