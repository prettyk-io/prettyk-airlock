"""
COS-058: Findings Correlation Engine.

Унифицирует находки из разных источников (SAST, SCA, DAST, Fuzzer),
дедуплицирует по composite key (CWE + file_path + title),
группирует по severity, привязывает к run_id/batch_id.

Инварианты:
  - Одна находка из двух источников с одинаковым CWE + file_path + title → одна запись
  - Разные CWE или file_path → разные записи (не дедуплицируются)
  - Severity сортировка: critical > high > medium > low > info
"""
from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional

Severity = Literal["critical", "high", "medium", "low", "info"]
FindingSource = Literal["sast", "sca", "dast", "fuzzer", "manual"]

_SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}


@dataclass
class NormalizedFinding:
    """COS-058: унифицированная находка из любого источника."""

    title: str                           # человекочитаемое название (e.g. "SQL Injection in login")
    severity: Severity                   # critical|high|medium|low|info
    source: FindingSource                # sast|sca|dast|fuzzer|manual
    cwe: str                             # CWE-ID (e.g. "CWE-89", "CWE-79")
    file_path: str = ""                  # путь к файлу (для SAST/SCA) или URL (для DAST)
    line: int | None = None              # строка кода (SAST) или None (DAST)
    description: str = ""                # детальное описание
    evidence_ref: str = ""               # ссылка на evidence-артефакт
    run_id: str = ""                     # ID прогона
    batch_id: str = ""                   # ID batch'а
    raw_payload: Dict[str, Any] = field(default_factory=dict)  # оригинальный payload (для аудита)

    def composite_key(self) -> str:
        """COS-058: dedup key — CWE + file_path + title (SHA-256[:32])."""
        payload = f"{self.cwe}|{self.file_path}|{self.title}"
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "severity": self.severity,
            "source": self.source,
            "cwe": self.cwe,
            "file_path": self.file_path,
            "line": self.line,
            "description": self.description,
            "evidence_ref": self.evidence_ref,
            "run_id": self.run_id,
            "batch_id": self.batch_id,
            "composite_key": self.composite_key(),
        }


@dataclass
class CorrelationResult:
    """Результат корреляции находок."""
    findings: List[NormalizedFinding] = field(default_factory=list)
    total_raw: int = 0           # сколько сырых находок пришло
    total_correlated: int = 0    # сколько уникальных после дедупликации
    duplicates_removed: int = 0  # сколько дублей убрано
    sources: Dict[str, int] = field(default_factory=dict)  # счётчики по источникам
    by_severity: Dict[str, int] = field(default_factory=dict)


