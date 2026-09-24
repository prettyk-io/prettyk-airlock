# -*- coding: utf-8 -*-
"""COS-168: PK-C-003.6 / DOCKER_AUDIT — Trivy container scan + gate.

Покрытие:
  - DTO: sha256-валидация digest'ов, закрытый severity, ``extra=ignore``,
    канонический ``trivy_scan_content_hash``, ``observed_severity_count``,
    ``resolve_normalized_digests``;
  - ``run_trivy_scan``: честный ``unavailable`` без бинарника (НЕ фейк);
  - ``parse_trivy_report``: trivy JSON → DTO (severity нормализована, counts
    пересчитаны из findings);
  - POST /api/v1/releases/{release_id}/trivy/attach:
      * clean (critical=0) + digest == ArtifactRecord.digest → PASS/CLEARED
        + крипто-запись в ledger (``source='cosmo-trivy-gate'``);
      * critical>0 → BLOCK/DENIED; critical «занижен», но есть finding → BLOCK;
      * digest mismatch конверта/отчёта → 422; digest != образа релиза → 422;
      * неизвестный release_id → 404;
  - GET /api/v1/releases/{release_id}/trivy: чтение последнего решения,
    404 при отсутствии.

Запуск:  pytest .../test_artifact_scan_gate.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import AsyncClient
from pydantic import ValidationError

_och = Path(__file__).resolve().parents[2]
if str(_och) not in sys.path:
    sys.path.insert(0, str(_och))

pytestmark = pytest.mark.asyncio

from orchestrator.cosmo.domain.artifact_record import ArtifactRecord  # noqa: E402
from orchestrator.cosmo.domain.artifact_scan import (  # noqa: E402
    TrivyGateAttachRequest,
    TrivyScanReport,
    observed_severity_count,
    resolve_normalized_digests,
    trivy_scan_content_hash,
)
from orchestrator.cosmo.ledger.artifact_record import record_artifact_record  # noqa: E402
from orchestrator.cosmo.ledger.artifact_scan_gate import (  # noqa: E402
    parse_trivy_report,
    run_trivy_scan,
)

import _testpg  # noqa: E402

_PG_URL = _testpg.TEST_PG_URL

DOMAIN = "cos168-dom"
PLAN = "cos168-plan"
APP = "cos168-app"
RUN = "cos168run0001"
REL = "cos168rel0001"
NAME = "cosmo-testapp"
VERSION = "0.1.0"
DIGEST = "sha256:" + "ef" * 32
DIG_B = "sha256:" + "cd" * 32
REGISTRY = "localhost:5100"


class _Proc:
    def __init__(self, rc: int, stdout: str = "", stderr: str = ""):
        self.returncode = rc
        self.stdout = stdout
        self.stderr = stderr


def _scan(digest: str = DIGEST, critical: int = 0,
          findings: list | None = None) -> dict:
    return {
        "scanner_version": "0.50.0",
        "artifact_digest": digest,
        "critical_count": critical,
        "high_count": 0,
        "medium_count": 0,
        "low_count": 0,
        "findings": findings or [],
    }


def _body(digest: str = DIGEST, scan: dict | None = None) -> dict:
    return {
        "artifact_digest": digest,
        "scan": _scan(digest) if scan is None else scan,
    }


async def _ledger_rows(run_id: str) -> list[dict]:
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(_PG_URL, echo=False)
    try:
        async with engine.connect() as conn:
            res = await conn.execute(
                text(
                    "SELECT id, type, content_hash, provenance_json "
                    "FROM evidence_ledger WHERE run_id = :rid "
                    "ORDER BY created_at ASC"
                ),
                {"rid": run_id},
            )
            return [dict(r) for r in res.mappings().all()]
    finally:
        await engine.dispose()


# ── DTO / helpers unit ───────────────────────────────────────────────────

class TestTrivyDto:
    def test_valid_request(self):
        req = TrivyGateAttachRequest.model_validate(_body())
        assert req.artifact_digest == DIGEST
        assert req.scan.critical_count == 0

    def test_malformed_digest_rejected(self):
        with pytest.raises(ValidationError):
            TrivyGateAttachRequest.model_validate(_body(digest="deadbeef"))

    def test_unknown_severity_rejected(self):
        with pytest.raises(ValidationError):
            TrivyGateAttachRequest.model_validate(_body(scan=_scan(findings=[
                {"id": "CVE-1", "severity": "catastrophic", "package_name": "x"},
            ])))

    def test_extra_fields_ignored(self):
        scan = _scan()
        scan["Results"] = [{"Vulnerabilities": []}]
        req = TrivyGateAttachRequest.model_validate(_body(scan=scan))
        assert req.scan.critical_count == 0

    def test_content_hash_deterministic(self):
        a = trivy_scan_content_hash(TrivyGateAttachRequest.model_validate(_body()).scan)
        b = trivy_scan_content_hash(TrivyGateAttachRequest.model_validate(_body()).scan)
        c = trivy_scan_content_hash(
            TrivyGateAttachRequest.model_validate(
                _body(scan=_scan(findings=[
                    {"id": "CVE-2", "severity": "low", "package_name": "x"},
                ]))
            ).scan
        )
        assert a == b
        assert a != c
        assert len(a) == 64

    def test_observed_severity_count(self):
        scan = TrivyScanReport(
            artifact_digest=DIGEST,
            critical_count=0,
            findings=[
                {"id": "CVE-1", "severity": "critical", "package_name": "x"},
                {"id": "CVE-2", "severity": "critical", "package_name": "y"},
                {"id": "CVE-3", "severity": "high", "package_name": "z"},
            ],
        )
        assert observed_severity_count(scan, "critical") == 2
        assert observed_severity_count(scan, "high") == 1

    def test_resolve_normalized_digests(self):
        assert resolve_normalized_digests("sha256:" + "a" * 64, "A" * 64) == (
            "a" * 64, "a" * 64,
        )

    def test_parse_trivy_report(self):
        raw = {
            "Results": [
                {"Vulnerabilities": [
                    {"VulnerabilityID": "CVE-2026-0001", "Severity": "CRITICAL",
                     "PkgName": "openssl", "InstalledVersion": "3.0.0",
                     "FixedVersion": "3.0.1"},
                    {"VulnerabilityID": "CVE-2026-0002", "Severity": "HIGH",
                     "PkgName": "curl"},
                ]},
            ]
        }
        report = parse_trivy_report(raw, DIGEST)
        assert report.critical_count == 1
        assert report.high_count == 1
        assert report.medium_count == 0
        assert len(report.findings) == 2
        assert report.findings[0].severity == "critical"
        assert report.findings[0].fixed_version == "3.0.1"

    def test_run_trivy_scan_unavailable_honest(self):
        res = run_trivy_scan("img", trivy_path="__no_such_trivy__")
        assert res.available is False
        assert res.source == "none"
        assert res.reason

    def test_run_trivy_scan_argv_cache_dir(self):
        calls = []

        def fake_run(argv, **kwargs):
            calls.append(argv)
            return _Proc(rc=0, stdout='{"Results": []}')

        res = run_trivy_scan(
            "cosmo-registry-zr:5000/cosmoport/zr/x:0.1.0",
            trivy_path="trivy",
            runner=fake_run,
            cache_dir="/cache/trivy",
        )
        argv = calls[0]
        assert "--cache-dir" in argv
        assert argv[argv.index("--cache-dir") + 1] == "/cache/trivy"
        assert "--skip-db-update" in argv
        assert res.source == "trivy"

    def test_run_trivy_scan_no_insecure_for_external_registry(self):
        calls = []

        def fake_run(argv, **kwargs):
            calls.append(argv)
            return _Proc(rc=0, stdout='{"Results": []}')

        run_trivy_scan(
            "registry.example.com/cosmoport/zr/x:0.1.0",
            trivy_path="trivy",
            runner=fake_run,
        )
        assert "--insecure" not in calls[0]

    def test_run_trivy_scan_insecure_for_allowlisted_registry(self):
        calls = []

        def fake_run(argv, **kwargs):
            calls.append(argv)
            return _Proc(rc=0, stdout='{"Results": []}')

        run_trivy_scan(
            "cosmo-registry-zr:5000/cosmoport/zr/x:0.1.0",
            trivy_path="trivy",
            runner=fake_run,
        )
        assert "--insecure" in calls[0]


# ── Route tests ──────────────────────────────────────────────────────────

class TestTrivyGateRoute:
    @pytest_asyncio.fixture(autouse=True)
    async def _seed(self, pg_client: AsyncClient):
        from sqlalchemy import text
        from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

        engine = create_async_engine(_PG_URL, echo=False)
        async with engine.begin() as conn:
            await conn.execute(text(
                "INSERT INTO domains (id, label, forge_type, forge_url, "
                "forge_token_ref, rbac_config, quota_max_runs, "
                "quota_max_storage_gb, quota_max_cpu, created_at) "
                "VALUES (:d, 'cos168', 'gitea', 'http://gitea:3000', 't', "
                "'{}'::jsonb, 50, 100, 8, now()) ON CONFLICT (id) DO NOTHING"
            ), {"d": DOMAIN})
            await conn.execute(text(
                "INSERT INTO apps (id, domain_id, level) VALUES (:a, :d, 0) "
                "ON CONFLICT (id) DO NOTHING"
            ), {"a": APP, "d": DOMAIN})
            await conn.execute(text(
                "INSERT INTO pipeline_plans (id, app_id, level, scope_id, "
                "compiled_hash, compiled_at) VALUES (:p, :a, 'app', :p, 'h', now()) "
                "ON CONFLICT (id) DO NOTHING"
            ), {"p": PLAN, "a": APP})
            await conn.execute(text(
                "INSERT INTO runs (id, plan_id, trigger, domain_id, status, "
                "initiator_user_id, initiator_role, findings_refs, created_at) "
                "VALUES (:r, :p, 'manual', :d, 'succeeded', 'system', 'system', "
                "'[]'::jsonb, now()) ON CONFLICT (id) DO NOTHING"
            ), {"r": RUN, "p": PLAN, "d": DOMAIN})
            await conn.execute(text(
                "INSERT INTO releases (id, domain_id, plan_id, status, "
                "current_zone, version, run_ids, approvals, artifacts, "
                "transfer_history, created_at) VALUES (:rel, :d, :p, 'approved', "
                "'zr', '1.0.0', CAST(:runs AS jsonb), '[]'::jsonb, '[]'::jsonb, "
                "'[]'::jsonb, now()) ON CONFLICT (id) DO NOTHING"
            ), {"rel": REL, "d": DOMAIN, "p": PLAN, "runs": f'["{RUN}"]'})

        session_maker = async_sessionmaker(engine, expire_on_commit=False)
        async with session_maker() as s:
            await record_artifact_record(
                s,
                ArtifactRecord(
                    name=NAME, version=VERSION, digest=DIGEST,
                    registry=REGISTRY, repository="cosmoport", namespace="zr",
                    run_id=RUN,
                ),
            )
        await engine.dispose()

    async def test_clean_scan_pass_and_ledger(self, pg_client: AsyncClient):
        res = await pg_client.post(
            f"/api/v1/releases/{REL}/trivy/attach", json=_body(),
        )
        assert res.status_code == 201, res.text
        body = res.json()
        assert body["accepted"] is True
        assert body["gate_verdict"] == "PASS"
        assert body["clearance"] == "CLEARED"
        assert body["release_id"] == REL
        assert body["artifact_digest"] == "ef" * 32
        assert len(body["scan_digest"]) == 64

        rows = await _ledger_rows(RUN)
        trivy_rows = [r for r in rows if r["provenance_json"].get(
            "source") == "cosmo-trivy-gate"]
        assert len(trivy_rows) == 1
        row = trivy_rows[0]
        assert row["type"] == "decision"
        assert row["content_hash"] == body["scan_digest"]
        prov = row["provenance_json"]
        assert prov["release_id"] == REL
        assert prov["gate_verdict"] == "PASS"
        assert prov["artifact_digest"] == "ef" * 32

    async def test_get_reads_back(self, pg_client: AsyncClient):
        posted = await pg_client.post(
            f"/api/v1/releases/{REL}/trivy/attach", json=_body(),
        )
        assert posted.status_code == 201, posted.text
        res = await pg_client.get(f"/api/v1/releases/{REL}/trivy")
        assert res.status_code == 200, res.text
        assert res.json()["gate_verdict"] == "PASS"
        assert res.json()["scan_digest"] == posted.json()["scan_digest"]

    async def test_critical_blocks(self, pg_client: AsyncClient):
        res = await pg_client.post(
            f"/api/v1/releases/{REL}/trivy/attach",
            json=_body(scan=_scan(critical=1, findings=[
                {"id": "CVE-2026-0001", "severity": "critical",
                 "package_name": "openssl", "installed_version": "3.0.0",
                 "fixed_version": "3.0.1"},
            ])),
        )
        assert res.status_code == 201, res.text
        assert res.json()["gate_verdict"] == "BLOCK"
        assert res.json()["clearance"] == "DENIED"

    async def test_critical_observed_when_reported_zero(
        self, pg_client: AsyncClient,
    ):
        res = await pg_client.post(
            f"/api/v1/releases/{REL}/trivy/attach",
            json=_body(scan=_scan(critical=0, findings=[
                {"id": "CVE-2026-0002", "severity": "critical",
                 "package_name": "zlib"},
            ])),
        )
        assert res.status_code == 201, res.text
        assert res.json()["gate_verdict"] == "BLOCK"

    async def test_envelope_scan_digest_mismatch_422(self, pg_client: AsyncClient):
        res = await pg_client.post(
            f"/api/v1/releases/{REL}/trivy/attach",
            json=_body(digest=DIG_B, scan=_scan(DIGEST)),
        )
        assert res.status_code == 422, res.text

    async def test_record_digest_mismatch_422(self, pg_client: AsyncClient):
        res = await pg_client.post(
            f"/api/v1/releases/{REL}/trivy/attach", json=_body(DIG_B),
        )
        assert res.status_code == 422, res.text

    async def test_unknown_release_404(self, pg_client: AsyncClient):
        res = await pg_client.post(
            "/api/v1/releases/ghost-trivy-rel/trivy/attach", json=_body(),
        )
        assert res.status_code == 404, res.text

    async def test_get_without_decision_404(self, pg_client: AsyncClient):
        res = await pg_client.get(f"/api/v1/releases/{REL}/trivy")
        assert res.status_code == 404, res.text