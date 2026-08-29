"""Cosmoport 2.0 — Aggregated Health & Status Dashboard endpoint.

GET /api/v1/status/dashboard — Быстрый просмотр состояния Control Plane без Grafana.
Включает:
  - Uptime и статус инфраструктуры (PostgreSQL, Valkey)
  - Сводку по запускам (Runs), батчам (Batches) и воротам (Gates)
  - Вычисленные алерты:
      * runs failed > 0 за 5 мин (Critical)
      * gates blocked > 3 за 15 мин (Warning)
      * API / DB latency > 500ms (Warning)
  - Инвентарь КИТС (Domains, Apps) и последние запуски
"""
from __future__ import annotations

import datetime
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.cosmo.api.deps import get_db
from orchestrator.cosmo.api.health import _STARTED_AT, _probe_postgres, _probe_valkey
from orchestrator.cosmo.db.models import (
    Application,
    Batch,
    Domain,
    EvidenceLedgerEntry,
    Gate,
    PipelinePlan,
    Run,
)

router = APIRouter(prefix="/api/v1/status", tags=["status"])


# ── Pydantic Schemas ──────────────────────────────────────────────────────────

class ProbeMetric(BaseModel):
    status: str
    latency_ms: Optional[float] = None
    error: Optional[str] = None


class ProbesStatus(BaseModel):
    database: ProbeMetric
    cache: ProbeMetric


class StatusAlert(BaseModel):
    name: str
    severity: str  # "critical" | "warning" | "info"
    active: bool
    threshold: str
    current_value: Any
    message: str


class DashboardSummary(BaseModel):
    total_domains: int = 0
    total_applications: int = 0
    total_pipeline_plans: int = 0
    total_runs: int = 0
    active_runs: int = 0
    succeeded_runs: int = 0
    failed_runs: int = 0
    blocked_runs: int = 0
    total_batches: int = 0
    total_gates: int = 0
    blocked_gates: int = 0
    total_evidence_entries: int = 0


class RecentRunSummary(BaseModel):
    id: str
    domain_id: str
    plan_id: str
    status: str
    trigger: str
    created_at: Optional[datetime.datetime] = None
    finished_at: Optional[datetime.datetime] = None


class StatusDashboardResponse(BaseModel):
    status: str  # "ok" | "degraded" | "critical"
    timestamp: str
    uptime_seconds: float
    summary: DashboardSummary
    runs_by_status: Dict[str, int]
    batches_by_status: Dict[str, int]
    gates_by_decision: Dict[str, int]
    alerts: List[StatusAlert]
    probes: ProbesStatus
    recent_runs: List[RecentRunSummary] = Field(default_factory=list)


# ── Helper Query Functions ───────────────────────────────────────────────────

