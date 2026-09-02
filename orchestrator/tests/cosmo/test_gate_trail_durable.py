# -*- coding: utf-8 -*-
"""COS-081: Durable Gate Decision Trail — behavioral tests against real PostgreSQL.

Contract:
1. Решение gate фиксируется в PG (gate_decision_trail) В ТОЙ ЖЕ транзакции,
   что и обновление gates — до возврата API-ответа (write-before-response).
2. Restart-survival: история решений переживает рестарт процесса (новый
   engine / новый процесс читает тот же PG).
3. Read-path: trail по gate (новые первыми) и по run_id (хронологически).
4. Append-only: репозиторий не имеет UPDATE/DELETE путей.

Repo-тесты — на уникальной scratch-БД test PG :5433 (COS-073/078 контракт),
API-тесты — через pg_client (conftest). Миграционная цепочка заморожена —
таблица GateTrailBase создаётся create_all (как models_transfer, COS-070).
"""
from __future__ import annotations

import sys
import uuid
from pathlib import Path
from urllib.parse import urlsplit

import pytest

import _testpg

_repo = Path(__file__).resolve().parents[3]
_orch = Path(__file__).resolve().parents[2]
for p in (str(_repo), str(_orch)):
    if p not in sys.path:
        sys.path.insert(0, p)

from orchestrator.cosmo.db.gate_trail_repo import (
    append_gate_decision,
    trail_for_gate,
    trail_for_run,
)
from orchestrator.cosmo.db.models_gate_trail import GateTrailBase

SCRATCH_DB = _testpg.scratch_name("gate_trail")
_POSTGRES_ADMIN_URL = _testpg.admin_dsn()

skip_pg = pytest.mark.skipif(
    not _testpg.pg_available(),
    reason="test PG (:5433) unreachable - docker compose -f services/docker-compose.test-pg.yml up -d",
)

pytestmark = [pytest.mark.asyncio, skip_pg]


def _async_url(dbname: str) -> str:
    """asyncpg URL на scratch-БД test PG (админ-части из TEST_PG_URL)."""
    parsed = urlsplit(_testpg.TEST_PG_URL)
    return (
        f"postgresql+asyncpg://{parsed.username}:{parsed.password}"
        f"@{parsed.hostname}:{parsed.port}/{dbname}"
    )


@pytest.fixture(scope="module")
def _scratch():
    """Scratch-БД + create_all GateTrailBase (sync, schema-level); дроп в конце."""
    import psycopg2
    from sqlalchemy import create_engine

    def _admin():
        return psycopg2.connect(_POSTGRES_ADMIN_URL)

    def _drop():
        conn = _admin()
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname = %s AND pid <> pg_backend_pid()",
            (SCRATCH_DB,),
        )
        cur.execute(f"DROP DATABASE IF EXISTS {SCRATCH_DB}")
        conn.close()

    _drop()
    conn = _admin()
    conn.autocommit = True
    conn.cursor().execute(f"CREATE DATABASE {SCRATCH_DB}")
    conn.close()

    engine = create_engine(_testpg.psycopg2_url(SCRATCH_DB))
    GateTrailBase.metadata.create_all(engine)
    engine.dispose()
    yield SCRATCH_DB
    _drop()


def _append_kwargs(run_id: str | None = "run-1", **over) -> dict:
    kw = dict(
        # уникальный gate_id per-test: scratch-БД module-scoped, строки
        # append-only (wipe нет) — cross-test contamination недопустим
        gate_id=f"gate-{uuid.uuid4().hex[:8]}",
        plan_id="plan-trail",
        decision="pass",
        decided_by="Maxim",
        initiator="test-admin",
        signature="sig-abc",
        policy_snapshot={"rules": [{"finding_type": "Critical", "action": "block"}]},
        run_id=run_id,
        batch_id=None,
        evidence_ids=["ev-1", "ev-2"],
    )
    kw.update(over)
    return kw


