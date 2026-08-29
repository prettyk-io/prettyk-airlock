# -*- coding: utf-8 -*-
"""COS-104: Finding Search Engine tests — 500 synthetic vulnerabilities."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_orch = Path(__file__).resolve().parents[1]
if str(_orch) not in sys.path:
    sys.path.insert(0, str(_orch))

from orchestrator.cosmo.ledger.finding_search import FindingSearchEngine


def _make_findings(count=500):
    """Generate 500 synthetic findings with varied severities, CWEs, and file paths."""
    severities = ["Critical", "High", "Medium", "Low", "Info"]
    cwe_list = ["CWE-89", "CWE-79", "CWE-352", "CWE-190", "CWE-287", "CWE-200", "CWE-22", "CWE-918"]
    tools = ["sonarqube", "zap", "dependency-check", "trivy"]
    paths = [
        "src/api/auth.py", "src/api/users.py", "src/models/user.py",
        "src/utils/crypto.py", "src/frontend/App.tsx", "config/nginx.conf",
        "docker-compose.yml", "src/db/migrations/001.py",
        "src/worker/tasks.py", "lib/parser/utils.go",
    ]

    findings = []
    for i in range(count):
        sev = severities[i % 5]
        cwe_idx = i % len(cwe_list)
        finding = {
            "id": f"f-{i:04d}",
            "title": f"Finding #{i}: {sev} severity issue in {paths[i % 10]}",
            "description": f"Description for finding #{i} — CWE-{cwe_list[cwe_idx].split('-')[1]} detected by {tools[i % 4]}",
            "severity": sev,
            "cwe_ids": [cwe_list[cwe_idx], cwe_list[(cwe_idx + 1) % len(cwe_list)]],
            "file_path": paths[i % 10],
            "source_tool": tools[i % 4],
            "message": f"This is finding #{i}",
            "rule_name": f"rule-{i % 20:02d}",
        }
        findings.append(finding)
    return findings


ALL_FINDINGS = _make_findings(500)


class TestFilter:
    def test_no_filters_returns_all(self):
        r = FindingSearchEngine.filter(ALL_FINDINGS)
        assert r["total"] == 500
        assert len(r["items"]) == 50  # default limit = 50

    def test_limit_100(self):
        r = FindingSearchEngine.filter(ALL_FINDINGS, limit=100)
        assert len(r["items"]) == 100
        assert r["total"] == 500

    def test_offset(self):
        r = FindingSearchEngine.filter(ALL_FINDINGS, offset=50, limit=50)
        assert r["offset"] == 50
        assert r["items"][0]["id"] == "f-0050"

    def test_filter_severity(self):
        r = FindingSearchEngine.filter(ALL_FINDINGS, severity="Critical")
        assert r["total"] == 100  # every 5th
        assert all(f["severity"] == "Critical" for f in r["items"])

    def test_filter_multiple_severities(self):
        r = FindingSearchEngine.filter(ALL_FINDINGS, severity=["Critical", "High"])
        assert r["total"] == 200
        sevs = {f["severity"] for f in r["items"]}
        assert sevs <= {"Critical", "High"}

    def test_filter_cwe_exact(self):
        r = FindingSearchEngine.filter(ALL_FINDINGS, cwe="CWE-89")
        assert r["total"] == 125  # 500 / 4 tool rotation hits CWE-89 every other

    def test_filter_cwe_ids_multiple(self):
        r = FindingSearchEngine.filter(ALL_FINDINGS, cwe_ids=["CWE-89", "CWE-79"])
        total_89 = FindingSearchEngine.filter(ALL_FINDINGS, cwe="CWE-89")["total"]
        total_79 = FindingSearchEngine.filter(ALL_FINDINGS, cwe="CWE-79")["total"]
        # Union should be >= max of either
        assert r["total"] >= max(total_89, total_79)

    def test_filter_file_path(self):
        r = FindingSearchEngine.filter(ALL_FINDINGS, file_path="auth.py")
        assert r["total"] == 50  # 500 / 10 paths = 50 each
        assert all("auth.py" in f["file_path"] for f in r["items"])

    def test_filter_file_path_case_insensitive(self):
        r = FindingSearchEngine.filter(ALL_FINDINGS, file_path="AUTH.PY")
        assert r["total"] == 50

    def test_filter_tool(self):
        r = FindingSearchEngine.filter(ALL_FINDINGS, tool="sonarqube")
        assert r["total"] == 125  # 500 / 4 tools
        assert all(f["source_tool"] == "sonarqube" for f in r["items"])

    def test_full_text_search_title(self):
        r = FindingSearchEngine.filter(ALL_FINDINGS, q="Critical")
        # "Critical" appears in title for Critical severity findings
        assert r["total"] == 100

    def test_full_text_search_description(self):
        r = FindingSearchEngine.filter(ALL_FINDINGS, q="dependency-check")
        assert r["total"] == 125  # every 4th

    def test_full_text_search_combined(self):
        r = FindingSearchEngine.filter(ALL_FINDINGS, q="finding")
        assert r["total"] == 500  # all have "finding" in title

    def test_combined_filters(self):
        r = FindingSearchEngine.filter(
            ALL_FINDINGS,
            severity="Critical",
            cwe="CWE-89",
            file_path="auth.py",
        )
        # Critical is every 5th, CWE-89 is every 8th rotating, auth.py is 1/10 paths
        # Approx: 500 / 5 / 8 * ~2 = ~12
        assert 5 <= r["total"] <= 30
        for f in r["items"]:
            assert f["severity"] == "Critical"
            assert "CWE-89" in f["cwe_ids"]
            assert "auth.py" in f["file_path"]

    def test_pagination_second_page(self):
        r1 = FindingSearchEngine.filter(ALL_FINDINGS, limit=50, offset=0)
        r2 = FindingSearchEngine.filter(ALL_FINDINGS, limit=50, offset=50)
        assert r1["items"][0]["id"] != r2["items"][0]["id"]
        assert r2["items"][0]["id"] == "f-0050"

    def test_no_results(self):
        r = FindingSearchEngine.filter(ALL_FINDINGS, q="xyznonexistent987654")
        assert r["total"] == 0
        assert len(r["items"]) == 0

    def test_empty_input(self):
        r = FindingSearchEngine.filter([])
        assert r["total"] == 0
        assert r["items"] == []

    def test_cwe_ids_string(self):
        """CWE in string format also matches."""
        findings = [{"id": "f1", "severity": "Medium", "cwe_ids": "CWE-79", "title": "XSS"}]
        r = FindingSearchEngine.filter(findings, cwe="CWE-79")
        assert r["total"] == 1

    def test_severity_case_sensitive(self):
        """Severity filter is exact (not case-insensitive)."""
        findings = [{"id": "f1", "severity": "critical", "title": "x"}]
        r = FindingSearchEngine.filter(findings, severity="Critical")
        assert r["total"] == 0