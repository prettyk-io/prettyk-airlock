"""Cosmoport 2.0 — Prometheus metrics endpoint.

GET /metrics — Prometheus exposition format без внешних зависимостей.

Метрики:
  cosmo_uptime_seconds            — время работы процесса (Gauge)
  cosmo_requests_total            — счётчик HTTP-запросов (Counter)
  cosmo_domains_total             — зарегистрировано доменов КИТС (Gauge)
  cosmo_applications_total        — зарегистрировано приложений (Gauge)
  cosmo_runs_total                — всего прогонов (Gauge)
  cosmo_runs_active               — активные прогоны (pending, queued, running)
  cosmo_runs_blocked              — заблокированные прогоны
  cosmo_runs_by_status            — прогоны с разбивкой по статусам
  cosmo_runs_failed_5m            — прогоны, упавшие за последние 5 минут
  cosmo_batches_by_status         — батчи по статусам
  cosmo_gates_total               — всего контрольных ворот (Gates)
  cosmo_gates_blocked             — ворота с вердиктом block
  cosmo_gates_blocked_15m         — ворота, заблокированные за последние 15 минут
  cosmo_gates_by_decision         — ворота с разбивкой по решениям
  cosmo_api_latency_ms            — задержка probe-проверок (DB, Cache)
"""
from __future__ import annotations

import datetime
import os
import threading
import time
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.cosmo.api.deps import get_db, require_principal
from orchestrator.cosmo.api.health import _STARTED_AT, _probe_postgres, _probe_valkey
from orchestrator.cosmo.db.models import Application, Batch, Domain, Gate, Run
from orchestrator.cosmo.domain.rbac import PrincipalContext

router = APIRouter(tags=["metrics"])

_REQUEST_COUNT = 0
_REQUEST_LOCK = threading.Lock()


def _inc_request() -> None:
    global _REQUEST_COUNT
    with _REQUEST_LOCK:
        _REQUEST_COUNT += 1


async def _query_scalar(stmt, db: AsyncSession, default: int = 0) -> int:
    try:
        result = await db.execute(stmt)
        val = result.scalar()
        return val if val is not None else default
    except Exception:
        return default


# ══════════════════════════════════════════════════════════════════════════════
# Trends Dashboard JSON endpoint
# ══════════════════════════════════════════════════════════════════════════════


class TrendDataPoint(BaseModel):
    date: str = Field(..., description="ISO date key (YYYY-MM-DD)")
    value: float


class FlakyGateItem(BaseModel):
    gate_id: str
    plan_id: str
    total_decisions: int
    blocks: int
    block_rate: float
    passes: int


class TrendsResponse(BaseModel):
    domain_id: str = "all"
    days: int = 30
    pass_rate_trend: list[TrendDataPoint] = Field(default_factory=list)
    findings_severity_trend: list[dict] = Field(default_factory=list)
    mean_duration_trend: list[TrendDataPoint] = Field(default_factory=list)
    flaky_gates: list[FlakyGateItem] = Field(default_factory=list)
    summary: dict = Field(default_factory=dict)


