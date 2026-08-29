"""
COS-005: SARIF 2.1.0 exporter (standalone, без GOSTAct).

Принимает список находок и генерирует валидный SARIF-файл.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List


def export_sarif(
    findings: List[Dict[str, Any]],
    *,
    target_url: str = "",
    run_id: str = "",
    tool_name: str = "PrettyK DAST",
) -> str:
    """Сгенерировать SARIF 2.1.0 из списка находок."""
    rules: Dict[str, int] = {}
    results: List[Dict[str, Any]] = []

    for f in findings:
        rule_id = f.get("alert", f.get("title", f"PK-{len(results)}"))
        if rule_id not in rules:
            rules[rule_id] = len(rules)

        results.append({
            "ruleId": str(rule_id)[:80],
            "ruleIndex": rules[rule_id],
            "level": sarif_level(f.get("risk", f.get("severity", "Info"))),
            "message": {
                "text": str(f.get("name", f.get("title", str(rule_id)))),
            },
            "locations": [
                {
                    "physicalLocation": {
                        "artifactLocation": {
                            "uri": str(f.get("url", target_url)),
                        },
                    },
                },
            ],
        })

    sarif = {
        "$schema": "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/master/Schemata/sarif-schema-2.1.0.json",
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": tool_name,
                        "informationUri": "https://prettyk.io",
                        "rules": [
                            {"id": rid, "name": rid}
                            for rid in rules
                        ],
                    },
                },
                "results": results,
            },
        ],
    }

    return json.dumps(sarif, ensure_ascii=False, indent=2)


def sarif_level(risk: str) -> str:
    """Convert PrettyK severity → SARIF level."""
    _map = {
        "Critical": "error",
        "High": "error",
        "Medium": "warning",
        "Low": "note",
        "Info": "note",
    }
    return _map.get(str(risk), "none")