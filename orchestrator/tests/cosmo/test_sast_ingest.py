# -*- coding: utf-8 -*-
"""SAST-INGEST-2: конвертер SARIF/CE-отчёта → findings + дедуп → живой мост COS-101.

Покрытие:
  - severity-канон (Sonar-градация → security-severity → SARIF level);
  - golden-фикстура SonarQube SARIF 2.1.0 (path/line, CWE, tool, detected_at);
  - пустой/битый отчёт — честно (пусто vs SastReportError);
  - дедуп composite key path+rule+line против runs.findings_refs (идемпотентность);
  - живой мост attach_findings на изолированном test PG (:5433).
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

import _testpg  # noqa: E402 — pytest кладёт этот каталог в sys.path

from orchestrator.cosmo.control_plane.sast_ingest import (  # noqa: E402
    SastReportError,
    convert_sonar_issues,
    dedup_findings,
    extract_sarif_findings,
    ingest_sarif_to_run,
    make_dedup_key,
    severity_from_security_score,
)

_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "sast" / "sonarqube_report.sarif"
_PG_URL = os.getenv(
    "COSMO_DATABASE_URL",
    "postgresql+asyncpg://cosmo:cosmo@127.0.0.1:5433/cosmo_test",
)

DOMAIN = "sast2-dom"
APP = "sast2-app"
PLAN = "sast2-plan"
RUN = "sast2run0001"
RUN_ALT = "sast2run0002"

_pg_needed = pytest.mark.skipif(
    not _testpg.pg_available(), reason="test PG unavailable (host :5433)"
)


# ── Severity-канон ───────────────────────────────────────────────────────


class TestSeverityCanon:
    def test_security_score_bands(self):
        assert severity_from_security_score("9.8") == "Critical"
        assert severity_from_security_score(7.0) == "High"
        assert severity_from_security_score("4.0") == "Medium"
        assert severity_from_security_score(0.1) == "Low"
        assert severity_from_security_score(0) == "Info"

    def test_security_score_invalid(self):
        assert severity_from_security_score(None) is None
        assert severity_from_security_score("junk") is None
        assert severity_from_security_score(True) is None


# ── SARIF-конвертер: golden + деградации ────────────────────────────────


class TestSarifConverter:
    def test_golden_sonarqube_fixture(self):
        """Фикстура STEP-1: severity по precedence, CWE, path/line, tool=sonarqube."""
        findings = extract_sarif_findings(_FIXTURE.read_bytes())
        assert len(findings) == 5  # extract не дедупит — 5 results

        sql = findings[0]
        assert sql["severity"] == "Critical"          # security-severity 9.8
        assert sql["cwe"] == "CWE-89"
        assert sql["cwe_ids"] == ["CWE-89"]
        assert sql["file_path"] == "src/db.py"
        assert sql["line"] == 42
        assert sql["rule_id"] == "python:S3649"
        assert sql["tool"] == "sonarqube"
        assert sql["source_tool"] == "sonarqube"
        assert sql["scan_type"] == "sast"
        assert sql["detected_at"] == "2026-09-25T12:00:00Z"
        assert "SQL" in sql["title"]

        xss = findings[1]
        # Sonar-градация CRITICAL приоритетнее security-severity 5.0 (Medium)
        assert xss["severity"] == "High"
        assert xss["cwe"] == "CWE-79"

        unused = findings[2]
        # Нет properties → SARIF level error → High
        assert unused["severity"] == "High"
        assert unused["cwe"] == ""
        assert unused["cwe_ids"] == []

        param = findings[3]
        assert param["severity"] == "Low"             # security-severity 1.6
        assert param["cwe"] == "CWE-200"

        assert findings[4]["file_path"] == "src/db.py"  # дубль S3649

    def test_empty_valid_sarif_is_empty(self):
        assert extract_sarif_findings({"version": "2.1.0", "runs": []}) == []
        assert extract_sarif_findings({"runs": [{"tool": {"driver": {"name": "SonarQube"}}, "results": []}]}) == []

    def test_broken_reports_raise_honestly(self):
        with pytest.raises(SastReportError):
            extract_sarif_findings(b"{not-json")
        with pytest.raises(SastReportError):
            extract_sarif_findings({})
        with pytest.raises(SastReportError):
            extract_sarif_findings({"runs": "nope"})

    def test_malformed_entries_skipped_message_only_kept(self):
        payload = {
            "runs": [{
                "tool": {"driver": {"name": "SonarQube"}},
                "results": [
                    "garbage",                                 # не-dict → пропуск
                    {"message": {"text": "no rule"}},          # без ruleId, но с message → честно сохраняем
                    {"ruleId": "python:S1", "message": {"text": "ok"}},
                ],
            }],
        }
        findings = extract_sarif_findings(payload)
        assert len(findings) == 2
        assert findings[0]["rule_id"] == ""
        assert findings[0]["title"] == "no rule"
        assert findings[1]["rule_id"] == "python:S1"

    def test_non_sonar_tool_keeps_driver_name(self):
        payload = {
            "runs": [{
                "tool": {"driver": {"name": "CodeQL"}},
                "results": [{"ruleId": "js/x", "message": {"text": "x"}, "level": "error"}],
            }],
        }
        assert extract_sarif_findings(payload)[0]["tool"] == "codeql"


# ── CE-API: api/issues/search ───────────────────────────────────────────


class TestCeIssuesConverter:
    def test_issues_to_findings(self):
        issues = [
            {
                "rule": "python:S3649",
                "severity": "BLOCKER",
                "message": "SQL injection",
                "component": "payments__api:src/db.py",
                "line": 42,
                "tags": ["cwe-89"],
                "creationDate": "2026-09-25T12:00:00Z",
            },
            {
                "rule": "javascript:S1481",
                "severity": "MINOR",
                "message": "unused var",
                "component": "payments__api:web/app.js",
                "line": 7,
            },
        ]
        findings = convert_sonar_issues(issues)
        assert [f["severity"] for f in findings] == ["Critical", "Low"]
        assert findings[0]["file_path"] == "src/db.py"
        assert findings[0]["cwe"] == "CWE-89"
        assert findings[0]["tool"] == "sonarqube"
        assert findings[1]["cwe_ids"] == []
        assert convert_sonar_issues([]) == []


# ── Дедуп composite key ─────────────────────────────────────────────────


class TestDedup:
    def test_key_is_path_rule_line(self):
        key = make_dedup_key({"file_path": "src/db.py", "rule_id": "python:S3649", "line": 42})
        assert key == "src/db.py|python:S3649|42"

    def test_intra_batch_and_against_existing(self):
        findings = extract_sarif_findings(_FIXTURE.read_bytes())
        fresh, skipped = dedup_findings([], findings)
        assert len(fresh) == 4 and skipped == 1  # дубль S3649 схлопнут

        again, skipped2 = dedup_findings(fresh, findings)
        assert again == [] and skipped2 == 5    # повторный ingest идемпотентен

    def test_different_line_not_deduped(self):
        base = [{"file_path": "a.py", "rule_id": "r", "line": 1}]
        incoming = [
            {"file_path": "a.py", "rule_id": "r", "line": 1},
            {"file_path": "a.py", "rule_id": "r", "line": 2},
        ]
        fresh, skipped = dedup_findings(base, incoming)
        assert skipped == 1 and len(fresh) == 1 and fresh[0]["line"] == 2


# ── Живой мост: SARIF → runs.findings_refs (test PG) ────────────────────


async def _session_factory():
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    engine = create_async_engine(_PG_URL, echo=False)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


async def _seed_run(run_id: str) -> None:
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(_PG_URL, echo=False)
    async with engine.begin() as conn:
        await conn.execute(text(
            "INSERT INTO domains (id, label, forge_type, forge_url, "
            "forge_token_ref, rbac_config, quota_max_runs, "
            "quota_max_storage_gb, quota_max_cpu, created_at) "
            "VALUES (:d, 'sast2', 'gitea', 'http://gitea:3000', "
            "'t', '{}'::jsonb, 50, 100, 8, now()) "
            "ON CONFLICT (id) DO NOTHING"
        ), {"d": DOMAIN})
        await conn.execute(text(
            "INSERT INTO apps (id, domain_id, level) "
            "VALUES (:a, :d, 0) ON CONFLICT (id) DO NOTHING"
        ), {"a": APP, "d": DOMAIN})
        await conn.execute(text(
            "INSERT INTO pipeline_plans (id, app_id, level, scope_id, "
            "compiled_hash, compiled_at) VALUES (:p, :a, 'app', :p, 'h', now()) "
            "ON CONFLICT (id) DO NOTHING"
        ), {"p": PLAN, "a": APP})
        await conn.execute(text(
            "INSERT INTO runs (id, plan_id, trigger, domain_id, status, "
            "initiator_user_id, initiator_role, findings_refs, created_at) "
            "VALUES (:r, :p, 'manual', :d, 'succeeded', 'system', "
            "'system', '[]'::jsonb, now()) "
            "ON CONFLICT (id) DO UPDATE SET findings_refs = '[]'::jsonb"
        ), {"r": run_id, "p": PLAN, "d": DOMAIN})
    await engine.dispose()


async def _stored_findings(run_id: str) -> list[dict]:
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(_PG_URL, echo=False)
    try:
        async with engine.connect() as conn:
            res = await conn.execute(
                text("SELECT findings_refs FROM runs WHERE id = :r"), {"r": run_id}
            )
            row = res.scalar_one_or_none()
            return list(row or [])
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@_pg_needed
class TestLiveBridge:
    async def test_ingest_and_dedup_idempotent(self):
        await _seed_run(RUN)
        engine, session_factory = await _session_factory()
        try:
            result = await ingest_sarif_to_run(session_factory, RUN, _FIXTURE.read_bytes())
            assert (result.parsed, result.attached, result.duplicates, result.total) == (5, 4, 1, 4)

            stored = await _stored_findings(RUN)
            assert len(stored) == 4
            assert stored[0]["severity"] == "Critical"     # severity-канон в носителе
            assert stored[0]["tool"] == "sonarqube"
            assert stored[0]["cwe_ids"] == ["CWE-89"]

            # повторный ingest того же отчёта — идемпотентно (дедуп path+rule+line)
            again = await ingest_sarif_to_run(session_factory, RUN, _FIXTURE.read_bytes())
            assert (again.parsed, again.attached, again.duplicates, again.total) == (5, 0, 5, 4)
            assert len(await _stored_findings(RUN)) == 4
        finally:
            await engine.dispose()

    async def test_missing_run_raises(self):
        engine, session_factory = await _session_factory()
        try:
            with pytest.raises(LookupError):
                await ingest_sarif_to_run(session_factory, RUN_ALT, _FIXTURE.read_bytes())
        finally:
            await engine.dispose()

    async def test_broken_report_not_attached(self):
        await _seed_run(RUN)
        engine, session_factory = await _session_factory()
        try:
            with pytest.raises(SastReportError):
                await ingest_sarif_to_run(session_factory, RUN, b"{broken")
            assert await _stored_findings(RUN) == []
        finally:
            await engine.dispose()