"""COS-087: GOST Compliance tests — three profiles + assembler."""
import pytest
from cosmo.ledger.findings_correlation import NormalizedFinding
from cosmo.ledger.gost_validator import (
    GostProfileValidator, GostAssembler,
    ComplianceVerdict, ComplianceReport, ComplianceRule, GostProfile,
)
from cosmo.ledger.gost_act import (
    GOSTAct, GOSTActHeader, GOSTActObject, GOSTFinding,
)


def _f(title="SQLi", severity="high", source="sast", cwe="CWE-89",
       file_path="src/auth.py", description="Detailed finding description here"):
    return NormalizedFinding(title=title, severity=severity, source=source,
                             cwe=cwe, file_path=file_path, description=description)

def _b(btype="static_scan"):
    return {"type": btype}


# =============================================================================
# Models
# =============================================================================

class TestModels:
    def test_verdict_enum(self):
        assert ComplianceVerdict.PASS.value == "PASS"
        assert ComplianceVerdict.FAIL.value == "FAIL"

    def test_report_to_dict(self):
        rpt = ComplianceReport(profile=GostProfile.GOST_56939,
                               verdict=ComplianceVerdict.PASS,
                               rules=[ComplianceRule(rule_id="G39-1", description="Has SAST", passed=True)],
                               total_rules=1, passed_rules=1)
        d = rpt.to_dict()
        assert d["verdict"] == "PASS"
        assert d["summary"]["pass_ratio"] == "100%"


# =============================================================================
# GOST 56939
# =============================================================================

class TestGost56939:
    def test_pass(self):
        fss = [_f(), _f(title="XSS", cwe="CWE-79", source="dast")]
        bss = [_b("static_scan"), _b("dynamic_test")]
        r = GostProfileValidator().validate_gost_56939(fss, bss)
        assert r.verdict == ComplianceVerdict.PASS
        assert r.passed_rules == r.total_rules

    def test_fail_no_sast(self):
        r = GostProfileValidator().validate_gost_56939([_f()], [_b("dynamic_test")])
        assert r.verdict == ComplianceVerdict.FAIL
        assert any(rr.rule_id == "G39-1" and not rr.passed for rr in r.rules)

    def test_fail_no_dast(self):
        r = GostProfileValidator().validate_gost_56939([_f()], [_b("static_scan")])
        assert r.verdict == ComplianceVerdict.FAIL
        assert any(rr.rule_id == "G39-2" and not rr.passed for rr in r.rules)

    def test_fail_critical_sast(self):
        fss = [_f(severity="critical"), _f()]
        bss = [_b("static_scan"), _b("dynamic_test")]
        r = GostProfileValidator().validate_gost_56939(fss, bss)
        assert r.verdict == ComplianceVerdict.FAIL
        assert any(rr.rule_id == "G39-3" and not rr.passed for rr in r.rules)

    def test_fail_critical_dast(self):
        fss = [_f(severity="critical", source="dast", file_path="/api")]
        bss = [_b("static_scan"), _b("dynamic_test")]
        r = GostProfileValidator().validate_gost_56939(fss, bss)
        assert r.verdict == ComplianceVerdict.FAIL
        assert any(rr.rule_id == "G39-4" and not rr.passed for rr in r.rules)

    def test_cwe_missing_critical(self):
        fss = [_f(severity="critical", cwe=""), _f(severity="critical", cwe="CWE-200")]
        bss = [_b("static_scan"), _b("dynamic_test")]
        r = GostProfileValidator().validate_gost_56939(fss, bss)
        assert any(rr.rule_id == "G39-5" and not rr.passed for rr in r.rules)


# =============================================================================
# GOST 71207
# =============================================================================

