# -*- coding: utf-8 -*-
"""COS-136: Contract A — приём вердиктов PrettyK Hub в Cosmoport.

Покрытие:
  - DTO Contract A: extra=forbid, нормализация вердикта, sha256-якоря;
  - POST /api/v1/hub/verdicts/ingest: приём, дедуп (idempotency_key и
    verdict_hash), 404 на неизвестный run, 422 на дрейф контракта;
  - крипто-запись в evidence_ledger (type='decision', source='prettyk-hub',
    provenance_hash == content_hash);
  - promotion-gate релиза: BLOCK → 400 на transfer, PASS после BLOCK →
    разблокировка (by construction, последний вердикт).

Запуск:  pytest .../test_hub_verdict_ingest.py -q
"""
from __future__ import annotations

import asyncio
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

from orchestrator.cosmo.domain.hub_verdict import (  # noqa: E402
    HubVerdictIngestRequest,
    HubVerdictIngestResponse,
    provenance_hash,
    verdict_hash,
)

DOMAIN = "hub-cos136-dom"
PLAN = "hub-cos136-plan"
RUN_BLOCK = "hubrun0000001"
RUN_PASS = "hubrun0000002"
RUN_NOVERDICT = "hubrun0000003"
REL_BLOCK = "hubrel0000001"
REL_PASS = "hubrel0000002"

_SHA_A = "a" * 64
_SHA_B = "sha256:" + "b" * 64

_PG_URL = os.getenv(
    "COSMO_DATABASE_URL",
    "postgresql+asyncpg://cosmo:cosmo@127.0.0.1:5433/cosmo_test",
)


def _ingest_body(run_id: str, hub_verdict: str, key: str, **over: object) -> dict:
    body = {
        "run_id": run_id,
        "box_verdict": "PASS",
        "hub_verdict": hub_verdict,
        "finding_ids": ["F-1"],
        "evidence_hashes": [_SHA_A, _SHA_B],
        "provenance_metadata": {"scanner": "prettyk-secops-studio"},
        "idempotency_key": key,
    }
    body.update(over)
    return body


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


# COS-145: трансфер требует ДВА крипто-свидетельства (клиренс + SBOM);
# без них маршрут отдаёт 403 fail-closed, а не доходит до Hub-гейта.
async def _grant_clearance(client: AsyncClient, release_id: str, run_id: str) -> None:
    res = await client.post(
        "/api/v1/hub/clearance/ingest",
        json={
            "evaluation_id": f"eval-{release_id}",
            "release_id": release_id,
            "run_id": run_id,
            "evaluated_at": "2026-09-19T12:00:00Z",
            "policy_version": "qg-policy@1",
            "security_execution_verdict": "PASS",
            "act_ref": "artifact://act/cos136",
            "qg_clearance": "PASS_GRANTED",
            "verdict": "PASS",
            "ready_for_transfer": True,
            "qualifying_context": True,
            "ok_to_transfer": True,
        },
    )
    assert res.status_code == 200, res.text
    assert res.json()["transfer_allowed"] is True, res.text


async def _attach_clean_sbom(client: AsyncClient, release_id: str) -> None:
    digest = "a" * 64
    res = await client.post(
        f"/api/v1/releases/{release_id}/sbom/attach",
        json={
            "artifact_digest": digest,
            "sbom": {
                "format": "cyclonedx-json",
                "syft_version": "1.0.0",
                "artifact_digest": digest,
                "packages_count": 1,
                "packages": [{"name": "openssl", "version": "3.0.0"}],
            },
            "vulnerabilities": {
                "scanner_version": "grype-0.80.0",
                "artifact_digest": digest,
                "critical_count": 0,
                "high_count": 0,
                "medium_count": 0,
                "low_count": 0,
                "findings": [],
            },
        },
    )
    assert res.status_code == 201, res.text


# ── DTO unit ─────────────────────────────────────────────────────────────

