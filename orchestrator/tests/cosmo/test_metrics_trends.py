"""COS-062: Metrics Trends API tests (PostgreSQL-only).

PG fixture: conftest.py (auto-skip if PostgreSQL :5432 unreachable).
"""
from __future__ import annotations

import datetime
import sys
from pathlib import Path

import pytest
from httpx import AsyncClient

_orch = Path(__file__).resolve().parents[1]
if str(_orch) not in sys.path:
    sys.path.insert(0, str(_orch))


@pytest.mark.asyncio
async def test_trends_empty_returns_defaults(pg_client: AsyncClient):
    """Trends endpoint on empty DB returns empty lists and zero summary."""
    res = await pg_client.get("/api/v1/metrics/trends")
    assert res.status_code == 200
    data = res.json()
    assert data["days"] == 30
    assert data["domain_id"] == "all"
    assert data["pass_rate_trend"] == []
    assert data["findings_severity_trend"] == []
    assert data["mean_duration_trend"] == []
    assert data["flaky_gates"] == []
    assert data["summary"]["total_runs"] == 0
    assert data["summary"]["pass_rate_pct"] == 0.0


@pytest.mark.asyncio
async def test_trends_custom_days_param(pg_client: AsyncClient):
    """Trends respects the 'days' query parameter."""
    res = await pg_client.get("/api/v1/metrics/trends?days=7")
    assert res.status_code == 200
    assert res.json()["days"] == 7


@pytest.mark.asyncio
async def test_trends_domain_filter(pg_client: AsyncClient):
    """Trends respects domain_id filter."""
    res = await pg_client.get("/api/v1/metrics/trends?domain_id=cbr&days=14")
    assert res.status_code == 200
    assert res.json()["domain_id"] == "cbr"


@pytest.mark.asyncio
async def test_trends_with_runs_and_gates(pg_client: AsyncClient):
    """Trends with seeded runs and gates computes pass rate and flaky gates."""
    # Seed domain + plan + runs + gates through the API
    await pg_client.post("/api/v1/domains", json={
        "id": "dom-trend", "label": "Trend Domain",
        "forge_binding": {"forge_type": "gitea", "url": "http://gitea", "token_ref": "vault:secret/data/token"},
    })
    await pg_client.post("/api/v1/apps", json={
        "id": "app-trend", "domain_id": "dom-trend", "level": 1,
        "repo_binding": {"forge_id": "gitea", "repo_path": "dom-trend/app"},
    }, headers={"X-Cosmo-Domain": "dom-trend"})
    await pg_client.post("/api/v1/plans", json={
        "id": "plan-trend", "app_id": "app-trend", "brick_ids": [],
    })

    # Create 3 succeeded runs
    for i in range(3):
        rid = f"run-ok-{i}"
        await pg_client.post("/api/v1/runs", json={
            "id": rid, "plan_id": "plan-trend", "trigger": "manual", "domain_id": "dom-trend",
        }, headers={"X-Cosmo-Domain": "dom-trend"})
        await pg_client.patch(f"/api/v1/runs/{rid}/status", json={"status": "running"}, headers={"X-Cosmo-Domain": "dom-trend"})
        await pg_client.patch(f"/api/v1/runs/{rid}/status", json={"status": "succeeded"}, headers={"X-Cosmo-Domain": "dom-trend"})

    # 1 failed run
    await pg_client.post("/api/v1/runs", json={
        "id": "run-fail", "plan_id": "plan-trend", "trigger": "manual", "domain_id": "dom-trend",
    }, headers={"X-Cosmo-Domain": "dom-trend"})
    await pg_client.patch("/api/v1/runs/run-fail/status", json={"status": "running"}, headers={"X-Cosmo-Domain": "dom-trend"})
    await pg_client.patch("/api/v1/runs/run-fail/status", json={"status": "failed"}, headers={"X-Cosmo-Domain": "dom-trend"})

    # Add flaky gate: 3 blocks, 1 pass
    for i in range(3):
        await pg_client.post("/api/v1/gates", json={
            "id": f"gate-flaky-{i}", "plan_id": "plan-trend", "type": "automatic",
            "position": i,
            "policy": {"rules": [{"finding_type": "Critical", "action": "block"}]},
        })
        await pg_client.post(f"/api/v1/gates/gate-flaky-{i}/decision", json={"decision": "block"}, headers={"X-Cosmo-Domain": "dom-trend"})
    await pg_client.post("/api/v1/gates", json={
        "id": "gate-pass", "plan_id": "plan-trend", "type": "automatic",
        "position": 4,
        "policy": {"rules": [{"finding_type": "Critical", "action": "block"}]},
    })
    await pg_client.post("/api/v1/gates/gate-pass/decision", json={"decision": "pass"}, headers={"X-Cosmo-Domain": "dom-trend"})

    # Query trends
    res = await pg_client.get("/api/v1/metrics/trends")
    assert res.status_code == 200
    data = res.json()

    assert data["summary"]["total_runs"] == 4
    assert data["summary"]["pass_rate_pct"] == 75.0
    assert data["summary"]["failed_runs"] == 1
    assert len(data["pass_rate_trend"]) >= 1
    assert len(data["mean_duration_trend"]) >= 1
    assert len(data["flaky_gates"]) >= 1