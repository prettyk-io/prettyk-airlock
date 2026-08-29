# -*- coding: utf-8 -*-
"""COS-106: Continuous Compliance Auditor tests."""
import sys
from pathlib import Path
from datetime import datetime, timedelta
import pytest
_orch = Path(__file__).resolve().parents[1]
if str(_orch) not in sys.path:
    sys.path.insert(0, str(_orch))
from orchestrator.cosmo.ledger.compliance_auditor import ComplianceAuditor, DomainComplianceSnapshot

NOW = datetime(2025, 6, 15, 12, 0, 0)

class TestDomainAudit:
    def test_perfect(self):
        snap = ComplianceAuditor().audit_domain("d1", "Perfect", NOW, [], [], NOW)
        assert snap.compliance_index == 100.0
        assert snap.status == "PASS"

    def test_stale_scan(self):
        snap = ComplianceAuditor().audit_domain("d2", "Old", NOW - timedelta(days=35), [], [], NOW)
        assert "STALE_SCAN" in snap.flags
        assert snap.compliance_index < 100

    def test_pending_gates(self):
        gates = [{"type": "manual", "decision": "manual_required"}, {"type": "automatic", "decision": "pass"}]
        snap = ComplianceAuditor().audit_domain("d3", "Gates", NOW, gates, [], NOW)
        assert "PENDING_GATES" in snap.flags
        assert snap.pending_gates == 1

    def test_sla_breached(self):
        findings = [{"id": "f1", "severity": "Critical", "detected_at": NOW - timedelta(hours=25)}]
        snap = ComplianceAuditor().audit_domain("d4", "Vulns", NOW, [], findings, NOW)
        assert "SLA_BREACHED" in snap.flags

    def test_critical_flags(self):
        findings = [{"id": "f1", "severity": "Critical", "detected_at": NOW}]
        snap = ComplianceAuditor().audit_domain("d5", "Crit", NOW, [], findings, NOW)
        assert "CRITICAL_FINDINGS" in snap.flags

    def test_no_false_critical(self):
        findings = [{"id": "f1", "severity": "Medium", "detected_at": NOW}]
        snap = ComplianceAuditor().audit_domain("d6", "Med", NOW, [], findings, NOW)
        assert "CRITICAL_FINDINGS" not in snap.flags

    def test_stale_plus_pending(self):
        snap = ComplianceAuditor().audit_domain("d7", "Mixed",
            NOW - timedelta(days=35),
            [{"type": "manual", "decision": "manual_required"}],
            [], NOW)
        assert snap.compliance_index <= 85

    def test_no_scan_is_stale(self):
        snap = ComplianceAuditor().audit_domain("d8", "NoScan", None, [], [], NOW)
        assert snap.stale_scan is True

    def test_label(self):
        snap = ComplianceAuditor().audit_domain("d9", "MyLabel", NOW, [], [], NOW)
        assert snap.label == "MyLabel"

class TestFullAudit:
    def test_two_domains(self):
        a = ComplianceAuditor()
        snaps = [a.audit_domain("d1", "A", NOW, [], [], NOW),
                 a.audit_domain("d2", "B", None, [], [], NOW)]
        assert len(snaps) == 2
        assert snaps[0].compliance_index == 100
        assert snaps[1].stale_scan is True

    def test_with_gates(self):
        snap = ComplianceAuditor().audit_domain("d1", "X", NOW,
            [{"type": "automatic", "decision": "pass"}], [], NOW)
        assert snap.pending_gates == 0