# -*- coding: utf-8 -*-
"""COS-165: deploy materialize — pull по digest → run → healthy → deployed.

Покрытие:
  - ``DeployRuntime`` (fake runner): pull+run+healthy → True; unhealthy →
    ``DockerDeployError``; pull fail → ``DockerDeployError`` (контейнер снесён);
  - маршрут ``deploy_release``: резолв digest по durable ArtifactRecord
    прогонов релиза (run_id-якорь COS-164), фактический deploy только после
    healthy → status ``deployed`` + artifacts; нет артефакта → 409; провал
    runtime → честный ``rollback`` + 502 (не фейковый deployed).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_och = Path(__file__).resolve().parents[3]
if str(_och) not in sys.path:
    sys.path.insert(0, str(_och))

pytestmark = pytest.mark.asyncio

from orchestrator.cosmo.adapters.runtime_docker import (  # noqa: E402
    DockerDeployError,
    DeployRuntime,
)
from orchestrator.cosmo.domain.artifact_record import ArtifactRecord  # noqa: E402
from orchestrator.cosmo.ledger.artifact_record import record_artifact_record  # noqa: E402

import _testpg  # noqa: E402

_PG_URL = _testpg.TEST_PG_URL

DOMAIN = "cos165-dom"
PLAN = "cos165-plan"
APP = "cos165-app"
NAME = "cosmo-testapp"
VERSION = "0.1.0"
DIGEST = "sha256:" + "cd" * 32
REGISTRY = "localhost:5100"


# ── DeployRuntime unit (fake runner) ─────────────────────────────────────────

class _Proc:
    def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = ""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class TestDeployRuntime:
    def test_deploy_healthy(self):
        calls: list[list[str]] = []

        def runner(argv, **kw):
            calls.append(argv)
            if argv[1] == "inspect":
                return _Proc(0, stdout="healthy\n")
            return _Proc(0)

        rt = DeployRuntime(runner=runner, health_timeout=5.0)
        assert rt.deploy("img@sha256:ab", "c1") is True
        assert ["docker", "pull", "img@sha256:ab"] in calls
        assert any(a[1] == "run" for a in calls)

    def test_deploy_unhealthy_raises_and_removes(self):
        calls: list[list[str]] = []

        def runner(argv, **kw):
            calls.append(argv)
            if argv[1] == "inspect":
                return _Proc(0, stdout="unhealthy\n")
            return _Proc(0)

        rt = DeployRuntime(runner=runner, health_timeout=5.0)
        with pytest.raises(DockerDeployError):
            rt.deploy("img@sha256:ab", "c1")
        assert any(a[1] == "rm" for a in calls)

    def test_pull_failure_raises(self):
        def runner(argv, **kw):
            if argv[1] == "pull":
                return _Proc(1, stderr="no such manifest")
            return _Proc(0)

        rt = DeployRuntime(runner=runner, health_timeout=5.0)
        with pytest.raises(DockerDeployError):
            rt.deploy("img@sha256:ab", "c1")


# ── route: deploy materialize ────────────────────────────────────────────────

class FakeRuntime:
    def __init__(self, fail: bool = False):
        self.pulled: list[str] = []
        self.containers: list[str] = []
        self._fail = fail

    def deploy(self, image_ref, container_name, labels=None):
        if self._fail:
            raise DockerDeployError("boom: not healthy")
        self.pulled.append(image_ref)
        self.containers.append(container_name)
        return True


async def _seed(release_status: str = "approved", with_record: bool = True):
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

    run_id = "cos165run001"
    release_id = "cos165-rel"

    engine = create_async_engine(_PG_URL, echo=False)
    async with engine.begin() as conn:
        await conn.execute(text(
            "INSERT INTO domains (id, label, forge_type, forge_url, "
            "forge_token_ref, rbac_config, quota_max_runs, "
            "quota_max_storage_gb, quota_max_cpu, created_at) "
            "VALUES (:d, 'cos165', 'gitea', 'http://gitea:3000', 't', "
            "'{}'::jsonb, 50, 100, 8, now()) ON CONFLICT (id) DO NOTHING"
        ), {"d": DOMAIN})
        await conn.execute(text(
            "INSERT INTO apps (id, domain_id, level) VALUES (:a, :d, 0) "
            "ON CONFLICT (id) DO NOTHING"
        ), {"a": APP, "d": DOMAIN})
        await conn.execute(text(
            "INSERT INTO pipeline_plans (id, app_id, level, scope_id, "
            "compiled_hash, compiled_at) VALUES (:p, :a, 'app', :p, 'h', now()) "
            "ON CONFLICT (id) DO NOTHING"
        ), {"p": PLAN, "a": APP})
        await conn.execute(text(
            "INSERT INTO runs (id, plan_id, trigger, domain_id, status, "
            "initiator_user_id, initiator_role, findings_refs, created_at) "
            "VALUES (:r, :p, 'manual', :d, 'succeeded', 'system', 'system', "
            "'[]'::jsonb, now()) ON CONFLICT (id) DO NOTHING"
        ), {"r": run_id, "p": PLAN, "d": DOMAIN})
        await conn.execute(text(
            "INSERT INTO releases (id, domain_id, plan_id, status, "
            "current_zone, version, run_ids, approvals, artifacts, "
            "transfer_history, created_at) VALUES (:rel, :d, :p, :st, 'zr', "
            "'1.0.0', CAST(:runs AS jsonb), '[]'::jsonb, '[]'::jsonb, "
            "'[]'::jsonb, now()) ON CONFLICT (id) DO NOTHING"
        ), {"rel": release_id, "d": DOMAIN, "p": PLAN, "st": release_status,
            "runs": f'["{run_id}"]'})

    if with_record:
        session_maker = async_sessionmaker(engine, expire_on_commit=False)
        async with session_maker() as s:
            await record_artifact_record(
                s,
                ArtifactRecord(
                    name=NAME, version=VERSION, digest=DIGEST,
                    registry=REGISTRY, repository="cosmoport", namespace="zr",
                    run_id=run_id,
                ),
            )

    await engine.dispose()
    return run_id, release_id


async def _release_status(release_id: str) -> str:
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(_PG_URL, echo=False)
    async with engine.begin() as conn:
        res = await conn.execute(text(
            "SELECT status FROM releases WHERE id = :r"
        ), {"r": release_id})
        row = res.first()
    await engine.dispose()
    return row[0] if row else ""


def _trivy_pass(digest: str) -> dict:
    """COS-168: clean trivy-отчёт (critical=0) → gate PASS."""
    return {
        "artifact_digest": digest,
        "scan": {
            "scanner_version": "0.50.0",
            "artifact_digest": digest,
            "critical_count": 0,
            "high_count": 0,
            "medium_count": 0,
            "low_count": 0,
            "findings": [],
        },
    }


class TestDeployReleaseRoute:
    async def test_deploy_materializes_and_marks_deployed(self, pg_client, monkeypatch):
        _, release_id = await _seed()
        fake = FakeRuntime()
        monkeypatch.setattr(
            "orchestrator.cosmo.api.routes.releases.get_deploy_runtime",
            lambda: fake,
        )

        attach = await pg_client.post(
            f"/api/v1/releases/{release_id}/trivy/attach", json=_trivy_pass(DIGEST),
        )
        assert attach.status_code == 201, attach.text

        r = await pg_client.post(f"/api/v1/releases/{release_id}/deploy")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "deployed"
        expected_ref = f"{NAME}:{VERSION}@{DIGEST}"
        assert expected_ref in body["artifacts"]
        assert fake.pulled == [f"{REGISTRY}/cosmoport/zr/{NAME}@{DIGEST}"]
        assert await _release_status(release_id) == "deployed"

    async def test_deploy_without_artifact_record_conflict(self, pg_client):
        _, release_id = await _seed(with_record=False)
        r = await pg_client.post(f"/api/v1/releases/{release_id}/deploy")
        assert r.status_code == 409, r.text

    async def test_deploy_without_trivy_gate_blocked(self, pg_client, monkeypatch):
        """COS-168: deploy materialize без trivy PASS → 409 (не deploying)."""
        _, release_id = await _seed()
        monkeypatch.setattr(
            "orchestrator.cosmo.api.routes.releases.get_deploy_runtime",
            lambda: FakeRuntime(),
        )
        r = await pg_client.post(f"/api/v1/releases/{release_id}/deploy")
        assert r.status_code == 409, r.text
        assert await _release_status(release_id) == "approved"

    async def test_deploy_failure_rolls_back(self, pg_client, monkeypatch):
        _, release_id = await _seed()
        monkeypatch.setattr(
            "orchestrator.cosmo.api.routes.releases.get_deploy_runtime",
            lambda: FakeRuntime(fail=True),
        )
        attach = await pg_client.post(
            f"/api/v1/releases/{release_id}/trivy/attach", json=_trivy_pass(DIGEST),
        )
        assert attach.status_code == 201, attach.text
        r = await pg_client.post(f"/api/v1/releases/{release_id}/deploy")
        assert r.status_code == 502, r.text
        assert await _release_status(release_id) == "rollback"
