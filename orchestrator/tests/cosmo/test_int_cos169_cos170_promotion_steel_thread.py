# -*- coding: utf-8 -*-
"""COS-169/170: Live E2E steel-thread smoke — multi-zone promotion ЗР→ЗТ→ЗПЭ.

Один наблюдаемый live-проход против реального registry-zr (:5100), ``cosmo-net``
и docker: build → push → capture → sbom → trivy → deploy → promote/land
ЗР→ЗТ→ЗПЭ, с durable Evidence на каждом переходе и честным negative-проходом
(mismatch digest на landing → 422, промо остановлено).

Honesty: SBOM генерится syft→python-inventory fallback (сигнатура генератора
честная); trivy-вердикт приходит attach-контрактом (бинарь trivy на стенде не
нужен — вердикт считает gate). Пропускается graceful при оффлайн-контуре.
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

REGISTRY = "localhost:5100"
NAME = "cosmo-testapp"
VERSION = "0.1.0"
APP_DIR = _REPO / "apps" / "cosmo-testapp"

DOMAIN = "cos170-dom"
APP = "cos170-app"
PLAN = "cos170-plan"

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


# ── seeding / helpers ────────────────────────────────────────────────────────

async def _seed(run_id: str, release_id: str, *, batch_id: str | None = None) -> None:
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(_PG_URL, echo=False)
    async with engine.begin() as conn:
        await conn.execute(text(
            "INSERT INTO domains (id, label, forge_type, forge_url, "
            "forge_token_ref, rbac_config, quota_max_runs, "
            "quota_max_storage_gb, quota_max_cpu, created_at) "
            "VALUES (:d, 'cos170', 'gitea', 'http://gitea:3000', 't', "
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


async def _promotion_rows(run_id: str) -> dict[str, list[str]]:
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(_PG_URL, echo=False)
    try:
        async with engine.connect() as conn:
            res = await conn.execute(
                text(
                    "SELECT provenance_json->>'source' AS source, "
                    "provenance_json->>'target_zone' AS zone, "
                    "provenance_json->>'status' AS status "
                    "FROM evidence_ledger WHERE run_id = :r "
                    "ORDER BY created_at, id"
                ),
                {"r": run_id},
            )
            rows = [dict(r) for r in res.mappings().all()]
    finally:
        await engine.dispose()
    out: dict[str, list[str]] = {"package": [], "landing": []}
    for r in rows:
        if r["source"] == "cosmo-promotion-package":
            out["package"].append(f'{r["zone"]}:{r["status"]}')
        elif r["source"] == "cosmo-promotion-landing":
            out["landing"].append(f'{r["zone"]}:{r["status"]}')
    return out


async def _zone(release_id: str) -> str:
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(_PG_URL, echo=False)
    try:
        async with engine.connect() as conn:
            res = await conn.execute(
                text("SELECT current_zone FROM releases WHERE id = :r"),
                {"r": release_id},
            )
            row = res.first()
    finally:
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


async def _build_push_capture_sbom_trivy_deploy(
    pg_client, run_id: str, release_id: str, batch_id: str, digest_file: str
) -> tuple[str, str]:
    """Полный pre-promotion pipeline → (manifest_digest, sbom_ref)."""
    spec = DockerBuildSpec(
        image_name=NAME, version=VERSION, registry=REGISTRY,
        repository="cosmoport", namespace="zr",
        dockerfile="Dockerfile", context=".",
    )
    script = "\n".join(render_docker_build_commands(spec, digest_file)) + "\n"
    proc = subprocess.run(
        [_GIT_BASH, "-c", script], cwd=str(APP_DIR),
        capture_output=True, text=True, timeout=600,
    )
    assert proc.returncode == 0, f"build/push failed: {proc.stderr}"
    manifest_digest = (APP_DIR / digest_file).read_text().strip()
    try:
        (APP_DIR / digest_file).unlink()
    except OSError:
        pass
    assert re.fullmatch(r"sha256:[0-9a-f]{64}", manifest_digest)

    marker = f"{NAME}:{VERSION}@{manifest_digest}"

    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

    engine = create_async_engine(_PG_URL, echo=False)
    session_maker = async_sessionmaker(engine, expire_on_commit=False)
    async with session_maker() as s:
        await capture_artifact_records(
            s, run_id=run_id, batch_id=batch_id,
            bricks=[{"name": "build-image", "definition": spec.model_dump()}],
            logs={"build-image": [f"echo {marker}"]},
        )

    sbom = await pg_client.post(
        "/api/v1/artifacts/sbom/image",
        json={"name": NAME, "version": VERSION},
    )
    assert sbom.status_code == 200, sbom.text
    sbom_ref = sbom.json()["sbom_ref"]

    attach = await pg_client.post(
        f"/api/v1/releases/{release_id}/trivy/attach",
        json=_trivy_pass(manifest_digest),
    )
    assert attach.status_code == 201, attach.text

    dep = await pg_client.post(f"/api/v1/releases/{release_id}/deploy")
    assert dep.status_code == 200, dep.text
    assert dep.json()["status"] == "deployed"

    await engine.dispose()
    return manifest_digest, sbom_ref


# ── live steel thread ────────────────────────────────────────────────────────

class TestCos170PromotionLive:
    async def test_promotion_zr_zt_zpe(self, pg_client):
        run_id = "cos170run-live"
        release_id = "cos170-rel-live"
        batch_id = "cos170bat-live"
        await _seed(run_id, release_id, batch_id=batch_id)

        manifest_digest, sbom_ref = await _build_push_capture_sbom_trivy_deploy(
            pg_client, run_id, release_id, batch_id, ".cos170_digest",
        )

        # 1. promotion ЗР→ЗТ (COS-169): pack + land (digest-matching).
        pkg_zt = await pg_client.post(f"/api/v1/releases/{release_id}/promote")
        assert pkg_zt.status_code == 200, pkg_zt.text
        assert pkg_zt.json()["target_zone"] == "zt"
        assert pkg_zt.json()["source_zone"] == "zr"
        assert pkg_zt.json()["artifacts"][0]["digest"] == manifest_digest
        assert pkg_zt.json()["artifacts"][0]["sbom_ref"] == sbom_ref

        land_zt = await pg_client.post(
            f"/api/v1/releases/{release_id}/promote/land",
            json={"target_zone": "zt",
                  "incoming_manifest_digest": pkg_zt.json()["package_digest"]},
        )
        assert land_zt.status_code == 200, land_zt.text
        assert land_zt.json()["status"] == "promoted"
        assert await _zone(release_id) == "zt"

        # 2. promotion ЗТ→ЗПЭ (COS-170): тот же артефакт, durable per-zone.
        pkg_zpe = await pg_client.post(f"/api/v1/releases/{release_id}/promote")
        assert pkg_zpe.status_code == 200, pkg_zpe.text
        assert pkg_zpe.json()["target_zone"] == "zpe"
        assert pkg_zpe.json()["source_zone"] == "zt"

        land_zpe = await pg_client.post(
            f"/api/v1/releases/{release_id}/promote/land",
            json={"target_zone": "zpe",
                  "incoming_manifest_digest": pkg_zpe.json()["package_digest"]},
        )
        assert land_zpe.status_code == 200, land_zpe.text
        assert land_zpe.json()["status"] == "promoted"
        assert await _zone(release_id) == "zpe"

        # 3. durable Evidence per-zone.
        rows = await _promotion_rows(run_id)
        assert sorted(rows["package"]) == ["zpe:packed", "zt:packed"]
        assert sorted(rows["landing"]) == ["zpe:promoted", "zt:promoted"]

        # 4. финальная зона → промо дальше невозможно.
        final = await pg_client.post(f"/api/v1/releases/{release_id}/promote")
        assert final.status_code == 400, final.text

        _run(["docker", "rm", "-f", f"{NAME}-{VERSION}"], timeout=60)

    async def test_promotion_mismatch_stops(self, pg_client):
        # Negative: битый digest на landing → честный 422, промо остановлено.
        run_id = "cos170run-neg"
        release_id = "cos170-rel-neg"
        batch_id = "cos170bat-neg"
        await _seed(run_id, release_id, batch_id=batch_id)

        _, _ = await _build_push_capture_sbom_trivy_deploy(
            pg_client, run_id, release_id, batch_id, ".cos170_neg_digest",
        )

        pkg = await pg_client.post(f"/api/v1/releases/{release_id}/promote")
        assert pkg.status_code == 200, pkg.text

        wrong = "0" * 64
        land = await pg_client.post(
            f"/api/v1/releases/{release_id}/promote/land",
            json={"target_zone": "zt", "incoming_manifest_digest": wrong},
        )
        assert land.status_code == 422, land.text
        assert await _zone(release_id) == "zr"

        rows = await _promotion_rows(run_id)
        assert rows["landing"] == []  # честно: promoted не записался

        _run(["docker", "rm", "-f", f"{NAME}-{VERSION}"], timeout=60)