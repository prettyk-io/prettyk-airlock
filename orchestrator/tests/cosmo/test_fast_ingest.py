"""COS-075: FastEvidenceIngest tests.
Tests:
- Single SARIF 2.1.0 parse with CWE/severity/file_path/line extraction
- Deduplication by composite_key (CWE + file_path + title)
- Batch ingest of 50 synthetic SARIF reports in < 5 seconds
- Cross-report deduplication
"""
import json
import time
from typing import Any

import pytest

# Expose orchestrator.cosmo on path
import sys
from pathlib import Path
_orch = Path(__file__).resolve().parents[1]
if str(_orch) not in sys.path:
    sys.path.insert(0, str(_orch))

from orchestrator.cosmo.ledger.fast_ingest import (
    FastEvidenceIngest,
    parse_sarif_document,
    SarifResult,
    FindingRecord,
    make_composite_key,
)


# ── Helpers ───────────────────────────────────────────────────────────

FINDING_TEMPLATES: list[dict[str, Any]] = [
    {"ruleId": "sast/cwe-89", "level": "error", "uri": "app/auth/login.py", "line": 42,
     "message": "SQL Injection in login endpoint", "cwe": "CWE-89"},
    {"ruleId": "sast/cwe-79", "level": "error", "uri": "app/views/profile.html", "line": 156,
     "message": "Stored Cross-Site Scripting (XSS) in User Profile", "cwe": "CWE-79"},
    {"ruleId": "sast/cwe-22", "level": "warning", "uri": "app/files/download.py", "line": 33,
     "message": "Path Traversal via file parameter", "cwe": "CWE-22"},
    {"ruleId": "dast/cwe-352", "level": "warning", "uri": "app/api/transfer.php", "line": 89,
     "message": "Missing CSRF token protection", "cwe": "CWE-352"},
    {"ruleId": "sca/cwe-200", "level": "note", "uri": "config/secrets.yaml", "line": 5,
     "message": "Hard-coded API Key in repository", "cwe": "CWE-200"},
    {"ruleId": "sast/cwe-94", "level": "error", "uri": "app/admin/upload.py", "line": 78,
     "message": "Remote Code Execution via unsafe eval()", "cwe": "CWE-94"},
    {"ruleId": "dast/cwe-918", "level": "error", "uri": "app/webhooks/dispatch.py", "line": 23,
     "message": "Server-Side Request Forgery (SSRF)", "cwe": "CWE-918"},
    {"ruleId": "sast/cwe-502", "level": "error", "uri": "app/cache/pickle_store.py", "line": 12,
     "message": "Insecure Deserialization via pickle.loads()", "cwe": "CWE-502"},
    {"ruleId": "sast/cwe-78", "level": "warning", "uri": "app/health/ping.py", "line": 67,
     "message": "OS Command Injection in health check", "cwe": "CWE-78"},
    {"ruleId": "dast/cwe-601", "level": "note", "uri": "app/auth/redirect.py", "line": 45,
     "message": "Open Redirect in OAuth callback", "cwe": "CWE-601"},
    {"ruleId": "sca/cwe-798", "level": "error", "uri": "app/config/database.py", "line": 20,
     "message": "Hardcoded JWT secret in config", "cwe": "CWE-798"},
    {"ruleId": "sast/cwe-611", "level": "warning", "uri": "app/xml/parser.py", "line": 9,
     "message": "XML External Entity (XXE) Injection", "cwe": "CWE-611"},
]


def build_sarif_report(
    findings: list[dict[str, Any]],
    tool_name: str = "SonarQube SAST Scanner",
) -> bytes:
    """Build a valid SARIF 2.1.0 JSON document."""
    rules = []
    for f in findings:
        rules.append({
            "id": f["ruleId"],
            "name": f["ruleId"],
            "shortDescription": {"text": f.get("description", f["message"])},
            "properties": {
                "cwe": f.get("cwe", ""),
                "recommendation": f.get("recommendation", "Apply proper input validation.")
            },
        })

    results = []
    for f in findings:
        results.append({
            "ruleId": f["ruleId"],
            "level": f["level"],
            "message": {"text": f["message"]},
            "locations": [
                {
                    "physicalLocation": {
                        "artifactLocation": {"uri": f["uri"]},
                        "region": {"startLine": f.get("line", 0)},
                    }
                }
            ],
        })

    report = {
        "$schema": "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/master/Schemata/sarif-schema-2.1.0.json",
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": tool_name,
                        "rules": rules,
                    }
                },
                "results": results,
            }
        ],
    }
    return json.dumps(report).encode("utf-8")


