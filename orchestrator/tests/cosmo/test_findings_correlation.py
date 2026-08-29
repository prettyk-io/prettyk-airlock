"""
COS-058: Findings Correlation Engine tests.

Проверяет:
  - Нормализацию из 4 источников (SAST, SCA, DAST, Fuzzer)
  - Дедупликацию по CWE + file_path + title
  - Сохранение разных находок (разные CWE или file_path)
  - Группировку по severity
  - Привязку к run_id и batch_id
  - Composite key стабильность
  - Severity маппинг из разных лейблов
  - CorrelationResult статистику
  - SARIF level mapping
"""
import pytest
from cosmo.ledger.findings_correlation import (
    FindingsCorrelator,
    NormalizedFinding,
    _normalize_severity,
    sarif_level,
)


def _make_sast(title="SQL Injection", file_path="src/auth.py", line=42, cwe="CWE-89", severity="high", run_id="run-1", batch_id="batch-sast"):
    return NormalizedFinding(
        title=title, severity=severity, source="sast", cwe=cwe, file_path=file_path, line=line,
        description="SQL injection in login handler", run_id=run_id, batch_id=batch_id,
    )

def _make_dast(title="XSS Reflected", file_path="https://app.local/search", cwe="CWE-79", severity="medium", run_id="run-1", batch_id="batch-dast"):
    return NormalizedFinding(
        title=title, severity=severity, source="dast", cwe=cwe, file_path=file_path, line=None,
        description="Reflected XSS in search parameter", run_id=run_id, batch_id=batch_id,
    )

def _make_fuzzer(title="SQL Injection Blind", file_path="/api/user/:id", cwe="CWE-89", severity="high", run_id="run-1", batch_id="batch-fuzz"):
    return NormalizedFinding(
        title=title, severity=severity, source="fuzzer", cwe=cwe, file_path=file_path, line=None,
        description="Time-based blind SQLi in user ID parameter", run_id=run_id, batch_id=batch_id,
    )

def _make_sca(title="CVE-2024-1234 in lodash", file_path="lodash@4.17.21", cwe="CWE-937", severity="medium", run_id="run-1", batch_id="batch-sca"):
    return NormalizedFinding(
        title=title, severity=severity, source="sca", cwe=cwe, file_path=file_path, line=None,
        description="Prototype pollution in lodash < 4.17.22", run_id=run_id, batch_id=batch_id,
    )

# ===========================================================================
# Normalize
# ===========================================================================

class TestNormalizeFromSources:
    def test_normalize_sast(self):
        raw = {"title": "SQLi", "severity": "high", "cwe": "CWE-89", "file_path": "src/auth.py", "line": 42, "run_id": "run-1", "batch_id": "b1"}
        f = FindingsCorrelator.normalize_sast(raw)
        assert f.source == "sast"
        assert f.cwe == "CWE-89"
        assert f.file_path == "src/auth.py"
        assert f.line == 42
        assert f.run_id == "run-1"
        assert f.batch_id == "b1"

    def test_normalize_sast_minimal(self):
        raw = {"title": "X"}
        f = FindingsCorrelator.normalize_sast(raw)
        assert f.source == "sast"
        assert f.severity == "medium"
        assert f.cwe == "CWE-200"
        assert f.file_path == ""

    def test_normalize_sca(self):
        raw = {"title": "CVE-X", "severity": "critical", "cwe": "CWE-937", "package": "lodash@4.17.21", "run_id": "r1"}
        f = FindingsCorrelator.normalize_sca(raw)
        assert f.source == "sca"
        assert f.severity == "critical"
        assert f.file_path == "lodash@4.17.21"
        assert f.line is None

    def test_normalize_dast(self):
        raw = {"alert": "XSS", "risk": "Medium", "cwe_id": "CWE-79", "url": "https://app/search", "run_id": "r1"}
        f = FindingsCorrelator.normalize_dast(raw)
        assert f.source == "dast"
        assert f.severity == "medium"
        assert f.cwe == "CWE-79"
        assert f.file_path == "https://app/search"

    def test_normalize_fuzzer(self):
        raw = {"title": "SSRF detected", "severity": "high", "url": "/api/fetch", "run_id": "r1"}
        f = FindingsCorrelator.normalize_fuzzer(raw)
        assert f.source == "fuzzer"
        assert f.file_path == "/api/fetch"
        assert f.line is None

# ===========================================================================
# Composite key (dedup)
# ===========================================================================