class TestHubVerdictDto:
    def test_minimal_request(self):
        req = HubVerdictIngestRequest(
            run_id="r1", box_verdict="PASS", hub_verdict="BLOCK",
            idempotency_key="k1",
        )
        assert req.finding_ids == []
        assert req.evidence_hashes == []
        assert req.provenance_metadata == {}

    def test_verdict_normalized_lowercase(self):
        req = HubVerdictIngestRequest(
            run_id="r1", box_verdict="pass", hub_verdict="block",
            idempotency_key="k1",
        )
        assert req.hub_verdict == "BLOCK"
        assert req.box_verdict == "PASS"

    def test_unknown_hub_verdict_rejected(self):
        with pytest.raises(ValidationError):
            HubVerdictIngestRequest(
                run_id="r1", box_verdict="PASS", hub_verdict="MAYBE",
                idempotency_key="k1",
            )

    def test_extra_field_forbidden(self):
        with pytest.raises(ValidationError):
            HubVerdictIngestRequest(
                run_id="r1", box_verdict="PASS", hub_verdict="PASS",
                idempotency_key="k1", hack=1,
            )

    def test_bad_evidence_hash_rejected(self):
        with pytest.raises(ValidationError):
            HubVerdictIngestRequest(
                run_id="r1", box_verdict="PASS", hub_verdict="PASS",
                evidence_hashes=["deadbeef"], idempotency_key="k1",
            )

    def test_blank_run_id_rejected(self):
        with pytest.raises(ValidationError):
            HubVerdictIngestRequest(
                run_id="   ", box_verdict="PASS", hub_verdict="PASS",
                idempotency_key="k1",
            )

    def test_response_extra_forbidden(self):
        with pytest.raises(ValidationError):
            HubVerdictIngestResponse(
                accepted=True, ledger_entry_id="e1", run_id="r1",
                status="PASS", hack=1,
            )

    def test_verdict_hash_deterministic(self):
        assert verdict_hash("r1", "block") == verdict_hash("r1", "BLOCK")
        assert verdict_hash("r1", "PASS") != verdict_hash("r2", "PASS")

    def test_provenance_hash_order_independent(self):
        assert provenance_hash({"a": 1, "b": 2}) == provenance_hash({"b": 2, "a": 1})
        assert provenance_hash({"a": 1}) != provenance_hash({"a": 2})


# ── Route tests ──────────────────────────────────────────────────────────

