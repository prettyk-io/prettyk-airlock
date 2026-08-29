"""COS-005: Тесты SARIF Exporter."""
import json
import pytest
from cosmo.ledger.sarif_exporter import export_sarif, sarif_level


class TestSARIFLevel:
    def test_critical_is_error(self):
        assert sarif_level("Critical") == "error"

    def test_high_is_error(self):
        assert sarif_level("High") == "error"

    def test_medium_is_warning(self):
        assert sarif_level("Medium") == "warning"

    def test_low_is_note(self):
        assert sarif_level("Low") == "note"

    def test_info_is_note(self):
        assert sarif_level("Info") == "note"

    def test_unknown_is_none(self):
        assert sarif_level("Future") == "none"


class TestExportSARIF:
    def test_export_with_findings(self):
        findings = [
            {"alert": "SQL Injection", "risk": "High", "url": "https://example.com/api", "name": "SQLi"},
            {"alert": "XSS", "risk": "Medium", "url": "https://example.com/search", "name": "XSS"},
        ]
        result = export_sarif(findings, target_url="https://example.com")
        parsed = json.loads(result)
        assert parsed["version"] == "2.1.0"
        assert parsed["$schema"].startswith("https://")
        assert len(parsed["runs"][0]["results"]) == 2

    def test_export_empty(self):
        result = export_sarif([])
        parsed = json.loads(result)
        assert len(parsed["runs"][0]["results"]) == 0

    def test_tool_name(self):
        result = export_sarif([], tool_name="My Scanner")
        parsed = json.loads(result)
        assert parsed["runs"][0]["tool"]["driver"]["name"] == "My Scanner"

    def test_severity_mapping(self):
        findings = [
            {"alert": "X", "risk": "Critical", "url": "", "name": "X"},
            {"alert": "Y", "risk": "Low", "url": "", "name": "Y"},
        ]
        result = export_sarif(findings)
        parsed = json.loads(result)
        levels = [r["level"] for r in parsed["runs"][0]["results"]]
        assert "error" in levels
        assert "note" in levels