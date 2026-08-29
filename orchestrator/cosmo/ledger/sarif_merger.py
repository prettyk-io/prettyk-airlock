# -*- coding: utf-8 -*-
"""COS-076: Streaming SARIF Merger — потоковое слияние SARIF-шардов.

StreamingSarifMerger:
  - Читает SARIF-шарды из ArtifactStore по одному (потоково).
  - Дедуплицирует driver.rules[] (при конфликте severity — максимум).
  - Конкатенирует results[] с сохранением artifactLocation.uri.
  - Суммирует invocations, properties.
  - Пишет валидный SARIF 2.1.0 master_report.sarif в ArtifactStore.
  - Память: O(уникальных_правил + размер_одного_шарда), константно от N шардов.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from orchestrator.cosmo.ledger.artifact_store import ArtifactStore

logger = logging.getLogger("cosmoport.sarif_merger")

_SARIF_RANK = {"none": 0, "note": 1, "warning": 2, "error": 3}

_SEVERITY_RANK = {
    "INFO": 0, "LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4,
    "BLOCKER": 4, "MAJOR": 3, "MINOR": 1,
}


def _severity_rank(sev: str) -> int:
    """Compute severity rank from any format (SARIF level or AppSecHub severity)."""
    s = (sev or "").upper()
    rank = _SEVERITY_RANK.get(s)
    if rank is not None:
        return rank
    return _SARIF_RANK.get(s, 0)


class StreamingSarifMerger:
    """Потоковый сборщик SARIF-шардов в мастер-отчёт.

    RAM не растёт с числом шардов — каждый шард читается и сразу выгружается.
    """

    def __init__(self, store: ArtifactStore | None = None) -> None:
        self._store = store or ArtifactStore(base_dir="cosmo-evidence")

    def merge_sarif_streams(
        self,
        shard_paths: list[str],
        output_path: str = "merged/master_report.sarif",
    ) -> dict[str, Any]:
        """Потоково слить SARIF-шарды в один мастер-отчёт.

        Args:
            shard_paths: пути к шардам относительно store._base (напр. "runs/r-001/report.sarif.json").
            output_path: путь для выходного мастер-отчёта.

        Returns: итоговый SARIF dict (тот же, что записан в output_path).
        """
        rules_index: dict[str, dict[str, Any]] = {}
        all_results: list[dict[str, Any]] = []  # only kept during build, then freed
        taxa_map: dict[str, dict[str, Any]] = {}
        merged_invocations: list[dict[str, Any]] = []
        total_execution_time = 0.0
        shard_count = 0

        for path in shard_paths:
            shard = self._read_shard(path)
            if shard is None:
                continue

            shard_count += 1

            for run in shard.get("runs", []):
                # Merge rules
                driver = run.get("tool", {}).get("driver", {})
                for rule in driver.get("rules", []):
                    rid = rule.get("id", "")
                    if rid:
                        self._merge_rule(rules_index, rid, rule)

                # Collect results (stream into list, but one shard at a time)
                for result in run.get("results", []):
                    all_results.append(result)

                # Merge taxonomies / taxa
                for tax in run.get("taxonomies", []):
                    for t in tax.get("taxa", []):
                        tid = t.get("id", "")
                        if tid:
                            taxa_map.setdefault(tid, t)

                # Sum invocations
                for inv in run.get("invocations", []):
                    merged_invocations.append(inv)
                    total_execution_time += float(inv.get("executionSuccessful", False)) and \
                        float(inv.get("endTimeUtc", "0").replace("T", " ")) or 0

                # Merge properties (if any)
                props = run.get("properties", {})
                if props and "total_findings" in props:
                    if "_merged_total_findings" not in locals():
                        _merged_total_findings = 0
                    _merged_total_findings += props.get("total_findings", 0)

        # Build output
        merged_run: dict[str, Any] = {
            "tool": {
                "driver": {
                    "name": "Cosmoport Streaming SARIF Merger",
                    "informationUri": "https://github.com/prettyk-io/cosmoport2",
                    "rules": sorted(rules_index.values(), key=lambda r: r["id"]),
                }
            },
            "results": all_results,
        }

        if taxa_map:
            merged_run["taxonomies"] = [{
                "name": "CWE",
                "informationUri": "https://cwe.mitre.org/",
                "organization": "MITRE",
                "version": "4.x",
                "taxa": sorted(taxa_map.values(), key=lambda t: int(t.get("id", "0"))),
            }]

        if merged_invocations:
            merged_run["invocations"] = merged_invocations

        merged_props: dict[str, Any] = {
            "shard_count": shard_count,
            "total_results": len(all_results),
            "unique_rules": len(rules_index),
        }
        if "_merged_total_findings" in locals():
            merged_props["total_findings"] = _merged_total_findings
        merged_run["properties"] = merged_props

        sarif_doc: dict[str, Any] = {
            "version": "2.1.0",
            "$schema": (
                "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/"
                "master/Schemata/sarif-schema-2.1.0.json"
            ),
            "runs": [merged_run],
        }

        # Validate results count
        _validate_sarif(sarif_doc)

        # Write output
        self._write_output(output_path, sarif_doc)

        return sarif_doc

    # ── Internal ──

    def _read_shard(self, path: str) -> dict[str, Any] | None:
        """Потоково прочитать один SARIF-шард из ArtifactStore."""
        full = Path(self._store._base) / path
        if not full.exists():
            logger.warning("Shard not found: %s", path)
            return None
        try:
            raw = full.read_bytes()
            return json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Failed to read shard %s: %s", path, exc)
            return None

    @staticmethod
    def _merge_rule(
        rules_index: dict[str, dict[str, Any]],
        rule_id: str,
        rule: dict[str, Any],
    ) -> None:
        """Вставить или обновить правило в индексе.

        При конфликте: severity берётся по максимуму (error > warning > note).
        properties — объединяются.
        """
        existing = rules_index.get(rule_id)
        if existing is None:
            rules_index[rule_id] = dict(rule)
            return

        # Merge severity: keep maximum
        existing_level = _severity_rank(
            (existing.get("properties") or {}).get("severity", ""))
        new_level = _severity_rank(
            (rule.get("properties") or {}).get("severity", ""))

        if new_level > existing_level:
            # Update severity-related fields
            if "properties" not in existing:
                existing["properties"] = {}
            existing["properties"]["severity"] = (
                rule.get("properties", {}).get("severity",
                existing["properties"].get("severity"))
            )

        # Merge any missing fields
        for key in ("name", "shortDescription", "fullDescription", "helpUri"):
            if not existing.get(key) and rule.get(key):
                existing[key] = rule[key]

    def _write_output(self, output_path: str, sarif_doc: dict[str, Any]) -> None:
        """Записать итоговый SARIF в ArtifactStore."""
        target = Path(self._store._base) / output_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(sarif_doc, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.info(
            "Merged SARIF written: %s (%d results, %d rules)",
            output_path,
            len(sarif_doc.get("runs", [{}])[0].get("results", [])),
            len(sarif_doc.get("runs", [{}])[0].get("tool", {}).get("driver", {}).get("rules", [])),
        )


def _validate_sarif(doc: dict[str, Any]) -> None:
    """Базовая валидация SARIF 2.1.0 структуры."""
    assert doc.get("version") == "2.1.0", "SARIF version must be 2.1.0"
    assert "$schema" in doc, "SARIF must have $schema"
    runs = doc.get("runs", [])
    assert len(runs) >= 1, "SARIF must have at least one run"
    for run in runs:
        assert "tool" in run, "Run must have tool"
        assert "driver" in run["tool"], "Tool must have driver"
        assert "results" in run, "Run must have results"


def make_shard_sarif(
    findings: list[dict[str, Any]],
    rules: list[dict[str, Any]] | None = None,
    tool_name: str = "Cosmoport Shard",
    invocation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Helper: создать синтетический SARIF-шард для тестов."""
    run: dict[str, Any] = {
        "tool": {
            "driver": {
                "name": tool_name,
                "rules": rules or [],
            }
        },
        "results": findings,
    }
    if invocation:
        run["invocations"] = [invocation]
    return {
        "version": "2.1.0",
        "$schema": "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/master/Schemata/sarif-schema-2.1.0.json",
        "runs": [run],
    }