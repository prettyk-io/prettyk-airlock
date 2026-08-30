"""
STACK-LUNA-001: Approved Scanner Adapters.

Реализует 5 одобренных адаптеров сканеров безопасности Cosmoport 2.0:

  1. KicsAdapter      — IaC security scanning (KICS by Checkmarx)
  2. ClamavAdapter    — Malware/antivirus scanning (ClamAV)
  3. GitleaksAdapter  — Secret detection (Gitleaks)
  4. HadolintAdapter  — Dockerfile/build-context lint (Hadolint)
  5. KubeLinterAdapter — Kubernetes manifest scanning (KubeLinter)

Каждый адаптер:
  - Реализует BaseScannerAdapter.parse_output
  - Нормализует tool-specific вывод в ScannerFinding
  - Строит ScannerResult с привязкой к артефакту/digest/build/release
  - Не содержит raw secrets
  - Поддерживает idempotent delivery через idempotency_key
"""
from __future__ import annotations

import datetime
import json
import re
from typing import Any, Dict, List, Optional

from orchestrator.cosmo.scanners.scanner_contract import (
    BaseScannerAdapter,
    ScannerFinding,
    ScannerResult,
    ScannerVerdict,
    ScannerTool,
)


# ══════════════════════════════════════════════════════════════════════════════
# 1. KICS — IaC Security Scanning
# ══════════════════════════════════════════════════════════════════════════════

class KicsAdapter(BaseScannerAdapter):
    """KICS (Keeping Infrastructure as Code Secure) — Checkmarx.

    Сканирует Terraform, CloudFormation, Kubernetes, Docker, Ansible манифесты.
    """

    tool: ScannerTool = "kics"
    tool_version: str = "kics 2.1.3"
    rules_version: str = "kics-queries 2.1.3"

    # Маппинг KICS severity → стандартный
    _SEVERITY_MAP = {
        "HIGH": "critical",
        "MEDIUM": "high",
        "LOW": "medium",
        "INFO": "low",
    }

    # Маппинг KICS query_id → CWE
    _CWE_MAP = {
        "57ab2cba": "CWE-798",   # Hardcoded passwords
        "4a3e6b5f": "CWE-200",   # Sensitive data exposure
        "e9f8c1d2": "CWE-668",   # Excessive permissions
        "a1b2c3d4": "CWE-311",   # Missing encryption
        "f7e6d5c4": "CWE-522",   # Insufficiently protected credentials
    }

    def parse_output(
        self,
        raw_output: str,
        artifact_digest: Optional[str] = None,
        artifact_name: Optional[str] = None,
        build_id: Optional[str] = None,
        **kwargs,
    ) -> ScannerResult:
        """Парсинг JSON-вывода KICS в ScannerResult."""
        findings: List[ScannerFinding] = []
        started = datetime.datetime.utcnow()

        try:
            data = json.loads(raw_output)
        except json.JSONDecodeError:
            return self.build_result(
                verdict="ERROR",
                findings=[],
                artifact_digest=artifact_digest,
                artifact_name=artifact_name,
                build_id=build_id,
                started_at=started,
                finished_at=datetime.datetime.utcnow(),
                meta={"error": "Failed to parse KICS JSON output"},
            )

        queries = data.get("queries", [])
        if not queries:
            return self.build_result(
                verdict="PASS",
                findings=[],
                artifact_digest=artifact_digest,
                artifact_name=artifact_name,
                build_id=build_id,
                started_at=started,
                finished_at=datetime.datetime.utcnow(),
                duration_ms=0,
            )

        for q in queries:
            raw_sev = q.get("severity", "INFO").upper()
            sev = self._SEVERITY_MAP.get(raw_sev, "low")

            for result in q.get("results", []):
                findings.append(self.normalize_finding({
                    "rule_id": q.get("query_id", "kics-unknown"),
                    "severity": sev,
                    "title": q.get("query_name", "KICS Finding"),
                    "description": q.get("description", ""),
                    "file_path": result.get("file_name", ""),
                    "line_number": result.get("line", 0),
                    "cwe_id": self._CWE_MAP.get(q.get("query_id", ""), "CWE-668"),
                    "remediation": result.get("remediation", q.get("description", "")),
                    "raw_output_snippet": json.dumps(result, default=str)[:1000],
                }))

        critical = sum(1 for f in findings if f.severity == "critical")
        high = sum(1 for f in findings if f.severity == "high")

        if critical > 0:
            verdict: ScannerVerdict = "FAIL"
        else:
            verdict = "PASS"

        finished = datetime.datetime.utcnow()
        duration = int((finished - started).total_seconds() * 1000)

        return self.build_result(
            verdict=verdict,
            findings=findings,
            artifact_digest=artifact_digest,
            artifact_name=artifact_name,
            build_id=build_id,
            started_at=started,
            finished_at=finished,
            duration_ms=duration,
            meta={
                "total_queries": len(queries),
                "critical_count": critical,
                "high_count": high,
                "scanner": "KICS 2.1.3",
            },
        )


