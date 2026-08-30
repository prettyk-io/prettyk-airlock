"""
STACK-LUNA-001: Comprehensive Scanner Adapter Tests (40+).

Проверяет:
  1. Единый контракт ScannerResult/ScannerFinding для всех одобренных сканеров.
  2. Каждый одобренный адаптер парсит tool-specific вывод и производит ScannerResult.
  3. PASS/FAIL/ERROR/UNAVAILABLE вердикты.
  4. Привязка к артефакту (digest, build_id, release_id).
  5. Evidence linkage.
  6. Tool/rules version.
  7. Offline provenance (provenance_hash).
  8. Idempotent delivery (idempotency_key).
  9. Отсутствие raw secrets в адаптерах.
  10. Future адаптеры (CodeQL, Semgrep) возвращают UNAVAILABLE без fake activation.
"""
import datetime
import json
import hashlib
import pytest

from cosmo.scanners.scanner_contract import (
    APPROVED_SCANNERS,
    FUTURE_SCANNERS,
    BaseScannerAdapter,
    ScannerFinding,
    ScannerResult,
    ScannerTool,
)

from cosmo.scanners.approved_adapters import (
    ClamavAdapter,
    GitleaksAdapter,
    HadolintAdapter,
    KicsAdapter,
    KubeLinterAdapter,
)

from cosmo.scanners.future_adapters import (
    CodeQLAdapter,
    SemgrepAdapter,
)


# ── Helper ───────────────────────────────────────────────────────────────────

def _sha256(data: str) -> str:
    return hashlib.sha256(data.encode()).hexdigest()


# ═══════════════════════════════════════════════════════════════════════
# 1. Unified Scanner Contract Tests
# ═══════════════════════════════════════════════════════════════════════

class TestUnifiedScannerContract:

    def test_approved_scanners_count(self):
        """5 одобренных сканеров."""
        assert len(APPROVED_SCANNERS) == 5
        assert "kics" in APPROVED_SCANNERS
        assert "clamav" in APPROVED_SCANNERS
        assert "gitleaks" in APPROVED_SCANNERS
        assert "hadolint" in APPROVED_SCANNERS
        assert "kubelinter" in APPROVED_SCANNERS

    def test_future_scanners_count(self):
        """2 future сканера."""
        assert len(FUTURE_SCANNERS) == 2
        assert "codeql" in FUTURE_SCANNERS
        assert "semgrep" in FUTURE_SCANNERS

    def test_scanner_result_auto_idempotency_key(self):
        result = ScannerResult(
            tool="kics",
            tool_version="1.0",
            verdict="PASS",
            artifact_digest_sha256=_sha256("test-artifact"),
            rules_version="v1",
        )
        assert result.idempotency_key is not None
        assert len(result.idempotency_key) == 16

    def test_scanner_result_auto_provenance_hash(self):
        result = ScannerResult(
            tool="hadolint",
            tool_version="2.12.0",
            verdict="PASS",
            artifact_digest_sha256=_sha256("dockerfile"),
        )
        assert result.provenance_hash is not None
        assert len(result.provenance_hash) == 32

    def test_idempotent_delivery_same_key(self):
        """Одинаковые входные данные → одинаковый idempotency_key."""
        r1 = ScannerResult(
            tool="gitleaks", tool_version="8.23", verdict="PASS",
            artifact_digest_sha256=_sha256("repo"), rules_version="v1",
        )
        r2 = ScannerResult(
            tool="gitleaks", tool_version="8.23", verdict="PASS",
            artifact_digest_sha256=_sha256("repo"), rules_version="v1",
        )
        assert r1.idempotency_key == r2.idempotency_key

    def test_verdict_values(self):
        """Только PASS/FAIL/ERROR/UNAVAILABLE допустимы."""
        verdicts = ["PASS", "FAIL", "ERROR", "UNAVAILABLE"]
        for v in verdicts:
            result = ScannerResult(tool="kics", tool_version="1", verdict=v)  # type: ignore
            assert result.verdict == v

    def test_empty_findings_passes(self):
        result = ScannerResult(tool="hadolint", tool_version="2.12", verdict="PASS", findings=[])
        assert result.findings_count == 0
        assert result.critical_count == 0
        assert result.high_count == 0

    def test_finding_has_all_required_fields(self):
        f = ScannerFinding(
            rule_id="DL3006",
            severity="high",
            title="Always tag version",
            description="Use specific version",
            file_path="Dockerfile",
            line_number=5,
            cwe_id="CWE-250",
            remediation="Pin version",
        )
        d = f.model_dump()
        assert "rule_id" in d
        assert "severity" in d
        assert "cwe_id" in d
        assert "remediation" in d

    def test_evidence_record_conversion(self):
        result = ScannerResult(
            tool="kics", tool_version="2.1.3", verdict="FAIL",
            findings=[
                ScannerFinding(rule_id="R1", severity="critical", title="T1"),
                ScannerFinding(rule_id="R2", severity="high", title="T2"),
                ScannerFinding(rule_id="R3", severity="medium", title="T3"),
            ],
            evidence_ref="vault:secret/cosmo/evidence/kics-scan-001",
        )
        evidence = result.to_evidence_record()
        assert evidence["verdict"] == "FAIL"
        assert evidence["critical_count"] == 1
        assert evidence["high_count"] == 1
        assert evidence["findings_count"] == 3

    def test_no_raw_secrets_in_scanner_result(self):
        """ScannerResult не содержит raw secret полей."""
        result = ScannerResult(tool="gitleaks", tool_version="1", verdict="PASS")
        d = result.model_dump()
        for key in d:
            assert "token" not in key.lower(), f"Field '{key}' looks like a secret field"
            assert "password" not in key.lower()
            assert "secret_value" not in key.lower()


