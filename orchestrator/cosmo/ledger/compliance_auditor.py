# -*- coding: utf-8 -*-
"""COS-106: Continuous Security Compliance Auditor.

DomainComplianceSnapshot: per-domain compliance assessment.
ComplianceAuditor: audit all domains for stale scans, pending gates, SLA breaches.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional, Literal

from pydantic import BaseModel, ConfigDict, Field


class DomainComplianceSnapshot(BaseModel):
    model_config = ConfigDict(extra="ignore")
    domain_id: str
    label: str = ""
    compliance_index: float = Field(ge=0, le=100, default=100.0)
    last_scan_days_ago: Optional[int] = None
    stale_scan: bool = False
    pending_gates: int = 0
    total_gates: int = 0
    sla_breached: int = 0
    total_findings: int = 0
    sla_within_pct: float = 100.0
    status: Literal["PASS", "WARN", "FAIL"] = "PASS"
    flags: list[str] = Field(default_factory=list)


class ComplianceAuditor:
    """Периодический аудитор соответствия КИТС нормативам."""

    SCAN_STALE_DAYS = 30
    CRITICAL_FINDING_MAX = 0
    HIGH_FINDING_MAX = 5

    def __init__(self, db_session_factory: Any = None) -> None:
        self._db = db_session_factory

    def audit_domain(
        self, domain_id: str, label: str = "",
        last_scan: Optional[datetime] = None,
        gates: list[dict] | None = None,
        findings: list[dict] | None = None,
        now: Optional[datetime] = None,
    ) -> DomainComplianceSnapshot:
        """Audit one domain. Принимает данные для тестопригодности.

        Args:
            domain_id: ID домена
            label: человекочитаемое имя
            last_scan: время последнего прогона
            gates: список гейтов [{decision, type}]
            findings: список находок [{severity, detected_at}]
        """
        current = (now or datetime.now(tz=timezone.utc)).replace(tzinfo=None)
        flags: list[str] = []
        penalties = 0  # loss points

        # Check 1: stale scan
        days_ago = None
        stale = False
        if last_scan is not None:
            if hasattr(last_scan, "tzinfo") and last_scan.tzinfo is not None:
                last_scan = last_scan.replace(tzinfo=None)
            days_ago = (current - last_scan).days
            if days_ago > self.SCAN_STALE_DAYS:
                stale = True
                flags.append("STALE_SCAN")
                penalties += 25
        else:
            stale = True
            flags.append("STALE_SCAN")
            penalties += 25

        # Check 2: pending gates
        gates = gates or []
        pending = sum(1 for g in gates if g.get("type") == "manual" and g.get("decision") == "manual_required")
        total_gates = len(gates)
        if pending > 0:
            flags.append("PENDING_GATES")
            penalties += 15

        # Check 3: SLA breaches
        findings = findings or []
        sla_b = 0

        # Critical found = auto-penalty
        crit_count = sum(1 for f in findings if f.get("severity") == "Critical")
        high_count = sum(1 for f in findings if f.get("severity") == "High")

        from orchestrator.cosmo.ledger.sla_tracker import calculate_sla_status
        for f in findings:
            sev = f.get("severity", "Medium")
            det = f.get("detected_at")
            if det is None:
                det = last_scan or current
            if isinstance(det, str):
                det = datetime.fromisoformat(det.replace("Z", "+00:00"))
            if hasattr(det, "tzinfo") and det.tzinfo is not None:
                det = det.replace(tzinfo=None)
            status = calculate_sla_status(sev, det, f.get("resolved_at"), now=current)
            if status == "sla_breached":
                sla_b += 1

        if sla_b > 0:
            flags.append("SLA_BREACHED")
            penalties += 25

        if crit_count > self.CRITICAL_FINDING_MAX:
            flags.append("CRITICAL_FINDINGS")
            penalties += 20

        if high_count > self.HIGH_FINDING_MAX:
            flags.append("HIGH_FINDINGS_EXCESS")
            penalties += 10

        idx = max(0, 100 - penalties)
        sla_pct = round((len(findings) - sla_b) / len(findings) * 100, 1) if findings else 100.0

        status = "PASS" if idx >= 85 else ("WARN" if idx >= 60 else "FAIL")

        return DomainComplianceSnapshot(
            domain_id=domain_id,
            label=label,
            compliance_index=idx,
            last_scan_days_ago=days_ago,
            stale_scan=stale,
            pending_gates=pending,
            total_gates=total_gates,
            sla_breached=sla_b,
            total_findings=len(findings),
            sla_within_pct=sla_pct,
            status=status,
            flags=flags,
        )

    def run_full_audit(self, domains: list[dict], domain_gates: dict[str, list[dict]] | None = None, domain_findings: dict[str, list[dict]] | None = None) -> list[DomainComplianceSnapshot]:
        """Аудит всех доменов."""
        gates_map = domain_gates or {}
        findings_map = domain_findings or {}
        results = []
        for d in domains:
            did = d.get("id", "")
            label = d.get("label", did)
            last_scan = d.get("last_scan")
            snap = self.audit_domain(
                domain_id=did, label=label, last_scan=last_scan,
                gates=gates_map.get(did, []), findings=findings_map.get(did, []),
            )
            results.append(snap)
        return results