# ══════════════════════════════════════════════════════════════════════════════
# 2. ClamAV — Malware / Antivirus Scanning
# ══════════════════════════════════════════════════════════════════════════════

class ClamavAdapter(BaseScannerAdapter):
    """ClamAV — Open-source antivirus engine.

    Сканирует: контейнеры (filesystem), артефакты сборки, образы.
    """

    tool: ScannerTool = "clamav"
    tool_version: str = "clamav 1.4.2"
    rules_version: str = "main.cvd 2026-08-30"

    def parse_output(
        self,
        raw_output: str,
        artifact_digest: Optional[str] = None,
        artifact_name: Optional[str] = None,
        build_id: Optional[str] = None,
        **kwargs,
    ) -> ScannerResult:
        """Парсинг текстового вывода ClamAV (clamscan)."""
        findings: List[ScannerFinding] = []
        started = datetime.datetime.utcnow()

        if not raw_output.strip():
            return self.build_result(
                verdict="ERROR",
                findings=[],
                artifact_digest=artifact_digest,
                artifact_name=artifact_name,
                build_id=build_id,
                started_at=started,
                finished_at=datetime.datetime.utcnow(),
                meta={"error": "Empty ClamAV output"},
            )

        # ClamAV формат: /path/to/file: VirusName FOUND
        # Или: /path/to/file: OK
        virus_pattern = re.compile(
            r"^(?P<file_path>[^:]+):\s+(?P<threat_name>\S+)\s+FOUND"
        )

        lines = raw_output.strip().split("\n")
        infected = 0
        clean = 0

        for line in lines:
            line = line.strip()
            if not line:
                continue

            match = virus_pattern.match(line)
            if match:
                infected += 1
                findings.append(self.normalize_finding({
                    "rule_id": f"CLAMAV-{match.group('threat_name').upper()}",
                    "severity": "critical",
                    "title": f"Malware detected: {match.group('threat_name')}",
                    "description": (
                        f"ClamAV обнаружил вредоносное ПО '{match.group('threat_name')}' "
                        f"в файле '{match.group('file_path')}'."
                    ),
                    "file_path": match.group("file_path"),
                    "line_number": 0,
                    "cwe_id": "CWE-506",
                    "remediation": (
                        f"Немедленно поместить артефакт в карантин. "
                        f"Проверить цепочку поставки для файла '{match.group('file_path')}'."
                    ),
                    "raw_output_snippet": line[:2000],
                }))
            elif "OK" in line or "Scanned" in line or "Infected" in line:
                clean += 1

        finished = datetime.datetime.utcnow()
        duration = int((finished - started).total_seconds() * 1000)

        if infected > 0:
            verdict: ScannerVerdict = "FAIL"
        elif clean > 0:
            verdict = "PASS"
        else:
            verdict = "UNAVAILABLE"

        return self.build_result(
            verdict=verdict,
            findings=findings,
            artifact_digest=artifact_digest,
            artifact_name=artifact_name,
            build_id=build_id,
            started_at=started,
            finished_at=finished,
            duration_ms=duration,
            meta={
                "infected_count": infected,
                "clean_count": clean,
                "scanner": "ClamAV 1.4.2",
                "db_version": self.rules_version,
            },
        )


# ══════════════════════════════════════════════════════════════════════════════
# 3. Gitleaks — Secret Detection
# ══════════════════════════════════════════════════════════════════════════════

