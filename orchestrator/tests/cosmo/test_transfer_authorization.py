# -*- coding: utf-8 -*-
"""COS-145/COS-146: авторизация межзонного трансфера и CAS-guard.

Покрытие:
  - DTO: ``TransferAuthorizationDecision`` / ``TransferReplayResponse``
    (``extra=forbid``, blank-reject), ``TransferTransition`` и константы;
  - guard (pure): ``evaluate_transition`` PROCEED/REPLAY/CONFLICT,
    ``replay_payload``, ``bypass_permitted`` (admin × env × опт-ин);
  - guard (PG): ``authorize`` fail-closed — нужны оба свидетельства
    (Quality Gate clearance + SBOM-аттестация), иначе отказ; сбой чтения
    свидетельства — тоже отказ; причина отказа объяснима;
  - маршрут ``/{id}/transfer`` и ``/{id}/transfer-v2``: 403 без клиренса,
    403 без SBOM, 403 при SBOM BLOCK, 200 при полном согласии;
  - COS-146 CAS: 409 при расхождении ``expected_current_zone``;
    идемпотентный replay — 200 ``duplicate_success`` без дублей истории;
  - audit: ``release_transfer_authorization`` на каждое решение,
    ``BYPASS_ATTEMPT`` на каждую попытку обхода (включая отклонённую);
    обход разрешён только system admin в dev-окружении.

Запуск:  pytest .../test_transfer_authorization.py -q
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import pytest_asyncio
from httpx import AsyncClient
from pydantic import ValidationError

_orch = Path(__file__).resolve().parents[1]
if str(_orch) not in sys.path:
    sys.path.insert(0, str(_orch))

pytestmark = pytest.mark.asyncio

from orchestrator.cosmo.domain.transfer_authorization import (  # noqa: E402
    CLEARANCE_AUTHORIZED_STATUS,
    SBOM_AUTHORIZED_VERDICT,
    STATUS_CHECK_FAILED,
    STATUS_MISSING,
    TRANSFER_AUTHORIZATION_AUDIT_ACTION,
    TRANSFER_BYPASS_AUDIT_ACTION,
    TRANSFER_REPLAY_STATUS,
    TransferAuthorizationDecision,
    TransferReplayResponse,
    TransferTransition,
)
from orchestrator.cosmo.control_plane.transfer_guard import (  # noqa: E402
    BYPASS_ENV_VALUES,
    BYPASS_OPT_IN_VAR,
    ENV_NAME_VAR,
    ReleaseTransferGuard,
    bypass_permitted,
)

DOMAIN = "test"
APP = "ta-cos145-app"
PLAN = "ta-cos145-plan"

RUN_MAIN = "tarun000000001"
RUN_ALT = "tarun000000002"

REL_DENY = "tarel0000000001"
REL_CLEAR_ONLY = "tarel0000000002"
REL_SBOM_BLOCK = "tarel0000000003"
REL_OK = "tarel0000000004"
REL_OK_V2 = "tarel0000000005"
REL_CONFLICT = "tarel0000000006"
REL_REPLAY = "tarel0000000007"
REL_BYPASS = "tarel0000000008"

_SHA = "a" * 64

_PG_URL = os.getenv(
    "COSMO_DATABASE_URL",
    "postgresql+asyncpg://cosmo:cosmo@127.0.0.1:5433/cosmo_test",
)


def _clearance_body(
    release_id: str,
    run_id: str,
    evaluation_id: str,
    *,
    granted: bool = True,
) -> dict:
    return {
        "evaluation_id": evaluation_id,
        "release_id": release_id,
        "run_id": run_id,
        "evaluated_at": "2026-09-19T12:00:00Z",
        "policy_version": "qg-policy@1",
        "security_execution_verdict": "PASS" if granted else "FAIL",
        "act_ref": "artifact://act/cos145",
        "qg_clearance": "PASS_GRANTED" if granted else "BLOCKED",
        "verdict": "PASS" if granted else "FAIL",
        "ready_for_transfer": granted,
        "qualifying_context": True,
        "ok_to_transfer": granted,
    }


def _sbom_body(critical: int = 0, digest: str = _SHA) -> dict:
    findings = [
        {
            "id": f"CVE-2026-{i:04d}",
            "severity": "critical",
            "package_name": "openssl",
            "installed_version": "3.0.0",
        }
        for i in range(critical)
    ]
    return {
        "artifact_digest": digest,
        "sbom": {
            "format": "cyclonedx-json",
            "syft_version": "1.0.0",
            "artifact_digest": digest,
            "packages_count": 1,
            "packages": [
                {"name": "openssl", "version": "3.0.0", "type": "library"},
            ],
        },
        "vulnerabilities": {
            "scanner_version": "grype-0.80.0",
            "artifact_digest": digest,
            "critical_count": critical,
            "high_count": 0,
            "medium_count": 0,
            "low_count": 0,
            "findings": findings,
        },
    }


async def _ingest_clearance(
    client: AsyncClient,
    release_id: str,
    *,
    run_id: str = RUN_MAIN,
    granted: bool = True,
) -> None:
    res = await client.post(
        "/api/v1/hub/clearance/ingest",
        json=_clearance_body(
            release_id, run_id, f"eval-{release_id}", granted=granted,
        ),
    )
    assert res.status_code == 200, res.text
    assert res.json()["transfer_allowed"] is granted, res.text


async def _attach_sbom(
    client: AsyncClient, release_id: str, *, critical: int = 0,
) -> None:
    res = await client.post(
        f"/api/v1/releases/{release_id}/sbom/attach",
        json=_sbom_body(critical=critical),
    )
    assert res.status_code == 201, res.text


def _audit_events(action: str, resource_id: str) -> list:
    from orchestrator.cosmo.api.routes.audit import _AUDIT_LOG_RECORDS

    return [
        e for e in _AUDIT_LOG_RECORDS
        if e.action == action and e.resource_id == resource_id
    ]


def _fake_release(
    *, current_zone: str = "zr", history: list | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id="rel-fake",
        current_zone=current_zone,
        transfer_history=history if history is not None else [],
    )


# ── DTO unit ─────────────────────────────────────────────────────────────


class TestTransferAuthorizationDto:
    def test_decision_roundtrip(self):
        decision = TransferAuthorizationDecision(
            authorized=False,
            release_id="rel-1",
            target_zone="zt",
            clearance_status=STATUS_MISSING,
            sbom_attestation_status=STATUS_MISSING,
            reasons=["no Quality Gate clearance recorded for release"],
            checked_at="2026-09-19T12:00:00+00:00",
        )
        assert decision.authorized is False
        assert decision.reasons

    def test_decision_extra_forbidden(self):
        with pytest.raises(ValidationError):
            TransferAuthorizationDecision(
                authorized=True, release_id="r", target_zone="zt",
                clearance_status="PASS_GRANTED",
                sbom_attestation_status="PASS", checked_at="t", hack=1,
            )

    def test_decision_blank_field_rejected(self):
        with pytest.raises(ValidationError):
            TransferAuthorizationDecision(
                authorized=True, release_id="   ", target_zone="zt",
                clearance_status="PASS_GRANTED",
                sbom_attestation_status="PASS", checked_at="t",
            )

    def test_replay_response_defaults(self):
        replay = TransferReplayResponse(
            release_id="rel-1", current_zone="zt", transfer_history_count=1,
        )
        assert replay.status == TRANSFER_REPLAY_STATUS == "duplicate_success"

    def test_replay_response_rejects_negative_count(self):
        with pytest.raises(ValidationError):
            TransferReplayResponse(
                release_id="rel-1", current_zone="zt",
                transfer_history_count=-1,
            )

    def test_replay_response_extra_forbidden(self):
        with pytest.raises(ValidationError):
            TransferReplayResponse(
                release_id="rel-1", current_zone="zt",
                transfer_history_count=0, hack=1,
            )

    def test_transition_values(self):
        assert TransferTransition.PROCEED.value == "proceed"
        assert TransferTransition.REPLAY.value == "duplicate_success"
        assert TransferTransition.CONFLICT.value == "conflict"

    def test_constants(self):
        assert CLEARANCE_AUTHORIZED_STATUS == "PASS_GRANTED"
        assert SBOM_AUTHORIZED_VERDICT == "PASS"
        assert STATUS_MISSING == "MISSING"
        assert STATUS_CHECK_FAILED == "CHECK_FAILED"
        assert TRANSFER_AUTHORIZATION_AUDIT_ACTION == "release_transfer_authorization"
        assert TRANSFER_BYPASS_AUDIT_ACTION == "BYPASS_ATTEMPT"


# ── Guard unit (pure) ────────────────────────────────────────────────────


class TestTransitionCas:
    def test_proceed_when_target_differs_from_current(self):
        rel = _fake_release(current_zone="zr")
        assert ReleaseTransferGuard.evaluate_transition(
            rel, target_zone="zt",
        ) is TransferTransition.PROCEED

    def test_proceed_defaults_to_next_zone(self):
        rel = _fake_release(current_zone="zr")
        assert ReleaseTransferGuard.evaluate_transition(
            rel, target_zone=None,
        ) is TransferTransition.PROCEED

    def test_conflict_on_expected_zone_mismatch(self):
        rel = _fake_release(current_zone="zr")
        assert ReleaseTransferGuard.evaluate_transition(
            rel, target_zone="zt", expected_current_zone="zt",
        ) is TransferTransition.CONFLICT

    def test_no_conflict_when_expected_matches(self):
        rel = _fake_release(current_zone="zr")
        assert ReleaseTransferGuard.evaluate_transition(
            rel, target_zone="zt", expected_current_zone="zr",
        ) is TransferTransition.PROCEED

    def test_replay_when_target_already_reached(self):
        rel = _fake_release(
            current_zone="zt",
            history=[{"from_zone": "zr", "to_zone": "zt"}],
        )
        assert ReleaseTransferGuard.evaluate_transition(
            rel, target_zone="zt",
        ) is TransferTransition.REPLAY

    def test_replay_reads_object_history_records(self):
        rel = _fake_release(
            current_zone="zpe",
            history=[SimpleNamespace(to_zone="zt"), SimpleNamespace(to_zone="zpe")],
        )
        assert ReleaseTransferGuard.evaluate_transition(
            rel, target_zone="zpe",
        ) is TransferTransition.REPLAY

    def test_no_replay_when_history_empty(self):
        rel = _fake_release(current_zone="zt")
        assert ReleaseTransferGuard.evaluate_transition(
            rel, target_zone="zt",
        ) is TransferTransition.PROCEED

    def test_replay_payload_reports_history_count(self):
        rel = _fake_release(
            current_zone="zt",
            history=[{"from_zone": "zr", "to_zone": "zt"}],
        )
        payload = ReleaseTransferGuard.replay_payload(rel)
        assert payload.status == "duplicate_success"
        assert payload.release_id == "rel-fake"
        assert payload.current_zone == "zt"
        assert payload.transfer_history_count == 1


class TestBypassPermitted:
    def test_non_admin_never_permitted(self):
        assert bypass_permitted(False, env="test", opt_in="1") is False

    def test_admin_requires_dev_env(self):
        assert bypass_permitted(True, env="prod", opt_in="") is False
        for env in BYPASS_ENV_VALUES:
            assert bypass_permitted(True, env=env, opt_in="") is True

    def test_admin_env_case_insensitive(self):
        assert bypass_permitted(True, env="  TEST ", opt_in="") is True

    def test_admin_explicit_opt_in_overrides_env(self):
        assert bypass_permitted(True, env="prod", opt_in="1") is True
        assert bypass_permitted(True, env="", opt_in="1") is True

    def test_admin_unset_env_denied(self):
        assert bypass_permitted(True, env="", opt_in="") is False

    def test_reads_environment_when_not_injected(self, monkeypatch):
        monkeypatch.delenv(ENV_NAME_VAR, raising=False)
        monkeypatch.delenv(BYPASS_OPT_IN_VAR, raising=False)
        assert bypass_permitted(True) is False
        monkeypatch.setenv(ENV_NAME_VAR, "dev")
        assert bypass_permitted(True) is True
        monkeypatch.setenv(BYPASS_OPT_IN_VAR, "1")
        assert bypass_permitted(True) is True


# ── Guard authorize (PG) ─────────────────────────────────────────────────


class TestGuardAuthorize:
    @pytest_asyncio.fixture(autouse=True)
    async def _seed(self, pg_client: AsyncClient):
        await _seed_all([
            (REL_DENY, RUN_MAIN),
            (REL_CLEAR_ONLY, RUN_MAIN),
            (REL_SBOM_BLOCK, RUN_MAIN),
            (REL_OK, RUN_MAIN),
        ])

    async def _authorize(self, release_id: str):
        from sqlalchemy.ext.asyncio import (
            async_sessionmaker, create_async_engine,
        )

        engine = create_async_engine(_PG_URL, echo=False)
        try:
            maker = async_sessionmaker(engine, expire_on_commit=False)
            async with maker() as session:
                return await ReleaseTransferGuard().authorize(
                    session, release_id, target_zone="zt", actor="tester",
                )
        finally:
            await engine.dispose()

    async def test_missing_witnesses_denies(self, pg_client: AsyncClient):
        decision = await self._authorize(REL_DENY)
        assert decision.authorized is False
        assert decision.clearance_status == STATUS_MISSING
        assert decision.sbom_attestation_status == STATUS_MISSING
        assert any("clearance" in r for r in decision.reasons)
        assert any("SBOM" in r for r in decision.reasons)

    async def test_clearance_only_denies(self, pg_client: AsyncClient):
        await _ingest_clearance(pg_client, REL_CLEAR_ONLY)
        decision = await self._authorize(REL_CLEAR_ONLY)
        assert decision.authorized is False
        assert decision.clearance_status == CLEARANCE_AUTHORIZED_STATUS
        assert decision.sbom_attestation_status == STATUS_MISSING

    async def test_sbom_block_denies(self, pg_client: AsyncClient):
        await _ingest_clearance(pg_client, REL_SBOM_BLOCK)
        await _attach_sbom(pg_client, REL_SBOM_BLOCK, critical=1)
        decision = await self._authorize(REL_SBOM_BLOCK)
        assert decision.authorized is False
        assert decision.sbom_attestation_status == "BLOCK"

    async def test_both_witnesses_allow(self, pg_client: AsyncClient):
        await _ingest_clearance(pg_client, REL_OK)
        await _attach_sbom(pg_client, REL_OK)
        decision = await self._authorize(REL_OK)
        assert decision.authorized is True
        assert decision.reasons == []

    async def test_authorize_records_audit(self, pg_client: AsyncClient):
        await self._authorize(REL_DENY)
        events = _audit_events(TRANSFER_AUTHORIZATION_AUDIT_ACTION, REL_DENY)
        assert events, "authorization audit event missing"
        assert events[0].status == "blocked"
        assert events[0].details_json["authorized"] is False

    async def test_check_failure_is_fail_closed(self, pg_client: AsyncClient):
        from sqlalchemy.ext.asyncio import (
            async_sessionmaker, create_async_engine,
        )

        class _Boom:
            async def latest_for_release(self, *_a, **_k):
                raise RuntimeError("ledger unavailable")

        engine = create_async_engine(_PG_URL, echo=False)
        try:
            maker = async_sessionmaker(engine, expire_on_commit=False)
            async with maker() as session:
                decision = await ReleaseTransferGuard(
                    clearance_gate=_Boom(),
                ).authorize(session, REL_DENY, target_zone="zt")
        finally:
            await engine.dispose()
        assert decision.authorized is False
        assert decision.clearance_status == STATUS_CHECK_FAILED


# ── Route tests ──────────────────────────────────────────────────────────


class TestTransferAuthorizationRoute:
    @pytest_asyncio.fixture(autouse=True)
    async def _seed(self, pg_client: AsyncClient):
        await _seed_all([
            (REL_DENY, RUN_MAIN, "zr", None),
            (REL_CLEAR_ONLY, RUN_MAIN, "zr", None),
            (REL_SBOM_BLOCK, RUN_MAIN, "zr", None),
            (REL_OK, RUN_MAIN, "zr", None),
            (REL_OK_V2, RUN_ALT, "zr", None),
            (REL_CONFLICT, RUN_MAIN, "zr", None),
            (REL_BYPASS, RUN_MAIN, "zr", None),
            (REL_REPLAY, RUN_MAIN, "zt", [{
                "from_zone": "zr", "to_zone": "zt", "initiated_by": "officer-0",
                "gate_check_passed": True, "comment": "",
            }]),
        ])

    async def test_denied_without_witnesses_403(self, pg_client: AsyncClient):
        res = await pg_client.post(
            f"/api/v1/releases/{REL_DENY}/transfer",
            json={"initiated_by": "officer-1"},
        )
        assert res.status_code == 403, res.text
        detail = res.json()["detail"]
        assert detail["authorized"] is False
        assert detail["clearance_status"] == STATUS_MISSING
        assert detail["sbom_attestation_status"] == STATUS_MISSING

    async def test_denied_without_sbom_403(self, pg_client: AsyncClient):
        await _ingest_clearance(pg_client, REL_CLEAR_ONLY)
        res = await pg_client.post(
            f"/api/v1/releases/{REL_CLEAR_ONLY}/transfer",
            json={"initiated_by": "officer-1"},
        )
        assert res.status_code == 403, res.text
        detail = res.json()["detail"]
        assert detail["clearance_status"] == CLEARANCE_AUTHORIZED_STATUS
        assert detail["sbom_attestation_status"] == STATUS_MISSING

    async def test_denied_when_sbom_blocked_403(self, pg_client: AsyncClient):
        await _ingest_clearance(pg_client, REL_SBOM_BLOCK)
        await _attach_sbom(pg_client, REL_SBOM_BLOCK, critical=1)
        res = await pg_client.post(
            f"/api/v1/releases/{REL_SBOM_BLOCK}/transfer",
            json={"initiated_by": "officer-1"},
        )
        assert res.status_code == 403, res.text
        assert res.json()["detail"]["sbom_attestation_status"] == "BLOCK"

    async def test_allowed_with_both_witnesses_200(self, pg_client: AsyncClient):
        await _ingest_clearance(pg_client, REL_OK)
        await _attach_sbom(pg_client, REL_OK)
        res = await pg_client.post(
            f"/api/v1/releases/{REL_OK}/transfer",
            json={"initiated_by": "officer-1"},
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["current_zone"] == "zt"
        assert len(body["transfer_history"]) == 1
        assert body["transfer_history"][0]["to_zone"] == "zt"

        events = _audit_events(TRANSFER_AUTHORIZATION_AUDIT_ACTION, REL_OK)
        assert events and events[0].status == "success"

    async def test_allowed_v2_with_both_witnesses_200(self, pg_client: AsyncClient):
        await _ingest_clearance(pg_client, REL_OK_V2, run_id=RUN_ALT)
        await _attach_sbom(pg_client, REL_OK_V2)
        res = await pg_client.post(
            f"/api/v1/releases/{REL_OK_V2}/transfer-v2",
            json={
                "target_zone": "zt",
                "officer_name": "Петров П.С.",
                "sign_signature": "gost_sig_hex",
            },
        )
        assert res.status_code == 200, res.text
        assert res.json()["current_zone"] == "zt"

    async def test_cas_conflict_409(self, pg_client: AsyncClient):
        await _ingest_clearance(pg_client, REL_CONFLICT)
        await _attach_sbom(pg_client, REL_CONFLICT)
        res = await pg_client.post(
            f"/api/v1/releases/{REL_CONFLICT}/transfer",
            json={"initiated_by": "officer-1", "expected_current_zone": "zt"},
        )
        assert res.status_code == 409, res.text
        assert "conflict" in res.json()["detail"].lower()

    async def test_replay_is_idempotent_200(self, pg_client: AsyncClient):
        await _ingest_clearance(pg_client, REL_REPLAY)
        await _attach_sbom(pg_client, REL_REPLAY)
        res = await pg_client.post(
            f"/api/v1/releases/{REL_REPLAY}/transfer",
            json={"initiated_by": "officer-1", "target_zone": "zt"},
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["status"] == "duplicate_success"
        assert body["release_id"] == REL_REPLAY
        assert body["current_zone"] == "zt"
        assert body["transfer_history_count"] == 1

        read = await pg_client.get(f"/api/v1/releases/{REL_REPLAY}")
        assert read.status_code == 200, read.text
        assert len(read.json()["transfer_history"]) == 1
        assert read.json()["current_zone"] == "zt"

    async def test_bypass_denied_403_and_audited(
        self, pg_client: AsyncClient, monkeypatch,
    ):
        # conftest выставляет COSMO_ENV=test; вне dev-окружения обход запрещён.
        monkeypatch.delenv(ENV_NAME_VAR, raising=False)
        monkeypatch.delenv(BYPASS_OPT_IN_VAR, raising=False)
        res = await pg_client.post(
            f"/api/v1/releases/{REL_BYPASS}/transfer"
            "?bypass_authorization=true",
            json={"initiated_by": "officer-1"},
        )
        assert res.status_code == 403, res.text
        assert "bypass" in res.json()["detail"].lower()

        events = _audit_events(TRANSFER_BYPASS_AUDIT_ACTION, REL_BYPASS)
        assert events, "bypass audit event missing"
        assert events[0].status == "blocked"
        assert events[0].details_json["permitted"] is False

    async def test_bypass_permitted_in_dev_env_200(
        self, pg_client: AsyncClient, monkeypatch,
    ):
        monkeypatch.setenv(ENV_NAME_VAR, "test")
        monkeypatch.delenv(BYPASS_OPT_IN_VAR, raising=False)
        res = await pg_client.post(
            f"/api/v1/releases/{REL_BYPASS}/transfer"
            "?bypass_authorization=true",
            json={"initiated_by": "officer-1"},
        )
        assert res.status_code == 200, res.text
        assert res.json()["current_zone"] == "zt"

        events = _audit_events(TRANSFER_BYPASS_AUDIT_ACTION, REL_BYPASS)
        assert events and events[0].status == "success"


# ── Seeding helpers ──────────────────────────────────────────────────────


async def _seed_all(releases: list[tuple]) -> None:
    """Один engine / одна транзакция: домен, app, план, прогоны, релизы.

    ``releases`` — кортежи ``(release_id, run_id)`` или
    ``(release_id, run_id, current_zone, transfer_history)``.
    """
    import json

    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(_PG_URL, echo=False)
    try:
        async with engine.begin() as conn:
            await conn.execute(text(
                "INSERT INTO domains (id, label, forge_type, forge_url, "
                "forge_token_ref, rbac_config, quota_max_runs, "
                "quota_max_storage_gb, quota_max_cpu, created_at) "
                "VALUES (:d, 'ta-cos145', 'gitea', 'http://gitea:3000', "
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
            for rid in (RUN_MAIN, RUN_ALT):
                await conn.execute(text(
                    "INSERT INTO runs (id, plan_id, trigger, domain_id, status, "
                    "initiator_user_id, initiator_role, findings_refs, created_at) "
                    "VALUES (:r, :p, 'manual', :d, 'succeeded', 'system', "
                    "'system', '[]'::jsonb, now()) ON CONFLICT (id) DO NOTHING"
                ), {"r": rid, "p": PLAN, "d": DOMAIN})
            for row in releases:
                release_id, run_id = row[0], row[1]
                zone = row[2] if len(row) > 2 else "zr"
                history = row[3] if len(row) > 3 else []
                await conn.execute(text(
                    "INSERT INTO releases (id, domain_id, plan_id, status, "
                    "current_zone, version, run_ids, approvals, artifacts, "
                    "transfer_history, created_at) VALUES (:rel, :d, :p, "
                    "'deployed', :zone, '1.0.0', CAST(:rids AS jsonb), "
                    "'[]'::jsonb, '[]'::jsonb, CAST(:hist AS jsonb), now()) "
                    "ON CONFLICT (id) DO NOTHING"
                ), {
                    "rel": release_id, "d": DOMAIN, "p": PLAN,
                    "zone": zone,
                    "rids": json.dumps([run_id]),
                    "hist": json.dumps(history or []),
                })
    finally:
        await engine.dispose()