async def _safe_count(stmt, db: AsyncSession, default: int = 0) -> int:
    try:
        res = await db.execute(stmt)
        val = res.scalar()
        return val if val is not None else default
    except Exception:
        return default


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/dashboard", response_model=StatusDashboardResponse)
async def get_status_dashboard(
    db: AsyncSession = Depends(get_db),
) -> StatusDashboardResponse:
    """Агрегированный дашборд состояния Cosmoport 2.0."""
    now_ts = time.time()
    uptime = round(now_ts - _STARTED_AT, 1)
    now_utc = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)

    # 1. Probes (DB & Valkey)
    pg_probe = await _probe_postgres(timeout=2.0)
    vk_probe = await _probe_valkey(timeout=2.0)

    probes = ProbesStatus(
        database=ProbeMetric(
            status=pg_probe.status,
            latency_ms=pg_probe.latency_ms,
            error=pg_probe.error,
        ),
        cache=ProbeMetric(
            status=vk_probe.status,
            latency_ms=vk_probe.latency_ms,
            error=vk_probe.error,
        ),
    )

    # 2. Inventory counts
    total_domains = await _safe_count(select(func.count()).select_from(Domain), db)
    total_apps = await _safe_count(select(func.count()).select_from(Application), db)
    total_plans = await _safe_count(select(func.count()).select_from(PipelinePlan), db)
    total_evidence = await _safe_count(select(func.count()).select_from(EvidenceLedgerEntry), db)

    # 3. Runs breakdown by status
    all_run_statuses = ["draft", "pending", "queued", "running", "succeeded", "failed", "blocked", "cancelled"]
    runs_by_status: Dict[str, int] = {st: 0 for st in all_run_statuses}
    try:
        run_rows = (await db.execute(
            select(Run.status, func.count(Run.id)).group_by(Run.status)
        )).all()
        for r_st, cnt in run_rows:
            runs_by_status[str(r_st)] = int(cnt)
    except Exception:
        pass

    total_runs = sum(runs_by_status.values())
    active_runs = runs_by_status.get("pending", 0) + runs_by_status.get("queued", 0) + runs_by_status.get("running", 0)
    succeeded_runs = runs_by_status.get("succeeded", 0)
    failed_runs = runs_by_status.get("failed", 0)
    blocked_runs = runs_by_status.get("blocked", 0)

    # 4. Batches breakdown by status
    all_batch_statuses = ["pending", "running", "passed", "failed", "blocked"]
    batches_by_status: Dict[str, int] = {st: 0 for st in all_batch_statuses}
    try:
        batch_rows = (await db.execute(
            select(Batch.status, func.count(Batch.id)).group_by(Batch.status)
        )).all()
        for b_st, cnt in batch_rows:
            batches_by_status[str(b_st)] = int(cnt)
    except Exception:
        pass
    total_batches = sum(batches_by_status.values())

    # 5. Gates breakdown by decision
    all_gate_decisions = ["pass", "block", "manual_required", "undecided"]
    gates_by_decision: Dict[str, int] = {dec: 0 for dec in all_gate_decisions}
    try:
        gate_rows = (await db.execute(
            select(Gate.decision, func.count(Gate.id)).group_by(Gate.decision)
        )).all()
        for g_dec, cnt in gate_rows:
            key = str(g_dec) if g_dec else "undecided"
            gates_by_decision[key] = int(cnt)
    except Exception:
        pass
    total_gates = sum(gates_by_decision.values())
    blocked_gates = gates_by_decision.get("block", 0)

    # 6. Time-window alert metrics
    five_min_ago = now_utc - datetime.timedelta(minutes=5)
    fifteen_min_ago = now_utc - datetime.timedelta(minutes=15)

    # Runs failed in last 5 min
    runs_failed_5m = await _safe_count(
        select(func.count()).select_from(Run).where(
            and_(
                Run.status == "failed",
                or_(
                    Run.finished_at >= five_min_ago,
                    and_(Run.finished_at.is_(None), Run.created_at >= five_min_ago),
                ),
            )
        ),
        db,
    )

    # Gates blocked in last 15 min
    gates_blocked_15m = await _safe_count(
        select(func.count()).select_from(Gate).where(
            and_(
                Gate.decision == "block",
                Gate.decided_at >= fifteen_min_ago,
            )
        ),
        db,
    )

    # Max probe latency
    max_latency = max(
        (pg_probe.latency_ms or 0.0),
        (vk_probe.latency_ms or 0.0),
    )

    # 7. Evaluate Alert Rules
    alerts: List[StatusAlert] = [
        StatusAlert(
            name="runs_failed_5m",
            severity="critical",
            active=(runs_failed_5m > 0),
            threshold="runs failed > 0 over 5m",
            current_value=runs_failed_5m,
            message=(
                f"CRITICAL: {runs_failed_5m} run(s) failed in the last 5 minutes!"
                if runs_failed_5m > 0
                else "OK: No failed runs in the last 5 minutes."
            ),
        ),
        StatusAlert(
            name="gates_blocked_15m",
            severity="warning",
            active=(gates_blocked_15m > 3),
            threshold="gates blocked > 3 over 15m",
            current_value=gates_blocked_15m,
            message=(
                f"WARNING: High gate blockage rate ({gates_blocked_15m} gates blocked in 15m)!"
                if gates_blocked_15m > 3
                else f"OK: Gate blockages within normal range ({gates_blocked_15m} in 15m)."
            ),
        ),
        StatusAlert(
            name="api_latency_high",
            severity="warning",
            active=(max_latency > 500.0 or pg_probe.status != "healthy" or vk_probe.status != "healthy"),
            threshold="probe latency > 500ms or dependency unhealthy",
            current_value=round(max_latency, 1),
            message=(
                f"WARNING: High dependency latency ({round(max_latency, 1)}ms) or probe failure."
                if (max_latency > 500.0 or pg_probe.status != "healthy" or vk_probe.status != "healthy")
                else f"OK: Dependency latency normal ({round(max_latency, 1)}ms)."
            ),
        ),
    ]

    # 8. Overall System Status
    if pg_probe.status != "healthy" or vk_probe.status != "healthy" or runs_failed_5m > 0:
        overall_status = "critical"
    elif gates_blocked_15m > 3 or max_latency > 500.0 or blocked_runs > 0:
        overall_status = "degraded"
    else:
        overall_status = "ok"

    # 9. Recent runs
    recent_runs: List[RecentRunSummary] = []
    try:
        run_stmt = select(Run).order_by(Run.created_at.desc()).limit(10)
        res_runs = await db.execute(run_stmt)
        for r in res_runs.scalars().all():
            recent_runs.append(
                RecentRunSummary(
                    id=r.id,
                    domain_id=r.domain_id,
                    plan_id=r.plan_id,
                    status=r.status,
                    trigger=r.trigger,
                    created_at=r.created_at,
                    finished_at=r.finished_at,
                )
            )
    except Exception:
        pass

    summary = DashboardSummary(
        total_domains=total_domains,
        total_applications=total_apps,
        total_pipeline_plans=total_plans,
        total_runs=total_runs,
        active_runs=active_runs,
        succeeded_runs=succeeded_runs,
        failed_runs=failed_runs,
        blocked_runs=blocked_runs,
        total_batches=total_batches,
        total_gates=total_gates,
        blocked_gates=blocked_gates,
        total_evidence_entries=total_evidence,
    )

    return StatusDashboardResponse(
        status=overall_status,
        timestamp=now_utc.isoformat() + "Z",
        uptime_seconds=uptime,
        summary=summary,
        runs_by_status=runs_by_status,
        batches_by_status=batches_by_status,
        gates_by_decision=gates_by_decision,
        alerts=alerts,
        probes=probes,
        recent_runs=recent_runs,
    )
