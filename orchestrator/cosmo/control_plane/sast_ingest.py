# -*- coding: utf-8 -*-
"""SAST-INGEST-2: отчёт SAST → канонические findings (живой мост COS-101).

Конвертер SARIF 2.1.0 (SonarQube-отчёт STEP-1) и/или CE-API ``api/issues/search``
в findings-json канонического носителя ``runs.findings_refs`` (COS-101/104):
поля, которые реально читают потребители — ``severity`` (канон
Critical|High|Medium|Low|Info), ``cwe_ids``, ``file_path``, ``tool``/
``source_tool``, ``title``/``description``.

Legacy-блюпринт ``ledger/fast_ingest.py`` (COS-075) таргетил несуществующую
``cosmo_findings``; здесь дедуп **ретаргетирован** на текущий носитель:
composite key ``path+rule+line`` проверяется против уже сохранённых
``runs.findings_refs`` до вызова живого моста ``attach_findings``.

Границы (BAN.md): сканер исполняется CI-шагом (STEP-1); здесь — только
преобразование уже готового отчёта и запись findings, без запуска сканера.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Iterable

logger = logging.getLogger("cosmo.sast_ingest")

CANON_TOOL = "sonarqube"
SCAN_TYPE = "sast"

#: Соответствие SonarQube-градаций канону gate engine (COS-055).
_SONAR_SEVERITY: dict[str, str] = {
    "BLOCKER": "Critical",
    "CRITICAL": "High",
    "MAJOR": "Medium",
    "MINOR": "Low",
    "INFO": "Info",
}

#: Fallback: SARIF level без явной Sonar-градации.
_SARIF_LEVEL: dict[str, str] = {
    "error": "High",
    "warning": "Medium",
    "note": "Low",
    "none": "Info",
}

_DEFAULT_SEVERITY = "Medium"


class SastReportError(ValueError):
    """Отчёт не является валидным SARIF/CE-документом (честная ошибка, не [])."""


# ── Severity ────────────────────────────────────────────────────────────


def severity_from_security_score(raw: Any) -> str | None:
    """SonarQube ``security-severity`` (CVSS-like 0..10) → канон severity."""
    if raw is None or isinstance(raw, bool):
        return None
    try:
        score = float(raw)
    except (TypeError, ValueError):
        return None
    if score >= 9.0:
        return "Critical"
    if score >= 7.0:
        return "High"
    if score >= 4.0:
        return "Medium"
    if score > 0:
        return "Low"
    return "Info"


def _severity_from_level(level: Any) -> str:
    return _SARIF_LEVEL.get(str(level or "").strip().lower(), _DEFAULT_SEVERITY)


def _pick_severity(rule_props: dict[str, Any], level: Any) -> str:
    """Precedence: Sonar-градация → security-severity → SARIF level."""
    raw_sonar = rule_props.get("severity")
    if isinstance(raw_sonar, str) and raw_sonar.strip().upper() in _SONAR_SEVERITY:
        return _SONAR_SEVERITY[raw_sonar.strip().upper()]
    scored = severity_from_security_score(rule_props.get("security-severity"))
    if scored is not None:
        return scored
    return _severity_from_level(level)


# ── Field extraction ────────────────────────────────────────────────────


def extract_cwe(rule_props: dict[str, Any] | None, rule_id: str = "") -> str:
    """CWE из properties (``cwe``/``cwe_id``) или tags (``external/cwe/cwe-89``)."""
    props = rule_props or {}
    for key in ("cwe", "cwe_id", "cweId"):
        val = props.get(key)
        if isinstance(val, str) and val.strip():
            return _normalize_cwe(val)
    tags = props.get("tags")
    if isinstance(tags, list):
        for tag in tags:
            if isinstance(tag, str) and "cwe" in tag.lower():
                return _normalize_cwe(tag)
    if rule_id.upper().startswith("CWE-"):
        return _normalize_cwe(rule_id)
    return ""


def _normalize_cwe(raw: str) -> str:
    """``external/cwe/cwe-89`` / ``cwe-89`` / ``CWE-89`` → ``CWE-89``."""
    token = raw.strip().split("/")[-1]
    if token.lower().startswith("cwe-"):
        return "CWE-" + token[4:].upper()
    return raw.strip().upper()


def _first_location(locations: Any) -> tuple[str, int]:
    if not isinstance(locations, list) or not locations:
        return "", 0
    loc = locations[0]
    if not isinstance(loc, dict):
        return "", 0
    physical = loc.get("physicalLocation") or {}
    artifact = (physical.get("artifactLocation") or {}) if isinstance(physical, dict) else {}
    path = artifact.get("uri") or ""
    path = str(path)
    if path.startswith("file://"):
        path = path[len("file://"):]
    region = (physical.get("region") or {}) if isinstance(physical, dict) else {}
    try:
        line = int(region.get("startLine") or 0)
    except (TypeError, ValueError):
        line = 0
    return path, line


def _message_text(result: dict[str, Any]) -> str:
    msg = result.get("message")
    if isinstance(msg, dict):
        return str(msg.get("text") or msg.get("markdown") or "")
    return str(msg or "")


def _tool_name(driver_name: Any, default: str) -> str:
    name = str(driver_name or "").strip().lower()
    if "sonar" in name:
        return CANON_TOOL
    return name or default


_FINDING_FIELDS = ("file_path", "rule_id", "line")


def _finding(
    *,
    title: str,
    message: str,
    severity: str,
    cwe: str,
    path: str,
    line: int,
    rule_id: str,
    tool: str,
    detected_at: str,
) -> dict[str, Any]:
    """Канонический finding-json моста COS-101 (COS-104-совместимые ключи)."""
    return {
        "title": title or rule_id,
        "description": message,
        "severity": severity,
        "cwe": cwe,
        "cwe_ids": [cwe] if cwe else [],
        "file_path": path,
        "line": line,
        "line_number": line,
        "rule_id": rule_id,
        "rule_name": rule_id,
        "tool": tool,
        "source_tool": tool,
        "scan_type": SCAN_TYPE,
        "detected_at": detected_at,
    }


# ── SARIF 2.1.0 ─────────────────────────────────────────────────────────


def _load_sarif(payload: bytes | str | dict[str, Any]) -> dict[str, Any]:
    if isinstance(payload, dict):
        data = payload
    else:
        raw = payload.decode("utf-8", errors="replace") if isinstance(payload, bytes) else str(payload)
        try:
            data = json.loads(raw)
        except ValueError as exc:
            raise SastReportError(f"invalid SARIF JSON: {exc}") from exc
    if not isinstance(data, dict) or "runs" not in data:
        raise SastReportError("not a SARIF document: 'runs' missing")
    if not isinstance(data["runs"], list):
        raise SastReportError("not a SARIF document: 'runs' is not a list")
    return data


def _run_timestamp(run: dict[str, Any], fallback: str) -> str:
    invocations = run.get("invocations")
    if isinstance(invocations, list) and invocations:
        first = invocations[0]
        if isinstance(first, dict):
            stamp = first.get("endTimeUtc") or first.get("startTimeUtc")
            if isinstance(stamp, str) and stamp:
                return stamp
    return fallback


def extract_sarif_findings(
    payload: bytes | str | dict[str, Any],
    *,
    tool_default: str = CANON_TOOL,
    detected_at: str = "",
) -> list[dict[str, Any]]:
    """SARIF 2.1.0 → канонические findings (severity-канон, path/line, CWE, tool).

    Пустой валидный SARIF (``runs: []`` / без results) → ``[]``.
    Битый JSON / не-SARIF структура → :class:`SastReportError` (не молчаливый []).
    """
    data = _load_sarif(payload)
    findings: list[dict[str, Any]] = []

    for run in data["runs"]:
        if not isinstance(run, dict):
            continue
        driver = ((run.get("tool") or {}).get("driver") or {}) if isinstance(run.get("tool"), dict) else {}
        tool = _tool_name(driver.get("name") if isinstance(driver, dict) else "", tool_default)
        stamp = _run_timestamp(run, detected_at)

        rules_index: dict[str, dict[str, Any]] = {}
        rules = driver.get("rules") if isinstance(driver, dict) else None
        if isinstance(rules, list):
            for rule in rules:
                if isinstance(rule, dict) and rule.get("id"):
                    rules_index[str(rule["id"])] = rule

        results = run.get("results")
        if not isinstance(results, list):
            continue
        for entry in results:
            if not isinstance(entry, dict):
                continue
            rule_id = str(entry.get("ruleId") or "")
            message = _message_text(entry)
            if not rule_id and not message:
                continue  # идентифицировать находку нечем — честно пропускаем
            rule_obj = rules_index.get(rule_id, {})
            props = rule_obj.get("properties") if isinstance(rule_obj.get("properties"), dict) else {}
            path, line = _first_location(entry.get("locations"))
            severity = _pick_severity(props, entry.get("level"))
            cwe = extract_cwe(props, rule_id)
            findings.append(_finding(
                title=message or rule_id,
                message=message,
                severity=severity,
                cwe=cwe,
                path=path,
                line=line,
                rule_id=rule_id,
                tool=tool,
                detected_at=stamp,
            ))

    return findings


# ── CE-API: api/issues/search ───────────────────────────────────────────


def convert_sonar_issues(
    issues: Iterable[dict[str, Any]],
    *,
    detected_at: str = "",
) -> list[dict[str, Any]]:
    """CE ``api/issues/search`` issues → канонические findings.

    ``component`` формата ``<projectKey>:<path>`` → ``file_path``; severity —
    Sonar-градация; CWE — из ``tags`` (``cwe-89``).
    """
    findings: list[dict[str, Any]] = []
    for issue in issues:
        if not isinstance(issue, dict):
            continue
        rule_id = str(issue.get("rule") or "")
        message = str(issue.get("message") or "")
        if not rule_id and not message:
            continue
        component = str(issue.get("component") or "")
        path = component.split(":", 1)[1] if ":" in component else component
        raw_sev = str(issue.get("severity") or "").strip().upper()
        severity = _SONAR_SEVERITY.get(raw_sev, _DEFAULT_SEVERITY)
        tags = issue.get("tags") if isinstance(issue.get("tags"), list) else []
        cwe = ""
        for tag in tags:
            if isinstance(tag, str) and "cwe" in tag.lower():
                cwe = _normalize_cwe(tag)
                break
        try:
            line = int(issue.get("line") or 0)
        except (TypeError, ValueError):
            line = 0
        findings.append(_finding(
            title=message or rule_id,
            message=message,
            severity=severity,
            cwe=cwe,
            path=path,
            line=line,
            rule_id=rule_id,
            tool=CANON_TOOL,
            detected_at=str(issue.get("creationDate") or detected_at),
        ))
    return findings


# ── Dedup (path+rule+line) → runs.findings_refs ─────────────────────────


def make_dedup_key(finding: dict[str, Any]) -> str:
    """Composite key дедупа: ``path|rule_id|line`` (legacy-блюпринт fast_ingest)."""
    return "|".join(
        str(finding.get(field) or "") for field in _FINDING_FIELDS
    )


def dedup_findings(
    existing: list[dict[str, Any]],
    incoming: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], int]:
    """Отфильтровать уже сохранённые/повторяющиеся findings.

    Возвращает ``(новые, число_пропущенных_дублей)``; дубли внутри входящего
    батча тоже схлопываются (первая находка выигрывает).
    """
    seen = {
        make_dedup_key(f) for f in existing if isinstance(f, dict)
    }
    fresh: list[dict[str, Any]] = []
    skipped = 0
    for finding in incoming:
        key = make_dedup_key(finding)
        if key in seen:
            skipped += 1
            continue
        seen.add(key)
        fresh.append(finding)
    return fresh, skipped


@dataclass
class SastIngestResult:
    """Итог ingest'а: parsed → attached с дедупом против runs.findings_refs."""
    run_id: str
    parsed: int
    attached: int
    duplicates: int
    total: int


