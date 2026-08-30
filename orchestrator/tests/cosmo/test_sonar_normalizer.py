# -*- coding: utf-8 -*-
"""COS-072: tests for Sonar SARIF Normalizer."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_orch = Path(__file__).resolve().parents[1]
if str(_orch) not in sys.path:
    sys.path.insert(0, str(_orch))

from orchestrator.cosmo.adapters.sonar_normalizer import (
    NormalizedFinding,
    build_sarif_210,
    extract_cwe,
    normalize_sonar_hotspots,
    normalize_sonar_issues,
    _normalize_severity,
    _build_location,
    _normalize_text_range,
    _extract_file_path,
)


# ══════════════════════════════════════════════════════════════════
# Real Sonar API payloads
# ══════════════════════════════════════════════════════════════════

_REAL_ISSUES = [
    {
        "key": "AYx8Z9abcdef123",
        "rule": "python:S2077",
        "severity": "CRITICAL",
        "component": "myproject:src/app/api/auth.py",
        "line": 42,
        "message": "Make sure using unescaped user-controlled data in SQL queries is safe here.",
        "type": "VULNERABILITY",
        "status": "OPEN",
        "resolution": None,
        "tags": ["cwe-89", "sql", "owasp-a1"],
        "creationDate": "2025-01-15T10:00:00+0000",
        "textRange": {"startLine": 42, "endLine": 42, "startOffset": 12, "endOffset": 45},
        "flows": [],
    },
    {
        "key": "AYx8Z9abcdef456",
        "rule": "python:S3776",
        "severity": "MAJOR",
        "component": "myproject:src/app/utils/parser.py",
        "line": 120,
        "message": "Cognitive Complexity of functions should not be too high",
        "type": "CODE_SMELL",
        "status": "OPEN",
        "resolution": None,
        "tags": ["brain-overload"],
        "creationDate": "2025-01-15T10:05:00+0000",
        "textRange": {"startLine": 120, "endLine": 210, "startOffset": 0, "endOffset": 0},
        "flows": [],
    },
    {
        "key": "AYx8Z9abcdef789",
        "rule": "python:S125",
        "severity": "MINOR",
        "component": "myproject:src/app/legacy/old.py",
        "line": 5,
        "message": "Remove this commented out code.",
        "type": "CODE_SMELL",
        "status": "RESOLVED",
        "resolution": "FIXED",
        "tags": ["bad-practice"],
        "creationDate": "2025-01-14T08:00:00+0000",
        "textRange": {"startLine": 5, "endLine": 5, "startOffset": 0, "endOffset": 80},
        "flows": [],
    },
]

_REAL_HOTSPOTS = [
    {
        "key": "hotspot-abc-001",
        "ruleKey": "python:S4790",
        "component": "myproject:src/app/crypto/hasher.py",
        "line": 33,
        "message": "Make sure using a weak hashing algorithm is safe here.",
        "status": "TO_REVIEW",
        "vulnerabilityProbability": "HIGH",
        "securityCategory": "weak-cryptography",
        "creationDate": "2025-01-15T11:00:00+0000",
    },
    {
        "key": "hotspot-abc-002",
        "ruleKey": "python:S1313",
        "component": "myproject:src/app/config.py",
        "line": 7,
        "message": "Using hardcoded IP addresses is security-sensitive",
        "status": "REVIEWED",
        "resolution": "ACKNOWLEDGED",
        "vulnerabilityProbability": "LOW",
        "securityCategory": "network",
        "creationDate": "2025-01-14T09:00:00+0000",
    },
]

_REAL_RULES = {
    "python:S2077": {"key": "python:S2077", "name": "SQL queries should not be vulnerable to injection attacks",
                     "severity": "CRITICAL", "lang": "python", "type": "VULNERABILITY",
                     "tags": ["cwe-89", "sql"], "htmlDesc": "Formatted SQL queries raise the risk of SQL injection."},
    "python:S3776": {"key": "python:S3776", "name": "Cognitive Complexity of functions should not be too high",
                     "severity": "MAJOR", "lang": "python", "type": "CODE_SMELL",
                     "tags": ["brain-overload"]},
    "python:S125": {"key": "python:S125", "name": "Sections of code should not be commented out",
                   "severity": "MINOR", "lang": "python", "type": "CODE_SMELL",
                   "tags": ["bad-practice"]},
}

_REAL_HOTSPOT_DETAILS = {
    "hotspot-abc-001": {
        "rule": {"key": "python:S4790", "name": "Using weak hashing algorithms is security-sensitive",
                 "severity": "CRITICAL", "lang": "python", "type": "SECURITY_HOTSPOT",
                 "tags": ["cwe-327", "cwe-328", "owasp-a3"]},
        "message": "Weak hashing library used (md5).",
        "vulnerabilityDescription": "Weak hashing can lead to collision attacks.",
        "fixRecommendations": "Use SHA-256 or better.",
        "textRange": {"startLine": 33, "endLine": 35, "startOffset": 4, "endOffset": 20},
    },
}


# ══════════════════════════════════════════════════════════════════
# normalize_sonar_issues
# ══════════════════════════════════════════════════════════════════

class TestNormalizeIssues:
    def test_empty(self):
        assert normalize_sonar_issues([]) == []

    def test_three_issues(self):
        findings = normalize_sonar_issues(_REAL_ISSUES, _REAL_RULES)
        assert len(findings) == 3

    def test_severity_mapped(self):
        findings = normalize_sonar_issues(_REAL_ISSUES, _REAL_RULES)
        assert findings[0].severity == "Critical"  # CRITICAL → Critical
        assert findings[1].severity == "High"       # MAJOR → High
        assert findings[2].severity == "Low"         # MINOR → Low

    def test_rule_name_enriched(self):
        findings = normalize_sonar_issues(_REAL_ISSUES, _REAL_RULES)
        assert "SQL queries" in findings[0].rule_name
        assert "Cognitive" in findings[1].rule_name

    def test_file_path_extracted(self):
        findings = normalize_sonar_issues(_REAL_ISSUES, _REAL_RULES)
        assert findings[0].file_path == "src/app/api/auth.py"
        assert findings[1].file_path == "src/app/utils/parser.py"

    def test_line_number(self):
        findings = normalize_sonar_issues(_REAL_ISSUES, _REAL_RULES)
        assert findings[0].line == 42

    def test_cwe_extraction(self):
        findings = normalize_sonar_issues(_REAL_ISSUES, _REAL_RULES)
        assert "CWE-89" in findings[0].cwe_ids
        assert len(findings[1].cwe_ids) == 0  # brain-overload not CWE

    def test_no_rules_graceful(self):
        findings = normalize_sonar_issues(_REAL_ISSUES)
        assert len(findings) == 3
        assert findings[0].rule_name == "python:S2077"  # rule_id as fallback

    def test_status_resolution(self):
        findings = normalize_sonar_issues(_REAL_ISSUES, _REAL_RULES)
        assert findings[0].status == "OPEN"
        assert findings[2].status == "RESOLVED"
        assert findings[2].resolution == "FIXED"

    def test_pydantic_validation(self):
        findings = normalize_sonar_issues(_REAL_ISSUES, _REAL_RULES)
        for f in findings:
            assert isinstance(f, NormalizedFinding)
            assert f.id != ""
            assert f.rule_id != ""


# ══════════════════════════════════════════════════════════════════
# normalize_sonar_hotspots
# ══════════════════════════════════════════════════════════════════

class TestNormalizeHotspots:
    def test_two_hotspots(self):
        findings = normalize_sonar_hotspots(_REAL_HOTSPOTS, _REAL_HOTSPOT_DETAILS)
        assert len(findings) == 2

    def test_severity_from_probability(self):
        findings = normalize_sonar_hotspots(_REAL_HOTSPOTS, _REAL_HOTSPOT_DETAILS)
        # hotspot-abc-001: CRITICAL + HIGH probability → Critical
        assert findings[0].severity == "Critical"
        # hotspot-abc-002: no rule, LOW probability → Low
        assert findings[1].severity == "Low"

    def test_type_security_hotspot(self):
        findings = normalize_sonar_hotspots(_REAL_HOTSPOTS, _REAL_HOTSPOT_DETAILS)
        for f in findings:
            assert f.type == "SECURITY_HOTSPOT"

    def test_details_enrichment(self):
        findings = normalize_sonar_hotspots(_REAL_HOTSPOTS, _REAL_HOTSPOT_DETAILS)
        f0 = findings[0]
        assert "Weak hashing" in f0.message
        assert f0.rule_name == "Using weak hashing algorithms is security-sensitive"
        assert f0.file_path == "src/app/crypto/hasher.py"

    def test_cwe_from_tags(self):
        findings = normalize_sonar_hotspots(_REAL_HOTSPOTS, _REAL_HOTSPOT_DETAILS)
        # hotspot-abc-001 has tags: cwe-327, cwe-328
        cwe_list = findings[0].cwe_ids
        assert "CWE-327" in cwe_list
        assert "CWE-328" in cwe_list


# ══════════════════════════════════════════════════════════════════
# extract_cwe
# ══════════════════════════════════════════════════════════════════

class TestExtractCWE:
    def test_tags_only(self):
        result = extract_cwe(tags=["cwe-89", "cwe-79"])
        ids = [r["id"] for r in result]
        assert 79 in ids
        assert 89 in ids

    def test_description_only(self):
        result = extract_cwe(rule_desc="See CWE-89 and CWE-352 for details")
        ids = [r["id"] for r in result]
        assert 89 in ids
        assert 352 in ids

    def test_tags_and_desc_merged(self):
        result = extract_cwe(tags=["cwe-79"], rule_desc="Also CWE-89")
        ids = [r["id"] for r in result]
        assert {79, 89} == set(ids)

    def test_deduplicates(self):
        result = extract_cwe(tags=["cwe-79", "cwe-79"], rule_desc="CWE-79 again")
        assert len(result) == 1

    def test_case_insensitive(self):
        result = extract_cwe(tags=["CWE-89", "cwe_327", "cwe 352"])
        ids = [r["id"] for r in result]
        assert {89, 327, 352} == set(ids)

    def test_colon_variant(self):
        result = extract_cwe(tags=["cwe:79"])
        assert result[0]["id"] == 79

    def test_hash_variant(self):
        result = extract_cwe(tags=["cwe#79"])
        assert result[0]["id"] == 79

    def test_empty_input(self):
        assert extract_cwe(tags=[], rule_desc="") == []
        assert extract_cwe() == []

    def test_output_format(self):
        result = extract_cwe(tags=["cwe-79"])
        assert "id" in result[0]
        assert "link" in result[0]
        assert "cwe.mitre.org" in result[0]["link"]
        assert result[0]["link"].endswith("/79.html")


# ══════════════════════════════════════════════════════════════════
# build_sarif_210
# ══════════════════════════════════════════════════════════════════

class TestBuildSarif210:
    def test_empty(self):
        sarif = build_sarif_210([])
        assert sarif["version"] == "2.1.0"
        assert "$schema" in sarif
        assert len(sarif["runs"]) == 1
        assert sarif["runs"][0]["results"] == []

    def test_with_issues(self):
        findings = normalize_sonar_issues(_REAL_ISSUES, _REAL_RULES)
        sarif = build_sarif_210(findings)
        run = sarif["runs"][0]
        assert len(run["results"]) == 3
        assert "tool" in run
        assert run["tool"]["driver"]["name"] == "SonarQube"

    def test_result_has_location(self):
        findings = normalize_sonar_issues(_REAL_ISSUES, _REAL_RULES)
        sarif = build_sarif_210(findings)
        r0 = sarif["runs"][0]["results"][0]
        assert "locations" in r0
        loc = r0["locations"][0]
        assert "physicalLocation" in loc
        pl = loc["physicalLocation"]
        assert "artifactLocation" in pl
        assert "uri" in pl["artifactLocation"]
        assert "src/app/api/auth.py" in pl["artifactLocation"]["uri"]

    def test_result_has_region(self):
        findings = normalize_sonar_issues(_REAL_ISSUES, _REAL_RULES)
        sarif = build_sarif_210(findings)
        r0 = sarif["runs"][0]["results"][0]
        assert "startLine" in r0["locations"][0]["physicalLocation"]["region"]

    def test_cwe_taxa(self):
        findings = normalize_sonar_issues(_REAL_ISSUES, _REAL_RULES)
        sarif = build_sarif_210(findings)
        run = sarif["runs"][0]
        # First issue has CWE-89
        assert "taxonomies" in run
        tax = run["taxonomies"][0]
        assert tax["name"] == "CWE"
        taxa_ids = [t["id"] for t in tax["taxa"]]
        assert "89" in taxa_ids

    def test_result_has_taxa_ref(self):
        findings = normalize_sonar_issues(_REAL_ISSUES, _REAL_RULES)
        sarif = build_sarif_210(findings)
        r0 = sarif["runs"][0]["results"][0]
        assert "taxa" in r0
        assert {"id": "89"} in r0["taxa"]

    def test_valid_json(self):
        findings = normalize_sonar_issues(_REAL_ISSUES, _REAL_RULES)
        sarif = build_sarif_210(findings)
        json_str = json.dumps(sarif)
        assert len(json_str) > 100
        parsed = json.loads(json_str)
        assert parsed["version"] == "2.1.0"

    def test_with_hotspots(self):
        findings = normalize_sonar_hotspots(_REAL_HOTSPOTS, _REAL_HOTSPOT_DETAILS)
        sarif = build_sarif_210(findings)
        results = sarif["runs"][0]["results"]
        # hotspot-abc-001 has CWE-327, CWE-328
        assert len(results) == 2
        cwe_taxa = [t["id"] for t in sarif["runs"][0].get("taxonomies", [{}])[0].get("taxa", [])]
        assert "327" in cwe_taxa or "328" in cwe_taxa

    def test_rules_index_deduplicated(self):
        findings = normalize_sonar_issues(_REAL_ISSUES, _REAL_RULES)
        sarif = build_sarif_210(findings)
        rules = sarif["runs"][0]["tool"]["driver"]["rules"]
        # Same rule (python:S3776) should appear once even for multiple issues
        rule_ids = [r["id"] for r in rules]
        assert rule_ids.count("python:S3776") <= 1


# ══════════════════════════════════════════════════════════════════
# Severity helpers
# ══════════════════════════════════════════════════════════════════

class TestSeverityMapper:
    @pytest.mark.parametrize("inp,expected", [
        ("BLOCKER", "Critical"),
        ("CRITICAL", "Critical"),
        ("MAJOR", "High"),
        ("MINOR", "Low"),
        ("INFO", "Low"),
        ("HIGH", "High"),
        ("MEDIUM", "Medium"),
        ("LOW", "Low"),
        ("Critical", "Critical"),
        ("High", "High"),
        (None, "Medium"),
        ("garbage", "Medium"),
    ])
    def test_normalize_severity(self, inp, expected):
        assert _normalize_severity(inp) == expected

    def test_hotspot_probability(self):
        assert _normalize_severity(probability="HIGH") == "High"
        assert _normalize_severity(probability="MEDIUM") == "Medium"
        assert _normalize_severity(probability="LOW") == "Low"


# ══════════════════════════════════════════════════════════════════
# Location helpers
# ══════════════════════════════════════════════════════════════════

class TestLocationHelpers:
    def test_extract_file_path(self):
        assert _extract_file_path("myproject:src/main.py") == "src/main.py"
        assert _extract_file_path("nocolon") == "nocolon"
        assert _extract_file_path(None) == "unknown"
        assert _extract_file_path("") == "unknown"

    def test_normalize_text_range(self):
        tr = {"startLine": 10, "endLine": 15, "startOffset": 0, "endOffset": 42}
        n = _normalize_text_range(tr)
        assert n["start_line"] == 10
        assert n["end_line"] == 15
        assert n["start_offset"] == 0
        assert n["end_offset"] == 42

    def test_normalize_text_range_skips_missing(self):
        n = _normalize_text_range({"startLine": 10})
        assert n == {"start_line": 10}

    def test_normalize_text_range_non_dict(self):
        assert _normalize_text_range(None) == {}
        assert _normalize_text_range("not dict") == {}
        assert _normalize_text_range(42) == {}

    def test_build_location(self):
        loc = _build_location(component="p:src/a.py", line=42,
                              text_range={"startLine": 42, "endLine": 42, "startOffset": 10, "endOffset": 30})
        assert loc["file_path"] == "src/a.py"
        assert loc["line"] == 42
        assert loc["text_range"]["start_line"] == 42
        assert loc["text_range"]["end_offset"] == 30

    def test_build_location_message(self):
        loc = _build_location(component="p:src/b.py", message="Bad code here")
        assert loc["message"] == "Bad code here"

    def test_build_location_fallback_line_from_text_range(self):
        loc = _build_location(component="p:x.py", text_range={"startLine": 99})
        assert loc["line"] == 99