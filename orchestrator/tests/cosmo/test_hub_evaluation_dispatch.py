# -*- coding: utf-8 -*-
"""COS-139 + COS-153: Contract B — Control Plane → PrettyK Hub evaluation.

Покрытие:
  - DTO Contract B: обязательные поля, ``extra=forbid``, версия контракта,
    нормализация дайджеста/зоны/вердикта, immutable identity;
  - clearance gate: Studio-вердикт обязан быть PASS; ``qualifying_context=False``
    запрещён для production-профилей (``zpe`` / ``production``);
  - HubEvaluationClient: адрес/``COSMO_HUB_URL``, bounded retry с backoff для
    transport/таймаута/429/5xx, немедленный отказ на 4xx, honest-ошибка;
  - HubEvaluationDispatcher: идемпотентность по ``evaluation_id``, дрейф
    контекста, запись события в audit trail (success/failed/duplicate);
  - routes: POST dispatch (202/400/404/502), GET status (200/404);
  - COS-153 durable read-through: исход отправки якорится в
    ``evidence_ledger`` (маркер ``evaluation_type=HUB_EVALUATION_DISPATCH``),
    ``GET`` переживает рестарт процесса, latest wins, in-memory реестра нет.

Запуск:  pytest .../test_hub_evaluation_dispatch.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from httpx import AsyncClient
from pydantic import ValidationError

_orch = Path(__file__).resolve().parents[1]
if str(_orch) not in sys.path:
    sys.path.insert(0, str(_orch))

pytestmark = pytest.mark.asyncio

import _testpg  # noqa: E402  (test dir on sys.path, см. conftest)

from _durable_probe import get_in_fresh_process  # noqa: E402

from orchestrator.cosmo.adapters.hub_client import (  # noqa: E402
    DEFAULT_HUB_URL,
    DEFAULT_MAX_ATTEMPTS,
    HUB_URL_ENV,
    HubDispatchError,
    HubEvaluationClient,
    evaluations_url,
)
from orchestrator.cosmo.api.main import app  # noqa: E402
from orchestrator.cosmo.api.routes.audit import _AUDIT_LOG_RECORDS  # noqa: E402
from orchestrator.cosmo.api.routes.hub import get_hub_dispatcher  # noqa: E402
from orchestrator.cosmo.control_plane.hub_dispatcher import (  # noqa: E402
    HUB_EVALUATION_AUDIT_ACTION,
    HubEvaluationDispatcher,
)
from orchestrator.cosmo.domain.hub_evaluation import (  # noqa: E402
    HUB_EVALUATION_LEDGER_TYPE,
    HubEvaluationContextError,
    HubEvaluationRequest,
    HubSecurityExecution,
    evaluation_identity,
    is_production_context,
)
from orchestrator.cosmo.ledger.hub_evaluation_ledger import (  # noqa: E402
    DISPATCH_OUTCOME_DISPATCHED,
    DispatchRecord,
    HubEvaluationLedger,
)

_SHA = "sha256:" + "c" * 64

_PG_URL = _testpg.TEST_PG_URL

DOMAIN = "hub-eval-dom"
APP = "hub-eval-app"
PLAN = "hub-eval-plan"
RUN = "run-1"


def _execution(verdict: str = "PASS") -> dict:
    return {
        "studio_run_id": "studio-1",
        "verdict": verdict,
        "act_ref": "artifact://act/1",
        "evidence_refs": ["artifact://evidence/1"],
    }


def _request_body(**over: object) -> dict:
    body = {
        "request_id": "qg-request-1",
        "evaluation_id": "qg-eval-1",
        "project_id": "project-1",
        "application_ids": ["app-1"],
        "release_id": "release-1",
        "run_id": RUN,
        "build_id": "build-1",
        "artifact_digest": _SHA,
        "release_profile": "ordinary@1",
        "target_zone": "zr",
        "qualifying_context": True,
        "security_execution": _execution(),
    }
    body.update(over)
    return body


def _audit_events(evaluation_id: str) -> list:
    return [
        e for e in _AUDIT_LOG_RECORDS
        if e.action == HUB_EVALUATION_AUDIT_ACTION
        and e.resource_id == evaluation_id
    ]


async def _ledger_rows(evaluation_id: str) -> list[dict]:
    """Durable-якоря Contract B по ``evaluation_id`` (ASC — порядок записи)."""
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(_PG_URL, echo=False)
    try:
        async with engine.connect() as conn:
            res = await conn.execute(
                text(
                    "SELECT id, type, content_hash, content_ref, provenance_json "
                    "FROM evidence_ledger "
                    "WHERE provenance_json->>'evaluation_id' = :eid "
                    "ORDER BY created_at ASC, id ASC"
                ),
                {"eid": evaluation_id},
            )
            return [dict(r) for r in res.mappings().all()]
    finally:
        await engine.dispose()


async def _seed_run() -> None:
    """Домен/app/план/прогон — FK ``evidence_ledger.run_id`` для якоря."""
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(_PG_URL, echo=False)
    try:
        async with engine.begin() as conn:
            await conn.execute(text(
                "INSERT INTO domains (id, label, forge_type, forge_url, "
                "forge_token_ref, rbac_config, quota_max_runs, "
                "quota_max_storage_gb, quota_max_cpu, created_at) "
                "VALUES (:d, 'hub-eval', 'gitea', 'http://gitea:3000', "
                "'t', '{}'::jsonb, 50, 100, 8, now()) "
                "ON CONFLICT (id) DO NOTHING"
            ), {"d": DOMAIN})
            await conn.execute(text(
                "INSERT INTO apps (id, domain_id, level) "
                "VALUES (:a, :d, 0) ON CONFLICT (id) DO NOTHING"
            ), {"a": APP, "d": DOMAIN})
            await conn.execute(text(
                "INSERT INTO pipeline_plans (id, app_id, level, scope_id, "
                "compiled_hash, compiled_at) VALUES (:p, :a, 'app', :p, "
                "'h', now()) ON CONFLICT (id) DO NOTHING"
            ), {"p": PLAN, "a": APP})
            await conn.execute(text(
                "INSERT INTO runs (id, plan_id, trigger, domain_id, status, "
                "initiator_user_id, initiator_role, findings_refs, created_at) "
                "VALUES (:r, :p, 'manual', :d, 'succeeded', 'system', "
                "'system', '[]'::jsonb, now()) ON CONFLICT (id) DO NOTHING"
            ), {"r": RUN, "p": PLAN, "d": DOMAIN})
    finally:
        await engine.dispose()


class _FakeLedger:
    """In-memory double для unit-тестов диспетчера (без БД).

    Повторяет семантику ``HubEvaluationLedger``: якорь на state-changing
    исходы, ``latest wins``, отдельный поиск успешной отправки.
    """

    def __init__(self) -> None:
        self.rows: list[tuple] = []

    async def record(self, session, *, request, response, outcome,
                     hub_response=None, actor="system") -> None:
        self.rows.append((request, response, outcome, hub_response or {}))

    async def latest_for_evaluation(self, session, evaluation_id):
        for request, response, _outcome, hub_response in reversed(self.rows):
            if request.evaluation_id == evaluation_id:
                return DispatchRecord(
                    response=response,
                    identity=evaluation_identity(request),
                    hub_response=hub_response,
                )
        return None

    async def latest_dispatched_for_evaluation(self, session, evaluation_id):
        for request, response, outcome, hub_response in reversed(self.rows):
            if (request.evaluation_id == evaluation_id
                    and outcome == DISPATCH_OUTCOME_DISPATCHED):
                return DispatchRecord(
                    response=response,
                    identity=evaluation_identity(request),
                    hub_response=hub_response,
                )
        return None


# ── DTO unit ─────────────────────────────────────────────────────────────


class TestHubEvaluationDto:
    def test_valid_request_defaults(self):
        req = HubEvaluationRequest(**_request_body())
        assert req.contract_version == "1.0"
        assert req.artifact_digest == _SHA
        assert req.target_zone == "zr"

    def test_unknown_contract_version_rejected(self):
        with pytest.raises(ValidationError):
            HubEvaluationRequest(**_request_body(contract_version="2.0"))

    def test_extra_field_forbidden(self):
        with pytest.raises(ValidationError):
            HubEvaluationRequest(**_request_body(hack=1))

    def test_bare_digest_normalized(self):
        req = HubEvaluationRequest(**_request_body(artifact_digest="d" * 64))
        assert req.artifact_digest == "sha256:" + "d" * 64

    def test_bad_digest_rejected(self):
        with pytest.raises(ValidationError):
            HubEvaluationRequest(**_request_body(artifact_digest="not-a-digest"))

    def test_blank_release_id_rejected(self):
        with pytest.raises(ValidationError):
            HubEvaluationRequest(**_request_body(release_id="   "))

    def test_empty_application_ids_rejected(self):
        with pytest.raises(ValidationError):
            HubEvaluationRequest(**_request_body(application_ids=[]))

    def test_unknown_zone_rejected(self):
        with pytest.raises(ValidationError):
            HubEvaluationRequest(**_request_body(target_zone="mars"))

    def test_execution_verdict_normalized(self):
        req = HubEvaluationRequest(
            **_request_body(security_execution=_execution("pass")),
        )
        assert req.security_execution.verdict == "PASS"

    def test_empty_evidence_refs_rejected(self):
        with pytest.raises(ValidationError):
            HubSecurityExecution(
                studio_run_id="studio-1", verdict="PASS",
                act_ref="artifact://act/1", evidence_refs=[],
            )

    def test_identity_is_exact_context(self):
        req = HubEvaluationRequest(**_request_body())
        assert evaluation_identity(req) == {
            "release_id": "release-1",
            "run_id": RUN,
            "build_id": "build-1",
            "artifact_digest": _SHA,
        }

    def test_production_context_detection(self):
        assert is_production_context("production@1", "zr") is True
        assert is_production_context("prod@2", "zr") is True
        assert is_production_context("ordinary@1", "zpe") is True
        assert is_production_context("ordinary@1", "zr") is False


class TestClearanceGate:
    def test_non_pass_studio_verdict_blocked(self):
        req = HubEvaluationRequest(
            **_request_body(security_execution=_execution("WARN")),
        )
        with pytest.raises(HubEvaluationContextError):
            req.enforce_required_context()

    def test_qualifying_context_false_production_blocked(self):
        req = HubEvaluationRequest(
            **_request_body(qualifying_context=False, target_zone="zpe"),
        )
        with pytest.raises(HubEvaluationContextError):
            req.enforce_required_context()

    def test_qualifying_context_false_production_profile_blocked(self):
        req = HubEvaluationRequest(
            **_request_body(qualifying_context=False,
                            release_profile="production@1"),
        )
        with pytest.raises(HubEvaluationContextError):
            req.enforce_required_context()

    def test_qualifying_context_false_ordinary_allowed(self):
        req = HubEvaluationRequest(
            **_request_body(qualifying_context=False, target_zone="zt"),
        )
        req.enforce_required_context()  # не бросает


# ── Client unit (httpx.MockTransport) ────────────────────────────────────


def _client(handler, **kwargs) -> HubEvaluationClient:
    kwargs.setdefault("backoff_base", 0.0)
    return HubEvaluationClient(
        transport=httpx.MockTransport(handler), **kwargs,
    )


class TestHubEvaluationClient:
    async def test_url_normalization(self):
        assert evaluations_url("http://hub:8000") == \
            "http://hub:8000/api/v1/evaluations"
        assert evaluations_url("http://hub:8000/api/v1") == \
            "http://hub:8000/api/v1/evaluations"
        assert evaluations_url("http://hub:8000/api/v1/evaluations") == \
            "http://hub:8000/api/v1/evaluations"

    async def test_default_url_from_env(self, monkeypatch):
        monkeypatch.setenv(HUB_URL_ENV, "http://hub.internal:9000")
        assert HubEvaluationClient().url == \
            "http://hub.internal:9000/api/v1/evaluations"

    async def test_default_url_constant(self, monkeypatch):
        monkeypatch.delenv(HUB_URL_ENV, raising=False)
        assert HubEvaluationClient().url == DEFAULT_HUB_URL

    async def test_dispatch_success_posts_envelope(self):
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(200, json={"qg_clearance": "PASS_GRANTED"})

        client = _client(handler)
        out = await client.dispatch({"evaluation_id": "qg-eval-1"})
        assert out["qg_clearance"] == "PASS_GRANTED"
        assert len(seen) == 1
        assert seen[0].method == "POST"
        assert str(seen[0].url) == client.url

    async def test_5xx_retried_then_success(self):
        attempts = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            attempts["n"] += 1
            if attempts["n"] == 1:
                return httpx.Response(503, text="unavailable")
            return httpx.Response(200, json={"status": "accepted"})

        client = _client(handler)
        out = await client.dispatch({})
        assert out["status"] == "accepted"
        assert attempts["n"] == 2

    async def test_429_retried(self):
        attempts = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            attempts["n"] += 1
            if attempts["n"] == 1:
                return httpx.Response(429, text="slow down")
            return httpx.Response(200, json={"status": "accepted"})

        client = _client(handler)
        await client.dispatch({})
        assert attempts["n"] == 2

    async def test_transport_error_retried_then_success(self):
        attempts = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            attempts["n"] += 1
            if attempts["n"] == 1:
                raise httpx.ConnectError("boom")
            return httpx.Response(200, json={"status": "accepted"})

        client = _client(handler)
        await client.dispatch({})
        assert attempts["n"] == 2

    async def test_exhausted_retries_raise_retryable(self):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("down")

        client = _client(handler)
        with pytest.raises(HubDispatchError) as ei:
            await client.dispatch({})
        assert ei.value.retryable is True
        assert ei.value.attempts == DEFAULT_MAX_ATTEMPTS

    async def test_4xx_not_retried(self):
        attempts = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            attempts["n"] += 1
            return httpx.Response(422, text="bad envelope")

        client = _client(handler)
        with pytest.raises(HubDispatchError) as ei:
            await client.dispatch({})
        assert ei.value.retryable is False
        assert ei.value.status_code == 422
        assert attempts["n"] == 1

    async def test_non_json_response_rejected(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text="<html>nope</html>")

        client = _client(handler)
        with pytest.raises(HubDispatchError):
            await client.dispatch({})


# ── Dispatcher unit (no DB, fake ledger) ─────────────────────────────────


def _ok_handler(calls: list[httpx.Request]):
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"qg_clearance": "PASS_GRANTED"})
    return handler


def _dispatcher(calls: list[httpx.Request]) -> HubEvaluationDispatcher:
    return HubEvaluationDispatcher(
        client=_client(_ok_handler(calls)), ledger=_FakeLedger(),
    )


class TestHubEvaluationDispatcher:
    async def test_dispatch_success_and_audit(self):
        calls: list[httpx.Request] = []
        dispatcher = _dispatcher(calls)
        req = HubEvaluationRequest(**_request_body(evaluation_id="qg-eval-ok"))

        res = await dispatcher.dispatch(req, session=None, actor="officer-1")
        assert res.dispatched is True
        assert res.status == "PASS_GRANTED"
        assert res.evaluation_id == "qg-eval-ok"
        assert res.dispatched_at
        assert len(calls) == 1

        events = _audit_events("qg-eval-ok")
        assert len(events) == 1
        assert events[0].status == "success"
        assert events[0].user_id == "officer-1"

    async def test_idempotent_by_evaluation_id(self):
        calls: list[httpx.Request] = []
        dispatcher = _dispatcher(calls)
        req = HubEvaluationRequest(**_request_body(evaluation_id="qg-eval-dup"))

        first = await dispatcher.dispatch(req, session=None)
        second = await dispatcher.dispatch(req, session=None)
        assert first.dispatched is True
        assert second.dispatched is False
        assert second.status == "duplicate"
        assert len(calls) == 1  # вторая отправка не состоялась
        assert len(_audit_events("qg-eval-dup")) == 2

    async def test_context_drift_rejected(self):
        calls: list[httpx.Request] = []
        dispatcher = _dispatcher(calls)
        await dispatcher.dispatch(
            HubEvaluationRequest(**_request_body(evaluation_id="qg-eval-drift")),
            session=None,
        )
        drifted = HubEvaluationRequest(
            **_request_body(evaluation_id="qg-eval-drift", release_id="release-2"),
        )
        with pytest.raises(HubEvaluationContextError):
            await dispatcher.dispatch(drifted, session=None)
        assert len(calls) == 1

    async def test_production_without_qualifying_context_not_sent(self):
        calls: list[httpx.Request] = []
        dispatcher = _dispatcher(calls)
        req = HubEvaluationRequest(
            **_request_body(evaluation_id="qg-eval-prod",
                            qualifying_context=False, target_zone="zpe"),
        )
        with pytest.raises(HubEvaluationContextError):
            await dispatcher.dispatch(req, session=None)
        assert calls == []  # clearance gate сработал до I/O

    async def test_failed_dispatch_recorded_in_audit_and_ledger(self):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("hub down")

        ledger = _FakeLedger()
        dispatcher = HubEvaluationDispatcher(
            client=_client(handler), ledger=ledger,
        )
        req = HubEvaluationRequest(**_request_body(evaluation_id="qg-eval-fail"))
        with pytest.raises(HubDispatchError):
            await dispatcher.dispatch(req, session=None, actor="officer-2")

        events = _audit_events("qg-eval-fail")
        assert len(events) == 1
        assert events[0].status == "failed"
        assert events[0].details_json["error"]

        # COS-153: сбой durable (не PASS) — GET вернёт failed, не 404.
        failed = await dispatcher.get(None, "qg-eval-fail")
        assert failed is not None
        assert failed.status == "failed"
        assert failed.dispatched is False

    async def test_failed_dispatch_does_not_block_retry(self):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("hub down")

        ledger = _FakeLedger()
        failing = HubEvaluationDispatcher(
            client=_client(handler), ledger=ledger,
        )
        req = HubEvaluationRequest(**_request_body(evaluation_id="qg-eval-retry"))
        with pytest.raises(HubDispatchError):
            await failing.dispatch(req, session=None)

        calls: list[httpx.Request] = []
        healthy = HubEvaluationDispatcher(
            client=_client(_ok_handler(calls)), ledger=ledger,
        )
        res = await healthy.dispatch(req, session=None)
        assert res.dispatched is True
        assert res.status == "PASS_GRANTED"
        assert len(calls) == 1

        latest = await healthy.get(None, "qg-eval-retry")
        assert latest.status == "PASS_GRANTED"

    async def test_get_unknown_returns_none(self):
        dispatcher = _dispatcher([])
        assert await dispatcher.get(None, "never-sent") is None

    def test_read_path_has_no_in_memory_registry(self):
        """COS-153: реестр-дубликат удалён — читаем только durable-источник."""
        from orchestrator.cosmo.control_plane import hub_dispatcher

        assert not hasattr(hub_dispatcher, "_DISPATCH_REGISTRY")
        assert not hasattr(hub_dispatcher, "reset_dispatch_registry")


# ── Route tests (pg_client + dispatcher override) ────────────────────────


@pytest_asyncio.fixture()
async def hub_client(pg_client: AsyncClient):
    """pg_client с подменённым диспетчером Contract B (MockTransport)."""
    calls: list[httpx.Request] = []
    dispatcher = HubEvaluationDispatcher(client=_client(_ok_handler(calls)))
    app.dependency_overrides[get_hub_dispatcher] = lambda: dispatcher
    try:
        yield pg_client, dispatcher, calls
    finally:
        app.dependency_overrides.pop(get_hub_dispatcher, None)


@pytest_asyncio.fixture()
async def hub_failing_client(pg_client: AsyncClient):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="hub down")

    dispatcher = HubEvaluationDispatcher(client=_client(handler))
    app.dependency_overrides[get_hub_dispatcher] = lambda: dispatcher
    try:
        yield pg_client
    finally:
        app.dependency_overrides.pop(get_hub_dispatcher, None)


class TestHubEvaluationRoutes:
    """Route-тесты на реальном PG (durable-якорь в evidence_ledger)."""

    @pytest_asyncio.fixture(autouse=True)
    async def _seed(self, pg_client: AsyncClient):
        await _seed_run()

    async def test_dispatch_202(self, hub_client):
        client, dispatcher, calls = hub_client
        res = await client.post(
            "/api/v1/hub/evaluations/dispatch",
            json=_request_body(evaluation_id="route-eval-1"),
        )
        assert res.status_code == 202, res.text
        body = res.json()
        assert body["dispatched"] is True
        assert body["evaluation_id"] == "route-eval-1"
        assert body["status"] == "PASS_GRANTED"
        assert len(calls) == 1

    async def test_dispatch_duplicate(self, hub_client):
        client, _, calls = hub_client
        payload = _request_body(evaluation_id="route-eval-dup")
        first = await client.post("/api/v1/hub/evaluations/dispatch", json=payload)
        second = await client.post("/api/v1/hub/evaluations/dispatch", json=payload)
        assert first.status_code == 202
        assert second.status_code == 202
        assert second.json()["status"] == "duplicate"
        assert len(calls) == 1

    async def test_dispatch_production_gate_400(self, hub_client):
        client, _, calls = hub_client
        res = await client.post(
            "/api/v1/hub/evaluations/dispatch",
            json=_request_body(evaluation_id="route-eval-prod",
                               qualifying_context=False, target_zone="zpe"),
        )
        assert res.status_code == 400, res.text
        assert "qualifying_context" in res.json()["detail"]
        assert calls == []

    async def test_dispatch_non_pass_execution_400(self, hub_client):
        client, _, _ = hub_client
        res = await client.post(
            "/api/v1/hub/evaluations/dispatch",
            json=_request_body(evaluation_id="route-eval-warn",
                               security_execution=_execution("WARN")),
        )
        assert res.status_code == 400, res.text
        assert "PASS" in res.json()["detail"]

    async def test_dispatch_contract_drift_422(self, hub_client):
        client, _, _ = hub_client
        res = await client.post(
            "/api/v1/hub/evaluations/dispatch",
            json=_request_body(evaluation_id="route-eval-bad", hack=1),
        )
        assert res.status_code == 422, res.text

    async def test_dispatch_unknown_run_404(self, hub_client):
        """COS-153: якорь требует существующий run (FK ledger) — 404 до I/O."""
        client, _, calls = hub_client
        res = await client.post(
            "/api/v1/hub/evaluations/dispatch",
            json=_request_body(evaluation_id="route-eval-ghost",
                               run_id="ghost-run"),
        )
        assert res.status_code == 404, res.text
        assert "ghost-run" in res.json()["detail"]
        assert calls == []

    async def test_dispatch_hub_down_502(self, hub_failing_client):
        res = await hub_failing_client.post(
            "/api/v1/hub/evaluations/dispatch",
            json=_request_body(evaluation_id="route-eval-502"),
        )
        assert res.status_code == 502, res.text

    async def test_get_status_200_and_404(self, hub_client):
        client, _, _ = hub_client
        await client.post(
            "/api/v1/hub/evaluations/dispatch",
            json=_request_body(evaluation_id="route-eval-read"),
        )
        ok = await client.get("/api/v1/hub/evaluations/route-eval-read")
        assert ok.status_code == 200, ok.text
        assert ok.json()["evaluation_id"] == "route-eval-read"

        missing = await client.get("/api/v1/hub/evaluations/route-eval-none")
        assert missing.status_code == 404, missing.text

    async def test_dispatch_anchors_ledger(self, hub_client):
        """COS-153: исход отправки запечатан durable-якорем."""
        client, _, _ = hub_client
        await client.post(
            "/api/v1/hub/evaluations/dispatch",
            json=_request_body(evaluation_id="route-eval-anchor"),
        )
        rows = await _ledger_rows("route-eval-anchor")
        assert len(rows) == 1
        prov = rows[0]["provenance_json"]
        assert prov["evaluation_type"] == HUB_EVALUATION_LEDGER_TYPE
        assert prov["outcome"] == DISPATCH_OUTCOME_DISPATCHED
        assert prov["evaluation_id"] == "route-eval-anchor"
        assert prov["source"] == "prettyk-hub"
        assert prov["response_status"] == "PASS_GRANTED"
        assert rows[0]["type"] == "decision"
        assert rows[0]["content_hash"] == prov["dispatch_hash"]

    async def test_duplicate_does_not_add_anchor(self, hub_client):
        """COS-153: дубликат состояние не меняет — второго якоря нет."""
        client, _, calls = hub_client
        payload = _request_body(evaluation_id="route-eval-dupanchor")
        await client.post("/api/v1/hub/evaluations/dispatch", json=payload)
        await client.post("/api/v1/hub/evaluations/dispatch", json=payload)
        assert len(calls) == 1
        assert len(await _ledger_rows("route-eval-dupanchor")) == 1

    async def test_failed_dispatch_is_durable_latest_wins(self, pg_client):
        """COS-153: сбой durable; успешный retry перекрывает (latest wins)."""
        eval_id = "route-eval-retry"

        def _down(request: httpx.Request) -> httpx.Response:
            return httpx.Response(503, text="hub down")

        failing = HubEvaluationDispatcher(
            client=_client(_down), ledger=HubEvaluationLedger(),
        )
        app.dependency_overrides[get_hub_dispatcher] = lambda: failing
        try:
            bad = await pg_client.post(
                "/api/v1/hub/evaluations/dispatch",
                json=_request_body(evaluation_id=eval_id),
            )
            assert bad.status_code == 502, bad.text
        finally:
            app.dependency_overrides.pop(get_hub_dispatcher, None)

        read = await pg_client.get(f"/api/v1/hub/evaluations/{eval_id}")
        assert read.status_code == 200, read.text
        assert read.json()["status"] == "failed"
        assert read.json()["dispatched"] is False

        calls: list[httpx.Request] = []
        healthy = HubEvaluationDispatcher(
            client=_client(_ok_handler(calls)), ledger=HubEvaluationLedger(),
        )
        app.dependency_overrides[get_hub_dispatcher] = lambda: healthy
        try:
            good = await pg_client.post(
                "/api/v1/hub/evaluations/dispatch",
                json=_request_body(evaluation_id=eval_id),
            )
            assert good.status_code == 202, good.text
            assert good.json()["dispatched"] is True
        finally:
            app.dependency_overrides.pop(get_hub_dispatcher, None)

        latest = await pg_client.get(f"/api/v1/hub/evaluations/{eval_id}")
        assert latest.status_code == 200, latest.text
        assert latest.json()["status"] == "PASS_GRANTED"

    async def test_get_survives_process_restart(self, hub_client):
        """COS-153: свежий процесс видит durable-статус из ledger."""
        client, _, _ = hub_client
        posted = await client.post(
            "/api/v1/hub/evaluations/dispatch",
            json=_request_body(evaluation_id="route-eval-durable"),
        )
        assert posted.status_code == 202, posted.text
        assert posted.json()["status"] == "PASS_GRANTED"

        status, body = get_in_fresh_process(
            "/api/v1/hub/evaluations/route-eval-durable", _PG_URL,
        )
        assert status == 200, body
        assert body["evaluation_id"] == "route-eval-durable"
        assert body["status"] == "PASS_GRANTED"
        assert body["dispatched"] is True

    async def test_get_unknown_in_fresh_process_404(self, hub_client):
        status, body = get_in_fresh_process(
            "/api/v1/hub/evaluations/route-eval-ghost-id", _PG_URL,
        )
        assert status == 404, body
