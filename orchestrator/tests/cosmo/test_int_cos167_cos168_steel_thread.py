# -*- coding: utf-8 -*-
"""COS-167 + COS-168: Live E2E steel-thread smoke — DOCKER_AUDIT
``build → push → capture → sbom → trivy → deploy``.

Один наблюдаемый live-проход против реального registry-zr (:5100) и
``cosmo-net``, с durable Evidence на каждом шаге. SBOM (COS-167) снимается
поверх собранного образа и якорится в Evidence Ledger со
``ArtifactRecord.sbom_ref``; trivy gate (COS-168) аттестуется и читается
``deploy_release`` (PASS → deploy, BLOCK → 409).

Honesty: SBOM генерится syft→python-inventory fallback (сигнатура генератора
честная); trivy-отчёт в live-прогоне приходит вызовом attach-контракта
(бинарь trivy на стенде не нужен — вердикт считает gate, а не фейк-сканер).

Пропускается graceful, если Docker, registry-zr или ``cosmo-net`` недоступны.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[3]  # D:\prettyk-airlock
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

pytestmark = pytest.mark.asyncio

import _testpg  # noqa: E402

_PG_URL = _testpg.TEST_PG_URL

from orchestrator.cosmo.domain.docker_build import (  # noqa: E402
    DockerBuildSpec,
    render_docker_build_commands,
)
from orchestrator.cosmo.control_plane.artifact_capture import (  # noqa: E402
    capture_artifact_records,
)
from orchestrator.cosmo.ledger.artifact_record import (  # noqa: E402
    latest_artifact_record,
    record_artifact_record,
)
from orchestrator.cosmo.domain.artifact_record import ArtifactRecord  # noqa: E402

REGISTRY = "localhost:5100"
NAME = "cosmo-testapp"
VERSION = "0.1.0"
APP_DIR = _REPO / "apps" / "cosmo-testapp"

DOMAIN = "cos167-dom"
APP = "cos167-app"
PLAN = "cos167-plan"

_GIT_BASH = "C:/Program Files/Git/bin/bash.exe"
if not Path(_GIT_BASH).exists():
    _GIT_BASH = "bash"


# ── availability probes (graceful skip) ──────────────────────────────────────

def _run(argv, timeout=60):
    try:
        return subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    except Exception:  # noqa: BLE001 — probe не должен ронять collection
        return None


def _docker_ready() -> bool:
    p = _run(["docker", "info"], timeout=30)
    return p is not None and p.returncode == 0


def _network_exists(name: str) -> bool:
    p = _run(["docker", "network", "ls", "--format", "{{.Name}}"], timeout=30)
    if p is None or p.returncode != 0:
        return False
    return name in (p.stdout or "").split()


def _registry_ready() -> bool:
    p = _run(["docker", "pull", f"{REGISTRY}/cosmoport/zr/{NAME}:{VERSION}"], timeout=120)
    return p is not None and p.returncode == 0


@pytest.fixture(autouse=True, scope="module")
def _require_live():
    missing = []
    if not _docker_ready():
        missing.append("docker")
    if not _network_exists("cosmo-net"):
        missing.append("cosmo-net")
    if not _registry_ready():
        missing.append("registry-zr:5100")
    if missing:
        pytest.skip("live stand offline: " + ", ".join(missing))


# ── seeding / ledger ─────────────────────────────────────────────────────────

async def _seed(run_id: str, release_id: str, *, batch_id: str | None = None) -> None:
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(_PG_URL, echo=False)
    async with engine.begin() as conn:
        await conn.execute(text(
            "INSERT INTO domains (id, label, forge_type, forge_url, "
            "forge_token_ref, rbac_config, quota_max_runs, "
            "quota_max_storage_gb, quota_max_cpu, created_at) "
            "VALUES (:d, 'cos167', 'gitea', 'http://gitea:3000', 't', "
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
        if batch_id:
            await conn.execute(text(
                "INSERT INTO batches (id, plan_id, type, status, bricks_refs, "
                "artifacts, evidence_refs) VALUES (:b, :p, 'build', 'passed', "
                "'[]'::jsonb, '[]'::jsonb, '[]'::jsonb) "
                "ON CONFLICT (id) DO NOTHING"
            ), {"b": batch_id, "p": PLAN})
        await conn.execute(text(
            "INSERT INTO releases (id, domain_id, plan_id, status, "
            "current_zone, version, run_ids, approvals, artifacts, "
            "transfer_history, created_at) VALUES (:rel, :d, :p, 'approved', "
            "'zr', '1.0.0', CAST(:runs AS jsonb), '[]'::jsonb, '[]'::jsonb, "
            "'[]'::jsonb, now()) ON CONFLICT (id) DO NOTHING"
        ), {"rel": release_id, "d": DOMAIN, "p": PLAN,
            "runs": f'["{run_id}"]'})
    await engine.dispose()


async def _ledger(run_id: str) -> list[dict]:
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(_PG_URL, echo=False)
    async with engine.begin() as conn:
        res = await conn.execute(text(
            "SELECT type, provenance_json->>'source' AS source, "
            "provenance_json->>'gate_verdict' AS verdict, "
            "provenance_json->>'sbom_ref' AS sbom_ref "
            "FROM evidence_ledger WHERE run_id = :r ORDER BY created_at, id"
        ), {"r": run_id})
        rows = [dict(r._mapping) for r in res.fetchall()]
    await engine.dispose()
    return rows


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


def _trivy_block(digest: str) -> dict:
    return {
        "artifact_digest": digest,
        "scan": {
            "scanner_version": "0.50.0",
            "artifact_digest": digest,
            "critical_count": 1,
            "high_count": 0,
            "medium_count": 0,
            "low_count": 0,
            "findings": [
                {
                    "id": "CVE-2099-0001",
                    "severity": "critical",
                    "package_name": "demo-pkg",
                    "installed_version": "1.0.0",
                    "fixed_version": "1.0.1",
                },
            ],
        },
    }


# ── live steel thread ────────────────────────────────────────────────────────

class TestCos167Cos168LiveSteelThread:
    async def test_sbom_trivy_pass_deploy(self, pg_client):
        # 1. build → push (реальный render), manifest-дайджест из ответа push.
        spec = DockerBuildSpec(
            image_name=NAME, version=VERSION, registry=REGISTRY,
            repository="cosmoport", namespace="zr",
            dockerfile="Dockerfile", context=".",
        )
        digest_file = ".cos167_digest"
        script = "\n".join(render_docker_build_commands(spec, digest_file)) + "\n"
        proc = subprocess.run(
            [_GIT_BASH, "-c", script], cwd=str(APP_DIR),
            capture_output=True, text=True, timeout=600,
        )
        assert proc.returncode == 0, (
            f"rendered build/push failed\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
        )
        manifest_digest = (APP_DIR / digest_file).read_text().strip()
        try:
            (APP_DIR / digest_file).unlink()
        except OSError:
            pass
        assert re.fullmatch(r"sha256:[0-9a-f]{64}", manifest_digest), manifest_digest

        marker = f"{NAME}:{VERSION}@{manifest_digest}"
        run_id = "cos167run-live"
        release_id = "cos167-rel-live"
        batch_id = "cos167bat-live"
        await _seed(run_id, release_id, batch_id=batch_id)

        # 2. capture (COS-164).
        from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

        engine = create_async_engine(_PG_URL, echo=False)
        session_maker = async_sessionmaker(engine, expire_on_commit=False)
        async with session_maker() as s:
            await capture_artifact_records(
                s, run_id=run_id, batch_id=batch_id,
                bricks=[{"name": "build-image", "definition": spec.model_dump()}],
                logs={"build-image": [f"echo {marker}"]},
            )

        # 3. SBOM (COS-167) — снять поверх образа, заякорить durable, sbom_ref.
        sbom = await pg_client.post(
            "/api/v1/artifacts/sbom/image",
            json={"name": NAME, "version": VERSION},
        )
        assert sbom.status_code == 200, sbom.text
        sbom_body = sbom.json()
        assert sbom_body["generator"] in {"syft", "python-inventory"}
        assert sbom_body["artifact_digest"] == manifest_digest
        assert sbom_body["canonical_ref"] == marker
        expected_ref = (
            f"oci://{REGISTRY}/cosmoport/zr/{NAME}@{manifest_digest}#sbom"
        )
        assert sbom_body["sbom_ref"] == expected_ref

        # read-back (COS-152: restart-survival, latest wins из ledger).
        read = await pg_client.get(
            f"/api/v1/artifacts/sbom/image/{NAME}/{VERSION}"
        )
        assert read.status_code == 200, read.text
        assert read.json()["generator"] == sbom_body["generator"]

        # 4. trivy PASS (COS-168) → attach 201 + durable read-back.
        attach = await pg_client.post(
            f"/api/v1/releases/{release_id}/trivy/attach",
            json=_trivy_pass(manifest_digest),
        )
        assert attach.status_code == 201, attach.text
        assert attach.json()["gate_verdict"] == "PASS"
        got = await pg_client.get(f"/api/v1/releases/{release_id}/trivy")
        assert got.status_code == 200, got.text
        assert got.json()["gate_verdict"] == "PASS"

        # 5. deploy (COS-165) — materialize ТОЛЬКО после trivy PASS.
        r = await pg_client.post(f"/api/v1/releases/{release_id}/deploy")
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "deployed"
        assert marker in r.json()["artifacts"]

        # 6. durable Evidence: sbom + trivy на месте; sbom_ref проставлен.
        rows = await _ledger(run_id)
        sources = {row["source"] for row in rows}
        assert "cosmo-artifact-sbom" in sources
        assert "cosmo-trivy-gate" in sources
        async with session_maker() as s:
            rec = await latest_artifact_record(s, NAME, VERSION)
        await engine.dispose()
        assert rec is not None
        assert rec.sbom_ref == expected_ref
        assert any(row["sbom_ref"] == expected_ref for row in rows)

        # cleanup live-контейнера.
        cname = f"{NAME}-{VERSION}"
        _run(["docker", "rm", "-f", cname], timeout=60)

    async def test_trivy_block_blocks_deploy(self, pg_client):
        # Critical>0 → gate BLOCK → deploy 409, статус не покидает approved.
        run_id = "cos168run-block"
        release_id = "cos168-rel-block"
        await _seed(run_id, release_id)

        digest = "sha256:" + "aa" * 32
        from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

        engine = create_async_engine(_PG_URL, echo=False)
        session_maker = async_sessionmaker(engine, expire_on_commit=False)
        async with session_maker() as s:
            await record_artifact_record(
                s,
                ArtifactRecord(
                    name=NAME, version=VERSION, digest=digest,
                    registry=REGISTRY, repository="cosmoport", namespace="zr",
                    run_id=run_id,
                ),
            )
        await engine.dispose()

        attach = await pg_client.post(
            f"/api/v1/releases/{release_id}/trivy/attach",
            json=_trivy_block(digest),
        )
        assert attach.status_code == 201, attach.text
        assert attach.json()["gate_verdict"] == "BLOCK"
        assert attach.json()["clearance"] == "DENIED"

        r = await pg_client.post(f"/api/v1/releases/{release_id}/deploy")
        assert r.status_code == 409, r.text
        assert await _release_status(release_id) == "approved"

        rows = await _ledger(run_id)
        trivy_rows = [row for row in rows if row["source"] == "cosmo-trivy-gate"]
        assert trivy_rows and trivy_rows[0]["verdict"] == "BLOCK"