# ═══════════════════════════════════════════════════════════════════════════
# Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestSarifParser:
    """Low-level SARIF 2.1.0 result extraction."""

    def test_parse_single_finding_all_fields(self):
        report = build_sarif_report([
            {"ruleId": "sast/cwe-89", "level": "error", "uri": "app/auth/login.py", "line": 42,
             "message": "SQL Injection in login endpoint", "cwe": "CWE-89"},
        ])
        results = parse_sarif_document(report)
        assert len(results) == 1
        r = results[0]
        assert r.rule_id == "sast/cwe-89"
        assert r.severity == "Critical"
        assert r.file_path == "app/auth/login.py"
        assert r.start_line == 42
        assert r.cwe == "CWE-89"
        assert "SQL Injection" in r.message

    def test_parse_sarif_with_multiple_findings(self):
        report = build_sarif_report(FINDING_TEMPLATES[:6])
        results = parse_sarif_document(report)
        assert len(results) == 6

    def test_parse_sarif_empty_results(self):
        report = build_sarif_report([])
        results = parse_sarif_document(report)
        assert results == []

    def test_parse_sarif_no_file_path(self):
        report_json = {
            "version": "2.1.0",
            "runs": [{
                "tool": {"driver": {"name": "TestTool"}},
                "results": [
                    {
                        "ruleId": "test-rule",
                        "level": "warning",
                        "message": {"text": "Missing file location test"},
                        "locations": [],
                    }
                ]
            }]
        }
        results = parse_sarif_document(json.dumps(report_json).encode("utf-8"))
        assert len(results) == 1
        assert results[0].file_path == ""

    def test_parse_sarif_extracts_scan_type(self):
        for tool_name, expected_scan in [
            ("SonarQube SAST Scanner", "sast"),
            ("OWASP ZAP", "dast"),
            ("Dependency Check", "sca"),
            ("UnknownTool", "unknown"),
        ]:
            report = build_sarif_report([FINDING_TEMPLATES[0]], tool_name=tool_name)
            results = parse_sarif_document(report)
            assert results[0].scan_type == expected_scan, f"Expected {expected_scan} for {tool_name}"


class TestDeduplication:
    """Deduplication by composite_key (CWE + file_path + title)."""

    def test_same_finding_deduplicates(self):
        ingest = FastEvidenceIngest()
        report = build_sarif_report([
            {"ruleId": "sast/CWE-89", "level": "error", "uri": "app/auth/login.py", "line": 42,
             "message": "SQL Injection in login endpoint", "cwe": "CWE-89"},
        ])

        batch1 = ingest.ingest_sarif_bytes(report, run_id="run-101")
        assert len(batch1) == 1
        assert ingest.stats.total_inserted == 1

        # Same report again
        batch2 = ingest.ingest_sarif_bytes(report, run_id="run-101")
        assert len(batch2) == 0
        assert ingest.stats.duplicates_skipped == 1
        assert ingest.stats.total_inserted == 1

    def test_different_cwe_not_deduplicated(self):
        ingest = FastEvidenceIngest()
        r1 = build_sarif_report([
            {"ruleId": "sast/CWE-89", "level": "error", "uri": "app/auth/login.py", "line": 42,
             "message": "SQL Injection", "cwe": "CWE-89"},
        ])
        r2 = build_sarif_report([
            {"ruleId": "sast/CWE-79", "level": "error", "uri": "app/auth/login.py", "line": 42,
             "message": "SQL Injection", "cwe": "CWE-79"},
        ])

        ingest.ingest_sarif_bytes(r1, run_id="run-101")
        ingest.ingest_sarif_bytes(r2, run_id="run-101")
        assert ingest.stats.total_inserted == 2
        assert ingest.stats.duplicates_skipped == 0

    def test_different_file_path_not_deduplicated(self):
        ingest = FastEvidenceIngest()
        r1 = build_sarif_report([
            {"ruleId": "sast/CWE-89", "level": "error", "uri": "app/auth/login.py", "line": 42,
             "message": "SQL Injection", "cwe": "CWE-89"},
        ])
        r2 = build_sarif_report([
            {"ruleId": "sast/CWE-89", "level": "error", "uri": "app/api/v2/login.py", "line": 15,
             "message": "SQL Injection", "cwe": "CWE-89"},
        ])

        ingest.ingest_sarif_bytes(r1, run_id="run-101")
        ingest.ingest_sarif_bytes(r2, run_id="run-101")
        assert ingest.stats.total_inserted == 2