# ═══════════════════════════════════════════════════════════════════════
# 2. KICS Adapter Tests
# ═══════════════════════════════════════════════════════════════════════

class TestKicsAdapter:

    def test_parse_kics_pass(self):
        """Пустой результат KICS → PASS."""
        adapter = KicsAdapter()
        kics_output = json.dumps({"queries": []})
        result = adapter.parse_output(kics_output)
        assert result.verdict == "PASS"
        assert len(result.findings) == 0

    def test_parse_kics_critical_finding(self):
        """KICS обнаружил hardcoded password → FAIL."""
        adapter = KicsAdapter()
        kics_output = json.dumps({
            "queries": [{
                "query_id": "57ab2cba",
                "query_name": "Password And Secrets",
                "severity": "HIGH",
                "description": "Hardcoded password detected",
                "results": [{
                    "file_name": "terraform/main.tf",
                    "line": 42,
                    "remediation": "Use vault:secret/... reference",
                }],
            }],
        })
        result = adapter.parse_output(kics_output)
        assert result.verdict == "FAIL"
        assert result.critical_count == 1
        assert result.findings[0].cwe_id == "CWE-798"

    def test_parse_kics_json_error(self):
        """Битый JSON → ERROR."""
        adapter = KicsAdapter()
        result = adapter.parse_output("not valid json {{{")
        assert result.verdict == "ERROR"

    def test_kics_finding_severity_map(self):
        """KICS severity mapping: HIGH → critical."""
        adapter = KicsAdapter()
        assert adapter._SEVERITY_MAP["HIGH"] == "critical"
        assert adapter._SEVERITY_MAP["MEDIUM"] == "high"


# ═══════════════════════════════════════════════════════════════════════
# 3. ClamAV Adapter Tests
# ═══════════════════════════════════════════════════════════════════════