class TestRepoDurable:
    """Repo-контракт на scratch-БД (async engine per test — как рестарт процесса)."""

    async def test_append_and_trail_for_gate(self, _scratch):
        from sqlalchemy.ext.asyncio import create_async_engine
        from sqlalchemy.ext.asyncio import async_sessionmaker

        engine = create_async_engine(_async_url(_scratch))
        maker = async_sessionmaker(engine, expire_on_commit=False)
        async with maker() as db:
            row = await append_gate_decision(db, **_append_kwargs())
            await db.commit()
            assert row.id
            gate_id = row.gate_id
        async with maker() as db:
            trail = await trail_for_gate(db, gate_id)
        await engine.dispose()

        assert len(trail) == 1
        t = trail[0]
        assert t["decision"] == "pass"
        assert t["decided_by"] == "Maxim"
        assert t["initiator"] == "test-admin"
        assert t["signature"] == "sig-abc"
        assert t["run_id"] == "run-1"
        assert t["policy_snapshot"] == {
            "rules": [{"finding_type": "Critical", "action": "block"}]
        }
        assert t["evidence_ids"] == ["ev-1", "ev-2"]
        assert t["decided_at"] is not None

    async def test_trail_for_gate_newest_first(self, _scratch):
        from datetime import datetime, timedelta

        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        engine = create_async_engine(_async_url(_scratch))
        maker = async_sessionmaker(engine, expire_on_commit=False)
        base = datetime(2026, 9, 2, 12, 0, 0)
        async with maker() as db:
            kw1 = _append_kwargs(decision="pass", decided_at=base)
            # обе записи на ОДИН gate — kw2 наследует gate_id kw1
            kw2 = _append_kwargs(
                gate_id=kw1["gate_id"], decision="block", decided_at=base + timedelta(minutes=5)
            )
            await append_gate_decision(db, **kw1)
            await append_gate_decision(db, **kw2)
            await db.commit()
        async with maker() as db:
            trail = await trail_for_gate(db, kw1["gate_id"])
        await engine.dispose()

        assert len(trail) == 2
        assert [t["decision"] for t in trail] == ["block", "pass"]

    async def test_trail_for_run_chronological(self, _scratch):
        from datetime import datetime, timedelta

        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        engine = create_async_engine(_async_url(_scratch))
        maker = async_sessionmaker(engine, expire_on_commit=False)
        base = datetime(2026, 9, 2, 13, 0, 0)
        run_main = f"run-{uuid.uuid4().hex[:8]}"
        run_other = f"run-{uuid.uuid4().hex[:8]}"
        async with maker() as db:
            kw1 = _append_kwargs(plan_id="plan-x", decision="pass",
                                 run_id=run_main, decided_at=base)
            kw2 = _append_kwargs(plan_id="plan-x", decision="block",
                                 run_id=run_main, decided_at=base + timedelta(seconds=30))
            # чужой run — не должен попасть в trail по run_main
            kw3 = _append_kwargs(plan_id="plan-x", decision="pass",
                                 run_id=run_other, decided_at=base + timedelta(seconds=10))
            await append_gate_decision(db, **kw1)
            await append_gate_decision(db, **kw2)
            await append_gate_decision(db, **kw3)
            await db.commit()
        async with maker() as db:
            trail = await trail_for_run(db, run_main)
            empty = await trail_for_run(db, f"run-unknown-{uuid.uuid4().hex[:6]}")
        await engine.dispose()

        assert [t["gate_id"] for t in trail] == [kw1["gate_id"], kw2["gate_id"]]
        assert all(t["run_id"] == run_main for t in trail)
        assert empty == []

    async def test_trail_for_gate_run_filter(self, _scratch):
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        engine = create_async_engine(_async_url(_scratch))
        maker = async_sessionmaker(engine, expire_on_commit=False)
        async with maker() as db:
            await append_gate_decision(
                db, gate_id="gate-f", plan_id="plan-f", decision="pass", run_id="run-1"
            )
            await append_gate_decision(
                db, gate_id="gate-f", plan_id="plan-f", decision="block", run_id="run-2"
            )
            await db.commit()
        async with maker() as db:
            only_r1 = await trail_for_gate(db, "gate-f", run_id="run-1")
            both = await trail_for_gate(db, "gate-f")
        await engine.dispose()

        assert len(only_r1) == 1 and only_r1[0]["run_id"] == "run-1"
        assert len(both) == 2

    async def test_restart_survival_new_engine(self, _scratch):
        """Durable: запись переживает dispose+новый engine (симуляция рестарта)."""
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        engine = create_async_engine(_async_url(_scratch))
        maker = async_sessionmaker(engine, expire_on_commit=False)
        token = f"restart-{uuid.uuid4().hex[:8]}"
        async with maker() as db:
            await append_gate_decision(
                db, gate_id="gate-restart", plan_id="plan-r", decision="pass",
                decided_by="Maxim", run_id=token,
            )
            await db.commit()
        await engine.dispose()  # «процесс умер»

        # новый «процесс»: свежий engine на тот же PG
        engine2 = create_async_engine(_async_url(_scratch))
        maker2 = async_sessionmaker(engine2, expire_on_commit=False)
        async with maker2() as db:
            trail = await trail_for_run(db, token)
        await engine2.dispose()

        assert len(trail) == 1
        assert trail[0]["decided_by"] == "Maxim"

    async def test_evidence_ids_jsonb_roundtrip(self, _scratch):
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        engine = create_async_engine(_async_url(_scratch))
        maker = async_sessionmaker(engine, expire_on_commit=False)
        evidence = [f"ev-{uuid.uuid4().hex[:6]}", "ev-fixed", "ev-3"]
        async with maker() as db:
            await append_gate_decision(
                db, gate_id="gate-ev", plan_id="plan-ev", decision="pass",
                evidence_ids=evidence, run_id="run-ev",
            )
            await db.commit()
        async with maker() as db:
            trail = await trail_for_gate(db, "gate-ev")
        await engine.dispose()

        assert trail[0]["evidence_ids"] == evidence


