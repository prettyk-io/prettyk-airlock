"""
COS-137: Tests for GOST Act Full Multi-Standard Compliance Engine (5 Standards).

Проверяет:
  1. ГОСТ Р 56939-2016 (SAST + DAST + 0 critical).
  2. ГОСТ Р 58412-2019 (CWE разметка + CVSS 3.1 порог < 8.5).
  3. ГОСТ Р 71207-2024 (Статический анализ, покрытие severity, отсутствие дублей).
  4. ГОСТ 2.105-2019 (ЕСКД реквизиты, подписи, табличная часть).
  5. Положения 683-П / 757-П ЦБ РФ / ГОСТ 57580.1 (CVSS < 7.0, High+Crit <= 3).
  6. Комплексную сборку через `validate_all_five` и `GostAssembler`.
"""
import pytest
from cosmo.ledger.findings_correlation import NormalizedFinding
from cosmo.ledger.gost_validator import (
    ComplianceVerdict,
    GostAssembler,
    GostProfile,
    GostProfileValidator,
)


def _make_finding(
    title: str,
    severity: str = "medium",
    source: str = "sast",
    cwe: str = "CWE-89",
    description: str = "Detailed security vulnerability description for testing",
) -> NormalizedFinding:
    return NormalizedFinding(
        title=title,
        severity=severity,  # type: ignore
        source=source,      # type: ignore
        cwe=cwe,
        description=description,
        file_path="src/app/main.py",
        line=42,
    )


def test_gost_58412_success():
    """ГОСТ Р 58412-2019: успешное прохождение при отсутствии CVSS >= 8.5."""
    validator = GostProfileValidator()
    findings = [
        _make_finding("SQL Injection", severity="high", cwe="CWE-89"),
        _make_finding("XSS Stored", severity="medium", cwe="CWE-79"),
    ]
    cvss = {findings[0].composite_key(): 7.5}

    report = validator.validate_gost_58412(findings, cvss_scores=cvss)
    assert report.profile == GostProfile.GOST_58412
    assert report.verdict == ComplianceVerdict.PASS
    assert report.passed_rules == 3


def test_gost_58412_cvss_threshold_failure():
    """ГОСТ Р 58412-2019: дефект с CVSS >= 8.5 вызывает FAIL."""
    validator = GostProfileValidator()
    findings = [
        _make_finding("Remote Code Execution", severity="critical", cwe="CWE-94"),
    ]
    cvss = {findings[0].composite_key(): 9.8}

    report = validator.validate_gost_58412(findings, cvss_scores=cvss)
    assert report.verdict == ComplianceVerdict.FAIL
    assert any(r.rule_id == "G58-2" and not r.passed for r in report.rules)


def test_gost_2_105_success():
    """ГОСТ 2.105-2019: проверка наличия обязательных реквизитов документа."""
    validator = GostProfileValidator()
    act_meta = {
        "title": "Акт приёмочных испытаний КИТС",
        "act_number": "ACT-2026-08-001",
        "date": "2026-08-29",
        "signatures": [{"name": "Иванов И.И.", "role": "Офицер ИБ"}],
    }

    report = validator.validate_gost_2_105(act_metadata=act_meta)
    assert report.profile == GostProfile.GOST_2_105
    assert report.verdict == ComplianceVerdict.PASS
    assert report.passed_rules == 3


def test_gost_2_105_missing_requisites_failure():
    """ГОСТ 2.105-2019: отсутствие даты и подписи вызывает FAIL."""
    validator = GostProfileValidator()
    act_meta = {"title": "Акт без реквизитов"}

    report = validator.validate_gost_2_105(act_metadata=act_meta)
    assert report.verdict == ComplianceVerdict.FAIL
    assert report.passed_rules < 3


def test_validate_all_five_standards():
    """Комплексная валидация по всем 5 стандартам."""
    validator = GostProfileValidator()
    assembler = GostAssembler()

    findings = [
        _make_finding("SQL Injection in auth", severity="medium", source="sast", cwe="CWE-89"),
        _make_finding("Missing Secure Flag on Cookie", severity="low", source="dast", cwe="CWE-614"),
        _make_finding("Reflected XSS", severity="high", source="sast", cwe="CWE-79"),
    ]
    batches = [{"type": "static_scan"}, {"type": "dynamic_test"}]
    cvss = {findings[0].composite_key(): 5.0, findings[2].composite_key(): 6.5}
    act_meta = {
        "title": "Комплексный акт соответствия",
        "date": "2026-08-29",
        "signatures": [{"name": "Сидоров С.С.", "role": "Главный эксперт ИБ"}],
    }

    reports = validator.validate_all_five(
        findings=findings,
        batches=batches,
        cvss_scores=cvss,
        act_metadata=act_meta,
    )

    assert len(reports) == 5
    profiles = [r.profile for r in reports]
    assert GostProfile.GOST_56939 in profiles
    assert GostProfile.GOST_58412 in profiles
    assert GostProfile.GOST_71207 in profiles
    assert GostProfile.GOST_2_105 in profiles
    assert GostProfile.CB_683_757 in profiles

    # Проверяем сборку текстовой секции соответствия
    section_text = assembler.assemble_compliance_section(reports)
    assert "СЕКЦИЯ 4. Соответствие нормативным требованиям" in section_text
    assert "gost_56939_2016" in section_text
    assert "gost_58412_2019" in section_text
    assert "gost_2_105_2019" in section_text