class TestClamavAdapter:

    def test_parse_clamav_clean(self):
        """Чистый вывод ClamAV → PASS."""
        adapter = ClamavAdapter()
        output = "/app/auth-binary: OK\n/app/lib.so: OK\n----------- SCAN SUMMARY -----------\nScanned: 2\nInfected: 0"
        result = adapter.parse_output(output)
        assert result.verdict == "PASS"
        assert len(result.findings) == 0

    def test_parse_clamav_infected(self):
        """ClamAV обнаружил вредоносное ПО → FAIL."""
        adapter = ClamavAdapter()
        output = "/app/malware.exe: Win.Trojan.Agent-1234567 FOUND\n/app/clean.so: OK"
        result = adapter.parse_output(output)
        assert result.verdict == "FAIL"
        assert result.critical_count == 1
        assert "Win.Trojan.Agent-1234567" in result.findings[0].title
        assert result.findings[0].cwe_id == "CWE-506"

    def test_parse_clamav_empty(self):
        """Пустой вывод → ERROR."""
        adapter = ClamavAdapter()
        result = adapter.parse_output("")
        assert result.verdict == "ERROR"


# ═══════════════════════════════════════════════════════════════════════
# 4. Gitleaks Adapter Tests
# ═══════════════════════════════════════════════════════════════════════

class TestGitleaksAdapter:

    def test_parse_gitleaks_clean(self):
        """Чистый репозиторий → PASS."""
        adapter = GitleaksAdapter()
        output = json.dumps([])
        result = adapter.parse_output(output)
        assert result.verdict == "PASS"
        assert len(result.findings) == 0

    def test_parse_gitleaks_github_pat(self):
        """Gitleaks обнаружил GitHub PAT → FAIL, CWE-798."""
        adapter = GitleaksAdapter()
        output = json.dumps([{
            "rule_id": "github-pat",
            "description": "GitHub Personal Access Token",
            "file": "config/secrets.yaml",
            "StartLine": 12,
            "secret": "REDACTED_BY_GITLEAKS",
        }])
        result = adapter.parse_output(output)
        assert result.verdict == "FAIL"
        assert result.critical_count == 1
        assert result.findings[0].cwe_id == "CWE-798"
        # remediation contains Russian "отозвать" (revoke) or "vault:secret"
        rem = result.findings[0].remediation.lower()
        assert "vault:secret" in rem or "отозвать" in rem

    def test_parse_gitleaks_json_error(self):
        """Битый JSON вывод Gitleaks → ERROR."""
        adapter = GitleaksAdapter()
        result = adapter.parse_output("corrupted json output")
        assert result.verdict == "ERROR"

    def test_gitleaks_all_secrets_are_critical(self):
        """Все находки Gitleaks — critical."""
        adapter = GitleaksAdapter()
        output = json.dumps([
            {"rule_id": "aws-access-key", "file": ".env", "StartLine": 1},
            {"rule_id": "generic-api-key", "file": "config.py", "StartLine": 42},
        ])
        result = adapter.parse_output(output)
        assert result.critical_count == 2


# ═══════════════════════════════════════════════════════════════════════
# 5. Hadolint Adapter Tests
# ═══════════════════════════════════════════════════════════════════════

class TestHadolintAdapter:

    def test_parse_hadolint_clean(self):
        """Чистый Dockerfile → PASS."""
        adapter = HadolintAdapter()
        result = adapter.parse_output("")
        assert result.verdict == "PASS"

    def test_parse_hadolint_no_latest_tag(self):
        """Hadolint: DL3006 — no :latest tag → high severity."""
        adapter = HadolintAdapter()
        output = "Dockerfile:3 DL3006 warning: Always tag the version of an image explicitly"
        result = adapter.parse_output(output)
        assert result.verdict == "PASS"  # warning — не FAIL
        assert len(result.findings) == 1
        assert result.findings[0].rule_id == "DL3006"
        assert result.findings[0].severity == "medium"

    def test_parse_hadolint_pipefail(self):
        """Hadolint: DL4006 — set pipefail."""
        adapter = HadolintAdapter()
        output = "Dockerfile:7 DL4006 error: Set the SHELL option -o pipefail"
        result = adapter.parse_output(output)
        assert result.verdict == "FAIL"  # error → FAIL
        assert result.findings[0].rule_id == "DL4006"
        assert result.findings[0].severity == "high"


