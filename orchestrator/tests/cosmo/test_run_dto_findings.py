# -*- coding: utf-8 -*-
"""COS-193: run DTO findings — типизированные dict-находки (регресс 500 на GET /runs).

Носитель ``runs.findings_refs`` хранит dicts (COS-101 пишет, COS-104 читает),
а DTO ``Run.findings`` оставался ``list[str]`` → pydantic ValidationError (500)
на GET /runs/{id} и /runs?domain_id= для любого прогона с dict-findings.
"""
from __future__ import annotations

from datetime import datetime

from orchestrator.cosmo.api.routes.runs import _to_run_schema
from orchestrator.cosmo.db.models import Run as RunORM
from orchestrator.cosmo.domain.run_model import FindingRef, Run


def _orm_run(findings: list) -> RunORM:
    return RunORM(
        id="run-cos193",
        plan_id="plan-cos193",
        trigger="manual",
        domain_id="dom-cos193",
        status="running",
        created_at=datetime.utcnow(),
        findings_refs=list(findings),
    )


def test_finding_ref_keeps_extras():
    ref = FindingRef(severity="Critical", rule="40012", path="a.py", line=7)
    assert ref.severity == "Critical"
    extras = ref.model_extra or {}
    assert extras["rule"] == "40012"
    assert extras["path"] == "a.py"


def test_run_dto_accepts_dict_findings():
    run = Run(
        id="r1", plan_id="p1", trigger="manual", domain_id="d1",
        findings=[{"severity": "Critical", "title": "SQLi"}],
    )
    assert isinstance(run.findings[0], FindingRef)
    assert run.findings[0].severity == "Critical"


def test_run_dto_accepts_legacy_string_findings():
    run = Run(
        id="r1", plan_id="p1", trigger="manual", domain_id="d1",
        findings=["finding-legacy-1"],
    )
    assert run.findings == ["finding-legacy-1"]


def test_to_run_schema_with_dict_findings_no_validation_error():
    """Корень COS-193: dict-findings проходят DTO, extras не теряются."""
    schema = _to_run_schema(_orm_run([
        {"severity": "Critical", "cwe_ids": ["CWE-89"]},
        {"severity": "High", "title": "XSS"},
    ]))
    assert len(schema.findings) == 2
    first = schema.findings[0]
    assert isinstance(first, FindingRef)
    assert first.severity == "Critical"
    assert (first.model_extra or {})["cwe_ids"] == ["CWE-89"]


def test_to_run_schema_empty_findings_unchanged():
    schema = _to_run_schema(_orm_run([]))
    assert schema.findings == []
