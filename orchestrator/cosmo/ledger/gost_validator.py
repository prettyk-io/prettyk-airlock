"""
COS-087: GOST Profile Validator — соответствие нормативным требованиям ЦБ РФ.

Три профиля:
  1. ГОСТ Р 56939-2016 «Безопасная разработка ПО»
     — обязательны SAST + DAST этапы
     — отсутствие критических уязвимостей в периметре
  2. ГОСТ Р 71207-2024 «Статический анализ»
     — полнота разметки CWE (>70% находок должны иметь CWE)
     — категоризация дефектов (все severity-уровни покрыты)
  3. Положения 683-П, 757-П
     — уязвимости с CVSS >= 7.0 автоматически блокируют допуск
     — максимальное допустимое количество High+Critical

ComplianceReport: структурированное заключение с вердиктом PASS/FAIL/CONDITIONAL.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List

from orchestrator.cosmo.ledger.findings_correlation import NormalizedFinding


class ComplianceVerdict(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    CONDITIONAL = "CONDITIONAL"


class GostProfile(str, Enum):
    GOST_56939 = "gost_56939_2016"
    GOST_71207 = "gost_71207_2024"
    CB_683_757 = "cb_683p_757p"


@dataclass
class ComplianceRule:
    """Одно правило проверки соответствия."""
    rule_id: str
    description: str
    passed: bool
    detail: str = ""
    profile: GostProfile | None = None


@dataclass
class ComplianceReport:
    """Структурированное заключение о соответствии ГОСТ."""
    profile: GostProfile
    verdict: ComplianceVerdict
    rules: List[ComplianceRule] = field(default_factory=list)
    total_rules: int = 0
    passed_rules: int = 0
    failed_rules: int = 0
    conditional_rules: int = 0
    detail: str = ""

    @property
    def pass_ratio(self) -> float:
        return self.passed_rules / self.total_rules if self.total_rules > 0 else 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "profile": self.profile.value,
            "verdict": self.verdict.value,
            "rules": [
                {
                    "rule_id": r.rule_id,
                    "description": r.description,
                    "passed": r.passed,
                    "detail": r.detail,
                }
                for r in self.rules
            ],
            "summary": {
                "total": self.total_rules,
                "passed": self.passed_rules,
                "failed": self.failed_rules,
                "conditional": self.conditional_rules,
                "pass_ratio": f"{self.pass_ratio:.0%}",
            },
            "detail": self.detail,
        }


# =============================================================================
# GostProfileValidator
# =============================================================================

class GostProfileValidator:
    """COS-087: валидатор соответствия нормативным требованиям.

    Принимает список NormalizedFinding + метаданные прогона (batches)
    и проверяет соответствие трём профилям.
    """

    _CVSS_THRESHOLD = 7.0
    _MAX_HIGH_CRITICAL_683P = 3

    # ── Validate all profiles ──────────────────────────────────────────

    def validate_all(
        self,
        findings: List[NormalizedFinding],
        batches: List[Dict[str, Any]] | None = None,
        cvss_scores: Dict[str, float] | None = None,
    ) -> List[ComplianceReport]:
        """Выполнить проверку по всем трём профилям.

        Args:
            findings: нормализованные находки из FindingsCorrelator
            batches: список batch'ей (type → ID) — для проверки SAST/DAST
            cvss_scores: finding_id → CVSS score для 683-П/757-П

        Returns:
            Список из трёх ComplianceReport (один на профиль)
        """
        batches = batches or []
        cvss_scores = cvss_scores or {}

        return [
            self.validate_gost_56939(findings, batches),
            self.validate_gost_71207(findings),
            self.validate_cb_683_757(findings, cvss_scores),
        ]

    # ── ГОСТ Р 56939-2016 ────────────────────────────────────────────

    def validate_gost_56939(
        self, findings: List[NormalizedFinding], batches: List[Dict[str, Any]]
    ) -> ComplianceReport:
        """ГОСТ Р 56939-2016: Безопасная разработка ПО.

        Требования:
          G39-1: Наличие SAST-этапа (batch type = 'static_scan')
          G39-2: Наличие DAST-этапа (batch type = 'dynamic_test')
          G39-3: Отсутствие critical находок в SAST (source='sast', severity='critical')
          G39-4: Отсутствие critical находок в DAST (source='dast', severity='critical')
          G39-5: Все critical находки имеют CWE-разметку
        """
        rules: List[ComplianceRule] = []
        batch_types = {b.get("type", "") for b in batches}

        # G39-1: SAST этап
        has_sast = "static_scan" in batch_types or "sast" in batch_types
        rules.append(ComplianceRule(
            rule_id="G39-1",
            description="Наличие SAST-этапа (static_scan)",
            passed=has_sast,
            detail="SAST этап присутствует" if has_sast else "SAST этап отсутствует — требуется для ГОСТ 56939",
            profile=GostProfile.GOST_56939,
        ))

        # G39-2: DAST этап
        has_dast = "dynamic_test" in batch_types or "dast" in batch_types
        rules.append(ComplianceRule(
            rule_id="G39-2",
            description="Наличие DAST-этапа (dynamic_test)",
            passed=has_dast,
            detail="DAST этап присутствует" if has_dast else "DAST этап отсутствует — требуется для ГОСТ 56939",
            profile=GostProfile.GOST_56939,
        ))

        # G39-3: Нет critical SAST находок
        sast_critical = [
            f for f in findings
            if f.source == "sast" and f.severity == "critical"
        ]
        no_sast_crit = len(sast_critical) == 0
        rules.append(ComplianceRule(
            rule_id="G39-3",
            description="Отсутствие критических находок SAST",
            passed=no_sast_crit,
            detail=(
                "0 critical SAST находок" if no_sast_crit
                else f"{len(sast_critical)} critical SAST находок: "
                     + ", ".join(f.title[:50] for f in sast_critical[:3])
            ),
            profile=GostProfile.GOST_56939,
        ))

        # G39-4: Нет critical DAST/периметр находок
        dast_critical = [
            f for f in findings
            if f.source in ("dast", "fuzzer") and f.severity == "critical"
        ]
        no_dast_crit = len(dast_critical) == 0
        rules.append(ComplianceRule(
            rule_id="G39-4",
            description="Отсутствие критических уязвимостей в периметре (DAST+Fuzzer)",
            passed=no_dast_crit,
            detail=(
                "0 critical DAST/периметр находок" if no_dast_crit
                else f"{len(dast_critical)} critical в периметре: "
                     + ", ".join(f.title[:50] for f in dast_critical[:3])
            ),
            profile=GostProfile.GOST_56939,
        ))

        # G39-5: CWE-разметка critical находок
        all_critical = [f for f in findings if f.severity == "critical"]
        if all_critical:
            cwe_missed = [f for f in all_critical if not f.cwe or f.cwe == "CWE-200"]
            all_tagged = len(cwe_missed) == 0
            rules.append(ComplianceRule(
                rule_id="G39-5",
                description="Все critical находки имеют CWE-разметку (не CWE-200)",
                passed=all_tagged,
                detail=(
                    f"Все {len(all_critical)} critical размечены" if all_tagged
                    else f"{len(cwe_missed)} critical без CWE: "
                         + ", ".join(f.title[:40] for f in cwe_missed[:3])
                ),
                profile=GostProfile.GOST_56939,
            ))
        else:
            rules.append(ComplianceRule(
                rule_id="G39-5", description="Все critical находки имеют CWE-разметку",
                passed=True, detail="Нет critical находок — правило не применимо",
                profile=GostProfile.GOST_56939,
            ))

        passed = sum(1 for r in rules if r.passed)
        all_pass = passed == len(rules)

        return ComplianceReport(
            profile=GostProfile.GOST_56939,
            verdict=ComplianceVerdict.PASS if all_pass else ComplianceVerdict.FAIL,
            rules=rules,
            total_rules=len(rules),
            passed_rules=passed,
            failed_rules=len(rules) - passed,
            detail=(
                "Соответствует ГОСТ Р 56939-2016" if all_pass
                else f"Не соответствует: {len(rules)-passed}/{len(rules)} правил не пройдены"
            ),
        )

    # ─ ГОСТ Р 71207-2024 ────────────────────────────────────────────────

    def validate_gost_71207(
        self, findings: List[NormalizedFinding]
    ) -> ComplianceReport:
        """ГОСТ Р 71207-2024: Статический анализ.

        Требования:
          G12-1: Доля находок с CWE-разметкой >= 70%
          G12-2: Все severity-уровни покрыты (critical/high/medium/low)
          G12-3: Отсутствие дубликатов (composite_key совпадает <= 1 раз)
          G12-4: Каждая находка имеет описание (description не пусто)
        """
        rules: List[ComplianceRule] = []

        # G12-1: CWE coverage
        total = len(findings)
        if total > 0:
            with_cwe = sum(1 for f in findings if f.cwe and f.cwe != "CWE-200")
            cwe_ratio = with_cwe / total
            cwe_ok = cwe_ratio >= 0.70
            rules.append(ComplianceRule(
                rule_id="G12-1",
                description=f"Доля находок с CWE-разметкой >= 70% (текущая: {cwe_ratio:.0%})",
                passed=cwe_ok,
                detail=f"{with_cwe}/{total} находок имеют CWE ({cwe_ratio:.0%})",
                profile=GostProfile.GOST_71207,
            ))
        else:
            rules.append(ComplianceRule(
                rule_id="G12-1", description="Доля находок с CWE >= 70%",
                passed=True, detail="Нет находок — правило не применимо",
                profile=GostProfile.GOST_71207,
            ))

        # G12-2: Severity coverage
        sev_found = {f.severity for f in findings}
        required = {"critical", "high", "medium", "low"}
        coverage_ok = required.issubset(sev_found) if total > 0 else False
        rules.append(ComplianceRule(
            rule_id="G12-2",
            description="Все severity-уровни покрыты (critical/high/medium/low)",
            passed=coverage_ok or total == 0,
            detail=f"Найдены: {sorted(sev_found)}" if total > 0 else "Нет находок",
            profile=GostProfile.GOST_71207,
        ))

        # G12-3: Deduplication check
        keys = [f.composite_key() for f in findings]
        dup_count = len(keys) - len(set(keys))
        no_dups = dup_count == 0
        rules.append(ComplianceRule(
            rule_id="G12-3",
            description="Отсутствие дубликатов находок (composite_key уникален)",
            passed=no_dups,
            detail=f"0 дубликатов" if no_dups else f"{dup_count} дубликатов найдено",
            profile=GostProfile.GOST_71207,
        ))

        # G12-4: Description coverage
        if total > 0:
            with_desc = sum(1 for f in findings if f.description and len(f.description) > 10)
            desc_ratio = with_desc / total
            desc_ok = desc_ratio >= 0.80
            rules.append(ComplianceRule(
                rule_id="G12-4",
                description=f"Доля находок с описанием >= 80% (текущая: {desc_ratio:.0%})",
                passed=desc_ok,
                detail=f"{with_desc}/{total} находок с описанием ({desc_ratio:.0%})",
                profile=GostProfile.GOST_71207,
            ))
        else:
            rules.append(ComplianceRule(
                rule_id="G12-4", description="Доля находок с описанием >= 80%",
                passed=True, detail="Нет находок",
                profile=GostProfile.GOST_71207,
            ))

        passed = sum(1 for r in rules if r.passed)
        all_pass = passed == len(rules)

        return ComplianceReport(
            profile=GostProfile.GOST_71207,
            verdict=ComplianceVerdict.PASS if all_pass else ComplianceVerdict.FAIL,
            rules=rules,
            total_rules=len(rules),
            passed_rules=passed,
            failed_rules=len(rules) - passed,
            detail=(
                "Соответствует ГОСТ Р 71207-2024" if all_pass
                else f"Не соответствует: {len(rules)-passed}/{len(rules)} правил не пройдены"
            ),
        )

    # ─ Положения 683-П / 757-П ────────────────────────────────────

    def validate_cb_683_757(
        self,
        findings: List[NormalizedFinding],
        cvss_scores: Dict[str, float],
    ) -> ComplianceReport:
        """Положения 683-П / 757-П ЦБ РФ.

        Требования:
          CB-1: Ни одной находки с CVSS >= 7.0 (автоматический блок)
          CB-2: Количество High+Critical <= 3 (допустимый порог)
          CB-3: Все находки с CVSS >= 4.0 имеют рекомендации по устранению
          CB-4: Отсутствие находок типа 'command-injection' с severity=critical
        """
        rules: List[ComplianceRule] = []

        # CB-1: CVSS threshold
        high_cvss = {
            f.composite_key(): score
            for f in findings
            for k, score in cvss_scores.items()
            if score >= self._CVSS_THRESHOLD and k in (f.composite_key(), f.title)
        }

        if high_cvss:
            detail_parts = [
                f"{cid[:12]}: CVSS {score}"
                for cid, score in list(high_cvss.items())[:3]
            ]
            rules.append(ComplianceRule(
                rule_id="CB-1",
                description=f"Ни одной находки с CVSS >= {self._CVSS_THRESHOLD}",
                passed=False,
                detail=f"Найдены: " + "; ".join(detail_parts) + (
                    f" ... ещё {len(high_cvss)-3}" if len(high_cvss) > 3 else ""
                ),
                profile=GostProfile.CB_683_757,
            ))
        else:
            rules.append(ComplianceRule(
                rule_id="CB-1",
                description=f"Ни одной находки с CVSS >= {self._CVSS_THRESHOLD}",
                passed=True,
                detail="Все находки ниже порога CVSS 7.0",
                profile=GostProfile.CB_683_757,
            ))

        # CB-2: High+Critical count
        hi_crit = [
            f for f in findings
            if f.severity in ("critical", "high")
        ]
        hi_crit_ok = len(hi_crit) <= self._MAX_HIGH_CRITICAL_683P
        rules.append(ComplianceRule(
            rule_id="CB-2",
            description=f"High+Critical <= {self._MAX_HIGH_CRITICAL_683P} (текущее: {len(hi_crit)})",
            passed=hi_crit_ok,
            detail=(
                f"{len(hi_crit)} High+Critical находок" if hi_crit_ok
                else f"{len(hi_crit)} High+Critical — превышен порог {self._MAX_HIGH_CRITICAL_683P}"
            ),
            profile=GostProfile.CB_683_757,
        ))

        # CB-3: Recommendations for CVSS >= 4.0
        if cvss_scores:
            medium_plus = [
                f for f in findings
                for k, score in cvss_scores.items()
                if score >= 4.0 and k in (f.composite_key(), f.title)
                and f.severity in ("critical", "high", "medium")
            ]
            missing_rec = [f for f in medium_plus if len(f.description) < 30]
            recs_ok = len(missing_rec) == 0
        else:
            recs_ok = True  # нет CVSS данных → skip
            missing_rec = []

        rules.append(ComplianceRule(
            rule_id="CB-3",
            description="Находки с CVSS >= 4.0 имеют рекомендации (описание >30 сим.)",
            passed=recs_ok,
            detail=(
                "Все находки с описанием" if recs_ok
                else f"{len(missing_rec)} находок без достаточного описания"
            ),
            profile=GostProfile.CB_683_757,
        ))

        # CB-4: Command injection critical
        cmd_crit = [
            f for f in findings
            if "injection" in f.title.lower() and f.severity == "critical"
        ]
        cmd_ok = len(cmd_crit) == 0
        rules.append(ComplianceRule(
            rule_id="CB-4",
            description="Отсутствие critical command-injection находок",
            passed=cmd_ok,
            detail=(
                "0 command-injection critical" if cmd_ok
                else f"{len(cmd_crit)} command-injection: "
                     + ", ".join(f.title[:40] for f in cmd_crit[:2])
            ),
            profile=GostProfile.CB_683_757,
        ))

        passed = sum(1 for r in rules if r.passed)
        all_pass = passed == len(rules)

        return ComplianceReport(
            profile=GostProfile.CB_683_757,
            verdict=ComplianceVerdict.PASS if all_pass else ComplianceVerdict.FAIL,
            rules=rules,
            total_rules=len(rules),
            passed_rules=passed,
            failed_rules=len(rules) - passed,
            detail=(
                "Соответствует 683-П / 757-П" if all_pass
                else f"Не соответствует: {len(rules)-passed}/{len(rules)} правил не пройдены"
            ),
        )


# �──────────────────────────────────────────────────────────
# GostAssembler (integration)
# �──────────────────────────────────────────────────────────

class GostAssembler:
    """COS-087: ассемблирование ГОСТ-Акта с секцией соответствия."""

    def assemble_compliance_section(
        self, reports: List[ComplianceReport]
    ) -> str:
        """Сформировать текстовую секцию «Соответствие нормативным требованиям»
        для включения в ГОСТ-Акт."""
        sections: List[str] = [
            "=" * 72,
            "  СЕКЦИЯ 4. Соответствие нормативным требованиям",
            "=" * 72,
            "",
        ]

        for report in reports:
            sections.append(f"## {report.profile.value}")
            sections.append(f"  Вердикт: {report.verdict.value}")
            sections.append(f"  Пройдено: {report.passed_rules}/{report.total_rules}")
            sections.append("")

            for rule in report.rules:
                status = "\u2713" if rule.passed else "\u2717"
                sections.append(f"  [{status}] {rule.rule_id}: {rule.description}")
                if rule.detail:
                    sections.append(f"       {rule.detail}")
            sections.append("")

        sections.append(f"ИТОГО: пройдено {sum(r.passed_rules for r in reports)}/"
                        f"{sum(r.total_rules for r in reports)} правил")
        sections.append("=" * 72)

        return "\n".join(sections)

    def assemble_act_with_compliance(
        self, act: Any, reports: List[ComplianceReport]
    ) -> Any:
        """Включить секцию соответствия в ГОСТ-Акт.

        Adds compliance_section to existing GOStAct (mutable copy).

        Args:
            act: GOStAct (Pydantic)
            reports: список ComlianceReport от GOStProfileValidator

        Returns:
            ГОСТ-Акт с заполненной секцией соответствия (dict)
        """
        act_dict = act.model_dump() if hasattr(act, 'model_dump') else dict(act)
        section_text = self.assemble_compliance_section(reports)
        act_dict["compliance_section"] = section_text
        act_dict["compliance_verdict"] = (
            "PASS" if all(r.verdict == ComplianceVerdict.PASS for r in reports)
            else "FAIL"
        )
        act_dict["compliance_summary"] = {
            "profiles": [
                {
                    "id": r.profile.value,
                    "verdict": r.verdict.value,
                    "passed": r.passed_rules,
                    "total": r.total_rules,
                }
                for r in reports
            ],
            "overall": (
                "PASS" if all(r.verdict == ComplianceVerdict.PASS for r in reports)
                else "FAIL"
            ),
        }
        return act_dict