class TestGost71207:
    def test_pass(self):
        fss = [_f(severity="critical", cwe="CWE-89", file_path="a.py"),
               _f(severity="high", cwe="CWE-79", file_path="b.py"),
               _f(severity="medium", cwe="CWE-22", file_path="c.py"),
               _f(severity="low", cwe="CWE-200", file_path="d.py")]
        r = GostProfileValidator().validate_gost_71207(fss)
        assert r.verdict == ComplianceVerdict.PASS

    def test_fail_low_cwe(self):
        fss = [_f(cwe="CWE-89"), _f(cwe="", file_path="b.py"), _f(cwe="", file_path="c.py")]
        r = GostProfileValidator().validate_gost_71207(fss)
        assert any(rr.rule_id == "G12-1" and not rr.passed for rr in r.rules)

    def test_sev_coverage(self):
        fss = [_f(severity="critical", file_path="a.py"),
               _f(severity="high", file_path="b.py"),
               _f(severity="medium", file_path="c.py"),
               _f(severity="low", file_path="d.py")]
        r = GostProfileValidator().validate_gost_71207(fss)
        assert any(rr.rule_id == "G12-2" and rr.passed for rr in r.rules)

    def test_dup_fail(self):
        fss = [_f(), _f()]  # same title+cwe+path
        r = GostProfileValidator().validate_gost_71207(fss)
        assert any(rr.rule_id == "G12-3" and not rr.passed for rr in r.rules)

    def test_empty_pass(self):
        r = GostProfileValidator().validate_gost_71207([])
        assert r.verdict == ComplianceVerdict.PASS


# =============================================================================
# 683-P / 757-P
# =============================================================================

class TestCB683_757:
    def test_pass(self):
        r = GostProfileValidator().validate_cb_683_757([_f()], {})
        assert r.verdict == ComplianceVerdict.PASS

    def test_fail_cvss(self):
        r = GostProfileValidator().validate_cb_683_757(
            [_f()],
            {_f().composite_key(): 8.5},
        )
        assert any(rr.rule_id == "CB-1" and not rr.passed for rr in r.rules)

    def test_fail_hi_crit_count(self):
        fss = [_f(severity="high", file_path=f"{i}.py") for i in range(5)]
        r = GostProfileValidator().validate_cb_683_757(fss, {})
        assert any(rr.rule_id == "CB-2" and not rr.passed for rr in r.rules)

    def test_cmd_inj_blocked(self):
        fss = [_f(title="Command injection", severity="critical")]
        r = GostProfileValidator().validate_cb_683_757(fss, {})
        assert any(rr.rule_id == "CB-4" and not rr.passed for rr in r.rules)


# =============================================================================
# Validate all
# =============================================================================

class TestValidateAll:
    def test_three_reports(self):
        reports = GostProfileValidator().validate_all([])
        assert len(reports) == 3

    def test_all_pass(self):
        fss = [_f(severity="critical", cwe="CWE-89", file_path="a.py", source="sca"),
               _f(severity="high", cwe="CWE-79", file_path="b.py"),
               _f(severity="medium", cwe="CWE-22", file_path="c.py"),
               _f(severity="low", cwe="CWE-200", file_path="d.py")]
        bss = [_b("static_scan"), _b("dynamic_test")]
        reports = GostProfileValidator().validate_all(fss, bss, {})
        assert all(r.verdict == ComplianceVerdict.PASS for r in reports)


# =============================================================================
# GostAssembler
# =============================================================================

class TestAssembler:
    def test_section_text(self):
        reports = GostProfileValidator().validate_all(
            [_f()], [_b("static_scan"), _b("dynamic_test")],
        )
        txt = GostAssembler().assemble_compliance_section(reports)
        assert "СЕКЦИЯ 4" in txt
        assert "gost_56939" in txt

    def test_assemble_act(self):
        act = GOSTAct(
            header=GOSTActHeader(project_name="Test"),
            object=GOSTActObject(name="App"),
            findings_table=[GOSTFinding(severity="High", title="SQLi", cwe="CWE-89")],
        )
        fss = [_f(severity="critical", cwe="CWE-89", file_path="a.py", source="sca"),
               _f(severity="high", cwe="CWE-79", file_path="b.py"),
               _f(severity="medium", cwe="CWE-22", file_path="c.py"),
               _f(severity="low", cwe="CWE-200", file_path="d.py")]
        reports = GostProfileValidator().validate_all(
            fss, [_b("static_scan"), _b("dynamic_test")],
        )
        d = GostAssembler().assemble_act_with_compliance(act, reports)
        assert d["compliance_verdict"] == "PASS"
        assert len(d["compliance_summary"]["profiles"]) == 3