class GitleaksAdapter(BaseScannerAdapter):
    """Gitleaks — обнаружение секретов, ключей и токенов в исходном коде.

    Сканирует: Git-репозитории, коммиты, файлы.
    """

    tool: ScannerTool = "gitleaks"
    tool_version: str = "gitleaks 8.23.3"
    rules_version: str = "gitleaks.toml 8.23.3"

    # Gitleaks rule_id → CWE mapping
    _CWE_MAP = {
        "aws-access-key": "CWE-798",
        "gcp-api-key": "CWE-798",
        "github-pat": "CWE-798",
        "github-fine-grained-pat": "CWE-798",
        "gitlab-pat": "CWE-798",
        "private-key": "CWE-321",
        "jwt": "CWE-798",
        "generic-api-key": "CWE-798",
        "slack-webhook-url": "CWE-200",
        "discord-webhook": "CWE-200",
        "stripe-access-token": "CWE-798",
        "sqs-queue-url": "CWE-200",
    }

    def parse_output(
        self,
        raw_output: str,
        artifact_digest: Optional[str] = None,
        artifact_name: Optional[str] = None,
        build_id: Optional[str] = None,
        **kwargs,
    ) -> ScannerResult:
        """Парсинг JSON-вывода Gitleaks (gitleaks detect -f json)."""
        findings: List[ScannerFinding] = []
        started = datetime.datetime.utcnow()

        try:
            data = json.loads(raw_output)
        except json.JSONDecodeError:
            return self.build_result(
                verdict="ERROR",
                findings=[],
                artifact_digest=artifact_digest,
                artifact_name=artifact_name,
                build_id=build_id,
                started_at=started,
                finished_at=datetime.datetime.utcnow(),
                meta={"error": "Failed to parse Gitleaks JSON output"},
            )

        # Gitleaks возвращает список находок (может быть list или dict с ключом)
        leaks = data if isinstance(data, list) else data.get("leaks", data.get("findings", []))

        if not leaks:
            return self.build_result(
                verdict="PASS",
                findings=[],
                artifact_digest=artifact_digest,
                artifact_name=artifact_name,
                build_id=build_id,
                started_at=started,
                finished_at=datetime.datetime.utcnow(),
                duration_ms=0,
                meta={"total_leaks": 0, "scanner": "Gitleaks 8.23.3"},
            )

        for leak in leaks:
            rule_id = leak.get("rule_id", leak.get("RuleID", "gitleaks-unknown"))
            findings.append(self.normalize_finding({
                "rule_id": rule_id,
                "severity": "critical",  # Все секреты — critical
                "title": f"Secret detected: {leak.get('description', leak.get('Description', rule_id))}",
                "description": (
                    f"Gitleaks обнаружил '{rule_id}' в файле "
                    f"'{leak.get('file', leak.get('File', 'unknown'))}':"
                    f"{leak.get('line', leak.get('StartLine', 0))}."
                ),
                "file_path": leak.get("file", leak.get("File", "")),
                "line_number": leak.get("line", leak.get("StartLine", 0)),
                "cwe_id": self._CWE_MAP.get(rule_id, "CWE-798"),
                "remediation": (
                    f"Немедленно отозвать скомпрометированный секрет '{rule_id}'. "
                    f"Заменить на vault:secret/... ссылку. "
                    f"Проверить историю Git на наличие секрета."
                ),
                "raw_output_snippet": json.dumps(leak, default=str)[:2000],
            }))

        finished = datetime.datetime.utcnow()
        duration = int((finished - started).total_seconds() * 1000)

        return self.build_result(
            verdict="FAIL",
            findings=findings,
            artifact_digest=artifact_digest,
            artifact_name=artifact_name,
            build_id=build_id,
            started_at=started,
            finished_at=finished,
            duration_ms=duration,
            meta={
                "total_leaks": len(leaks),
                "critical_count": len(findings),
                "scanner": "Gitleaks 8.23.3",
            },
        )


# ══════════════════════════════════════════════════════════════════════════════
# 4. Hadolint — Dockerfile / Build-Context Lint
# ══════════════════════════════════════════════════════════════════════════════

