"""
COS-211: CBR Provision 834-P / 701-P Compliance & Audit Validator.

Реализует:
  1. Валидацию Положения Банка России № 834-П (Защита информации в платежных системах):
     - Контроль целостности платежных распоряжений (ГОСТ Р 34.10-2012)
     - Обязательное применение MFA для администраторов и операторов
     - Неизменяемость журналов регистрации операций (Audit Hash Chain)
  2. Валидацию Положения Банка России № 701-П (Бесперебойность платежных систем):
     - Требования к целевому времени восстановления (RTO <= 2 часов)
     - Наличие катастрофоустойчивого резервирования (DR/Multi-Region)
     - Мониторинг аномалий и метрик доступности SLA >= 99.99%
"""
from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

try:
    from cosmo.ledger.gost_validator import ComplianceReport, ComplianceRule, ComplianceVerdict, GostProfile
except ImportError:
    from orchestrator.cosmo.ledger.gost_validator import ComplianceReport, ComplianceRule, ComplianceVerdict, GostProfile  # type: ignore


class CBRProvisionValidator:
    """COS-211: Валидатор нормативных положений ЦБ РФ 834-П и 701-П."""

    @classmethod
    def validate_834_p(
        cls,
        domain_id: str,
        has_gost_signing: bool = True,
        mfa_enforced: bool = True,
        audit_chain_verified: bool = True,
        open_critical_findings: int = 0,
    ) -> ComplianceReport:
        """Положение Банка России № 834-П (Безопасность платежей)."""
        rules: List[ComplianceRule] = []

        # 834-1: Контроль целостности и ГОСТ подпись
        rules.append(ComplianceRule(
            rule_id="834-P-01",
            description="Применение квалифицированной ГОСТ ЭЦП для контроля целостности платежных сообщений",
            passed=has_gost_signing,
            detail="ГОСТ Р 34.10-2012 / 34.11-2012 активен" if has_gost_signing else "Отсутствует ГОСТ-подписание",
        ))

        # 834-2: MFA для критических ролей
        rules.append(ComplianceRule(
            rule_id="834-P-02",
            description="Обязательная двухфакторная аутентификация (MFA) для привилегированных субъектов",
            passed=mfa_enforced,
            detail="MFA принудительно включен" if mfa_enforced else "MFA не настроен для администраторов",
        ))

        # 834-3: Неизменяемость журналов аудита
        rules.append(ComplianceRule(
            rule_id="834-P-03",
            description="Неизменяемость и криптографическая целостность журналов аудита (Audit Trail)",
            passed=audit_chain_verified,
            detail="Криптографическая цепочка аудита подтверждена" if audit_chain_verified else "Нарушена целостность журнала аудита",
        ))

        # 834-4: Отсутствие критических уязвимостей
        no_crit = (open_critical_findings == 0)
        rules.append(ComplianceRule(
            rule_id="834-P-04",
            description="Отсутствие неустраненных критических уязвимостей в контуре платежной системы",
            passed=no_crit,
            detail="0 критических уязвимостей" if no_crit else f"{open_critical_findings} критических уязвимостей",
        ))

        passed_count = sum(1 for r in rules if r.passed)
        verdict = ComplianceVerdict.PASS if passed_count == len(rules) else ComplianceVerdict.FAIL

        return ComplianceReport(
            profile=GostProfile.CB_683_757,
            verdict=verdict,
            rules=rules,
            total_rules=len(rules),
            passed_rules=passed_count,
            failed_rules=len(rules) - passed_count,
            detail=f"Положение 834-П ЦБ РФ: {verdict.value} ({passed_count}/{len(rules)})",
        )

    @classmethod
    def validate_701_p(
        cls,
        domain_id: str,
        rto_minutes: Optional[int | float] = None,
        multi_region_enabled: bool = True,
        sla_ratio: Optional[float] = None,
        *,
        rto_hours: Optional[float] = None,
        has_disaster_recovery: Optional[bool] = None,
        sla_uptime_percent: Optional[float] = None,
        has_automated_monitoring: bool = True,
        **kwargs: Any,
    ) -> ComplianceReport:
        """Положение Банка России № 701-П (Бесперебойность платежных систем)."""
        rules: List[ComplianceRule] = []

        if rto_hours is not None:
            calc_rto_min = int(rto_hours * 60)
        elif rto_minutes is not None:
            calc_rto_min = int(rto_minutes)
        else:
            calc_rto_min = 45

        dr_enabled = has_disaster_recovery if has_disaster_recovery is not None else multi_region_enabled

        if sla_uptime_percent is not None:
            calc_sla = sla_uptime_percent / 100.0
        elif sla_ratio is not None:
            calc_sla = sla_ratio
        else:
            calc_sla = 0.9999

        # 701-1: RTO <= 120 минут
        rto_ok = calc_rto_min <= 120
        rules.append(ComplianceRule(
            rule_id="701-P-01",
            description=f"Целевое время восстановления RTO <= 120 мин (текущее: {calc_rto_min} мин)",
            passed=rto_ok,
            detail=f"RTO = {calc_rto_min} мин" if rto_ok else f"RTO {calc_rto_min} мин превышает лимит 120 мин",
        ))

        # 701-2: Катастрофоустойчивость и резервирование
        rules.append(ComplianceRule(
            rule_id="701-P-02",
            description="Наличие географически распределенного горячего резерва (Multi-Region DR)",
            passed=dr_enabled,
            detail="Резервный ЦОД подключен" if dr_enabled else "Отсутствует резервный регион",
        ))

        # 701-3: SLA доступности >= 99.99%
        sla_ok = calc_sla >= 0.9999
        rules.append(ComplianceRule(
            rule_id="701-P-03",
            description=f"Коэффициент готовности SLA >= 99.99% (текущий: {calc_sla:.4%})",
            passed=sla_ok,
            detail=f"SLA = {calc_sla:.4%}" if sla_ok else f"SLA {calc_sla:.4%} ниже нормы 99.99%",
        ))

        # 701-4: Автоматизированный мониторинг
        rules.append(ComplianceRule(
            rule_id="701-P-04",
            description="Автоматизированный непрерывный мониторинг метрик непрерывности",
            passed=has_automated_monitoring,
            detail="Мониторинг активен" if has_automated_monitoring else "Отсутствует система мониторинга",
        ))

        passed_count = sum(1 for r in rules if r.passed)
        verdict = ComplianceVerdict.PASS if passed_count == len(rules) else ComplianceVerdict.FAIL

        return ComplianceReport(
            profile=GostProfile.CB_683_757,
            verdict=verdict,
            rules=rules,
            total_rules=len(rules),
            passed_rules=passed_count,
            failed_rules=len(rules) - passed_count,
            detail=f"Положение 701-П ЦБ РФ: {verdict.value} ({passed_count}/{len(rules)})",
        )