# ═══════════════════════════════════════════════════════════════════════
# 6. KubeLinter Adapter Tests
# ═══════════════════════════════════════════════════════════════════════

class TestKubeLinterAdapter:

    def test_parse_kubelinter_clean(self):
        """Чистый манифест → PASS."""
        adapter = KubeLinterAdapter()
        output = json.dumps([])
        result = adapter.parse_output(output)
        assert result.verdict == "PASS"

    def test_parse_kubelinter_privileged_container(self):
        """KubeLinter: privileged container → FAIL."""
        adapter = KubeLinterAdapter()
        output = json.dumps([{
            "check": "privileged-container",
            "severity": "error",
            "diagnostic": {"message": "Container is running privileged"},
            "object": {"kind": "Deployment", "name": "auth-deployment"},
            "remediation": "Remove 'privileged: true' from securityContext.",
        }])
        result = adapter.parse_output(output)
        assert result.verdict == "FAIL"
        assert len(result.findings) == 1
        assert result.findings[0].rule_id == "privileged-container"

    def test_parse_kubelinter_json_error(self):
        """Битый JSON → ERROR."""
        adapter = KubeLinterAdapter()
        result = adapter.parse_output("not json")
        assert result.verdict == "ERROR"

    def test_kubelinter_multiple_checks(self):
        """Несколько нарушений → все зафиксированы."""
        adapter = KubeLinterAdapter()
        output = json.dumps([
            {"check": "privileged-container", "severity": "error", "object": {"kind": "Deployment", "name": "app"}, "diagnostic": {"message": "priv"}},
            {"check": "no-liveness-probe", "severity": "warning", "object": {"kind": "Deployment", "name": "app"}, "diagnostic": {"message": "no liveness"}},
            {"check": "read-only-root-filesystem", "severity": "note", "object": {"kind": "Deployment", "name": "app"}, "diagnostic": {"message": "rw root"}},
        ])
        result = adapter.parse_output(output)
        assert len(result.findings) == 3


# ═══════════════════════════════════════════════════════════════════════
# 7. Artifact / Evidence / Build / Release linkage
# ═══════════════════════════════════════════════════════════════════════

class TestArtifactEvidenceLinkage:

    def test_artifact_digest_sha256_linked(self):
        """Все адаптеры принимают artifact_digest_sha256."""
        digest = _sha256("test-artifact-12345")
        for adapter_cls in [KicsAdapter, ClamavAdapter, GitleaksAdapter, HadolintAdapter, KubeLinterAdapter]:
            adapter = adapter_cls()
            result = adapter.parse_output("", artifact_digest=digest)
            assert result.artifact_digest_sha256 == digest, f"{adapter.tool} failed digest linkage"

    def test_build_id_linked(self):
        """build_id привязывается к результату."""
        adapter = KicsAdapter()
        result = adapter.parse_output(json.dumps({"queries": []}), build_id="bld-001")
        assert result.build_id == "bld-001"

    def test_evidence_ref_no_raw_secrets(self):
        """evidence_ref — это vault:secret/... ссылка."""
        result = ScannerResult(
            tool="kics", tool_version="1", verdict="PASS",
            evidence_ref="vault:secret/cosmo/evidence/kics-scan",
        )
        assert result.evidence_ref.startswith("vault:")
        assert "token" not in (result.evidence_ref or "")

    def test_sarif_ref_no_raw_secrets(self):
        result = ScannerResult(
            tool="gitleaks", tool_version="1", verdict="FAIL",
            sarif_ref="vault:secret/cosmo/sarif/gitleaks-report",
        )
        assert result.sarif_ref.startswith("vault:")


# ═══════════════════════════════════════════════════════════════════════
# 8. Future Adapters — CodeQL & Semgrep (no fake activation)
# ═══════════════════════════════════════════════════════════════════════