class TestCompositeKey:
    def test_same_key_for_identical(self):
        f1 = _make_sast(title="SQLi", file_path="src/auth.py", cwe="CWE-89")
        f2 = _make_sast(title="SQLi", file_path="src/auth.py", cwe="CWE-89")
        assert f1.composite_key() == f2.composite_key()

    def test_different_cwe_different_key(self):
        assert _make_sast(cwe="CWE-89").composite_key() != _make_sast(cwe="CWE-79").composite_key()

    def test_different_file_path_different_key(self):
        assert _make_sast(file_path="src/auth.py").composite_key() != _make_sast(file_path="src/login.py").composite_key()

    def test_different_title_different_key(self):
        assert _make_sast(title="SQLi in login").composite_key() != _make_sast(title="SQLi in search").composite_key()

    def test_key_is_32_hex_chars(self):
        key = _make_sast().composite_key()
        assert len(key) == 32
        assert all(c in "0123456789abcdef" for c in key)

    def test_same_key_different_sources(self):
        f1 = _make_sast(title="SQLi", file_path="/api/auth", cwe="CWE-89")
        f2 = _make_fuzzer(title="SQLi", file_path="/api/auth", cwe="CWE-89")
        assert f1.composite_key() == f2.composite_key()

# ===========================================================================
# Deduplication
# ===========================================================================

class TestDeduplication:
    def test_duplicate_not_added(self):
        corr = FindingsCorrelator()
        assert corr.ingest([_make_sast()]) == 1
        assert corr.ingest([_make_sast()]) == 0
        assert len(corr) == 1

    def test_different_cwe_not_duplicate(self):
        corr = FindingsCorrelator()
        assert corr.ingest([_make_sast(cwe="CWE-89")]) == 1
        assert corr.ingest([_make_sast(cwe="CWE-79")]) == 1

    def test_different_file_path_not_duplicate(self):
        corr = FindingsCorrelator()
        assert corr.ingest([_make_sast(file_path="src/auth.py")]) == 1
        assert corr.ingest([_make_sast(file_path="src/payment.py")]) == 1

    def test_different_title_not_duplicate(self):
        corr = FindingsCorrelator()
        assert corr.ingest([_make_sast(title="SQLi login")]) == 1
        assert corr.ingest([_make_sast(title="SQLi search")]) == 1

    def test_sast_fuzzer_same_finding_dedup(self):
        corr = FindingsCorrelator()
        sast = _make_sast(title="SQL Injection in auth", file_path="/api/auth", cwe="CWE-89")
        fuzz = _make_fuzzer(title="SQL Injection in auth", file_path="/api/auth", cwe="CWE-89")
        assert corr.ingest([sast]) == 1
        assert corr.ingest([fuzz]) == 0
        assert len(corr) == 1

# ===========================================================================
# Ingest raw from sources
# ===========================================================================

class TestIngestRaw:
    def test_sast_raw(self):
        corr = FindingsCorrelator()
        raw = [
            {"title": "SQLi", "severity": "high", "cwe": "CWE-89", "file_path": "src/a.py", "line": 42, "run_id": "r1"},
            {"title": "XSS", "severity": "medium", "cwe": "CWE-79", "file_path": "src/b.py", "line": 15, "run_id": "r1"},
            {"title": "SQLi", "severity": "high", "cwe": "CWE-89", "file_path": "src/a.py", "line": 42, "run_id": "r1"},
        ]
        assert corr.ingest_raw(raw, "sast") == 2

    def test_dast_raw(self):
        corr = FindingsCorrelator()
        raw = [
            {"alert": "XSS", "risk": "Medium", "cwe_id": "CWE-79", "url": "https://app/search", "run_id": "r1"},
            {"alert": "SQLi", "risk": "High", "cwe_id": "CWE-89", "url": "https://app/api", "run_id": "r1"},
        ]
        assert corr.ingest_raw(raw, "dast") == 2

    def test_fuzzer_raw(self):
        corr = FindingsCorrelator()
        assert corr.ingest_raw([{"title": "SSRF", "severity": "high", "url": "/api/fetch", "run_id": "r1"}], "fuzzer") == 1

    def test_unknown_source_returns_0(self):
        assert FindingsCorrelator().ingest_raw([{"title": "X"}], "unknown") == 0

# ===========================================================================
# Severity normalization
# ===========================================================================

class TestSeverityNormalization:
    def test_critical(self):
        assert _normalize_severity("critical") == "critical"
        assert _normalize_severity("BLOCKER") == "critical"

    def test_high(self):
        assert _normalize_severity("high") == "high"
        assert _normalize_severity("MAJOR") == "high"

    def test_medium(self):
        assert _normalize_severity("medium") == "medium"
        assert _normalize_severity("warn") == "medium"

    def test_low(self):
        assert _normalize_severity("low") == "low"

    def test_info(self):
        assert _normalize_severity("info") == "info"
        assert _normalize_severity("note") == "info"

    def test_unknown_defaults_to_medium(self):
        assert _normalize_severity("strange") == "medium"
        assert _normalize_severity(None) == "medium"

    def test_sarif_level(self):
        assert sarif_level("Critical") == "error"
        assert sarif_level("High") == "warning"
        assert sarif_level("Medium") == "note"
        assert sarif_level("Info") == "none"
        assert sarif_level("Future") == "none"

# ===========================================================================
# Grouping
# ===========================================================================

