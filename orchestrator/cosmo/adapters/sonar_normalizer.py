# -*- coding: utf-8 -*-
"""COS-072: Sonar SARIF Normalizer — портирован из Cosmoport 1.0 (D:\\main.py).

Нормализует SonarQube issues + hotspots в NormalizedFinding (Pydantic),
генерирует валидный SARIF 2.1.0 с locations, rules, taxa (CWE).
"""
from __future__ import annotations

import hashlib
import re
from typing import Any, Optional
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field


StrictModel = ConfigDict(extra="ignore")


# ── Pydantic model ──

class NormalizedFinding(BaseModel):
    """Нормализованная находка (Sonar issue / hotspot)."""
    model_config = StrictModel

    id: str = Field(..., description="Уникальный ключ (Sonar issue key / hotspot key)")
    rule_id: str = Field(..., description="Sonar rule key")
    rule_name: str = Field(default="", description="Название правила")
    severity: str = Field(default="Medium", description="Critical|High|Medium|Low")
    type: str = Field(default="BUG", description="BUG|VULNERABILITY|CODE_SMELL|SECURITY_HOTSPOT")
    message: str = Field(default="", description="Сообщение находки")
    status: str = Field(default="OPEN", description="Статус в Sonar")
    resolution: Optional[str] = Field(default=None, description="Резолюция (FIXED и т.д.)")
    file_path: str = Field(default="unknown", description="Путь к файлу")
    line: Optional[int] = Field(default=None, ge=1, description="Номер строки")
    end_line: Optional[int] = Field(default=None, ge=1, description="Конечная строка")
    language: str = Field(default="unknown", description="Язык")
    tags: list[str] = Field(default_factory=list)
    cwe_ids: list[str] = Field(default_factory=list, description="CWE-идентификаторы")
    url: str = Field(default="", description="Ссылка на находку в SonarQube")
    sonar_raw: dict[str, Any] = Field(default_factory=dict, description="Сырые данные для propertyBag")


# ── Severity mapping ──

_SEVERITY_MAP: dict[str, str] = {
    "BLOCKER": "Critical",
    "CRITICAL": "Critical",
    "MAJOR": "High",
    "MINOR": "Low",
    "INFO": "Low",
    "HIGH": "High",
    "MEDIUM": "Medium",
    "LOW": "Low",
}

_SARIF_LEVEL: dict[str, str] = {
    "BLOCKER": "error",
    "CRITICAL": "error",
    "MAJOR": "warning",
    "MINOR": "note",
    "INFO": "note",
}

_HOTSPOT_PROBABILITY_LEVEL: dict[str, str] = {
    "HIGH": "error",
    "MEDIUM": "warning",
    "LOW": "note",
}


# ── Normalize issues ──

def normalize_sonar_issues(
    raw_issues: list[dict[str, Any]],
    rules_by_key: dict[str, dict[str, Any]] | None = None,
) -> list[NormalizedFinding]:
    """Нормализует сырые SonarQube issues в NormalizedFinding.

    Args:
        raw_issues: список issue из Sonar API (/api/issues/search).
        rules_by_key: опциональный dict rule_key → rule_data для обогащения.

    Returns: list[NormalizedFinding].
    """
    rules = rules_by_key or {}
    findings: list[NormalizedFinding] = []

    for issue in raw_issues:
        rule_key = issue.get("rule", "")
        rule_data = rules.get(rule_key, {})

        location = _build_location(
            component=issue.get("component"),
            line=issue.get("line"),
            text_range=issue.get("textRange"),
        )

        severity = _severity_to_appsechub(issue.get("severity"))
        tags = issue.get("tags", [])
        rule_desc = rule_data.get("name") or issue.get("message", "")

        cwe_ids = extract_cwe(tags, rule_desc)
        cwe_strs = [f"CWE-{c['id']}" for c in cwe_ids]

        f = NormalizedFinding(
            id=issue.get("key", ""),
            rule_id=rule_key,
            rule_name=rule_data.get("name") or rule_key,
            severity=severity,
            type=issue.get("type", "BUG"),
            message=issue.get("message", ""),
            status=issue.get("status", "OPEN"),
            resolution=issue.get("resolution"),
            file_path=location.get("file_path") or _extract_file_path(issue.get("component")),
            line=location.get("line"),
            end_line=(location.get("text_range") or {}).get("end_line"),
            language=rule_data.get("lang", "unknown"),
            tags=tags,
            cwe_ids=cwe_strs,
            url=issue.get("url", ""),
            sonar_raw=issue,
        )
        findings.append(f)

    return findings


# ── Normalize hotspots ──

