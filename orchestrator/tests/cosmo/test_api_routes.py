# -*- coding: utf-8 -*-
"""COS-010: Tests for FastAPI REST API routes (PostgreSQL-only).

Tests all CRUD and lifecycle operations with isolated async database:
- Health & Readiness endpoints (/live, /ready, /health)
- Domains (/api/v1/domains) & AppGraph (/api/v1/domains/{id}/graph)
- Applications & Groups (/api/v1/apps, /api/v1/groups)
- Pipeline Bricks & Plans (/api/v1/bricks, /api/v1/plans, /api/v1/plans/compile)
- Runs & Batches (/api/v1/runs, /api/v1/batches)
- Security Gates (/api/v1/gates)

PG fixture: conftest.py (auto-skip if PostgreSQL :5432 unreachable).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from httpx import AsyncClient

_orch = Path(__file__).resolve().parents[1]
if str(_orch) not in sys.path:
    sys.path.insert(0, str(_orch))

# ── Health Tests ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_health_endpoints(pg_client: AsyncClient):
    res_live = await pg_client.get("/live")
    assert res_live.status_code == 200
    assert res_live.json()["status"] == "ok"

    res_health = await pg_client.get("/health")
    assert res_health.status_code == 200
    data = res_health.json()
    assert "status" in data
    assert "uptime_seconds" in data
    assert "dependencies" in data


# ── Domain Tests ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_domains_crud(pg_client: AsyncClient):
    # 1. List empty
    res = await pg_client.get("/api/v1/domains")
    assert res.status_code == 200
    assert res.json() == []

    # 2. Create domain
    domain_payload = {
        "id": "dom-1",
        "label": "Test Domain Alpha",
        "forge_binding": {
            "forge_type": "gitea",
            "url": "http://gitea.local:3000",
            "token_ref": "VAULT/GITEA_ALPHA",
        },
        "rbac_config": {"admin": ["user1"]},
        "quota": {"max_runs": 20, "max_storage_gb": 50, "max_cpu": 4},
    }
    res = await pg_client.post("/api/v1/domains", json=domain_payload)
    assert res.status_code == 201
    created = res.json()
    assert created["id"] == "dom-1"
    assert created["label"] == "Test Domain Alpha"
    assert created["quota"]["max_runs"] == 20

    # 3. Conflict on duplicate ID
    res_conflict = await pg_client.post("/api/v1/domains", json=domain_payload)
    assert res_conflict.status_code == 409

    # 4. Get domain
    res_get = await pg_client.get("/api/v1/domains/dom-1")
    assert res_get.status_code == 200
    assert res_get.json()["id"] == "dom-1"

    # 5. Update domain
    update_payload = {
        "label": "Updated Domain Alpha",
        "quota": {"max_runs": 30, "max_storage_gb": 60, "max_cpu": 6},
    }
    res_put = await pg_client.put("/api/v1/domains/dom-1", json=update_payload)
    assert res_put.status_code == 200
    assert res_put.json()["label"] == "Updated Domain Alpha"
    assert res_put.json()["quota"]["max_runs"] == 30

    # 6. Delete domain
    res_del = await pg_client.delete("/api/v1/domains/dom-1")
    assert res_del.status_code == 204

    res_get_404 = await pg_client.get("/api/v1/domains/dom-1")
    assert res_get_404.status_code == 404


# ── Apps & Groups Tests ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_apps_and_groups_crud(pg_client: AsyncClient):
    await pg_client.post("/api/v1/domains", json={
        "id": "dom-app-test", "label": "App Test Domain",
        "forge_binding": {"forge_type": "gitea", "url": "http://gitea.local", "token_ref": "TOK"},
    })

    # 1. Create Group
    res_grp = await pg_client.post("/api/v1/groups", json={
        "id": "grp-core", "domain_id": "dom-app-test", "level": 1, "name": "Core Services",
    })
    assert res_grp.status_code == 201
    assert res_grp.json()["name"] == "Core Services"

    # 2. Create Application in group
    res_app = await pg_client.post("/api/v1/apps", json={
        "id": "app-auth", "domain_id": "dom-app-test", "level": 1, "group_id": "grp-core",
        "repo_binding": {"forge_id": "gitea", "repo_path": "dom-app-test/auth-service", "default_branch": "develop"},
    })
    assert res_app.status_code == 201
    assert res_app.json()["repo_binding"]["repo_path"] == "dom-app-test/auth-service"

    # 3. Create Library (level 0)
    res_lib = await pg_client.post("/api/v1/apps", json={
        "id": "lib-crypto", "domain_id": "dom-app-test", "level": 0,
        "repo_binding": {"forge_id": "gitea", "repo_path": "dom-app-test/crypto-lib"},
    })
    assert res_lib.status_code == 201

    # 4. Get AppGraph
    res_graph = await pg_client.get("/api/v1/domains/dom-app-test/graph")
    assert res_graph.status_code == 200
    graph = res_graph.json()
    assert len(graph["groups"]) == 1
    assert len(graph["apps"]) == 1
    assert len(graph["libraries"]) == 1

    # 5. Update repo binding
    res_upd = await pg_client.put("/api/v1/apps/app-auth/repo-binding", json={
        "forge_id": "gitea", "repo_path": "dom-app-test/auth-v2",
        "default_branch": "main", "webhook_id": "wh-99",
    })
    assert res_upd.status_code == 200
    assert res_upd.json()["repo_path"] == "dom-app-test/auth-v2"

    # 6. Delete
    assert (await pg_client.delete("/api/v1/apps/app-auth")).status_code == 204
    assert (await pg_client.delete("/api/v1/groups/grp-core")).status_code == 204


# ── Pipeline Bricks & Plans Tests ──────────────────────────────────────

@pytest.mark.asyncio
async def test_pipeline_bricks_and_plan_compilation(pg_client: AsyncClient):
    await pg_client.post("/api/v1/domains", json={
        "id": "dom-pipe", "label": "Pipeline Domain",
        "forge_binding": {"forge_type": "gitea", "url": "http://gitea", "token_ref": "T"},
    })
    await pg_client.post("/api/v1/apps", json={
        "id": "app-pipe", "domain_id": "dom-pipe", "level": 1,
        "repo_binding": {"forge_id": "gitea", "repo_path": "dom-pipe/app"},
    })

    for brick in [
        {"id": "b-build", "name": "App Build", "type": "build", "source": "internal",
         "definition": {"image": "golang:1.22", "timeout_s": 600}},
        {"id": "b-sast", "name": "Sonar SAST", "type": "sast", "source": "internal",
         "definition": {"image": "sonarqube:scanner", "timeout_s": 1200}, "depends_on": ["b-build"]},
        {"id": "b-dast", "name": "ZAP DAST", "type": "dast", "source": "internal",
         "definition": {"image": "owasp/zap2docker:latest", "timeout_s": 1800}, "depends_on": ["b-sast"]},
    ]:
        assert (await pg_client.post("/api/v1/bricks", json=brick)).status_code == 201

    res_sast = await pg_client.get("/api/v1/bricks?type=sast")
    assert res_sast.status_code == 200
    assert len(res_sast.json()) == 1

    res_compile = await pg_client.post("/api/v1/plans/compile", json={
        "plan_id": "plan-pipe-1", "app_id": "app-pipe",
        "brick_ids": ["b-build", "b-sast", "b-dast"],
    })
    assert res_compile.status_code == 201
    plan = res_compile.json()
    assert plan["id"] == "plan-pipe-1"
    assert plan["brick_ids"] == ["b-build", "b-sast", "b-dast"]
    assert plan["compiled_hash"] is not None

    res_batches = await pg_client.get("/api/v1/batches?plan_id=plan-pipe-1")
    assert res_batches.status_code == 200
    assert len(res_batches.json()) >= 2


# ── Runs & Batches Lifecycle Tests ─────────────────────────────────────

@pytest.mark.asyncio
async def test_runs_and_batches_lifecycle(pg_client: AsyncClient):
    # Setup
    await pg_client.post("/api/v1/domains", json={
        "id": "dom-run", "label": "Run Domain",
        "forge_binding": {"forge_type": "gitea", "url": "http://gitea", "token_ref": "T"},
    })
    await pg_client.post("/api/v1/apps", json={
        "id": "app-run", "domain_id": "dom-run", "level": 1,
        "repo_binding": {"forge_id": "gitea", "repo_path": "dom-run/app"},
    })
    await pg_client.post("/api/v1/bricks", json={
        "id": "b-smoke", "name": "Smoke", "type": "autotest", "source": "internal",
        "definition": {"image": "pytest:latest"},
    })
    await pg_client.post("/api/v1/plans/compile", json={
        "plan_id": "plan-run-1", "app_id": "app-run", "brick_ids": ["b-smoke"],
    })

    # 1. Trigger Run
    res_run = await pg_client.post("/api/v1/runs", json={
        "id": "run-101", "plan_id": "plan-run-1", "trigger": "scheduled",
        "initiator_user_id": "cron-service", "initiator_role": "system", "domain_id": "dom-run",
    })
    assert res_run.status_code == 201
    assert res_run.json()["status"] == "pending"

    # 2. Transition: pending → queued → running → succeeded
    for st in ["queued", "running", "succeeded"]:
        res = await pg_client.patch(
            "/api/v1/runs/run-101/status",
            json={"status": st},
            headers={"X-Cosmo-Domain": "dom-run"},
        )
        assert res.status_code == 200, f"Expected 200 for status={st}, got {res.status_code}: {res.text}"

    res_get = await pg_client.get("/api/v1/runs/run-101", headers={"X-Cosmo-Domain": "dom-run"})
    assert res_get.status_code == 200
    assert res_get.json()["status"] == "succeeded"

    # 3. Create+ Cancel another run
    await pg_client.post("/api/v1/runs", json={
        "id": "run-102", "plan_id": "plan-run-1", "trigger": "manual",
        "initiator_user_id": "operator-1", "domain_id": "dom-run",
    })
    res_cancel = await pg_client.post("/api/v1/runs/run-102/cancel")
    assert res_cancel.status_code == 200
    assert res_cancel.json()["status"] == "cancelled"


# ── Security Gates Tests ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_gates_and_decisions(pg_client: AsyncClient):
    await pg_client.post("/api/v1/domains", json={
        "id": "dom-gate", "label": "Gate Domain",
        "forge_binding": {"forge_type": "gitea", "url": "http://gitea", "token_ref": "T"},
    })
    await pg_client.post("/api/v1/apps", json={
        "id": "app-gate", "domain_id": "dom-gate", "level": 1,
        "repo_binding": {"forge_id": "gitea", "repo_path": "dom-gate/app"},
    })
    await pg_client.post("/api/v1/plans", json={
        "id": "plan-gate-1", "app_id": "app-gate", "brick_ids": [],
    })

    # 1. Create automatic gate
    res_auto = await pg_client.post("/api/v1/gates", json={
        "id": "gate-auto", "plan_id": "plan-gate-1", "type": "automatic", "position": 0,
        "policy": {"rules": [
            {"finding_type": "Critical", "action": "block"},
            {"finding_type": "High", "action": "warn", "max_count": 3},
        ]},
    })
    assert res_auto.status_code == 201

    # 2. Create manual gate + decide
    await pg_client.post("/api/v1/gates", json={
        "id": "gate-manual", "plan_id": "plan-gate-1", "type": "manual", "position": 1,
        "policy": {"rules": [{"finding_type": "Critical", "action": "block"}]},
    })

    res_dec = await pg_client.post("/api/v1/gates/gate-manual/decision", json={
        "decision": "pass", "decided_by": "secops-lead@company.ru", "signature": "sig-sha256-verified",
    })
    assert res_dec.status_code == 200
    dec = res_dec.json()
    assert dec["decision"] == "pass"
    assert dec["decided_by"] == "secops-lead@company.ru"

    # 3. Manual gate requires decided_by — reject
    res_bad = await pg_client.post("/api/v1/gates/gate-manual/decision", json={"decision": "block"})
    assert res_bad.status_code == 400