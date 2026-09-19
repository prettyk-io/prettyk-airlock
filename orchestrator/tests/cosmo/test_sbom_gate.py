# -*- coding: utf-8 -*-
"""COS-138: PK-C-003.6 — Release Bundle SBOM (Syft) & Grype Attestation Gate.

Покрытие:
  - DTO SBOM/Grype: sha256-валидация digest'ов, закрытый severity, ``extra=ignore``
    (внешние отчёты богаче контракта), канонический ``sbom_content_hash``;
  - POST /api/v1/releases/{release_id}/sbom/attach:
      * clean SBOM → gate PASS/clearance CLEARED + крипто-запись в ledger
        (``type='decision'``, ``content_hash == sha256(SBOM)``, привязка release_id);
      * digest mismatch конверта/отчётов → 422;
      * critical > 0 → gate BLOCK/clearance DENIED (аттестация фиксируется);
      * critical «занижен» в отчёте, но есть critical-finding → BLOCK (честно);
      * digest не совпал с digest'ом артефакта релиза → 422;
      * неизвестный release_id → 404;
  - GET /api/v1/releases/{release_id}/sbom: чтение последней аттестации,
    404 при отсутствии.

Запуск:  pytest .../test_sbom_gate.py -q
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import AsyncClient
from pydantic import ValidationError

_orch = Path(__file__).resolve().parents[1]
if str(_orch) not in sys.path:
    sys.path.insert(0, str(_orch))

pytestmark = pytest.mark.asyncio

from orchestrator.cosmo.domain.sbom_scan import (  # noqa: E402
    ReleaseSbomAttachRequest,
    sbom_content_hash,
)

DOMAIN = "sbom-cos138-dom"
PLAN = "sbom-cos138-plan"
RUN_CLEAN = "sbomrun0000001"
RUN_CRIT = "sbomrun0000002"
RUN_PIN = "sbomrun0000003"
REL_CLEAN = "sbomrel0000001"
REL_CRIT = "sbomrel0000002"
REL_PIN = "sbomrel0000003"

_DIG_A = "sha256:" + "a" * 64
_DIG_B = "sha256:" + "b" * 64

_PG_URL = os.getenv(
    "COSMO_DATABASE_URL",
    "postgresql+asyncpg://cosmo:cosmo@127.0.0.1:5433/cosmo_test",
)


def _sbom(digest: str = _DIG_A, **over: object) -> dict:
    body = {
        "format": "spdx-json",
        "syft_version": "1.5.0",
        "artifact_digest": digest,
        "packages_count": 2,
        "packages": [
            {
                "name": "openssl", "version": "3.0.0", "type": "apk",
                "purl": "pkg:apk/openssl@3.0.0", "license": "Apache-2.0",
            },
            {"name": "zlib", "version": "1.2.11", "type": "apk"},
        ],
    }
    body.update(over)
    return body


def _grype(digest: str = _DIG_A, critical: int = 0,
           findings: list | None = None) -> dict:
    return {
        "scanner_version": "0.80.0",
        "artifact_digest": digest,
        "critical_count": critical,
        "high_count": 1 if critical == 0 else 0,
        "medium_count": 0,
        "low_count": 0,
        "findings": findings or [],
    }


def _body(digest: str = _DIG_A, sbom: dict | None = None,
          grype: dict | None = None) -> dict:
    return {
        "sbom": _sbom(digest) if sbom is None else sbom,
        "vulnerabilities": _grype(digest) if grype is None else grype,
        "artifact_digest": digest,
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
                    "FROM evidence_ledger WHERE run_id = :rid ORDER BY created_at ASC"
                ),
                {"rid": run_id},
            )
            return [dict(r) for r in res.mappings().all()]
    finally:
        await engine.dispose()


# ── DTO unit ─────────────────────────────────────────────────────────────

class TestSbomScanDto:
    def test_valid_request(self):
        req = ReleaseSbomAttachRequest.model_validate(_body())
        assert req.sbom.format == "spdx-json"
        assert req.sbom.packages_count == 2
        assert req.vulnerabilities.critical_count == 0

    def test_malformed_artifact_digest_rejected(self):
        with pytest.raises(ValidationError):
            ReleaseSbomAttachRequest.model_validate(_body(digest="deadbeef"))

    def test_unknown_severity_rejected(self):
        with pytest.raises(ValidationError):
            ReleaseSbomAttachRequest.model_validate(_body(
                grype=_grype(findings=[
                    {"id": "CVE-1", "severity": "catastrophic",
                     "package_name": "openssl"},
                ]),
            ))

    def test_extra_tool_fields_ignored(self):
        grype = _grype()
        grype["matches"] = [{"vulnerability": {}}]
        req = ReleaseSbomAttachRequest.model_validate(_body(
            sbom=_sbom(descriptor={"name": "syft"}, artifacts=[{"extra": 1}]),
            grype=grype,
        ))
        assert req.sbom.packages_count == 2

    def test_sbom_content_hash_deterministic(self):
        a = sbom_content_hash(ReleaseSbomAttachRequest.model_validate(_body()).sbom)
        b = sbom_content_hash(ReleaseSbomAttachRequest.model_validate(_body()).sbom)
        changed = _body(sbom=_sbom(packages=[
            {"name": "openssl", "version": "3.0.1", "type": "apk"},
        ]))
        c = sbom_content_hash(
            ReleaseSbomAttachRequest.model_validate(changed).sbom
        )
        assert a == b
        assert a != c


# ── Route tests ──────────────────────────────────────────────────────────

class TestSbomGateRoute:
    """Route-тесты на реальном PG через pg_client (admin principal)."""

    @pytest_asyncio.fixture(autouse=True)
    async def _seed(self, pg_client: AsyncClient):
        from sqlalchemy import text
        from sqlalchemy.ext.asyncio import create_async_engine

        engine = create_async_engine(_PG_URL, echo=False)
        async with engine.begin() as conn:
            await conn.execute(text(
                "INSERT INTO domains (id, label, forge_type, forge_url, "
                "forge_token_ref, rbac_config, quota_max_runs, "
                "quota_max_storage_gb, quota_max_cpu, created_at) "
                "VALUES (:d, 'sbom-cos138', 'gitea', 'http://gitea:3000', "
                "'t', '{}'::jsonb, 50, 100, 8, now()) "
                "ON CONFLICT (id) DO NOTHING"
            ), {"d": DOMAIN})
            await conn.execute(text(
                "INSERT INTO apps (id, domain_id, level) "
                "VALUES ('sbom-cos138-app', :d, 0) ON CONFLICT (id) DO NOTHING"
            ), {"d": DOMAIN})
            await conn.execute(text(
                "INSERT INTO pipeline_plans (id, app_id, level, scope_id, "
                "compiled_hash, compiled_at) VALUES (:p, 'sbom-cos138-app', "
                "'app', :p, 'h', now()) ON CONFLICT (id) DO NOTHING"
            ), {"p": PLAN})
            for rid in (RUN_CLEAN, RUN_CRIT, RUN_PIN):
                await conn.execute(text(
                    "INSERT INTO runs (id, plan_id, trigger, domain_id, status, "
                    "initiator_user_id, initiator_role, findings_refs, created_at) "
                    "VALUES (:r, :p, 'manual', :d, 'succeeded', 'system', "
                    "'system', '[]'::jsonb, now()) ON CONFLICT (id) DO NOTHING"
                ), {"r": rid, "p": PLAN, "d": DOMAIN})
            for rel, run, arts in (
                (REL_CLEAN, RUN_CLEAN, "[]"),
                (REL_CRIT, RUN_CRIT, "[]"),
                (REL_PIN, RUN_PIN, f'[{{"name": "image.tar", "sha256": "{"a" * 64}"}}]'),
            ):
                await conn.execute(text(
                    "INSERT INTO releases (id, domain_id, plan_id, status, "
                    "current_zone, version, run_ids, approvals, artifacts, "
                    "transfer_history, created_at) VALUES (:rel, :d, :p, "
                    "'deployed', 'zr', '1.0.0', CAST(:rids AS jsonb), "
                    "'[]'::jsonb, CAST(:arts AS jsonb), '[]'::jsonb, now()) "
                    "ON CONFLICT (id) DO NOTHING"
                ), {"rel": rel, "d": DOMAIN, "p": PLAN,
                    "rids": f'["{run}"]', "arts": arts})
        await engine.dispose()

    async def test_clean_sbom_pass_and_ledger(self, pg_client: AsyncClient):
        res = await pg_client.post(
            f"/api/v1/releases/{REL_CLEAN}/sbom/attach", json=_body(),
        )
        assert res.status_code == 201, res.text
        body = res.json()
        assert body["accepted"] is True
        assert body["gate_verdict"] == "PASS"
        assert body["clearance"] == "CLEARED"
        assert body["release_id"] == REL_CLEAN
        assert body["artifact_digest"] == "a" * 64
        assert len(body["sbom_digest"]) == 64

        rows = await _ledger_rows(RUN_CLEAN)
        assert len(rows) == 1
        row = rows[0]
        assert row["type"] == "decision"
        assert row["content_hash"] == body["sbom_digest"]
        prov = row["provenance_json"]
        assert prov["source"] == "cosmo-sbom-gate"
        assert prov["release_id"] == REL_CLEAN
        assert prov["gate_verdict"] == "PASS"
        assert len(prov["provenance_hash"]) == 64

    async def test_clean_sbom_get_reads_back(self, pg_client: AsyncClient):
        posted = await pg_client.post(
            f"/api/v1/releases/{REL_CLEAN}/sbom/attach", json=_body(),
        )
        assert posted.status_code == 201, posted.text
        res = await pg_client.get(f"/api/v1/releases/{REL_CLEAN}/sbom")
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["gate_verdict"] == "PASS"
        assert body["sbom_digest"] == posted.json()["sbom_digest"]

    async def test_digest_mismatch_422(self, pg_client: AsyncClient):
        res = await pg_client.post(
            f"/api/v1/releases/{REL_CLEAN}/sbom/attach",
            json=_body(digest=_DIG_B, sbom=_sbom(_DIG_A), grype=_grype(_DIG_A)),
        )
        assert res.status_code == 422, res.text
        assert len(await _ledger_rows(RUN_CLEAN)) == 0

    async def test_critical_blocks(self, pg_client: AsyncClient):
        res = await pg_client.post(
            f"/api/v1/releases/{REL_CRIT}/sbom/attach",
            json=_body(grype=_grype(critical=1, findings=[
                {"id": "CVE-2026-0001", "severity": "critical",
                 "package_name": "openssl", "installed_version": "3.0.0",
                 "fixed_version": "3.0.1"},
            ])),
        )
        assert res.status_code == 201, res.text
        body = res.json()
        assert body["gate_verdict"] == "BLOCK"
        assert body["clearance"] == "DENIED"

        rows = await _ledger_rows(RUN_CRIT)
        assert len(rows) == 1
        assert rows[0]["provenance_json"]["critical_count"] == 1

    async def test_critical_observed_when_reported_zero(
        self, pg_client: AsyncClient,
    ):
        res = await pg_client.post(
            f"/api/v1/releases/{REL_CRIT}/sbom/attach",
            json=_body(grype=_grype(critical=0, findings=[
                {"id": "CVE-2026-0002", "severity": "critical",
                 "package_name": "zlib"},
            ])),
        )
        assert res.status_code == 201, res.text
        assert res.json()["gate_verdict"] == "BLOCK"

    async def test_release_pinned_digest_mismatch_422(
        self, pg_client: AsyncClient,
    ):
        res = await pg_client.post(
            f"/api/v1/releases/{REL_PIN}/sbom/attach", json=_body(_DIG_B),
        )
        assert res.status_code == 422, res.text

    async def test_unknown_release_404(self, pg_client: AsyncClient):
        res = await pg_client.post(
            "/api/v1/releases/sbom-ghost-rel/sbom/attach", json=_body(),
        )
        assert res.status_code == 404, res.text

    async def test_get_without_attestation_404(self, pg_client: AsyncClient):
        res = await pg_client.get(f"/api/v1/releases/{REL_CLEAN}/sbom")
        assert res.status_code == 404, res.text