# ---------------------------------------------------------------------------
# API integration (pg_client): write-before-response + read-path + back-compat
# ---------------------------------------------------------------------------


async def _seed_plan_with_gate(pg_client, suffix: str = "a") -> dict:
    """Domain + app + plan + gate через API (паттерн test_metrics_trends)."""
    dom = f"dom-trail-{suffix}"
    await pg_client.post("/api/v1/domains", json={
        "id": dom, "label": f"Trail Domain {suffix}",
        "forge_binding": {
            "forge_type": "gitea", "url": "http://gitea",
            "token_ref": "vault:secret/data/token",
        },
    })
    await pg_client.post("/api/v1/apps", json={
        "id": f"app-trail-{suffix}", "domain_id": dom, "level": 1,
        "repo_binding": {"forge_id": "gitea", "repo_path": f"{dom}/app"},
    }, headers={"X-Cosmo-Domain": dom})
    await pg_client.post("/api/v1/plans", json={
        "id": f"plan-trail-{suffix}", "app_id": f"app-trail-{suffix}", "brick_ids": [],
    })
    res = await pg_client.post("/api/v1/gates", json={
        "id": f"gate-trail-{suffix}", "plan_id": f"plan-trail-{suffix}",
        "type": "automatic", "position": 0,
        "policy": {"rules": [{"finding_type": "Critical", "action": "block"}]},
    })
    assert res.status_code in (200, 201), res.text
    return {"domain": dom, "gate": f"gate-trail-{suffix}", "plan": f"plan-trail-{suffix}"}