class TestBatchIngestSpeed:
    """Speed target: 50 reports in < 5 seconds."""

    def test_batch_50_synthetic_reports_under_5_seconds(self):
        ingest = FastEvidenceIngest()

        reports: list[bytes] = []
        for i in range(50):
            # Vary the message per report so each one produces unique findings
            per_report = [
                {
                    "ruleId": FINDING_TEMPLATES[0]["ruleId"],
                    "level": FINDING_TEMPLATES[0]["level"],
                    "uri": FINDING_TEMPLATES[0]["uri"],
                    "line": FINDING_TEMPLATES[0]["line"],
                    "message": f"{FINDING_TEMPLATES[0]['message']} (batch {i})",
                    "cwe": FINDING_TEMPLATES[0]["cwe"],
                },
                {
                    "ruleId": FINDING_TEMPLATES[1]["ruleId"],
                    "level": FINDING_TEMPLATES[1]["level"],
                    "uri": FINDING_TEMPLATES[1]["uri"],
                    "line": FINDING_TEMPLATES[1]["line"],
                    "message": f"{FINDING_TEMPLATES[1]['message']} (batch {i})",
                    "cwe": FINDING_TEMPLATES[1]["cwe"],
                },
                {
                    "ruleId": FINDING_TEMPLATES[2]["ruleId"],
                    "level": FINDING_TEMPLATES[2]["level"],
                    "uri": FINDING_TEMPLATES[2]["uri"],
                    "line": FINDING_TEMPLATES[2]["line"],
                    "message": f"{FINDING_TEMPLATES[2]['message']} (batch {i})",
                    "cwe": FINDING_TEMPLATES[2]["cwe"],
                },
            ]
            report = build_sarif_report(per_report)
            reports.append(report)

        start = time.monotonic()
        findings = ingest.ingest_batch_sarif(reports, run_id="run-fast-50")
        elapsed = time.monotonic() - start

        assert elapsed < 5.0, (
            f"Batch ingest of 50 SARIF reports took {elapsed:.2f}s; target is < 5.0s"
        )
        assert len(findings) == 150  # 50 reports × 3 unique findings each (different messages)
        assert ingest.stats.total_results == 150
        assert ingest.stats.total_inserted == 150
        assert ingest.stats.duplicates_skipped == 0
        assert ingest.stats.batches_processed == 50
        assert ingest.stats.elapsed_seconds < 5.0

    def test_batch_50_with_inline_duplicates(self):
        """50 reports, 3 findings each: 2 vary (unique), 1 is always the same."""
        ingest = FastEvidenceIngest()

        reports: list[bytes] = []
        for i in range(50):
            rotated = [
                {
                    "ruleId": FINDING_TEMPLATES[0]["ruleId"],
                    "level": FINDING_TEMPLATES[0]["level"],
                    "uri": FINDING_TEMPLATES[0]["uri"],
                    "line": FINDING_TEMPLATES[0]["line"],
                    "message": f"{FINDING_TEMPLATES[0]['message']} (var {i})",
                    "cwe": FINDING_TEMPLATES[0]["cwe"],
                },
                {
                    "ruleId": FINDING_TEMPLATES[1]["ruleId"],
                    "level": FINDING_TEMPLATES[1]["level"],
                    "uri": FINDING_TEMPLATES[1]["uri"],
                    "line": FINDING_TEMPLATES[1]["line"],
                    "message": f"{FINDING_TEMPLATES[1]['message']} (var {i})",
                    "cwe": FINDING_TEMPLATES[1]["cwe"],
                },
                dict(FINDING_TEMPLATES[2]),  # Always the same Path Traversal
            ]
            report = build_sarif_report(rotated)
            reports.append(report)

        start = time.monotonic()
        findings = ingest.ingest_batch_sarif(reports, run_id="run-dup-50")
        elapsed = time.monotonic() - start

        assert elapsed < 5.0, f"Batch ingest took {elapsed:.2f}s"
        # 2 unique × 50 + 1 persistent = 101
        assert len(findings) == 101
        assert ingest.stats.total_results == 150
        assert ingest.stats.total_inserted == 101
        assert ingest.stats.duplicates_skipped == 49  # The 49 dupes of FINDING_TEMPLATES[2]

    def test_large_sarif_single_report(self):
        """Stress test: single large SARIF with 500 findings."""
        ingest = FastEvidenceIngest()

        bulk_findings: list[dict[str, Any]] = []
        for i in range(500):
            idx = i % len(FINDING_TEMPLATES)
            f = dict(FINDING_TEMPLATES[idx])
            f["ruleId"] = f"{f['ruleId']}-{i}"
            f["uri"] = f"{f['uri']}-{i}"
            bulk_findings.append(f)

        report = build_sarif_report(bulk_findings)

        start = time.monotonic()
        findings = ingest.ingest_sarif_bytes(report, run_id="run-bulk-500")
        elapsed = time.monotonic() - start

        assert elapsed < 1.0, f"Single 500-finding SARIF took {elapsed:.2f}s"
        assert len(findings) == 500


