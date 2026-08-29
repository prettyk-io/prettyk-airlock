# -*- coding: utf-8 -*-
"""COS-105: Vulnerability SLA Monitor & Remediation Tracker.

SLA deadlines per ЦБ РФ: Critical=24h, High=7d, Medium=30d, Low=90d, Info=180d.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional, Literal

from pydantic import BaseModel, ConfigDict, Field

SLAStatus = Literal["within_sla", "sla_breached", "resolved"]

_SLA_HOURS = {
    "Critical": 24, "High": 7 * 24, "Medium": 30 * 24,
    "Low": 90 * 24, "Info": 180 * 24,
}


class VulnerabilitySLA(BaseModel):
    model_config = ConfigDict(extra="ignore")
    finding_id: str = Field(..., min_length=1)
    severity: str
    detected_at: datetime
    sla_deadline: datetime
    status: SLAStatus = "within_sla"
    resolution: Optional[str] = None
    resolved_at: Optional[datetime] = None


def calculate_deadline(severity: str, detected_at: datetime) -> datetime:
    hours = _SLA_HOURS.get(severity, 180 * 24)
    return detected_at + timedelta(hours=hours)


def calculate_sla_status(
    severity: str, detected_at: datetime,
    resolved_at: Optional[datetime] = None, now: Optional[datetime] = None,
) -> SLAStatus:
    deadline = calculate_deadline(severity, detected_at)
    if resolved_at is not None:
        return "resolved" if resolved_at <= deadline else "sla_breached"

    current = (now or datetime.now(tz=timezone.utc)).replace(tzinfo=None)
    if deadline.tzinfo is not None:
        deadline = deadline.replace(tzinfo=None)
    return "sla_breached" if current > deadline else "within_sla"


def check_breached_slas(
    findings: list[dict[str, Any]], now: Optional[datetime] = None,
) -> list[VulnerabilitySLA]:
    current = (now or datetime.now(tz=timezone.utc)).replace(tzinfo=None)
    breached: list[VulnerabilitySLA] = []
    for f in findings:
        sev = f.get("severity", "Medium")
        fid = f.get("id") or f.get("finding_id", "")
        det = f.get("detected_at")
        if det is None:
            det = current
        if isinstance(det, str):
            det = datetime.fromisoformat(det.replace("Z", "+00:00"))
        if hasattr(det, "tzinfo") and det.tzinfo is not None:
            det = det.replace(tzinfo=None)
        resolved = f.get("resolved_at")
        status = calculate_sla_status(sev, det, resolved, now=current)
        if status == "sla_breached":
            deadline = calculate_deadline(sev, det)
            breached.append(VulnerabilitySLA(
                finding_id=fid, severity=sev, detected_at=det,
                sla_deadline=deadline, status="sla_breached",
                resolution=f.get("resolution"), resolved_at=resolved,
            ))
    return breached


def sla_summary(findings: list[dict[str, Any]]) -> dict[str, Any]:
    results = []
    for f in findings:
        sev = f.get("severity", "Medium")
        det = f.get("detected_at")
        if det and isinstance(det, str):
            det = datetime.fromisoformat(det.replace("Z", "+00:00"))
        if det and hasattr(det, "tzinfo") and det.tzinfo is not None:
            det = det.replace(tzinfo=None)
        status = calculate_sla_status(sev, det, f.get("resolved_at"))
        results.append({"severity": sev, "status": status})

    total = len(results)
    breached = sum(1 for r in results if r["status"] == "sla_breached")

    by_sev: dict[str, dict] = {}
    for sev in ["Critical", "High", "Medium", "Low", "Info"]:
        sev_items = [r for r in results if r["severity"] == sev]
        if sev_items:
            b = sum(1 for r in sev_items if r["status"] == "sla_breached")
            by_sev[sev] = {
                "total": len(sev_items), "breached": b,
                "within_pct": round((len(sev_items) - b) / len(sev_items) * 100, 1),
            }

    return {
        "total": total, "breached": breached, "within_sla": total - breached,
        "resolved": sum(1 for r in results if r["status"] == "resolved"),
        "by_severity": by_sev,
        "overall_pct": round((total - breached) / total * 100, 1) if total > 0 else 100.0,
    }