class TestApiTrail:
    """Acceptance: решение в PG до возврата ответа; рестарт не теряет; read-path."""

    async def test_decision_persisted_before_response(self, pg_client):
        """После возврата POST-ответа строка уже в PG — читаем НОВЫМ engine
        (симуляция рестарта процесса сразу после ответа)."""
        seeded = await _seed_plan_with_gate(pg_client, "wbr")

        res = await pg_client.post(
            f"/api/v1/gates/{seeded['gate']}/decision",
            json={
                "decision": "block",
                "decided_by": "Maxim",
                "signature": "sig-wbr",
                "run_id": "run-wbr",
                "batch_id": "batch-wbr",
                "evidence_ids": ["ev-a", "ev-b"],
            },
            headers={"X-Cosmo-Domain": seeded["domain"]},
        )
        assert res.status_code == 200, res.text

        # restart-симуляция: отдельный engine мимо приложения
        from sqlalchemy import text
        from sqlalchemy.ext.asyncio import create_async_engine

        url = _async_url(urlsplit(_testpg.TEST_PG_URL).path.lstrip("/"))
        engine = create_async_engine(url)
        try:
            async with engine.connect() as conn:
                rows = (
                    await conn.execute(
                        text(
                            "SELECT gate_id, decision, decided_by, initiator, run_id, "
                            "batch_id, evidence_ids, signature FROM gate_decision_trail "
                            "WHERE gate_id = :g"
                        ),
                        {"g": seeded["gate"]},
                    )
                ).mappings().all()
        finally:
            await engine.dispose()

        assert len(rows) == 1
        r = dict(rows[0])
        assert r["decision"] == "block"
        assert r["decided_by"] == "Maxim"
        assert r["initiator"] == "test-admin"  # principal из auth-контекста
        assert r["run_id"] == "run-wbr"
        assert r["batch_id"] == "batch-wbr"
        assert r["evidence_ids"] == ["ev-a", "ev-b"]
        assert r["signature"] == "sig-wbr"

    async def test_read_path_by_gate(self, pg_client):
        seeded = await _seed_plan_with_gate(pg_client, "rp")
        for dec in ("pass", "block", "pass"):
            res = await pg_client.post(
                f"/api/v1/gates/{seeded['gate']}/decision",
                json={"decision": dec, "decided_by": "Maxim", "run_id": "run-rp"},
                headers={"X-Cosmo-Domain": seeded["domain"]},
            )
            assert res.status_code == 200, res.text

        res = await pg_client.get(f"/api/v1/gates/{seeded['gate']}/decisions")
        assert res.status_code == 200
        trail = res.json()
        assert len(trail) == 3
        assert [t["decision"] for t in trail] == ["pass", "block", "pass"]  # newest first

        res_f = await pg_client.get(
            f"/api/v1/gates/{seeded['gate']}/decisions", params={"run_id": "run-rp"}
        )
        assert res_f.status_code == 200
        assert len(res_f.json()) == 3

    async def test_read_path_by_run(self, pg_client):
        """Acceptance read-path: trail всех решений прогона по run_id."""
        seeded = await _seed_plan_with_gate(pg_client, "run")
        for dec in ("pass", "block"):
            res = await pg_client.post(
                f"/api/v1/gates/{seeded['gate']}/decision",
                json={"decision": dec, "decided_by": "Maxim", "run_id": "run-42"},
                headers={"X-Cosmo-Domain": seeded["domain"]},
            )
            assert res.status_code == 200, res.text

        res = await pg_client.get("/api/v1/gates/trail/runs/run-42")
        assert res.status_code == 200
        trail = res.json()
        assert len(trail) == 2
        assert all(t["run_id"] == "run-42" for t in trail)
        assert [t["decision"] for t in trail] == ["pass", "block"]  # chronological
        # empty trail для run без решений
        res_e = await pg_client.get("/api/v1/gates/trail/runs/run-none")
        assert res_e.status_code == 200 and res_e.json() == []

    async def test_policy_snapshot_captured(self, pg_client):
        seeded = await _seed_plan_with_gate(pg_client, "pol")
        res = await pg_client.post(
            f"/api/v1/gates/{seeded['gate']}/decision",
            json={"decision": "pass", "decided_by": "Maxim"},
            headers={"X-Cosmo-Domain": seeded["domain"]},
        )
        assert res.status_code == 200, res.text

        res = await pg_client.get(f"/api/v1/gates/{seeded['gate']}/decisions")
        trail = res.json()
        # policy_json нормализуется GatePolicyRule (max_count) — сверяем семантику
        rule = trail[0]["policy_snapshot"]["rules"][0]
        assert rule["finding_type"] == "Critical"
        assert rule["action"] == "block"

    async def test_backcompat_payload_without_trail_fields(self, pg_client):
        """Старый payload (decision/decided_by/signature) валиден; trail пишется
        с run_id=NULL — write-before-response не ломает существующих клиентов."""
        seeded = await _seed_plan_with_gate(pg_client, "bc")
        res = await pg_client.post(
            f"/api/v1/gates/{seeded['gate']}/decision",
            json={"decision": "pass", "decided_by": "Legacy"},
            headers={"X-Cosmo-Domain": seeded["domain"]},
        )
        assert res.status_code == 200, res.text

        res = await pg_client.get(f"/api/v1/gates/{seeded['gate']}/decisions")
        assert res.status_code == 200
        trail = res.json()
        assert len(trail) == 1
        assert trail[0]["decision"] == "pass"
        assert trail[0]["run_id"] is None
        assert trail[0]["batch_id"] is None
        assert trail[0]["evidence_ids"] == []

    async def test_unknown_gate_trail_404(self, pg_client):
        res = await pg_client.get("/api/v1/gates/gate-unknown/decisions")
        assert res.status_code == 404

    async def test_multiple_gates_same_run_trail_mixed(self, pg_client):
        """Два gate одного плана, решения в контексте одного run — read-path
        по run собирает оба (хронологически)."""
        seeded = await _seed_plan_with_gate(pg_client, "mg")
        gate2 = f"{seeded['gate']}-2"
        res = await pg_client.post("/api/v1/gates", json={
            "id": gate2, "plan_id": seeded["plan"], "type": "automatic",
            "position": 1,
            "policy": {"rules": [{"finding_type": "Critical", "action": "block"}]},
        })
        assert res.status_code in (200, 201), res.text

        for g, dec in ((seeded["gate"], "pass"), (gate2, "block")):
            res = await pg_client.post(
                f"/api/v1/gates/{g}/decision",
                json={"decision": dec, "decided_by": "Maxim", "run_id": "run-mg"},
                headers={"X-Cosmo-Domain": seeded["domain"]},
            )
            assert res.status_code == 200, res.text

        res = await pg_client.get("/api/v1/gates/trail/runs/run-mg")
        assert res.status_code == 200
        trail = res.json()
        assert {t["gate_id"] for t in trail} == {seeded["gate"], gate2}
        assert [t["decision"] for t in trail] == ["pass", "block"]
