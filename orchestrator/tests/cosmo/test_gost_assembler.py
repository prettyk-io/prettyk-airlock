# -*- coding: utf-8 -*-
"""COS-069: tests for GOSTActAssembler."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_orch = Path(__file__).resolve().parents[1]
if str(_orch) not in sys.path:
    sys.path.insert(0, str(_orch))

from orchestrator.cosmo.ledger.gost_assembler import GOSTActAssembler
from orchestrator.cosmo.ledger.gost_act import (
    GOSTAct,
    GOSTActHeader,
    GOSTActObject,
    GOSTFinding,
    GOSTSignature,
)
from orchestrator.cosmo.ledger.gost_renderer import render_gost_act_html


# ══════════════════════════════════════════════════════════════════
# assemble_act
# ══════════════════════════════════════════════════════════════════

def _sample_findings():
    return [
        {"severity": "Critical", "title": "SQL Injection", "message": "SQLi in auth.py",
         "cwe_ids": ["CWE-89"], "evidence_refs": ["ev-1"], "description": "Found SQLi"},
        {"severity": "High", "title": "XSS", "message": "XSS in form",
         "cwe_ids": ["CWE-79"], "description": "Reflected XSS detected"},
        {"severity": "Medium", "title": "Hardcoded credentials",
         "cwe_ids": ["CWE-798"], "description": "Password in config.py"},
    ]


class TestAssembleAct:
    def test_empty_act(self):
        a = GOSTActAssembler()
        act = a.assemble_act("run-001")
        assert isinstance(act, GOSTAct)
        assert act.header.organization == "Центральный Банк РФ"
        assert "run-001" in act.object.url
        # Verdict row + no real findings = 1 finding (the verdict)
        assert len(act.findings_table) == 1
        assert "Заключение" in act.findings_table[0].title

    def test_with_findings(self):
        a = GOSTActAssembler()
        act = a.assemble_act("run-002", findings=_sample_findings())
        # 3 findings + 1 verdict row = 4
        assert len(act.findings_table) == 4
        # First row is verdict
        assert "Заключение" in act.findings_table[0].title
        assert act.findings_table[1].severity == "Critical"
        assert "SQL Injection" in act.findings_table[1].title
        assert act.findings_table[1].cwe == "CWE-89"

    def test_header_fields(self):
        a = GOSTActAssembler()
        act = a.assemble_act("run-abc12345")
        assert act.header.project_name != ""
        assert act.header.act_number == "ACT-ABC12345"
        assert act.header.organization == "Центральный Банк РФ"

    def test_object_fields(self):
        a = GOSTActAssembler()
        act = a.assemble_act("run-x", findings=[])
        assert "run-x" in act.object.url
        assert act.object.name != ""

    def test_findings_severity_mapped(self):
        a = GOSTActAssembler()
        act = a.assemble_act("run-003", findings=_sample_findings())
        sevs = [f.severity for f in act.findings_table if "Заключение" not in f.title]
        assert "Critical" in sevs
        assert "High" in sevs
        assert "Medium" in sevs

    def test_invalid_severity_defaults_to_medium(self):
        a = GOSTActAssembler()
        act = a.assemble_act("run-004", findings=[{"severity": "GARBAGE", "title": "X"}])
        non_verdict = [f for f in act.findings_table if "Заключение" not in f.title]
        assert non_verdict[0].severity == "Medium"

    def test_cwe_extraction(self):
        a = GOSTActAssembler()
        act = a.assemble_act("run-005", findings=[
            {"severity": "High", "title": "XSS", "cwe_ids": ["CWE-79", "CWE-80"], "message": ""},
        ])
        non_verdict = [f for f in act.findings_table if "Заключение" not in f.title]
        assert non_verdict[0].cwe == "CWE-79"

    def test_no_cwe_defaults_empty(self):
        a = GOSTActAssembler()
        act = a.assemble_act("run-006", findings=[
            {"severity": "Low", "title": "Style issue", "message": "lint"},
        ])
        non_verdict = [f for f in act.findings_table if "Заключение" not in f.title]
        assert non_verdict[0].cwe == ""

    def test_finding_title_fallback(self):
        a = GOSTActAssembler()
        act = a.assemble_act("run-007", findings=[
            {"severity": "Medium", "rule_name": "S3776", "message": "Cognitive complexity"},
        ])
        non_verdict = [f for f in act.findings_table if "Заключение" not in f.title]
        assert "Cognitive" in non_verdict[0].title

    def test_recommendation_added(self):
        a = GOSTActAssembler()
        act = a.assemble_act("run-008", findings=_sample_findings())
        critical_finding = act.findings_table[1]
        assert "устранить" in critical_finding.recommendation.lower()


# ══════════════════════════════════════════════════════════════════
# Verdict & Signatures
# ══════════════════════════════════════════════════════════════════

class TestVerdictAndSignatures:
    def test_passed_verdict(self):
        a = GOSTActAssembler()
        act = a.assemble_act("run-010", gate_decisions={"g1": "pass"})
        verdict_row = act.findings_table[0]
        assert "Passed" in verdict_row.title

    def test_blocked_verdict(self):
        a = GOSTActAssembler()
        act = a.assemble_act("run-011", gate_decisions={"g1": "block", "g2": "pass"})
        verdict_row = act.findings_table[0]
        assert "Blocked" in verdict_row.title

    def test_blocked_by_status(self):
        a = GOSTActAssembler()
        # Mock run meta with blocked status
        a._load_run_meta = MagicMock(return_value={"run_id": "run-012", "status": "blocked", "plan_id": "p"})
        act = a.assemble_act("run-012")
        verdict_row = act.findings_table[0]
        assert "Blocked" in verdict_row.title

    def test_signatures_from_gates(self):
        a = GOSTActAssembler()
        act = a.assemble_act("run-013", gate_decisions={"gate-build": "pass", "gate-dast": "block"})
        assert len(act.signatures) == 2
        assert act.signatures[0].status == "signed"  # pass
        assert act.signatures[1].status == "unsigned"  # block

    def test_default_signature_when_no_gates(self):
        a = GOSTActAssembler()
        act = a.assemble_act("run-014")
        assert len(act.signatures) == 1
        assert act.signatures[0].role == "Руководитель тестирования"
        assert act.signatures[0].status == "signed"

    def test_recommendation_normative_base(self):
        a = GOSTActAssembler()
        act = a.assemble_act("run-015", findings=_sample_findings())
        verdict_row = act.findings_table[0]
        assert "ГОСТ Р 56939" in verdict_row.recommendation
        assert "683-П" in verdict_row.recommendation or "757-П" in verdict_row.recommendation


# ══════════════════════════════════════════════════════════════════
# HTML report
# ══════════════════════════════════════════════════════════════════

class TestGenerateHTML:
    def test_html_contains_project_name(self):
        a = GOSTActAssembler()
        html = a.generate_html_report("run-020", findings=_sample_findings())
        assert "<!DOCTYPE html>" in html
        assert "<html" in html
        assert "Центральный Банк РФ" in html

    def test_html_contains_findings(self):
        a = GOSTActAssembler()
        html = a.generate_html_report("run-021", findings=_sample_findings())
        assert "SQL Injection" in html
        assert "XSS" in html

    def test_html_contains_act_number(self):
        a = GOSTActAssembler()
        html = a.generate_html_report("run-abc12345")
        assert "ACT-ABC12345" in html

    def test_html_empty_findings(self):
        a = GOSTActAssembler()
        html = a.generate_html_report("run-022", findings=[])
        # Verdict row always present
        assert "Заключение" in html

    def test_html_is_valid_html(self):
        a = GOSTActAssembler()
        html = a.generate_html_report("run-023", findings=_sample_findings())
        # Has closing tags
        assert "</html>" in html
        assert "</body>" in html
        assert "</table>" in html

    def test_html_contains_verdict(self):
        a = GOSTActAssembler()
        html = a.generate_html_report("run-024", findings=_sample_findings())
        assert "Заключение" in html

    def test_html_severity_classes(self):
        a = GOSTActAssembler()
        html = a.generate_html_report("run-025", findings=_sample_findings())
        assert "class=\"critical\"" in html
        assert "class=\"high\"" in html


# �══════════════════════════════════════════════════════════════════════
# Save to artifacts
# �══════════════════════════════════════════════════════════════════════

class TestSaveToArtifacts:
    def test_save_creates_files(self, tmp_path):
        import tempfile, shutil
        d = tempfile.mkdtemp(prefix="gost_artifacts_")
        try:
            from orchestrator.cosmo.ledger.artifact_store import ArtifactStore
            store = ArtifactStore(base_dir=d)
            a = GOSTActAssembler(store=store)
            ref = a.save_act_to_artifacts("run-030", findings=_sample_findings())

            assert ref.sha256 != ""
            assert ref.content_type == "gost-act"
            assert "gost" in ref.path.lower()

            # Check files exist
            json_path = Path(d) / ref.path
            assert json_path.exists()

            html_path = Path(d) / "gost" / "run-030" / "act.html"
            assert html_path.exists()

            # JSON is valid
            content = json.loads(json_path.read_text(encoding="utf-8"))
            assert content["header"]["organization"] == "Центральный Банк РФ"
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_save_creates_valid_html(self, tmp_path):
        import tempfile, shutil
        d = tempfile.mkdtemp(prefix="gost_html_")
        try:
            from orchestrator.cosmo.ledger.artifact_store import ArtifactStore
            store = ArtifactStore(base_dir=d)
            a = GOSTActAssembler(store=store)
            a.save_act_to_artifacts("run-031", findings=_sample_findings())

            html_path = Path(d) / "gost" / "run-031" / "act.html"
            html = html_path.read_text(encoding="utf-8")
            assert "<!DOCTYPE html>" in html
            assert "SQL Injection" in html
            assert "</html>" in html
        finally:
            shutil.rmtree(d, ignore_errors=True)


# �══════════════════════════════════════════════════════════════════════
# GOST renderer integration
# �══════════════════════════════════════════════════════════════════════

class TestRenderIntegration:
    def test_nder_gost_act_html_direct(self):
        act = GOSTAct(
            header=GOSTActHeader(project_name="Test Project", act_number="ACT-001"),
            object=GOSTActObject(name="Test App", url="https://tst", domain="digital-ruble"),
            findings_table=[
                GOSTFinding(severity="Critical", title="SQLi", cwe="CWE-89",
                           description="SQL injection found", recommendation="Fix it"),
            ],
            signatures=[
                GOSTSignature(role="Reviewer", name="Alice", date="2025-01-01", status="signed"),
            ],
        )
        html = render_gost_act_html(act)
        assert "Test Project" in html
        assert "SQLi" in html
        assert "Alice" in html
        assert "critical" in html.lower()