class TestCompositeKey:
    """Composite key generation."""

    def test_composite_key_is_deterministic(self):
        k1 = make_composite_key("run-1", "CWE-89", "app/login.py", "SQL Injection")
        k2 = make_composite_key("run-1", "CWE-89", "app/login.py", "SQL Injection")
        assert k1 == k2

    def test_composite_key_changes_on_any_field(self):
        base = make_composite_key("run-1", "CWE-89", "app/login.py", "SQL Injection")
        assert base != make_composite_key("run-2", "CWE-89", "app/login.py", "SQL Injection")
        assert base != make_composite_key("run-1", "CWE-79", "app/login.py", "SQL Injection")
        assert base != make_composite_key("run-1", "CWE-89", "app/other.py", "SQL Injection")
        assert base != make_composite_key("run-1", "CWE-89", "app/login.py", "XSS Attack")


class TestArtifactStoreRoundtrip:
    """Verify SARIF flows through ArtifactStore → FastEvidenceIngest."""

    def test_store_and_ingest_via_artifact_store(self):
        import tempfile, os
        from orchestrator.cosmo.ledger.artifact_store import ArtifactStore

        with tempfile.TemporaryDirectory() as tmpdir:
            store = ArtifactStore(base_dir=tmpdir)
            ingest = FastEvidenceIngest(artifact_store=store)

            sarif_bytes = build_sarif_report([
                {"ruleId": "sast/CWE-79", "level": "error", "uri": "app/views/index.html", "line": 200,
                 "message": "Reflected XSS in search param", "cwe": "CWE-79"},
            ])

            # Store artifact
            ref = store.store(sarif_bytes, provenance="run-store/1/sarif", content_type="log", ext="sarif")
            assert ref.ref_id is not None
            assert len(ref.sha256) == 64

            # Ingest from store
            findings = ingest.ingest_from_store(ref.ref_id, run_id="run-store")
            assert len(findings) == 1
            assert findings[0].title == "Reflected XSS in search param"
            assert findings[0].cwe == "CWE-79"