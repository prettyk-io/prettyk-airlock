"""
STACK-LUNA-001: Future Scanner Adapter Contracts.

CodeQL и Semgrep — future контракты. НЕ активированы. НЕ выполняют реального сканирования.
Определены только сигнатуры адаптеров для обеспечения совместимости при будущем подключении.

Любая попытка вызова parse_output на future-адаптере возвращает UNAVAILABLE.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from orchestrator.cosmo.scanners.scanner_contract import (
    BaseScannerAdapter,
    ScannerFinding,
    ScannerResult,
    ScannerTool,
)


class CodeQLAdapter(BaseScannerAdapter):
    """CodeQL — GitHub semantic code analysis engine. FUTURE CONTRACT ONLY.

    Статус: **future**. Не активирован. Не выполняет реального сканирования.
    Контракт определён для будущей интеграции с GitHub Advanced Security.
    """

    tool: ScannerTool = "codeql"
    tool_version: str = "codeql 2.20.0 (future)"
    rules_version: str = "codeql-cli 2.20.0 (future)"

    def parse_output(self, raw_output: str, **kwargs) -> ScannerResult:
        """FUTURE: Возвращает UNAVAILABLE до активации контракта."""
        import datetime
        return self.build_result(
            verdict="UNAVAILABLE",
            findings=[],
            started_at=datetime.datetime.utcnow(),
            finished_at=datetime.datetime.utcnow(),
            duration_ms=0,
            meta={
                "status": "future_contract",
                "message": (
                    "CodeQL adapter is a FUTURE contract (STACK-LUNA-001). "
                    "Not activated. Requires GitHub Advanced Security license "
                    "and codeql-cli binary in scanner worker image."
                ),
                "activation_requirements": [
                    "GitHub Advanced Security license",
                    "codeql-cli binary",
                    "codeql database create/bundle",
                    "SARIF output parser",
                ],
            },
        )


class SemgrepAdapter(BaseScannerAdapter):
    """Semgrep — fast static analysis for many languages. FUTURE CONTRACT ONLY.

    Статус: **future**. Не активирован. Не выполняет реального сканирования.
    Контракт определён для будущей интеграции Semgrep OSS / Semgrep Pro.
    """

    tool: ScannerTool = "semgrep"
    tool_version: str = "semgrep 1.100.0 (future)"
    rules_version: str = "semgrep-rules p/default (future)"

    def parse_output(self, raw_output: str, **kwargs) -> ScannerResult:
        """FUTURE: Возвращает UNAVAILABLE до активации контракта."""
        import datetime
        return self.build_result(
            verdict="UNAVAILABLE",
            findings=[],
            started_at=datetime.datetime.utcnow(),
            finished_at=datetime.datetime.utcnow(),
            duration_ms=0,
            meta={
                "status": "future_contract",
                "message": (
                    "Semgrep adapter is a FUTURE contract (STACK-LUNA-001). "
                    "Not activated. Requires Semgrep CLI binary in scanner worker image."
                ),
                "activation_requirements": [
                    "Semgrep CLI binary (OSS or Pro)",
                    "semgrep-rules registry access",
                    "SARIF output parser",
                ],
            },
        )