def normalize_sonar_hotspots(
    raw_hotspots: list[dict[str, Any]],
    hotspot_details: dict[str, dict[str, Any]] | None = None,
) -> list[NormalizedFinding]:
    """Нормализует сырые SonarQube Security Hotspots в NormalizedFinding.

    Args:
        raw_hotspots: список hotspot из Sonar API (/api/hotspots/search).
        hotspot_details: опциональный dict hotspot_key → details.

    Returns: list[NormalizedFinding].
    """
    details = hotspot_details or {}
    findings: list[NormalizedFinding] = []

    for hotspot in raw_hotspots:
        hk = hotspot.get("key", "")
        d = details.get(hk, {})
        rule_info = d.get("rule", {}) if isinstance(d, dict) else {}
        rule_key = hotspot.get("ruleKey") or rule_info.get("key", "")
        rule_name = rule_info.get("name") or hotspot.get("ruleName", "")
        probability = hotspot.get("vulnerabilityProbability")

        location = _build_location(
            component=hotspot.get("component"),
            line=hotspot.get("line"),
            text_range=d.get("textRange") if isinstance(d, dict) else None,
        )

        severity = _severity_to_appsechub(
            severity=rule_info.get("severity"),
            probability=probability,
        )
        tags = rule_info.get("tags", [])
        rule_desc = rule_name or d.get("message") or hotspot.get("message", "")

        cwe_ids = extract_cwe(tags, rule_desc)
        cwe_strs = [f"CWE-{c['id']}" for c in cwe_ids]

        f = NormalizedFinding(
            id=hk,
            rule_id=rule_key,
            rule_name=rule_name,
            severity=severity,
            type="SECURITY_HOTSPOT",
            message=d.get("message") or hotspot.get("message", ""),
            status=hotspot.get("status", "TO_REVIEW"),
            resolution=hotspot.get("resolution"),
            file_path=location.get("file_path") or _extract_file_path(hotspot.get("component")),
            line=location.get("line"),
            end_line=(location.get("text_range") or {}).get("end_line"),
            language=rule_info.get("lang", "unknown"),
            tags=tags,
            cwe_ids=cwe_strs,
            url=hotspot.get("url", ""),
            sonar_raw=hotspot,
        )
        findings.append(f)

    return findings


# ── SARIF 2.1.0 builder ──