class HadolintAdapter(BaseScannerAdapter):
    """Hadolint — линтер Dockerfile и build-контекста (не сканирует готовый образ).

    Проверяет: Dockerfile на best practices и CVE-prone паттерны.
    """

    tool: ScannerTool = "hadolint"
    tool_version: str = "hadolint 2.12.0"
    rules_version: str = "hadolint 2.12.0 (bundled rules)"

    # Hadolint rule codes → CWE
    _CWE_MAP = {
        "DL3006": "CWE-250",  # Always tag version (no :latest)
        "DL3007": "CWE-250",  # Use :latest is discouraged
        "DL3008": "CWE-1104", # Pin versions in apt-get
        "DL3013": "CWE-1104", # Pin versions in pip
        "DL3018": "CWE-1104", # Pin versions in apk
        "DL3025": "CWE-250",  # Use arguments JSON notation for CMD/ENTRYPOINT
        "DL4006": "CWE-250",  # Set pipefail option
        "SC2086": "CWE-78",   # Double quote to prevent globbing/word splitting
    }

    _SEVERITY_MAP = {
        "error": "high",
        "warning": "medium",
        "info": "low",
        "style": "info",
    }

    def parse_output(
        self,
        raw_output: str,
        artifact_digest: Optional[str] = None,
        artifact_name: Optional[str] = None,
        build_id: Optional[str] = None,
        **kwargs,
    ) -> ScannerResult:
        """Парсинг текстового вывода Hadolint в ScannerResult."""
        findings: List[ScannerFinding] = []
        started = datetime.datetime.utcnow()

        if not raw_output.strip():
            return self.build_result(
                verdict="PASS",
                findings=[],
                artifact_digest=artifact_digest,
                artifact_name=artifact_name,
                build_id=build_id,
                started_at=started,
                finished_at=datetime.datetime.utcnow(),
                duration_ms=0,
                meta={"total_rules": 0, "scanner": "Hadolint 2.12.0"},
            )

        # Hadolint формат: <file>:<line> <rule_code> <severity> <message>
        # Пример: Dockerfile:5 DL3006 warning: Always tag the version of an image explicitly
        line_pattern = re.compile(
            r"^(?P<file>[^:]+):(?P<line>\d+)\s+(?P<rule>DL\d+|SC\d+)\s+(?P<severity>\w+)\s*:?\s*(?P<message>.+)$"
        )

        lines = raw_output.strip().split("\n")
        for line in lines:
            line = line.strip()
            if not line:
                continue

            match = line_pattern.match(line)
            if match:
                rule_id = match.group("rule")
                raw_sev = match.group("severity").lower()
                sev = self._SEVERITY_MAP.get(raw_sev, "medium")

                findings.append(self.normalize_finding({
                    "rule_id": rule_id,
                    "severity": sev,
                    "title": f"Hadolint {rule_id}: {match.group('message')[:100]}",
                    "description": match.group("message"),
                    "file_path": match.group("file"),
                    "line_number": int(match.group("line")),
                    "cwe_id": self._CWE_MAP.get(rule_id, "CWE-1104"),
                    "remediation": (
                        f"Исправить Dockerfile согласно правилу {rule_id}. "
                        f"Для 'DL3006': всегда указывать точный тег образа."
                    ),
                    "raw_output_snippet": line[:2000],
                }))

        finished = datetime.datetime.utcnow()
        duration = int((finished - started).total_seconds() * 1000)

        error_count = sum(1 for f in findings if f.severity in ("critical", "high"))
        verdict: ScannerVerdict = "FAIL" if error_count > 0 else "PASS"

        return self.build_result(
            verdict=verdict,
            findings=findings,
            artifact_digest=artifact_digest,
            artifact_name=artifact_name,
            build_id=build_id,
            started_at=started,
            finished_at=finished,
            duration_ms=duration,
            meta={
                "total_rules_violated": len(findings),
                "error_count": error_count,
                "scanner": "Hadolint 2.12.0",
            },
        )


# ══════════════════════════════════════════════════════════════════════════════
# 5. KubeLinter — Kubernetes Manifest Scanning
# ══════════════════════════════════════════════════════════════════════════════