async def ingest_findings_to_run(
    session_factory: Any,
    run_id: str,
    findings: list[dict[str, Any]],
) -> SastIngestResult:
    """Уже сконвертированные findings → дедуп против носителя → живой мост.

    Общий вход для SARIF и CE-путей; идемпотентен по composite key
    ``path+rule+line``. Run должен существовать (LookupError).
    """
    from orchestrator.cosmo.control_plane.findings_bridge import attach_findings
    from orchestrator.cosmo.db.models import Run as RunORM

    async with session_factory() as session:
        run = await session.get(RunORM, run_id)
        if run is None:
            raise LookupError(f"Run '{run_id}' not found")
        existing = [f for f in (run.findings_refs or []) if isinstance(f, dict)]

    fresh, duplicates = dedup_findings(existing, findings)
    if fresh:
        total = await attach_findings(session_factory, run_id, fresh)
    else:
        total = len(existing)
    logger.info(
        "SAST-INGEST: run=%s parsed=%d attached=%d duplicates=%d total=%d",
        run_id, len(findings), len(fresh), duplicates, total,
    )
    return SastIngestResult(
        run_id=run_id,
        parsed=len(findings),
        attached=len(fresh),
        duplicates=duplicates,
        total=total,
    )


async def ingest_sarif_to_run(
    session_factory: Any,
    run_id: str,
    payload: bytes | str | dict[str, Any],
    *,
    tool_default: str = CANON_TOOL,
) -> SastIngestResult:
    """SARIF-отчёт → канонические findings → :func:`ingest_findings_to_run`."""
    findings = extract_sarif_findings(payload, tool_default=tool_default)
    return await ingest_findings_to_run(session_factory, run_id, findings)