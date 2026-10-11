# -*- coding: utf-8 -*-
"""COS-193: HTTP-регресс — GET /runs на прогоне с dict-findings (латентный 500).

Сценарий карточки: прогон с findings (dicts, мост COS-101) → оба GET
(/runs/{id} и /runs?domain_id=) отвечают 200 и данными, а не 500.
"""
from __future__ import annotations

import pytest

# Тот же домен, что у steel thread (integration-админ), изолированный test PG.
DOM = "it-integration"


def _H() -> dict:
    return {"X-Cosmo-Domain": DOM}


async def _seed_run(h) -> tuple[str, str]:
    r = await h.client.post("/api/v1/domains", json={
        "id": DOM,
        "label": "COS-193 DTO Domain",
        "forge_binding": {
            "forge_type": "gitea",
            "url": "https://gitea.integration.example",
            "token_ref": "vault://integration/token",
        },
        "quota": {"max_runs": 10, "max_storage_gb": 100, "max_cpu": 4},
    })
    assert r.status_code == 201, r.text

    r = await h.client.post("/api/v1/apps", json={
        "id": "dto-app",
        "domain_id": DOM,
        "level": 1,
        "repo_binding": {
            "forge_id": "gitea",
            "repo_path": f"{DOM}/dto-app",
            "default_branch": "main",
        },
    })
    assert r.status_code == 201, r.text

    bricks = [
        {"id": "dto-build", "name": "Build", "type": "build",
         "source": "repos/dto",
         "definition": {"image": "golang:1.22", "executor": "woodpecker"}},
        {"id": "dto-sast", "name": "SAST", "type": "sast",
         "source": "repos/dto",
         "definition": {"image": "sonarsource/sonar-scanner-cli:latest",
                        "executor": "woodpecker"}},
    ]
    for b in bricks:
        r = await h.client.post("/api/v1/bricks", json=b)
        assert r.status_code == 201, r.text

    r = await h.client.post("/api/v1/plans/compile", json={
        "plan_id": "dto-plan",
        "app_id": "dto-app",
        "brick_ids": [b["id"] for b in bricks],
        "level": "app",
    })
    assert r.status_code == 201, r.text

    run_id = "dto-run-1"
    r = await h.client.post("/api/v1/runs", json={
        "id": run_id,
        "plan_id": "dto-plan",
        "trigger": "manual",
        "initiator_user_id": "integration-admin",
        "initiator_role": "admin_sec",
        "domain_id": DOM,
    })
    assert r.status_code == 201, r.text
    return "dto-plan", run_id


@pytest.mark.asyncio
async def test_get_runs_with_dict_findings_200(steel_thread):
    """Регресс COS-193: dict-findings не роняют GET /runs (был 500)."""
    h = steel_thread
    _plan_id, run_id = await _seed_run(h)

    # Мост COS-101: находки сканера → runs.findings_refs (dicts, severity в нижнем регистре).
    r = await h.client.post(
        f"/api/v1/runs/{run_id}/findings",
        json={"findings": [
            {"severity": "critical", "title": "SQL Injection", "cwe_ids": ["CWE-89"]},
            {"severity": "High", "title": "Reflected XSS"},
        ]},
        headers=_H(),
    )
    assert r.status_code == 201, r.text
    assert r.json()["attached"] == 2

    # GET detail: раньше — pydantic ValidationError → 500.
    r = await h.client.get(f"/api/v1/runs/{run_id}", headers=_H())
    assert r.status_code == 200, r.text
    body = r.json()
    severities = [f["severity"] for f in body["findings"]]
    assert severities == ["Critical", "High"]  # канон моста
    assert body["findings"][0]["cwe_ids"] == ["CWE-89"]  # extras сохранены

    # GET list (domain-scoped): тот же контракт.
    r = await h.client.get("/api/v1/runs", params={"domain_id": DOM}, headers=_H())
    assert r.status_code == 200, r.text
    target = next(x for x in r.json() if x["id"] == run_id)
    assert len(target["findings"]) == 2
    assert target["findings"][1]["title"] == "Reflected XSS"