class TestHubVerdictIngestRoute:
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
                "VALUES (:d, 'hub-cos136', 'gitea', 'http://gitea:3000', "
                "'t', '{}'::jsonb, 50, 100, 8, now()) "
                "ON CONFLICT (id) DO NOTHING"
            ), {"d": DOMAIN})
            await conn.execute(text(
                "INSERT INTO apps (id, domain_id, level) "
                "VALUES ('hub-cos136-app', :d, 0) ON CONFLICT (id) DO NOTHING"
            ), {"d": DOMAIN})
            await conn.execute(text(
                "INSERT INTO pipeline_plans (id, app_id, level, scope_id, "
                "compiled_hash, compiled_at) VALUES (:p, 'hub-cos136-app', "
                "'app', :p, 'h', now()) ON CONFLICT (id) DO NOTHING"
            ), {"p": PLAN})
            for rid in (RUN_BLOCK, RUN_PASS, RUN_NOVERDICT):
                await conn.execute(text(
                    "INSERT INTO runs (id, plan_id, trigger, domain_id, status, "
                    "initiator_user_id, initiator_role, findings_refs, created_at) "
                    "VALUES (:r, :p, 'manual', :d, 'succeeded', 'system', "
                    "'system', '[]'::jsonb, now()) ON CONFLICT (id) DO NOTHING"
                ), {"r": rid, "p": PLAN, "d": DOMAIN})
            await conn.execute(text(
                "INSERT INTO releases (id, domain_id, plan_id, status, "
                "current_zone, version, run_ids, approvals, artifacts, "
                "transfer_history, created_at) VALUES (:rel, :d, :p, "
                "'deployed', 'zr', '1.0.0', CAST(:rids AS jsonb), "
                "'[]'::jsonb, '[]'::jsonb, '[]'::jsonb, now()) "
                "ON CONFLICT (id) DO NOTHING"
            ), {"rel": REL_BLOCK, "d": DOMAIN, "p": PLAN,
                "rids": f'["{RUN_BLOCK}"]'})
            await conn.execute(text(
                "INSERT INTO releases (id, domain_id, plan_id, status, "
                "current_zone, version, run_ids, approvals, artifacts, "
                "transfer_history, created_at) VALUES (:rel, :d, :p, "
                "'deployed', 'zr', '1.0.0', CAST(:rids AS jsonb), "
                "'[]'::jsonb, '[]'::jsonb, '[]'::jsonb, now()) "
                "ON CONFLICT (id) DO NOTHING"
            ), {"rel": REL_PASS, "d": DOMAIN, "p": PLAN,
                "rids": f'["{RUN_PASS}"]'})
        await engine.dispose()

    async def test_ingest_new_verdict(self, pg_client: AsyncClient):
        res = await pg_client.post(
            "/api/v1/hub/verdicts/ingest",
            json=_ingest_body(RUN_BLOCK, "BLOCK", "key-block-1"),
        )
        assert res.status_code == 202, res.text
        body = res.json()
        assert body["accepted"] is True
        assert body["status"] == "BLOCK"
        assert body["run_id"] == RUN_BLOCK
        assert body["ledger_entry_id"]

        rows = await _ledger_rows(RUN_BLOCK)
        assert len(rows) == 1
        row = rows[0]
        assert row["type"] == "decision"
        prov = row["provenance_json"]
        assert prov["source"] == "prettyk-hub"
        assert prov["hub_verdict"] == "BLOCK"
        assert prov["idempotency_key"] == "key-block-1"
        assert prov["provenance_hash"] == row["content_hash"]

    async def test_duplicate_idempotency_key(self, pg_client: AsyncClient):
        first = await pg_client.post(
            "/api/v1/hub/verdicts/ingest",
            json=_ingest_body(RUN_PASS, "PASS", "key-dup"),
        )
        assert first.status_code == 202
        second = await pg_client.post(
            "/api/v1/hub/verdicts/ingest",
            json=_ingest_body(RUN_PASS, "PASS", "key-dup"),
        )
        assert second.status_code == 202
        assert second.json()["status"] == "duplicate"
        assert second.json()["ledger_entry_id"] == first.json()["ledger_entry_id"]
        assert len(await _ledger_rows(RUN_PASS)) == 1

    async def test_duplicate_verdict_hash(self, pg_client: AsyncClient):
        first = await pg_client.post(
            "/api/v1/hub/verdicts/ingest",
            json=_ingest_body(RUN_PASS, "BLOCK", "key-h1"),
        )
        assert first.status_code == 202
        # другой idempotency_key, но тот же (run_id, hub_verdict)
        second = await pg_client.post(
            "/api/v1/hub/verdicts/ingest",
            json=_ingest_body(RUN_PASS, "BLOCK", "key-h2"),
        )
        assert second.status_code == 202
        assert second.json()["status"] == "duplicate"
        assert len(await _ledger_rows(RUN_PASS)) == 1

    async def test_unknown_run_404(self, pg_client: AsyncClient):
        res = await pg_client.post(
            "/api/v1/hub/verdicts/ingest",
            json=_ingest_body("ghost-run", "PASS", "key-ghost"),
        )
        assert res.status_code == 404, res.text

    async def test_contract_drift_422(self, pg_client: AsyncClient):
        bad_verdict = await pg_client.post(
            "/api/v1/hub/verdicts/ingest",
            json=_ingest_body(RUN_PASS, "MAYBE", "key-bad"),
        )
        assert bad_verdict.status_code == 422, bad_verdict.text

        extra = await pg_client.post(
            "/api/v1/hub/verdicts/ingest",
            json=_ingest_body(RUN_PASS, "PASS", "key-x", hack=1),
        )
        assert extra.status_code == 422, extra.text

        bad_hash = await pg_client.post(
            "/api/v1/hub/verdicts/ingest",
            json=_ingest_body(RUN_PASS, "PASS", "key-y",
                              evidence_hashes=["nope"]),
        )
        assert bad_hash.status_code == 422, bad_hash.text

    async def test_promotion_blocked_on_transfer(self, pg_client: AsyncClient):
        # COS-145: сперва закрываем fail-closed авторизацию трансфера —
        # иначе маршрут отдаёт 403 и не доходит до Hub-гейта.
        await _grant_clearance(pg_client, REL_BLOCK, RUN_BLOCK)
        await _attach_clean_sbom(pg_client, REL_BLOCK)

        ingest = await pg_client.post(
            "/api/v1/hub/verdicts/ingest",
            json=_ingest_body(RUN_BLOCK, "BLOCK", "key-transfer-block"),
        )
        assert ingest.status_code == 202, ingest.text

        res = await pg_client.post(
            f"/api/v1/releases/{REL_BLOCK}/transfer",
            json={"initiated_by": "officer-1"},
        )
        assert res.status_code == 400, res.text
        assert "Hub verdict BLOCK" in res.json()["detail"]

    async def test_promotion_unblocked_after_pass(self, pg_client: AsyncClient):
        # COS-145: сперва закрываем fail-closed авторизацию трансфера.
        await _grant_clearance(pg_client, REL_PASS, RUN_PASS)
        await _attach_clean_sbom(pg_client, REL_PASS)

        block = await pg_client.post(
            "/api/v1/hub/verdicts/ingest",
            json=_ingest_body(RUN_PASS, "BLOCK", "key-b"),
        )
        assert block.status_code == 202
        await asyncio.sleep(0.01)
        passed = await pg_client.post(
            "/api/v1/hub/verdicts/ingest",
            json=_ingest_body(RUN_PASS, "PASS", "key-p"),
        )
        assert passed.status_code == 202
        assert passed.json()["status"] == "PASS"

        res = await pg_client.post(
            f"/api/v1/releases/{REL_PASS}/transfer",
            json={"initiated_by": "officer-2"},
        )
        assert res.status_code == 200, res.text