class TestGrouping:
    def test_by_severity(self):
        corr = FindingsCorrelator()
        corr.ingest([
            _make_sast(title="C1", cwe="CWE-1", file_path="a.py", severity="critical"),
            _make_dast(title="H1", cwe="CWE-2", file_path="b", severity="high"),
            _make_fuzzer(title="L1", cwe="CWE-3", file_path="c", severity="low"),
        ])
        assert len(corr.by_severity("critical")) == 1
        assert len(corr.by_severity("high")) == 1
        assert len(corr.by_severity("low")) == 1

    def test_by_source(self):
        corr = FindingsCorrelator()
        corr.ingest([_make_sast(), _make_dast(), _make_fuzzer(), _make_sca()])
        assert len(corr.by_source("sast")) == 1
        assert len(corr.by_source("dast")) == 1

    def test_by_run_id(self):
        corr = FindingsCorrelator()
        corr.ingest([_make_sast(run_id="run-a"), _make_dast(run_id="run-a"), _make_fuzzer(run_id="run-b")])
        assert len(corr.by_run("run-a")) == 2
        assert len(corr.by_run("run-b")) == 1

    def test_by_batch_id(self):
        corr = FindingsCorrelator()
        corr.ingest([_make_sast(batch_id="b-sast"), _make_dast(batch_id="b-sast"), _make_fuzzer(batch_id="b-fuzz")])
        assert len(corr.by_batch("b-sast")) == 2
        assert len(corr.by_batch("b-fuzz")) == 1

    def test_count_by_severity(self):
        corr = FindingsCorrelator()
        corr.ingest([
            _make_sast(title="C1", cwe="CWE-1", file_path="a.py", severity="critical"),
            _make_sast(title="H1", cwe="CWE-2", file_path="b.py", severity="high"),
            _make_sast(title="H2", cwe="CWE-3", file_path="c.py", severity="high"),
            _make_sast(title="M1", cwe="CWE-4", file_path="d.py", severity="medium"),
        ])
        cnts = corr.count_by_severity()
        assert cnts["critical"] == 1
        assert cnts["high"] == 2
        assert cnts["medium"] == 1

# ===========================================================================
# Sorting
# ===========================================================================

class TestSorting:
    def test_all_findings_sorted_by_severity(self):
        corr = FindingsCorrelator()
        corr.ingest([
            _make_sast(title="L", severity="low"),
            _make_sast(title="H", severity="high"),
            _make_sast(title="C", severity="critical"),
            _make_sast(title="M", severity="medium"),
            _make_sast(title="I", severity="info"),
        ])
        severities = [f.severity for f in corr.all_findings()]
        assert severities == ["critical", "high", "medium", "low", "info"]

# ===========================================================================
# CorrelationResult
# ===========================================================================

class TestCorrelationResult:
    def test_correlate_returns_stats(self):
        corr = FindingsCorrelator()
        raw = [
            _make_sast(title="A", cwe="CWE-1", file_path="a.py"),
            _make_sast(title="A", cwe="CWE-1", file_path="a.py"),
            _make_sast(title="B", cwe="CWE-2", file_path="b.py"),
            _make_dast(title="C", cwe="CWE-3", file_path="c"),
        ]
        result = corr.correlate(raw)
        assert result.total_raw == 4
        assert result.total_correlated == 3
        assert result.duplicates_removed == 1

    def test_correlate_empty(self):
        result = FindingsCorrelator().correlate([])
        assert result.total_raw == 0
        assert result.total_correlated == 0

    def test_correlate_by_severity_counts(self):
        corr = FindingsCorrelator()
        raw = [
            _make_sast(title="SQLi Login", cwe="CWE-89", file_path="src/login.py", severity="critical"),
            _make_dast(title="XSS Search", cwe="CWE-79", file_path="https://app/search", severity="high"),
            _make_fuzzer(title="SSRF Fetch", cwe="CWE-918", file_path="/api/fetch", severity="medium"),
        ]
        result = corr.correlate(raw)
        assert result.by_severity["critical"] == 1
        assert result.by_severity["high"] == 1
        assert result.by_severity["medium"] == 1

    def test_mixed_sources(self):
        corr = FindingsCorrelator()
        result = corr.correlate([_make_sast(), _make_dast(), _make_fuzzer(), _make_sca()])
        assert result.sources == {"sast": 1, "dast": 1, "fuzzer": 1, "sca": 1}

# ===========================================================================
# To dict
# ===========================================================================

class TestToDict:
    def test_to_dict_has_composite_key(self):
        d = _make_sast().to_dict()
        assert d["composite_key"] == _make_sast().composite_key()
        assert d["severity"] == "high"
        assert d["source"] == "sast"

    def test_to_dict_roundtrip(self):
        d = _make_sast().to_dict()
        assert d["title"] == "SQL Injection"
        assert d["cwe"] == "CWE-89"
        assert d["file_path"] == "src/auth.py"
        assert d["line"] == 42

    def test_raw_payload_preserved(self):
        f = FindingsCorrelator.normalize_sast({"title": "XSS", "severity": "critical", "cwe": "CWE-79", "file_path": "src/x.ts", "line": 99, "extra_field": "keep_me"})
        assert "extra_field" in f.raw_payload
        assert f.raw_payload["extra_field"] == "keep_me"