def build_sarif_210(
    findings: list[NormalizedFinding],
    rules_meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Генерирует валидный SARIF 2.1.0 отчёт с locations, rules, taxa (CWE).

    Args:
        findings: нормализованные находки.
        rules_meta: опциональный dict rule_id → {name, description, helpUri}.

    Returns: SARIF 2.1.0 dict.
    """
    rules_index: dict[str, dict[str, Any]] = {}
    results: list[dict[str, Any]] = []
    all_cwe: dict[int, dict[str, Any]] = {}

    for f in findings:
        rule_id = f.rule_id or "sonarqube:unknown"
        level = _sarif_level_from_severity(f.severity)

        # Collect CWE for taxa
        for cwe_id_str in f.cwe_ids:
            try:
                cwe_num = int(cwe_id_str.replace("CWE-", ""))
                all_cwe.setdefault(cwe_num, {
                    "id": str(cwe_num),
                    "name": cwe_id_str,
                    "helpUri": f"https://cwe.mitre.org/data/definitions/{cwe_num}.html",
                })
            except ValueError:
                pass

        # Ensure rule descriptor
        if rule_id not in rules_index:
            rule_meta = (rules_meta or {}).get(rule_id, {})
            rule_descriptor: dict[str, Any] = {
                "id": rule_id,
                "name": f.rule_name or rule_id,
                "shortDescription": {"text": f.rule_name or rule_id},
                "properties": _compact({
                    "severity": f.severity,
                    "type": f.type,
                    "language": f.language,
                    "tags": f.tags,
                }),
            }
            if rule_meta.get("description"):
                rule_descriptor["fullDescription"] = {"text": rule_meta["description"]}
            if rule_meta.get("helpUri"):
                rule_descriptor["helpUri"] = rule_meta["helpUri"]
            rules_index[rule_id] = rule_descriptor

        # Build location
        location = _build_sarif_location(f)

        # Build result
        result: dict[str, Any] = {
            "ruleId": rule_id,
            "level": level,
            "kind": "fail",
            "message": {"text": f.message or f.rule_name},
            "locations": [location],
            "properties": _compact({
                "sonar_key": f.id,
                "sonar_severity": f.sonar_raw.get("severity"),
                "sonar_type": f.type,
                "sonar_status": f.status,
                "finder_url": f.url,
                "tags": f.tags,
            }),
        }
        if f.cwe_ids:
            result["taxa"] = [{"id": c.replace("CWE-", "")} for c in f.cwe_ids]
        results.append(result)

    # Build SARIF document
    rules_list = list(rules_index.values())
    taxa_list = list(all_cwe.values()) if all_cwe else None

    run: dict[str, Any] = {
        "tool": {
            "driver": {
                "name": "SonarQube",
                "informationUri": "https://www.sonarsource.com/products/sonarqube/",
                "rules": rules_list,
            }
        },
        "results": results,
    }
    if taxa_list:
        run["taxonomies"] = [{
            "name": "CWE",
            "informationUri": "https://cwe.mitre.org/",
            "organization": "MITRE",
            "version": "4.x",
            "taxa": taxa_list,
        }]

    return {
        "version": "2.1.0",
        "$schema": (
            "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/"
            "master/Schemata/sarif-schema-2.1.0.json"
        ),
        "runs": [run],
    }


# ── CWE extraction ──

def extract_cwe(tags: list[str] | None = None, rule_desc: str = "") -> list[dict[str, Any]]:
    """Извлечение CWE-идентификаторов из тегов и описания правила.

    Args:
        tags: список тегов правила (напр. ["cwe-79", "owasp-a1"]).
        rule_desc: текстовое описание правила.

    Returns: list[{"id": int, "link": str}].
    """
    pattern = re.compile(r"cwe[-_ :#]?(\d+)", re.IGNORECASE)
    cwe_ids: set[int] = set()

    for tag in (tags or []):
        for match in pattern.findall(tag):
            cwe_ids.add(int(match))

    if rule_desc:
        for match in pattern.findall(rule_desc):
            cwe_ids.add(int(match))

    return [
        {
            "id": cwe_id,
            "link": f"https://cwe.mitre.org/data/definitions/{cwe_id}.html",
        }
        for cwe_id in sorted(cwe_ids)
    ]


# ── Severity helpers ──

def _severity_to_appsechub(
    severity: Optional[str] = None,
    probability: Optional[str] = None,
) -> str:
    """Преобразование severity Sonar → формат AppSecHub (Critical/High/Medium/Low)."""
    if severity in {"Low", "Medium", "High", "Critical"}:
        return severity  # type: ignore[return-value]
    mapped = _SEVERITY_MAP.get((severity or "").upper())
    if mapped:
        return mapped
    prob_mapped = _HOTSPOT_PROBABILITY_LEVEL.get((probability or "").upper(), "")
    rank = {"error": "High", "warning": "Medium", "note": "Low"}.get(prob_mapped)
    if rank:
        return rank
    return "Medium"


def _sarif_level_from_severity(severity: str) -> str:
    """Severity → SARIF level (error/warning/note)."""
    upper = severity.upper() if severity else ""
    return _SARIF_LEVEL.get(upper, "warning")


# ── Location helpers ──

def _build_location(
    component: Optional[str] = None,
    line: Any = None,
    text_range: Any = None,
    message: Optional[str] = None,
) -> dict[str, Any]:
    """Формирование единого объекта локации."""
    loc: dict[str, Any] = {
        "component": component,
        "file_path": _extract_file_path(component),
    }
    if line is not None:
        loc["line"] = line
    normalized = _normalize_text_range(text_range)
    if normalized:
        loc["text_range"] = normalized
        if loc.get("line") is None and normalized.get("start_line") is not None:
            loc["line"] = normalized["start_line"]
    if message:
        loc["message"] = message
    return loc


def _extract_file_path(component_key: Optional[str]) -> str:
    """Извлекает путь файла из Sonar component key."""
    if not component_key:
        return "unknown"
    parts = component_key.split(":", 1)
    return parts[1] if len(parts) == 2 else component_key


def _normalize_text_range(text_range: Any) -> dict[str, Any]:
    """Нормализует Sonar textRange camelCase → snake_case."""
    if not isinstance(text_range, dict):
        return {}
    result: dict[str, Any] = {}
    for key in ("startLine", "endLine", "startOffset", "endOffset"):
        val = text_range.get(key)
        if val is not None:
            snake = _camel_to_snake(key)
            result[snake] = val
    return result


def _camel_to_snake(camel: str) -> str:
    """startLine → start_line."""
    return re.sub(r'(?<!^)(?=[A-Z])', '_', camel).lower()


def _build_sarif_location(finding: NormalizedFinding) -> dict[str, Any]:
    """Строит SARIF location из NormalizedFinding."""
    uri = _to_sarif_uri(finding.file_path)
    sarif_loc: dict[str, Any] = {
        "physicalLocation": {
            "artifactLocation": {"uri": uri},
        }
    }
    region: dict[str, Any] = {}
    if finding.line:
        region["startLine"] = finding.line
    if finding.end_line:
        region["endLine"] = finding.end_line
    if region:
        sarif_loc["physicalLocation"]["region"] = region
    return sarif_loc


def _to_sarif_uri(raw_uri: Optional[str]) -> str:
    """Нормализация URI под SARIF."""
    if not raw_uri:
        return "unknown"
    return quote(str(raw_uri), safe="/:@-._~%!$&'()*+,;=?#[]")


def _compact(d: dict[str, Any]) -> dict[str, Any]:
    """Удаляет None и пустые строки из dict (чистый propertyBag)."""
    result: dict[str, Any] = {}
    for k, v in d.items():
        if v is None:
            continue
        if isinstance(v, str) and not v.strip():
            continue
        if isinstance(v, list) and len(v) == 0:
            continue
        result[k] = v
    return result