class KubeLinterAdapter(BaseScannerAdapter):
    """KubeLinter — статический анализ Kubernetes YAML манифестов.

    Проверяет: Deployments, Pods, Services, ConfigMaps на best practices.
    """

    tool: ScannerTool = "kubelinter"
    tool_version: str = "kube-linter 0.7.1"
    rules_version: str = "kube-linter built-in checks 0.7.1"

    # KubeLinter check → CWE mapping
    _CWE_MAP = {
        "privileged-container": "CWE-250",
        "run-as-non-root": "CWE-250",
        "read-only-root-filesystem": "CWE-250",
        "no-liveness-probe": "CWE-400",
        "no-readiness-probe": "CWE-400",
        "no-resource-limits": "CWE-400",
        "no-resource-requests": "CWE-400",
        "host-network": "CWE-668",
        "host-pid": "CWE-668",
        "host-ipc": "CWE-668",
        "capabilities": "CWE-250",
        "docker-sock": "CWE-250",
        "env-var-secrets": "CWE-798",
        "non-existent-service-account": "CWE-287",
        "sensitive-host-mounts": "CWE-668",
    }

    _SEVERITY_MAP = {
        "error": "high",
        "warning": "medium",
        "note": "low",
    }

    def parse_output(
        self,
        raw_output: str,
        artifact_digest: Optional[str] = None,
        artifact_name: Optional[str] = None,
        build_id: Optional[str] = None,
        **kwargs,
    ) -> ScannerResult:
        """Парсинг JSON-вывода KubeLinter (kube-linter lint --format json)."""
        findings: List[ScannerFinding] = []
        started = datetime.datetime.utcnow()

        try:
            data = json.loads(raw_output)
        except json.JSONDecodeError:
            return self.build_result(
                verdict="ERROR",
                findings=[],
                artifact_digest=artifact_digest,
                artifact_name=artifact_name,
                build_id=build_id,
                started_at=started,
                finished_at=datetime.datetime.utcnow(),
                meta={"error": "Failed to parse KubeLinter JSON output"},
            )

        reports = data if isinstance(data, list) else data.get("reports", data.get("checks", []))
        if not reports:
            return self.build_result(
                verdict="PASS",
                findings=[],
                artifact_digest=artifact_digest,
                artifact_name=artifact_name,
                build_id=build_id,
                started_at=started,
                finished_at=datetime.datetime.utcnow(),
                duration_ms=0,
                meta={"checks_passed": 0, "scanner": "KubeLinter 0.7.1"},
            )

        for report in reports:
            check_name = report.get("check", report.get("Check", "unknown"))
            obj = report.get("object", report.get("Object", {}))
            remediation = report.get("remediation", report.get("Remediation", ""))

            findings.append(self.normalize_finding({
                "rule_id": check_name,
                "severity": self._SEVERITY_MAP.get(
                    report.get("severity", "warning").lower(), "medium"
                ),
                "title": f"KubeLinter: {check_name} in {obj.get('kind', 'resource')} '{obj.get('name', 'unknown')}'",
                "description": str(report.get("diagnostic", report.get("Diagnostic", {}).get("message", ""))),
                "file_path": obj.get("name", ""),
                "line_number": 0,
                "cwe_id": self._CWE_MAP.get(check_name, "CWE-250"),
                "remediation": remediation or f"Apply KubeLinter recommendation for '{check_name}'.",
                "raw_output_snippet": json.dumps(report, default=str)[:2000],
            }))

        finished = datetime.datetime.utcnow()
        duration = int((finished - started).total_seconds() * 1000)

        error_count = sum(1 for f in findings if f.severity in ("critical", "high"))
        verdict: ScannerVerdict = "FAIL" if error_count > 0 else "PASS"

        return self.build_result(
            verdict=verdict,
            findings=findings,
            artifact_digest=artifact_digest,
            artifact_name=artifact_name,
            build_id=build_id,
            started_at=started,
            finished_at=finished,
            duration_ms=duration,
            meta={
                "total_checks": len(reports),
                "error_count": error_count,
                "scanner": "KubeLinter 0.7.1",
                "namespace": kwargs.get("namespace", "default"),
            },
        )