class FindingsCorrelator:
    """COS-058: движок корреляции находок из разных источников."""

    def __init__(self):
        self._seen: Dict[str, NormalizedFinding] = {}  # composite_key → finding

    # ── Normalize ──

    @staticmethod
    def normalize_sast(raw: Dict[str, Any]) -> NormalizedFinding:
        """SAST finding (SonarQube, Semgrep) → NormalizedFinding."""
        return NormalizedFinding(
            title=str(raw.get("title", raw.get("message", raw.get("rule_id", "SAST Finding")))),
            severity=_normalize_severity(raw.get("severity", raw.get("level", "medium"))),
            source="sast",
            cwe=str(raw.get("cwe", raw.get("rule_id", "CWE-200"))).upper(),
            file_path=str(raw.get("file_path", raw.get("file", raw.get("component", "")))),
            line=int(raw["line"]) if raw.get("line") else None,
            description=str(raw.get("description", raw.get("message", ""))),
            evidence_ref=str(raw.get("evidence_ref", raw.get("artifact", ""))),
            run_id=str(raw.get("run_id", "")),
            batch_id=str(raw.get("batch_id", "")),
            raw_payload=dict(raw),
        )

    @staticmethod
    def normalize_sca(raw: Dict[str, Any]) -> NormalizedFinding:
        """SCA finding (Trivy, Dependency-Check) → NormalizedFinding."""
        return NormalizedFinding(
            title=str(raw.get("title", raw.get("package", raw.get("vulnerability_id", "SCA Finding")))),
            severity=_normalize_severity(raw.get("severity", raw.get("level", "medium"))),
            source="sca",
            cwe=str(raw.get("cwe", raw.get("vulnerability_id", "CWE-937"))).upper(),
            file_path=str(raw.get("file_path", raw.get("dependency", raw.get("package", "")))),
            line=None,
            description=str(raw.get("description", raw.get("summary", ""))),
            evidence_ref=str(raw.get("evidence_ref", "")),
            run_id=str(raw.get("run_id", "")),
            batch_id=str(raw.get("batch_id", "")),
            raw_payload=dict(raw),
        )

    @staticmethod
    def normalize_dast(raw: Dict[str, Any]) -> NormalizedFinding:
        """DAST finding (scanner/ZAP) → NormalizedFinding."""
        return NormalizedFinding(
            title=str(raw.get("title", raw.get("alert", raw.get("name", "DAST Finding")))),
            severity=_normalize_severity(raw.get("severity", raw.get("risk", "medium"))),
            source="dast",
            cwe=str(raw.get("cwe", raw.get("cwe_id", "CWE-200"))).upper(),
            file_path=str(raw.get("url", raw.get("file_path", ""))),
            line=None,
            description=str(raw.get("description", raw.get("detail", ""))),
            evidence_ref=str(raw.get("evidence_ref", raw.get("artifact", ""))),
            run_id=str(raw.get("run_id", "")),
            batch_id=str(raw.get("batch_id", "")),
            raw_payload=dict(raw),
        )

    @staticmethod
    def normalize_fuzzer(raw: Dict[str, Any]) -> NormalizedFinding:
        """Fuzzer finding → NormalizedFinding."""
        return NormalizedFinding(
            title=str(raw.get("title", raw.get("injection_type", raw.get("alert", "Fuzzer Finding")))),
            severity=_normalize_severity(raw.get("severity", raw.get("level", "medium"))),
            source="fuzzer",
            cwe=str(raw.get("cwe", "CWE-200")).upper(),
            file_path=str(raw.get("url", raw.get("file_path", raw.get("endpoint", "")))),
            line=None,
            description=str(raw.get("description", raw.get("detail", raw.get("payload", "")))),
            evidence_ref=str(raw.get("evidence_ref", "")),
            run_id=str(raw.get("run_id", "")),
            batch_id=str(raw.get("batch_id", "")),
            raw_payload=dict(raw),
        )

    # ── Ingest ──

    def ingest(self, findings: List[NormalizedFinding]) -> int:
        """Добавить нормализованные находки с дедупликацией. Возвращает число новых."""
        added = 0
        for f in findings:
            key = f.composite_key()
            if key not in self._seen:
                self._seen[key] = f
                added += 1
        return added

    def ingest_raw(self, raw_findings: List[Dict[str, Any]], source: FindingSource) -> int:
        """Принять сырые находки из одного источника — нормализовать + дедуплицировать."""
        normalizer = {
            "sast": self.normalize_sast,
            "sca": self.normalize_sca,
            "dast": self.normalize_dast,
            "fuzzer": self.normalize_fuzzer,
        }
        normalize_fn = normalizer.get(source)
        if normalize_fn is None:
            return 0

        normalized = [normalize_fn(raw) for raw in raw_findings]
        return self.ingest(normalized)

    # ── Query ──

    def all_findings(self) -> List[NormalizedFinding]:
        """Все уникальные находки, отсортированные по severity."""
        return sorted(self._seen.values(), key=lambda f: _SEVERITY_ORDER.get(f.severity, 99))

    def by_severity(self, severity: Severity) -> List[NormalizedFinding]:
        return [f for f in self._seen.values() if f.severity == severity]

    def by_source(self, source: FindingSource) -> List[NormalizedFinding]:
        return [f for f in self._seen.values() if f.source == source]

    def by_run(self, run_id: str) -> List[NormalizedFinding]:
        return [f for f in self._seen.values() if f.run_id == run_id]

    def by_batch(self, batch_id: str) -> List[NormalizedFinding]:
        return [f for f in self._seen.values() if f.batch_id == batch_id]

    def count_by_severity(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for f in self._seen.values():
            counts[f.severity] = counts.get(f.severity, 0) + 1
        return dict(sorted(counts.items(), key=lambda x: _SEVERITY_ORDER.get(x[0], 99)))

    def count_by_source(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for f in self._seen.values():
            counts[f.source] = counts.get(f.source, 0) + 1
        return counts

    # ── Correlation report ──

    def correlate(
        self,
        raw_findings: List[NormalizedFinding],
    ) -> CorrelationResult:
        """Прогнать сырые находки через коррелятор — dedup + группировка.

        Возвращает CorrelationResult с уникальными находками и статистикой.
        """
        total_raw = len(raw_findings)
        self._seen.clear()

        added = self.ingest(raw_findings)
        all_f = self.all_findings()

        sources: Dict[str, int] = {}
        for f in all_f:
            sources[f.source] = sources.get(f.source, 0) + 1

        return CorrelationResult(
            findings=all_f,
            total_raw=total_raw,
            total_correlated=added,
            duplicates_removed=total_raw - added,
            sources=sources,
            by_severity=self.count_by_severity(),
        )

    def __len__(self) -> int:
        return len(self._seen)


# ── Helpers ────────────────────────────────────────────────────────────────

_SEVERITY_ALIASES: Dict[str, Severity] = {
    # Critical
    "critical": "critical", "blocker": "critical", "urgent": "critical",
    # High
    "high": "high", "major": "high", "important": "high",
    # Medium
    "medium": "medium", "normal": "medium", "moderate": "medium",
    "warn": "medium", "warning": "medium",
    # Low
    "low": "low", "minor": "low", "trivial": "low",
    # Info
    "info": "info", "informational": "info", "note": "info", "none": "info",
}


def _normalize_severity(raw: str | None) -> Severity:
    """Маппинг severity-лейблов из разных источников в канонический Severity."""
    if not raw:
        return "medium"
    key = str(raw).strip().lower()
    return _SEVERITY_ALIASES.get(key, "medium")


def sarif_level(risk: str) -> str:
    """Convert severity → SARIF level."""
    _map = {"Critical": "error", "High": "warning", "Medium": "note", "Low": "note", "Info": "none"}
    return _map.get(risk, "none")