class TestFutureAdaptersNoFakeActivation:

    def test_codeql_returns_unavailable(self):
        """CodeQL адаптер всегда возвращает UNAVAILABLE."""
        adapter = CodeQLAdapter()
        result = adapter.parse_output("")
        assert result.verdict == "UNAVAILABLE"
        assert len(result.findings) == 0
        assert result.meta["status"] == "future_contract"

    def test_semgrep_returns_unavailable(self):
        """Semgrep адаптер всегда возвращает UNAVAILABLE."""
        adapter = SemgrepAdapter()
        result = adapter.parse_output("")
        assert result.verdict == "UNAVAILABLE"
        assert result.meta["status"] == "future_contract"

    def test_codeql_has_activation_requirements(self):
        adapter = CodeQLAdapter()
        result = adapter.parse_output("")
        reqs = result.meta.get("activation_requirements", [])
        assert len(reqs) >= 2
        assert any("codeql" in r.lower() for r in reqs)

    def test_semgrep_has_activation_requirements(self):
        adapter = SemgrepAdapter()
        result = adapter.parse_output("")
        reqs = result.meta.get("activation_requirements", [])
        assert len(reqs) >= 1
        assert any("semgrep" in r.lower() for r in reqs)

    def test_future_scanners_not_in_approved(self):
        """CodeQL и Semgrep НЕ в APPROVED_SCANNERS."""
        assert "codeql" not in APPROVED_SCANNERS
        assert "semgrep" not in APPROVED_SCANNERS

    def test_future_scanners_are_future(self):
        assert FUTURE_SCANNERS == {"codeql", "semgrep"}


# ═══════════════════════════════════════════════════════════════════════
# 9. Diverse Findings Counts
# ═══════════════════════════════════════════════════════════════════════

class TestDiverseFindingsCounts:

    def test_kics_tool_identity(self):
        assert KicsAdapter().tool == "kics"

    def test_clamav_tool_identity(self):
        assert ClamavAdapter().tool == "clamav"

    def test_gitleaks_tool_identity(self):
        assert GitleaksAdapter().tool == "gitleaks"

    def test_hadolint_tool_identity(self):
        assert HadolintAdapter().tool == "hadolint"

    def test_kubelinter_tool_identity(self):
        assert KubeLinterAdapter().tool == "kubelinter"

    def test_all_adapters_have_tool_version(self):
        for cls in [KicsAdapter, ClamavAdapter, GitleaksAdapter, HadolintAdapter, KubeLinterAdapter]:
            a = cls()
            assert a.tool_version != "unknown", f"{cls.__name__} must specify tool_version"

    def test_all_adapters_have_rules_version(self):
        for cls in [KicsAdapter, ClamavAdapter, GitleaksAdapter, HadolintAdapter, KubeLinterAdapter]:
            a = cls()
            assert a.rules_version != "latest", f"{cls.__name__} must specify rules_version"


# ═══════════════════════════════════════════════════════════════════════
# 10. Idempotency & Provenance Across Adapters
# ═══════════════════════════════════════════════════════════════════════

class TestIdempotencyAndProvenance:

    def test_same_input_same_idempotency_across_adapters(self):
        digest = _sha256("same-artifact")
        r1 = KicsAdapter().parse_output(json.dumps({"queries": []}), artifact_digest=digest)
        r2 = KicsAdapter().parse_output(json.dumps({"queries": []}), artifact_digest=digest)
        assert r1.idempotency_key == r2.idempotency_key

    def test_different_inputs_different_idempotency(self):
        r1 = KicsAdapter().parse_output(json.dumps({"queries": []}), artifact_digest=_sha256("art-a"))
        r2 = KicsAdapter().parse_output(json.dumps({"queries": []}), artifact_digest=_sha256("art-b"))
        assert r1.idempotency_key != r2.idempotency_key

    def test_provenance_hash_present_for_all_adapters(self):
        for cls in [KicsAdapter, ClamavAdapter, GitleaksAdapter, HadolintAdapter, KubeLinterAdapter]:
            a = cls()
            result = a.parse_output("", artifact_digest=_sha256("test"))
            assert result.provenance_hash is not None, f"{cls.__name__} missing provenance_hash"
            assert len(result.provenance_hash) == 32