@router.get("/api/v1/metrics/trends", response_model=TrendsResponse)
async def trends(
    domain_id: str = Query("all", description="Domain ID filter"),
    days: int = Query(30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
    principal: PrincipalContext = Depends(require_principal()),
) -> TrendsResponse:
    """Security trends dashboard: pass rate, findings severity, run duration, flaky gates.

    COS-068: authentication required (aggregated security posture).
    """
    now_utc = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    start_dt = now_utc - datetime.timedelta(days=days)

    # ── Run data ──────────────────────────────────────────────────────
    run_stmt = select(Run).where(Run.created_at >= start_dt)
    if domain_id != "all":
        run_stmt = run_stmt.where(Run.domain_id == domain_id)
    run_result = await db.execute(run_stmt)
    runs = run_result.scalars().all()

    # ── Gate data ─────────────────────────────────────────────────────
    gate_stmt = select(Gate)
    gate_result = await db.execute(gate_stmt)
    gates = gate_result.scalars().all()

    # ── Compute trends ────────────────────────────────────────────────
    date_buckets: dict[str, dict] = {}
    for r in runs:
        dk = (r.created_at or now_utc).strftime("%Y-%m-%d")
        if dk not in date_buckets:
            date_buckets[dk] = {"total": 0, "succeeded": 0, "failed": 0, "durations": [], "critical": 0, "high": 0, "medium": 0}
        bucket = date_buckets[dk]
        bucket["total"] += 1
        if r.status == "succeeded":
            bucket["succeeded"] += 1
        elif r.status == "failed":
            bucket["failed"] += 1
        if r.started_at and r.finished_at:
            bucket["durations"].append((r.finished_at - r.started_at).total_seconds())

        # Simulate findings severity from findings_refs JSONB or mock
        findings = r.findings_refs or []
        for f in (findings if isinstance(findings, list) else []):
            sev = str(f.get("severity", "")).lower() if isinstance(f, dict) else ""
            if sev in ("critical", "high", "medium"):
                bucket[sev] = bucket.get(sev, 0) + 1

    pass_rate_trend: list[TrendDataPoint] = []
    mean_duration_trend: list[TrendDataPoint] = []
    findings_trend: list[dict] = []
    sorted_dates = sorted(date_buckets.keys())

    for dk in sorted_dates:
        b = date_buckets[dk]
        pr = (b["succeeded"] / b["total"] * 100) if b["total"] > 0 else 0
        pass_rate_trend.append(TrendDataPoint(date=dk, value=round(pr, 1)))
        if b["durations"]:
            avg_dur = sum(b["durations"]) / len(b["durations"])
            mean_duration_trend.append(TrendDataPoint(date=dk, value=round(avg_dur, 1)))
        findings_trend.append({
            "date": dk,
            "critical": b.get("critical", 0),
            "high": b.get("high", 0),
            "medium": b.get("medium", 0),
        })

    # Flaky gates: gates with most blocks
    gate_counts: dict[str, dict] = {}
    for g in gates:
        if g.id not in gate_counts:
            gate_counts[g.id] = {"plan_id": g.plan_id or "N/A", "total": 0, "passes": 0, "blocks": 0}
        gate_counts[g.id]["total"] += 1
        if g.decision == "block":
            gate_counts[g.id]["blocks"] += 1
        elif g.decision == "pass":
            gate_counts[g.id]["passes"] += 1

    flaky_gates: list[FlakyGateItem] = []
    for gid, stats in gate_counts.items():
        if stats["total"] > 0:
            block_rate = (stats["blocks"] / stats["total"]) * 100
            if block_rate > 0:
                flaky_gates.append(FlakyGateItem(
                    gate_id=gid,
                    plan_id=stats["plan_id"],
                    total_decisions=stats["total"],
                    blocks=stats["blocks"],
                    block_rate=round(block_rate, 1),
                    passes=stats["passes"],
                ))

    flaky_gates.sort(key=lambda x: x.block_rate, reverse=True)

    # Summary
    total_runs = sum(b["total"] for b in date_buckets.values())
    total_succeeded = sum(b["succeeded"] for b in date_buckets.values())
    total_failed = sum(b["failed"] for b in date_buckets.values())
    overall_pr = (total_succeeded / total_runs * 100) if total_runs > 0 else 0
    all_durs = [d for b in date_buckets.values() for d in b.get("durations", [])]
    avg_dur = (sum(all_durs) / len(all_durs)) if all_durs else 0
    total_crit = sum(b.get("critical", 0) for b in date_buckets.values())

    return TrendsResponse(
        domain_id=domain_id,
        days=days,
        pass_rate_trend=pass_rate_trend,
        findings_severity_trend=findings_trend,
        mean_duration_trend=mean_duration_trend,
        flaky_gates=flaky_gates[:8],
        summary={
            "total_runs": total_runs,
            "pass_rate_pct": round(overall_pr, 1),
            "failed_runs": total_failed,
            "mean_duration_seconds": round(avg_dur, 1),
            "total_critical_findings": total_crit,
            "last_updated": now_utc.isoformat(),
        },
    )


# ── COS-105: SLA Monitor endpoint ──

@router.get("/api/v1/metrics/sla", summary="Vulnerability SLA compliance summary")
async def sla_monitor(
    domain_id: str = Query("all", description="Domain ID filter"),
    db: AsyncSession = Depends(get_db),
    principal: PrincipalContext = Depends(require_principal()),
):
    """Сводка по соблюдению SLA (ЦБ РФ: Critical=24h, High=7d, Medium=30d, Low=90d).

    COS-068: authentication required.
    """
    from orchestrator.cosmo.ledger.sla_tracker import sla_summary
    from orchestrator.cosmo.db.models import Run as RunModel

    # Fetch runs with findings for the domain
    stmt = select(RunModel)
    if domain_id != "all":
        stmt = stmt.where(RunModel.domain_id == domain_id)
    result = await db.execute(stmt)
    runs = result.scalars().all()

    # Collect all findings from all runs
    all_findings: list[dict] = []
    for run in runs:
        findings = run.findings_refs or []
        for f in findings:
            if isinstance(f, dict):
                fid = f.get("id") or f.get("key", "")
                sev = f.get("severity", "Medium")
                det = run.finished_at or run.created_at
                all_findings.append({
                    "id": fid,
                    "finding_id": fid,
                    "severity": sev,
                    "detected_at": det,
                })

    summary = sla_summary(all_findings)
    return {"domain_id": domain_id, **summary}


# ══════════════════════════════════════════════════════════════════════════════
# Prometheus /metrics
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/metrics")
async def metrics(db: AsyncSession = Depends(get_db)) -> str:
    """Prometheus text exposition format — метрики Cosmo Control Plane.

    COS-068: намеренно БЕЗ authentication — scrape-контракт Prometheus
    (scraper не носит пользовательских credentials). Эндпоинт отдаёт
    только агрегированные счётчики без пер-пользовательских данных;
    сетевая изоляция — зона Caddy/infra (Buddy).
    """
    _inc_request()
    now_ts = time.time()
    uptime = now_ts - _STARTED_AT
    now_utc = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)

    # 1. Probes
    pg_probe = await _probe_postgres(timeout=2.0)
    vk_probe = await _probe_valkey(timeout=2.0)

    # 2. Inventory
    total_domains = await _query_scalar(select(func.count()).select_from(Domain), db)
    total_apps = await _query_scalar(select(func.count()).select_from(Application), db)

    # 3. Runs metrics
    total_runs = await _query_scalar(select(func.count()).select_from(Run), db)
    active_runs = await _query_scalar(
        select(func.count()).select_from(Run).where(
            Run.status.in_(["pending", "queued", "running"]),
        ),
        db,
    )
    blocked_runs = await _query_scalar(
        select(func.count()).select_from(Run).where(Run.status == "blocked"),
        db,
    )

    all_run_statuses = ["draft", "pending", "queued", "running", "succeeded", "failed", "blocked", "cancelled"]
    runs_by_status: dict[str, int] = {st: 0 for st in all_run_statuses}
    try:
        run_rows = (await db.execute(
            select(Run.status, func.count(Run.id)).group_by(Run.status)
        )).all()
        for r_st, cnt in run_rows:
            runs_by_status[str(r_st)] = int(cnt)
    except Exception:
        pass

    five_min_ago = now_utc - datetime.timedelta(minutes=5)
    runs_failed_5m = await _query_scalar(
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

    # 4. Batches metrics
    batches_by_status: dict[str, int] = {st: 0 for st in ["pending", "running", "passed", "failed", "blocked"]}
    try:
        batch_rows = (await db.execute(
            select(Batch.status, func.count(Batch.id)).group_by(Batch.status)
        )).all()
        for b_st, cnt in batch_rows:
            batches_by_status[str(b_st)] = int(cnt)
    except Exception:
        pass

    # 5. Gates metrics
    total_gates = await _query_scalar(select(func.count()).select_from(Gate), db)
    gates_blocked = await _query_scalar(
        select(func.count()).select_from(Gate).where(Gate.decision == "block"),
        db,
    )
    fifteen_min_ago = now_utc - datetime.timedelta(minutes=15)
    gates_blocked_15m = await _query_scalar(
        select(func.count()).select_from(Gate).where(
            and_(
                Gate.decision == "block",
                Gate.decided_at >= fifteen_min_ago,
            )
        ),
        db,
    )

    gates_by_decision: dict[str, int] = {d: 0 for d in ["pass", "block", "manual_required", "undecided"]}
    try:
        gate_rows = (await db.execute(
            select(Gate.decision, func.count(Gate.id)).group_by(Gate.decision)
        )).all()
        for g_dec, cnt in gate_rows:
            key = str(g_dec) if g_dec else "undecided"
            gates_by_decision[key] = int(cnt)
    except Exception:
        pass

    # ── Format builder ──

    def metric(
        name: str,
        value: float,
        type_: str = "gauge",
        help_: str = "",
        labels: Optional[dict[str, str]] = None,
    ) -> str:
        lines = []
        if help_:
            lines.append(f"# HELP {name} {help_}")
        lines.append(f"# TYPE {name} {type_}")
        if labels:
            label_str = ",".join(f'{k}="{v}"' for k, v in sorted(labels.items()))
            lines.append(f"{name}{{{label_str}}} {value}")
        else:
            lines.append(f"{name} {value}")
        return "\n".join(lines)

    parts = [
        metric("cosmo_uptime_seconds", uptime, type_="gauge", help_="Process uptime in seconds"),
        metric("cosmo_requests_total", _REQUEST_COUNT, type_="counter", help_="Total HTTP requests to API"),
        metric("cosmo_domains_total", total_domains, type_="gauge", help_="Total registered domains"),
        metric("cosmo_applications_total", total_apps, type_="gauge", help_="Total registered applications"),
        metric("cosmo_runs_total", total_runs, type_="gauge", help_="Total pipeline runs"),
        metric("cosmo_runs_active", active_runs, type_="gauge", help_="Active runs (pending, queued, running)"),
        metric("cosmo_runs_blocked", blocked_runs, type_="gauge", help_="Blocked runs"),
        metric("cosmo_runs_failed_5m", runs_failed_5m, type_="gauge", help_="Runs failed in last 5 minutes"),
        metric("cosmo_gates_total", total_gates, type_="gauge", help_="Total security gates"),
        metric("cosmo_gates_blocked", gates_blocked, type_="gauge", help_="Total gates with block decision"),
        metric("cosmo_gates_blocked_15m", gates_blocked_15m, type_="gauge", help_="Gates blocked in last 15 minutes"),
        metric(
            "cosmo_api_latency_ms",
            pg_probe.latency_ms or 0.0,
            type_="gauge",
            help_="Database probe latency in milliseconds",
            labels={"dependency": "postgres"},
        ),
        metric(
            "cosmo_api_latency_ms",
            vk_probe.latency_ms or 0.0,
            type_="gauge",
            help_="Cache probe latency in milliseconds",
            labels={"dependency": "valkey"},
        ),
    ]

    for status_name, cnt in sorted(runs_by_status.items()):
        parts.append(metric(
            "cosmo_runs_by_status", cnt,
            type_="gauge",
            help_="Runs breakdown by status",
            labels={"status": status_name},
        ))

    for batch_status, cnt in sorted(batches_by_status.items()):
        parts.append(metric(
            "cosmo_batches_by_status", cnt,
            type_="gauge",
            help_="Batches breakdown by status",
            labels={"status": batch_status},
        ))

    for dec_name, cnt in sorted(gates_by_decision.items()):
        parts.append(metric(
            "cosmo_gates_by_decision", cnt,
            type_="gauge",
            help_="Gates breakdown by decision",
            labels={"decision": dec_name},
        ))

    return "\n".join(parts) + "\n"


# ── COS-106: Compliance Audit endpoint ──

@router.get("/api/v1/compliance/audit", summary="Security compliance audit across all domains")
async def compliance_audit(
    db: AsyncSession = Depends(get_db),
    principal: PrincipalContext = Depends(require_principal()),
):
    """Сводный отчёт аудита по всем КИТС.

    Проверяет: устаревшие сканы, неотвеченные гейты, SLA-просрочки.
    Возвращает: список DomainComplianceSnapshot с compliance_index 0-100.

    COS-068: authentication required.
    """
    from orchestrator.cosmo.db.models import Domain as DomainModel, Run as RunModel, Gate as GateModel
    from orchestrator.cosmo.ledger.compliance_auditor import ComplianceAuditor, DomainComplianceSnapshot
    from sqlalchemy import func

    # Fetch all domains
    domain_result = await db.execute(select(DomainModel))
    domains = domain_result.scalars().all()

    auditor = ComplianceAuditor()
    snapshots = []

    for domain in domains:
        # Last scan time for this domain
        run_result = await db.execute(
            select(func.max(RunModel.finished_at)).where(RunModel.domain_id == domain.id)
        )
        last_scan = run_result.scalar()

        # Gates — collect all gates for all plans
        gates_list = []
        gate_result = await db.execute(select(GateModel))
        gates = gate_result.scalars().all()
        for g in gates:
            gates_list.append({"type": g.type, "decision": g.decision or ""})

        # Findinds from all runs
        findings_result = await db.execute(
            select(RunModel.findings_refs).where(RunModel.domain_id == domain.id)
        )
        all_findings = []
        for row in findings_result.all():
            refs = row[0] or []
            for f in refs:
                if isinstance(f, dict):
                    all_findings.append(f)

        snap = auditor.audit_domain(
            domain_id=domain.id, label=domain.label or domain.id,
            last_scan=last_scan, gates=gates_list, findings=all_findings,
        )
        snapshots.append(snap.model_dump())

    return {
        "domains": snapshots,
        "summary": {
            "total_domains": len(snapshots),
            "pass": sum(1 for s in snapshots if s["status"] == "PASS"),
            "warn": sum(1 for s in snapshots if s["status"] == "WARN"),
            "fail": sum(1 for s in snapshots if s["status"] == "FAIL"),
            "avg_compliance_idx": round(
                sum(s["compliance_index"] for s in snapshots) / len(snapshots), 1
            ) if snapshots else 100.0,
        },
    }
