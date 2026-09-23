# -*- coding: utf-8 -*-
"""COS-166: Live E2E steel-thread smoke — build → push → capture → deploy → run.

Один наблюдаемый live-проход против реального registry-zr (:5100) и compose
(cеть ``cosmo-net``), с durable Evidence на каждом шаге. Не мок:
``docker build`` / ``docker push`` / ``docker pull`` / ``docker run`` —
реальные; digest — manifest-digest, которым registry ответил на push.

Ключевая находка COS-166 (закрыта код-фиксом в COS-162 render):
  - ``docker push <qualified>@sha256:<digest>`` неработоспособен — docker
    возвращает «cannot push a digest reference»;
  - ``docker build --iidfile`` даёт CONFIG digest (image id ``64f724…``),
    а registry хранит MANIFEST digest (``59903d…``) — они РАЗНЫЕ (разный
    алгоритм: config-blob vs JSON-manifest);
  - исправленный render шлёт push по ТЕГУ (no-``latest``) и снимает
    manifest-digest из строки ``digest: sha256:...`` ответа push.

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

DOMAIN = "cos166-dom"
APP = "cos166-app"
PLAN = "cos166-plan"

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
            "VALUES (:d, 'cos166', 'gitea', 'http://gitea:3000', 't', "
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
            "provenance_json->>'digest' AS digest, "
            "provenance_json->>'canonical_ref' AS ref "
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
    """COS-168: clean trivy-отчёт (critical=0) → gate PASS для deploy."""
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


# ── live steel thread ────────────────────────────────────────────────────────

class TestCos166LiveSteelThread:
    async def test_build_push_capture_deploy_run(self, pg_client):
        spec = DockerBuildSpec(
            image_name=NAME, version=VERSION, registry=REGISTRY,
            repository="cosmoport", namespace="zr",
            dockerfile="Dockerfile", context=".",
        )

        # 1. build → push через реальный render (docker build/push, Git Bash).
        digest_file = ".cos166_digest"
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
        # live: config-digest из iidfile ≠ manifest-digest из ответа push
        iid = _run(["docker", "inspect", "--format", "{{.Id}}",
                    f"{NAME}:{VERSION}"], timeout=30)
        assert iid is not None and iid.stdout.strip() != manifest_digest

        marker = f"{NAME}:{VERSION}@{manifest_digest}"
        run_id = "cos166run-live"
        batch_id = "cos166bat-live"
        release_id = "cos166-rel-live"
        await _seed(run_id, release_id, batch_id=batch_id)

        # 2. capture (COS-164) — реальный digest из реального push-вывода.
        from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

        engine = create_async_engine(_PG_URL, echo=False)
        session_maker = async_sessionmaker(engine, expire_on_commit=False)
        async with session_maker() as s:
            entry_ids = await capture_artifact_records(
                s, run_id=run_id, batch_id=batch_id,
                bricks=[{"name": "build-image",
                         "definition": spec.model_dump()}],
                logs={"build-image": [f"echo {marker}"]},
            )
        assert len(entry_ids) == 1

        # 2b. COS-168: trivy attach PASS (critical=0) — deploy требует gate.
        attach = await pg_client.post(
            f"/api/v1/releases/{release_id}/trivy/attach",
            json=_trivy_pass(manifest_digest),
        )
        assert attach.status_code == 201, attach.text

        # 3. deploy (COS-165) — real docker pull+run, не monkeypatch.
        r = await pg_client.post(f"/api/v1/releases/{release_id}/deploy")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "deployed"
        assert marker in body["artifacts"]

        # 4. контейнер Up (healthy) — фактический, не фейк.
        cname = f"{NAME}-{VERSION}"
        try:
            p = _run(["docker", "inspect", "--format", "{{.State.Health.Status}}",
                      cname], timeout=30)
            assert p is not None and p.returncode == 0
            assert p.stdout.strip() == "healthy"
        finally:
            _run(["docker", "rm", "-f", cname], timeout=60)

        # 5. durable Evidence + canonical_ref консистентны по всей цепочке.
        rows = await _ledger(run_id)
        sources = {row["source"] for row in rows}
        assert "cosmo-artifact-record" in sources
        assert "cosmo-release-deploy" in sources

        async with session_maker() as s:
            rec = await latest_artifact_record(s, NAME, VERSION)
        await engine.dispose()
        assert rec is not None
        assert rec.digest == manifest_digest
        assert rec.canonical_ref() == marker
        assert any(row["ref"] == marker for row in rows)

    async def test_bogus_digest_rolls_back_not_deployed(self, pg_client):
        # Negьative: ArtifactRecord с битым digest → честный rollback + 502.
        run_id = "cos166run-neg"
        release_id = "cos166-rel-neg"
        await _seed(run_id, release_id)

        from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

        engine = create_async_engine(_PG_URL, echo=False)
        session_maker = async_sessionmaker(engine, expire_on_commit=False)
        bogus = "sha256:" + "ee" * 32
        async with session_maker() as s:
            await record_artifact_record(
                s,
                ArtifactRecord(
                    name=NAME, version=VERSION, digest=bogus,
                    registry=REGISTRY, repository="cosmoport", namespace="zr",
                    run_id=run_id,
                ),
            )
        await engine.dispose()

        # COS-168: trivy attach PASS для bogus digest — иначе deploy встанет
        # на 409 ещё до pull (gate), а тест проверяет реальный rollback pull'а.
        attach = await pg_client.post(
            f"/api/v1/releases/{release_id}/trivy/attach",
            json=_trivy_pass(bogus),
        )
        assert attach.status_code == 201, attach.text

        r = await pg_client.post(f"/api/v1/releases/{release_id}/deploy")
        assert r.status_code == 502, r.text
        assert await _release_status(release_id) == "rollback"

        rows = await _ledger(run_id)
        assert any(row["source"] == "cosmo-release-deploy-failed" for row in rows)

        # контейнера нет / не healthy (rollback снёс или не поднял).
        p = _run(["docker", "inspect", "--format", "{{.State.Health.Status}}",
                  f"{NAME}-{VERSION}"], timeout=30)
        assert not (p is not None and p.returncode == 0
                    and p.stdout.strip() == "healthy")