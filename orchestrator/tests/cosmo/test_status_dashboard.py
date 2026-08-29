# -*- coding: utf-8 -*-
"""COS-056: Tests for Health Dashboard (/api/v1/status/dashboard) & Metrics (PG-only).

Tests:
  - Aggregated metrics summary (empty DB and with entities)
  - Status alert evaluation (runs_failed_5m, gates_blocked_15m, api_latency_high)
  - Breakdown maps (runs_by_status, batches_by_status, gates_by_decision)
  - Prometheus /metrics exposition formatting

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


@pytest.mark.asyncio
async def test_status_dashboard_empty(pg_client: AsyncClient):
    """GET /api/v1/status/dashboard на пустой базе возвращает валидный дашборд."""
    r = await pg_client.get("/api/v1/status/dashboard")
    assert r.status_code == 200
    data = r.json()

    assert data["status"] in ("ok", "degraded", "critical")
    assert "timestamp" in data
    assert data["uptime_seconds"] >= 0
    assert data["summary"]["total_runs"] == 0
    assert data["summary"]["total_domains"] == 0
    assert data["summary"]["total_gates"] == 0
    assert len(data["alerts"]) == 3
    assert "runs_by_status" in data
    assert "batches_by_status" in data
    assert "gates_by_decision" in data


@pytest.mark.asyncio
async def test_status_dashboard_with_entities(pg_client: AsyncClient):
    """GET /api/v1/status/dashboard корректно считает сущности и статусы."""
    # 1. Create domain
    await pg_client.post("/api/v1/domains", json={
        "id": "dom-dash-1", "label": "Dashboard Test Domain",
        "forge_binding": {"forge_type": "gitea", "url": "http://gitea:3000", "token_ref": "VAULT/TOKEN"},
    })
    # 2. Create app
    await pg_client.post("/api/v1/apps", json={
        "id": "app-dash-1", "domain_id": "dom-dash-1", "level": 1,
        "repo_binding": {"forge_id": "gitea", "repo_path": "dom-dash-1/app-1"},
    })
    # 3. Create plan
    await pg_client.post("/api/v1/plans", json={
        "id": "plan-dash-1", "app_id": "app-dash-1", "level": "app",
        "scope_id": "app-dash-1", "brick_ids": [],
    })
    # 4. Create runs: 1 running, 1 failed
    await pg_client.post("/api/v1/runs", json={
        "id": "run-dash-1", "plan_id": "plan-dash-1", "trigger": "manual", "domain_id": "dom-dash-1",
    })
    await pg_client.patch("/api/v1/runs/run-dash-1/status", json={"status": "running"}, headers={"X-Cosmo-Domain": "dom-dash-1"})

    await pg_client.post("/api/v1/runs", json={
        "id": "run-dash-2", "plan_id": "plan-dash-1", "trigger": "manual", "domain_id": "dom-dash-1",
    })
    await pg_client.patch("/api/v1/runs/run-dash-2/status", json={"status": "failed"}, headers={"X-Cosmo-Domain": "dom-dash-1"})

    # Check dashboard
    dash = await pg_client.get("/api/v1/status/dashboard")
    assert dash.status_code == 200
    res = dash.json()

    assert res["summary"]["total_domains"] == 1
    assert res["summary"]["total_applications"] == 1
    assert res["summary"]["total_runs"] == 2
    assert res["summary"]["active_runs"] == 1
    assert res["summary"]["failed_runs"] == 1

    # Alert for failed run in last 5m
    failed_alert = next((a for a in res["alerts"] if a["name"] == "runs_failed_5m"), None)
    assert failed_alert is not None
    assert failed_alert["active"] is True
    assert failed_alert["current_value"] == 1


@pytest.mark.asyncio
async def test_prometheus_metrics_endpoint(pg_client: AsyncClient):
    """GET /metrics возвращает валидный Prometheus exposition text."""
    r = await pg_client.get("/metrics")
    assert r.status_code == 200
    text = r.text

    assert "cosmo_uptime_seconds" in text
    assert "cosmo_requests_total" in text
    assert "cosmo_runs_total" in text
    assert "cosmo_runs_active" in text
    assert "cosmo_runs_failed_5m" in text
    assert "cosmo_gates_blocked" in text
    assert "cosmo_api_latency_ms" in text
    assert "# TYPE cosmo_runs_total gauge" in text