# -*- coding: utf-8 -*-
"""COS-141: Contract C — Hub Quality Gate clearance callback & transfer gate.

Покрытие:
  - DTO Contract C: полнота полей, строгие enum, ``extra=forbid``, дефолты,
    инвариант ``qualifying_context=false`` и правило авторизации трансфера;
  - крипто-якорь: SHA256 клиренса запечатан в ledger (``content_hash`` ==
    ``provenance_json.clearance_hash``), маркер ``QG_CLEARANCE``;
  - идемпотентность по ``(evaluation_id, release_id)`` и 400 при дрейфе
    ``run_id``/``policy_version``;
  - блокировка трансфера при BLOCKED/REJECTED/ok_to_transfer=False/execution
    FAIL и разрешение при полном согласии политик;
  - GET-эндпоинты (200/404) и «последний клиренс побеждает».

Запуск:  pytest .../test_hub_clearance.py -q
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

from orchestrator.cosmo.domain.hub_clearance import (  # noqa: E402
    HubClearanceIngestRequest,
    HubClearanceIngestResponse,
    clearance_hash,
    compute_transfer_allowed,
)

DOMAIN = "hub-cos141-dom"
PLAN = "hub-cos141-plan"
RUN_MAIN = "hubclrrun0001"
RUN_ALT = "hubclrrun0002"
RUN_SEEDED = (RUN_MAIN, RUN_ALT)

_PG_URL = os.getenv(
    "COSMO_DATABASE_URL",
    "postgresql+asyncpg://cosmo:cosmo@127.0.0.1:5433/cosmo_test",
)


def _body(**over: object) -> dict:
    body = {
        "evaluation_id": "qg-eval-c141",
        "release_id": "hubclrrel0001",
        "run_id": RUN_MAIN,
        "evaluated_at": "2026-09-19T12:00:00Z",
        "policy_version": "qg-policy@1",
        "security_execution_verdict": "PASS",
        "act_ref": "artifact://act/c141",
        "qg_clearance": "PASS_GRANTED",
        "verdict": "PASS",
        "ready_for_transfer": True,
        "qualifying_context": True,
        "ok_to_transfer": True,
        "evidence_refs": ["artifact://evidence/c141"],
        "explanation_ref": "artifact://explain/c141",
        "metadata": {"scanner": "prettyk-hub"},
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
                    "SELECT id, type, content_ref, content_hash, provenance_json "
                    "FROM evidence_ledger WHERE run_id = :rid "
                    "ORDER BY created_at ASC, id ASC"
                ),
                {"rid": run_id},
            )
            return [dict(r) for r in res.mappings().all()]
    finally:
        await engine.dispose()


# ── DTO unit ─────────────────────────────────────────────────────────────


class TestHubClearanceDto:
    def test_valid_request_defaults(self):
        req = HubClearanceIngestRequest(
            evaluation_id="e1", release_id="r1", run_id="run1",
            evaluated_at="2026-09-19T12:00:00Z", policy_version="p@1",
            security_execution_verdict="PASS", act_ref="artifact://a",
            qg_clearance="PASS_GRANTED", verdict="PASS",
            ready_for_transfer=True, qualifying_context=True,
            ok_to_transfer=True,
        )
        assert req.contract_version == "1.0"
        assert req.evidence_refs == []
        assert req.explanation_ref == ""
        assert req.metadata == {}

    def test_contract_version_locked(self):
        with pytest.raises(ValidationError):
            HubClearanceIngestRequest(**_body(contract_version="2.0"))

    def test_extra_field_forbidden(self):
        with pytest.raises(ValidationError):
            HubClearanceIngestRequest(**_body(hack=1))

    def test_bad_clearance_status_rejected(self):
        with pytest.raises(ValidationError):
            HubClearanceIngestRequest(**_body(qg_clearance="MAYBE"))

    def test_bad_verdict_rejected(self):
        with pytest.raises(ValidationError):
            HubClearanceIngestRequest(**_body(verdict="MAYBE"))

    def test_bad_execution_verdict_rejected(self):
        with pytest.raises(ValidationError):
            HubClearanceIngestRequest(
                **_body(security_execution_verdict="MAYBE"),
            )

    def test_blank_required_field_rejected(self):
        with pytest.raises(ValidationError):
            HubClearanceIngestRequest(**_body(run_id="   "))

    def test_blank_evidence_ref_rejected(self):
        with pytest.raises(ValidationError):
            HubClearanceIngestRequest(**_body(evidence_refs=["ok", "  "]))

    def test_response_extra_forbidden(self):
        with pytest.raises(ValidationError):
            HubClearanceIngestResponse(
                status="accepted", evaluation_id="e1", release_id="r1",
                clearance_status="PASS_GRANTED", transfer_allowed=True,
                ledger_entry_id="x", timestamp="t", hack=1,
            )

    def test_qualifying_context_violation_detected(self):
        assert HubClearanceIngestRequest(
            **_body(qualifying_context=False, qg_clearance="PASS_GRANTED"),
        ).violates_qualifying_context() is True
        assert HubClearanceIngestRequest(
            **_body(qualifying_context=False, qg_clearance="BLOCKED",
                    ok_to_transfer=True),
        ).violates_qualifying_context() is True
        assert HubClearanceIngestRequest(
            **_body(qualifying_context=False, qg_clearance="BLOCKED",
                    ok_to_transfer=False),
        ).violates_qualifying_context() is False
        assert HubClearanceIngestRequest(
            **_body(qualifying_context=True),
        ).violates_qualifying_context() is False

    def test_transfer_rule_requires_all_three(self):
        assert compute_transfer_allowed(
            qg_clearance="PASS_GRANTED", ok_to_transfer=True,
            security_execution_verdict="PASS",
        ) is True
        assert compute_transfer_allowed(
            qg_clearance="PASS_GRANTED", ok_to_transfer=True,
            security_execution_verdict="WARN",
        ) is True
        assert compute_transfer_allowed(
            qg_clearance="BLOCKED", ok_to_transfer=True,
            security_execution_verdict="PASS",
        ) is False
        assert compute_transfer_allowed(
            qg_clearance="REJECTED", ok_to_transfer=True,
            security_execution_verdict="PASS",
        ) is False
        assert compute_transfer_allowed(
            qg_clearance="PASS_GRANTED", ok_to_transfer=False,
            security_execution_verdict="PASS",
        ) is False
        assert compute_transfer_allowed(
            qg_clearance="PASS_GRANTED", ok_to_transfer=True,
            security_execution_verdict="FAIL",
        ) is False
        assert compute_transfer_allowed(
            qg_clearance="PASS_GRANTED", ok_to_transfer=True,
            security_execution_verdict="ERROR",
        ) is False

    def test_clearance_hash_deterministic_and_order_independent(self):
        assert clearance_hash({"a": 1, "b": 2}) == clearance_hash({"b": 2, "a": 1})
        assert clearance_hash({"a": 1}) != clearance_hash({"a": 2})


# ── Route tests (pg_client) ──────────────────────────────────────────────


class TestHubClearanceRoutes:
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
                "VALUES (:d, 'hub-cos141', 'gitea', 'http://gitea:3000', "
                "'t', '{}'::jsonb, 50, 100, 8, now()) "
                "ON CONFLICT (id) DO NOTHING"
            ), {"d": DOMAIN})
            await conn.execute(text(
                "INSERT INTO apps (id, domain_id, level) "
                "VALUES ('hub-cos141-app', :d, 0) ON CONFLICT (id) DO NOTHING"
            ), {"d": DOMAIN})
            await conn.execute(text(
                "INSERT INTO pipeline_plans (id, app_id, level, scope_id, "
                "compiled_hash, compiled_at) VALUES (:p, 'hub-cos141-app', "
                "'app', :p, 'h', now()) ON CONFLICT (id) DO NOTHING"
            ), {"p": PLAN})
            for rid in RUN_SEEDED:
                await conn.execute(text(
                    "INSERT INTO runs (id, plan_id, trigger, domain_id, status, "
                    "initiator_user_id, initiator_role, findings_refs, created_at) "
                    "VALUES (:r, :p, 'manual', :d, 'succeeded', 'system', "
                    "'system', '[]'::jsonb, now()) ON CONFLICT (id) DO NOTHING"
                ), {"r": rid, "p": PLAN, "d": DOMAIN})
        await engine.dispose()

    async def test_full_success_clearance(self, pg_client: AsyncClient):
        res = await pg_client.post(
            "/api/v1/hub/clearance/ingest",
            json=_body(evaluation_id="eval-ok", release_id="rel-ok"),
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["status"] == "accepted"
        assert body["clearance_status"] == "PASS_GRANTED"
        assert body["transfer_allowed"] is True
        assert body["ledger_entry_id"]
        assert body["timestamp"]

        rows = await _ledger_rows(RUN_MAIN)
        assert len(rows) == 1
        row = rows[0]
        assert row["type"] == "decision"
        prov = row["provenance_json"]
        assert prov["clearance_type"] == "QG_CLEARANCE"
        assert prov["source"] == "prettyk-hub"
        assert prov["contract"] == "C"
        assert prov["clearance_hash"] == row["content_hash"]
        assert prov["transfer_allowed"] is True
        assert row["content_ref"] == "hub://clearance/rel-ok/eval-ok"

    async def test_blocked_clearance_denies_transfer(self, pg_client: AsyncClient):
        res = await pg_client.post(
            "/api/v1/hub/clearance/ingest",
            json=_body(evaluation_id="eval-block", release_id="rel-block",
                       qg_clearance="BLOCKED", verdict="FAIL",
                       ok_to_transfer=False),
        )
        assert res.status_code == 200, res.text
        assert res.json()["clearance_status"] == "BLOCKED"
        assert res.json()["transfer_allowed"] is False

    async def test_rejected_clearance_denies_transfer(self, pg_client: AsyncClient):
        res = await pg_client.post(
            "/api/v1/hub/clearance/ingest",
            json=_body(evaluation_id="eval-rej", release_id="rel-rej",
                       qg_clearance="REJECTED", verdict="FAIL",
                       ok_to_transfer=False),
        )
        assert res.status_code == 200, res.text
        assert res.json()["clearance_status"] == "REJECTED"
        assert res.json()["transfer_allowed"] is False

    async def test_ok_to_transfer_false_denies(self, pg_client: AsyncClient):
        res = await pg_client.post(
            "/api/v1/hub/clearance/ingest",
            json=_body(evaluation_id="eval-notok", release_id="rel-notok",
                       ok_to_transfer=False),
        )
        assert res.status_code == 200, res.text
        assert res.json()["clearance_status"] == "PASS_GRANTED"
        assert res.json()["transfer_allowed"] is False

    async def test_execution_fail_denies_even_with_granted(
        self, pg_client: AsyncClient,
    ):
        res = await pg_client.post(
            "/api/v1/hub/clearance/ingest",
            json=_body(evaluation_id="eval-execfail", release_id="rel-execfail",
                       security_execution_verdict="FAIL"),
        )
        assert res.status_code == 200, res.text
        assert res.json()["transfer_allowed"] is False

    async def test_duplicate_returns_same_entry(self, pg_client: AsyncClient):
        payload = _body(evaluation_id="eval-dup", release_id="rel-dup")
        first = await pg_client.post("/api/v1/hub/clearance/ingest", json=payload)
        second = await pg_client.post("/api/v1/hub/clearance/ingest", json=payload)
        assert first.status_code == 200 and second.status_code == 200
        assert second.json()["status"] == "duplicate"
        assert second.json()["ledger_entry_id"] == first.json()["ledger_entry_id"]
        assert len(await _ledger_rows(RUN_MAIN)) == 1

    async def test_drift_run_id_400(self, pg_client: AsyncClient):
        payload = _body(evaluation_id="eval-drift", release_id="rel-drift")
        assert (await pg_client.post(
            "/api/v1/hub/clearance/ingest", json=payload,
        )).status_code == 200
        drifted = dict(payload, run_id=RUN_ALT)
        res = await pg_client.post("/api/v1/hub/clearance/ingest", json=drifted)
        assert res.status_code == 400, res.text
        assert "different immutable context" in res.json()["detail"]

    async def test_drift_policy_version_400(self, pg_client: AsyncClient):
        payload = _body(evaluation_id="eval-drift2", release_id="rel-drift2")
        assert (await pg_client.post(
            "/api/v1/hub/clearance/ingest", json=payload,
        )).status_code == 200
        drifted = dict(payload, policy_version="qg-policy@2")
        res = await pg_client.post("/api/v1/hub/clearance/ingest", json=drifted)
        assert res.status_code == 400, res.text

    async def test_qualifying_context_violation_rejected(self, pg_client: AsyncClient):
        res = await pg_client.post(
            "/api/v1/hub/clearance/ingest",
            json=_body(evaluation_id="eval-qc", release_id="rel-qc",
                       qualifying_context=False, qg_clearance="PASS_GRANTED"),
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["status"] == "rejected"
        assert body["transfer_allowed"] is False

    async def test_unknown_run_404(self, pg_client: AsyncClient):
        res = await pg_client.post(
            "/api/v1/hub/clearance/ingest",
            json=_body(evaluation_id="eval-ghost", release_id="rel-ghost",
                       run_id="ghost-run"),
        )
        assert res.status_code == 404, res.text

    async def test_contract_drift_422(self, pg_client: AsyncClient):
        res = await pg_client.post(
            "/api/v1/hub/clearance/ingest",
            json=_body(evaluation_id="eval-bad", release_id="rel-bad", hack=1),
        )
        assert res.status_code == 422, res.text

    async def test_get_by_release_and_evaluation(self, pg_client: AsyncClient):
        await pg_client.post(
            "/api/v1/hub/clearance/ingest",
            json=_body(evaluation_id="eval-read", release_id="rel-read"),
        )
        by_release = await pg_client.get("/api/v1/hub/clearance/rel-read")
        assert by_release.status_code == 200, by_release.text
        assert by_release.json()["evaluation_id"] == "eval-read"

        by_eval = await pg_client.get(
            "/api/v1/hub/clearance/by-evaluation/eval-read",
        )
        assert by_eval.status_code == 200, by_eval.text
        assert by_eval.json()["release_id"] == "rel-read"

    async def test_get_unknown_404(self, pg_client: AsyncClient):
        assert (await pg_client.get(
            "/api/v1/hub/clearance/rel-none",
        )).status_code == 404
        assert (await pg_client.get(
            "/api/v1/hub/clearance/by-evaluation/eval-none",
        )).status_code == 404

    async def test_latest_clearance_wins(self, pg_client: AsyncClient):
        granted = _body(evaluation_id="eval-latest-1", release_id="rel-latest")
        blocked = _body(evaluation_id="eval-latest-2", release_id="rel-latest",
                        qg_clearance="BLOCKED", verdict="FAIL",
                        ok_to_transfer=False)
        assert (await pg_client.post(
            "/api/v1/hub/clearance/ingest", json=granted,
        )).status_code == 200
        assert (await pg_client.post(
            "/api/v1/hub/clearance/ingest", json=blocked,
        )).status_code == 200

        latest = await pg_client.get("/api/v1/hub/clearance/rel-latest")
        assert latest.status_code == 200, latest.text
        assert latest.json()["clearance_status"] == "BLOCKED"
        assert latest.json()["transfer_allowed"] is False


# ── Gate manager direct (fail-closed) ────────────────────────────────────


class TestClearanceGateManager:
    async def test_transfer_not_authorized_without_clearance(self):
        from sqlalchemy.ext.asyncio import (
            async_sessionmaker, create_async_engine,
        )

        from orchestrator.cosmo.ledger.hub_clearance_gate import (
            release_transfer_allowed,
        )

        engine = create_async_engine(_PG_URL, echo=False)
        try:
            session_maker = async_sessionmaker(engine, expire_on_commit=False)
            async with session_maker() as session:
                allowed = await release_transfer_allowed(
                    session, "rel-never-cleared-c141",
                )
            assert allowed is False
        finally:
            await engine.dispose()
