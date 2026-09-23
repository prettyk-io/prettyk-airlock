# -*- coding: utf-8 -*-
"""COS-167: PK-C-003.6 / DOCKER_AUDIT — SBOM поверх собранного образа.

Покрытие:
  - DTO: request name/version, response roundtrip, ``compute_sbom_ref`` детерминизм;
  - POST /api/v1/artifacts/sbom/image:
      * по актуальному ArtifactRecord генерится честный SBOM (syft → python-inventory
        fallback), документ CycloneDX 1.5, durable-якорь (source=cosmo-artifact-sbom),
        ``ArtifactRecord.sbom_ref`` проставляется (latest wins);
      * digest-сверка: ``artifact_digest`` == manifest-digest ArtifactRecord'а;
      * нет durable-записи артефакта (`name:version`) → 404;
  - GET /api/v1/artifacts/sbom/image/{name}/{version}: durable read, latest wins,
    404 ghost.

Запуск:  pytest .../test_artifact_sbom.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import AsyncClient

_och = Path(__file__).resolve().parents[2]
if str(_och) not in sys.path:
    sys.path.insert(0, str(_och))

pytestmark = pytest.mark.asyncio

from orchestrator.cosmo.domain.artifact_record import ArtifactRecord  # noqa: E402
from orchestrator.cosmo.domain.artifact_sbom import (  # noqa: E402
    ArtifactSbomRequest,
    ArtifactSbomResponse,
)
from orchestrator.cosmo.ledger.artifact_record import (  # noqa: E402
    latest_artifact_record,
    record_artifact_record,
)
from orchestrator.cosmo.ledger.artifact_sbom import compute_sbom_ref  # noqa: E402

import _testpg  # noqa: E402

_PG_URL = _testpg.TEST_PG_URL

DOMAIN = "cos167-dom"
PLAN = "cos167-plan"
APP = "cos167-app"
RUN = "cos167run0001"
NAME = "cosmo-testapp"
VERSION = "0.1.0"
DIGEST = "sha256:" + "ab" * 32
REGISTRY = "localhost:5100"


def _record() -> ArtifactRecord:
    return ArtifactRecord(
        name=NAME, version=VERSION, digest=DIGEST,
        registry=REGISTRY, repository="cosmoport", namespace="zr",
        run_id=RUN,
    )


async def _seed_record() -> None:
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

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
        ), {"r": RUN, "p": PLAN, "d": DOMAIN})

    session_maker = async_sessionmaker(engine, expire_on_commit=False)
    async with session_maker() as s:
        await record_artifact_record(s, _record())
    await engine.dispose()


async def _ledger_rows(run_id: str) -> list[dict]:
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(_PG_URL, echo=False)
    try:
        async with engine.connect() as conn:
            res = await conn.execute(
                text(
                    "SELECT id, type, content_hash, provenance_json "
                    "FROM evidence_ledger WHERE run_id = :rid "
                    "ORDER BY created_at ASC"
                ),
                {"rid": run_id},
            )
            return [dict(r) for r in res.mappings().all()]
    finally:
        await engine.dispose()


# ── DTO / helpers unit ───────────────────────────────────────────────────

class TestArtifactSbomDto:
    def test_request_valid(self):
        req = ArtifactSbomRequest.model_validate({"name": NAME, "version": VERSION})
        assert req.name == NAME
        assert req.version == VERSION

    def test_compute_sbom_ref_deterministic(self):
        a = compute_sbom_ref(_record())
        b = compute_sbom_ref(_record())
        assert a == b
        assert a.startswith("oci://")
        assert a.endswith(f"@{DIGEST}#sbom")


# ── Route tests ──────────────────────────────────────────────────────────

class TestArtifactSbomRoute:
    @pytest_asyncio.fixture(autouse=True)
    async def _seed(self, pg_client: AsyncClient):
        await _seed_record()

    async def test_generate_anchors_and_links_sbom_ref(self, pg_client: AsyncClient):
        res = await pg_client.post(
            "/api/v1/artifacts/sbom/image",
            json={"name": NAME, "version": VERSION},
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["name"] == NAME
        assert body["version"] == VERSION
        assert body["artifact_digest"] == DIGEST
        assert body["sbom_ref"].endswith(f"@{DIGEST}#sbom")
        assert body["generator"] in ("syft", "python-inventory")
        assert body["document"]["bomFormat"] == "CycloneDX"
        assert body["document"]["specVersion"] == "1.5"
        assert len(body["content_hash"]) == 64

        # SBOM durable + ArtifactRecord.sbom_ref проставлен (latest wins).
        rows = await _ledger_rows(RUN)
        sbom_rows = [r for r in rows if r["provenance_json"].get(
            "source") == "cosmo-artifact-sbom"]
        assert len(sbom_rows) == 1
        assert sbom_rows[0]["type"] == "decision"

        from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
        engine = create_async_engine(_PG_URL, echo=False)
        session_maker = async_sessionmaker(engine, expire_on_commit=False)
        async with session_maker() as s:
            record = await latest_artifact_record(s, NAME, VERSION)
        await engine.dispose()
        assert record is not None
        assert record.sbom_ref == body["sbom_ref"]

    async def test_read_back_durable(self, pg_client: AsyncClient):
        posted = await pg_client.post(
            "/api/v1/artifacts/sbom/image",
            json={"name": NAME, "version": VERSION},
        )
        assert posted.status_code == 200, posted.text
        res = await pg_client.get(
            f"/api/v1/artifacts/sbom/image/{NAME}/{VERSION}",
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["bomFormat"] == "CycloneDX"
        assert body["specVersion"] == "1.5"
        assert body["generator"] == posted.json()["generator"]

    async def test_missing_artifact_record_404(self, pg_client: AsyncClient):
        res = await pg_client.post(
            "/api/v1/artifacts/sbom/image",
            json={"name": "ghost-app", "version": "9.9.9"},
        )
        assert res.status_code == 404, res.text

    async def test_read_unknown_404(self, pg_client: AsyncClient):
        res = await pg_client.get("/api/v1/artifacts/sbom/image/ghost-app/9.9.9")
        assert res.status_code == 404, res.text

    async def test_response_roundtrip_shape(self):
        rec = _record()
        resp = ArtifactSbomResponse(
            name=rec.name, version=rec.version, artifact_digest=rec.digest,
            canonical_ref=rec.canonical_ref(),
            sbom_ref=compute_sbom_ref(rec),
            generator="python-inventory", tool_name="python-inventory",
            content_hash="a" * 64,
            document={"bomFormat": "CycloneDX", "specVersion": "1.5",
                      "serialNumber": "urn:uuid:00000000-0000-0000-0000-000000000000",
                      "version": 1, "generator": "python-inventory",
                      "vulnSummary": {"available": False, "reason": "n/a"}},
        )
        assert resp.sbom_ref.endswith("#sbom")