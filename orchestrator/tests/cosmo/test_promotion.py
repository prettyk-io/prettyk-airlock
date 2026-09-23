# -*- coding: utf-8 -*-
"""COS-169/170: Promotion packing + landing (ЗР→ЗТ→ЗПЭ).

Покрытие:
  - DTO/каноны: детерминированный пакетный digest (не зависит от времени),
    idempotent fingerprint, canonical_ref-сортировка;
  - POST /api/v1/releases/{release_id}/promote:
      * deployed + artifact record + SBOM (sbom_ref) + trivy PASS → packed;
      * idempotent re-pack → duplicate, тот же digest/revision, один ledger-ряд;
      * BLOCK/отсутствие trivy или отсутствие SBOM → 409 (честный блок);
  - POST /api/v1/releases/{release_id}/promote/land:
      * корректный manifest-digest → promoted + зона zr→zt + durable landing;
      * mismatch digest → 422, зона НЕ двинулась;
      * нелинейный переход (zr→zpe) → 409;
      * нет пакета (не пачился) → 404;
      * multi-zone zr→zt→zpe (COS-170) на обоих хостах;
  - GET promotion + promotion/land read-back (restart-survival, latest wins).

Запуск:  pytest .../test_promotion.py -q
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
from orchestrator.cosmo.domain.promotion import (  # noqa: E402
    PromotionArtifact,
    build_promotion_manifest,
    compute_package_digest,
    promotion_content_fingerprint,
)
from orchestrator.cosmo.ledger.artifact_record import record_artifact_record  # noqa: E402

import _testpg  # noqa: E402

_PG_URL = _testpg.TEST_PG_URL

DOMAIN = "cos169-dom"
PLAN = "cos169-plan"
APP = "cos169-app"
RUN = "cos169run0001"
REL = "cos169rel0001"
NAME = "cosmo-testapp"
VERSION = "0.1.0"
DIGEST = "sha256:" + "ef" * 32
REGISTRY = "localhost:5100"
SBOM_REF = f"oci://{REGISTRY}/cosmoport/zr/{NAME}@{DIGEST}#sbom"


def _trivy_pass(digest: str = DIGEST) -> dict:
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


def _trivy_block(digest: str = DIGEST) -> dict:
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
                {"id": "CVE-2099-0001", "severity": "critical",
                 "package_name": "demo", "installed_version": "1.0.0"},
            ],
        },
    }


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


async def _release_zone(release_id: str) -> str:
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


# ── DTO / canon unit ────────────────────────────────────────────────────

class TestPromotionCanon:
    def test_package_digest_deterministic(self):
        arts = [PromotionArtifact(
            name=NAME, version=VERSION, digest=DIGEST,
            canonical_ref=f"{NAME}:{VERSION}@{DIGEST}",
            sbom_ref=SBOM_REF, trivy_verdict="PASS")]
        m1 = build_promotion_manifest(REL, "zr", "zt", 1, arts)
        m2 = build_promotion_manifest(REL, "zr", "zt", 1, arts)
        assert compute_package_digest(m1) == compute_package_digest(m2)
        assert len(compute_package_digest(m1)) == 64

    def test_artifact_order_independent(self):
        a = PromotionArtifact(name="a", version="1.0.0", digest=DIGEST,
                              canonical_ref="a:1.0.0@" + DIGEST,
                              sbom_ref="oci://a#sbom", trivy_verdict="PASS")
        b = PromotionArtifact(name="b", version="1.0.0", digest=DIGEST,
                              canonical_ref="b:1.0.0@" + DIGEST,
                              sbom_ref="oci://b#sbom", trivy_verdict="PASS")
        m1 = build_promotion_manifest(REL, "zr", "zt", 1, [a, b])
        m2 = build_promotion_manifest(REL, "zr", "zt", 1, [b, a])
        assert compute_package_digest(m1) == compute_package_digest(m2)
        assert promotion_content_fingerprint([a, b]) == promotion_content_fingerprint([b, a])

    def test_fingerprint_changes_on_gate(self):
        base = PromotionArtifact(name=NAME, version=VERSION, digest=DIGEST,
                                 canonical_ref=f"{NAME}:{VERSION}@{DIGEST}",
                                 sbom_ref=SBOM_REF, trivy_verdict="PASS")
        blocked = base.model_copy(update={"trivy_verdict": "BLOCK"})
        assert promotion_content_fingerprint([base]) != promotion_content_fingerprint([blocked])


# ── Route tests ─────────────────────────────────────────────────────────

class TestPromotionRoute:
    @pytest_asyncio.fixture(autouse=True)
    async def _seed(self, pg_client: AsyncClient):
        from sqlalchemy import text
        from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

        engine = create_async_engine(_PG_URL, echo=False)
        async with engine.begin() as conn:
            await conn.execute(text(
                "INSERT INTO domains (id, label, forge_type, forge_url, "
                "forge_token_ref, rbac_config, quota_max_runs, "
                "quota_max_storage_gb, quota_max_cpu, created_at) "
                "VALUES (:d, 'cos169', 'gitea', 'http://gitea:3000', 't', "
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
            await conn.execute(text(
                "INSERT INTO releases (id, domain_id, plan_id, status, "
                "current_zone, version, run_ids, approvals, artifacts, "
                "transfer_history, created_at) VALUES (:rel, :d, :p, 'deployed', "
                "'zr', '1.0.0', CAST(:runs AS jsonb), '[]'::jsonb, '[]'::jsonb, "
                "'[]'::jsonb, now()) ON CONFLICT (id) DO NOTHING"
            ), {"rel": REL, "d": DOMAIN, "p": PLAN, "runs": f'["{RUN}"]'})

        session_maker = async_sessionmaker(engine, expire_on_commit=False)
        async with session_maker() as s:
            await record_artifact_record(
                s,
                ArtifactRecord(
                    name=NAME, version=VERSION, digest=DIGEST,
                    registry=REGISTRY, repository="cosmoport", namespace="zr",
                    sbom_ref=SBOM_REF, run_id=RUN,
                ),
            )
        await engine.dispose()

    async def _trivy_pass_attach(self, pg_client: AsyncClient):
        res = await pg_client.post(
            f"/api/v1/releases/{REL}/trivy/attach", json=_trivy_pass(),
        )
        assert res.status_code == 201, res.text
        assert res.json()["gate_verdict"] == "PASS"

    async def test_pack_and_idempotent_repack(self, pg_client: AsyncClient):
        await self._trivy_pass_attach(pg_client)
        r1 = await pg_client.post(f"/api/v1/releases/{REL}/promote")
        assert r1.status_code == 200, r1.text
        body = r1.json()
        assert body["status"] == "packed"
        assert body["revision"] == 1
        assert body["target_zone"] == "zt"
        assert body["source_zone"] == "zr"
        assert len(body["package_digest"]) == 64
        assert body["artifacts"][0]["sbom_ref"] == SBOM_REF
        assert body["artifacts"][0]["trivy_verdict"] == "PASS"

        digest = body["package_digest"]

        # Idempotent re-pack: тот же digest/revision, статус duplicate.
        r2 = await pg_client.post(f"/api/v1/releases/{REL}/promote")
        assert r2.status_code == 200, r2.text
        b2 = r2.json()
        assert b2["status"] == "duplicate"
        assert b2["package_digest"] == digest
        assert b2["revision"] == 1

        # Один durable-ряд пака (не размножается).
        rows = await _ledger_rows(RUN)
        pack_rows = [r for r in rows if r["provenance_json"].get(
            "source") == "cosmo-promotion-package"]
        assert len(pack_rows) == 1
        assert pack_rows[0]["content_hash"] == digest

    async def test_pack_read_back(self, pg_client: AsyncClient):
        await self._trivy_pass_attach(pg_client)
        posted = await pg_client.post(f"/api/v1/releases/{REL}/promote")
        assert posted.status_code == 200, posted.text
        got = await pg_client.get(
            f"/api/v1/releases/{REL}/promotion", params={"target_zone": "zt"},
        )
        assert got.status_code == 200, got.text
        assert got.json()["package_digest"] == posted.json()["package_digest"]

    async def test_pack_blocked_without_trivy(self, pg_client: AsyncClient):
        # Артефакт есть, trivy-вердикта нет → pack 409.
        res = await pg_client.post(f"/api/v1/releases/{REL}/promote")
        assert res.status_code == 409, res.text
        assert "trivy" in res.json()["detail"].lower()

    async def test_pack_blocked_on_trivy_block(self, pg_client: AsyncClient):
        res = await pg_client.post(
            f"/api/v1/releases/{REL}/trivy/attach", json=_trivy_block(),
        )
        assert res.status_code == 201, res.text
        res = await pg_client.post(f"/api/v1/releases/{REL}/promote")
        assert res.status_code == 409, res.text
        assert "block" in res.json()["detail"].lower() or "BLOCK" in res.json()["detail"]

    async def test_land_promoted_and_durable(self, pg_client: AsyncClient):
        await self._trivy_pass_attach(pg_client)
        pkg = await pg_client.post(f"/api/v1/releases/{REL}/promote")
        assert pkg.status_code == 200, pkg.text
        digest = pkg.json()["package_digest"]

        land = await pg_client.post(
            f"/api/v1/releases/{REL}/promote/land",
            json={"target_zone": "zt", "incoming_manifest_digest": digest},
        )
        assert land.status_code == 200, land.text
        body = land.json()
        assert body["status"] == "promoted"
        assert body["gate_pass"] is True
        assert body["sbom_present"] is True
        assert body["current_zone"] == "zt"
        assert await _release_zone(REL) == "zt"

        # durable landing read-back.
        got = await pg_client.get(
            f"/api/v1/releases/{REL}/promotion/land",
            params={"target_zone": "zt"},
        )
        assert got.status_code == 200, got.text
        assert got.json()["status"] == "promoted"

        rows = await _ledger_rows(RUN)
        land_rows = [r for r in rows if r["provenance_json"].get(
            "source") == "cosmo-promotion-landing"]
        assert len(land_rows) == 1
        assert land_rows[0]["provenance_json"]["status"] == "promoted"

    async def test_land_mismatch_422_no_zone_move(self, pg_client: AsyncClient):
        await self._trivy_pass_attach(pg_client)
        pkg = await pg_client.post(f"/api/v1/releases/{REL}/promote")
        digest = pkg.json()["package_digest"]

        wrong = "a" * 64  # guaranteed ≠ digest
        land = await pg_client.post(
            f"/api/v1/releases/{REL}/promote/land",
            json={"target_zone": "zt", "incoming_manifest_digest": wrong},
        )
        assert land.status_code == 422, land.text
        assert land.json()["detail"]["status"] == "mismatch"
        assert await _release_zone(REL) == "zr"

        # match but правильно: digest == пакет (регистрация не флуд).
        assert wrong != digest

    async def test_land_idempotent_replay_duplicate(self, pg_client: AsyncClient):
        await self._trivy_pass_attach(pg_client)
        pkg = await pg_client.post(f"/api/v1/releases/{REL}/promote")
        digest = pkg.json()["package_digest"]

        land1 = await pg_client.post(
            f"/api/v1/releases/{REL}/promote/land",
            json={"target_zone": "zt", "incoming_manifest_digest": digest},
        )
        assert land1.status_code == 200, land1.text
        assert land1.json()["status"] == "promoted"

        # Повторный landing того же перехода → честный duplicate, без 2-го ряда.
        land2 = await pg_client.post(
            f"/api/v1/releases/{REL}/promote/land",
            json={"target_zone": "zt", "incoming_manifest_digest": digest},
        )
        assert land2.status_code == 200, land2.text
        assert land2.json()["status"] == "duplicate"
        assert await _release_zone(REL) == "zt"

        rows = await _ledger_rows(RUN)
        land_rows = [r for r in rows if r["provenance_json"].get(
            "source") == "cosmo-promotion-landing"]
        assert len(land_rows) == 1

    async def test_land_without_package_404(self, pg_client: AsyncClient):
        res = await pg_client.post(
            f"/api/v1/releases/{REL}/promote/land",
            json={"target_zone": "zt",
                  "incoming_manifest_digest": "a" * 64},
        )
        assert res.status_code == 404, res.text

    async def test_multi_zone_zr_zt_zpe(self, pg_client: AsyncClient):
        """COS-170: сквозной проход zr→zt→zpe, durable evidence на каждом переходе."""
        await self._trivy_pass_attach(pg_client)

        # hop 1: zr → zt
        pkg1 = await pg_client.post(f"/api/v1/releases/{REL}/promote")
        assert pkg1.status_code == 200, pkg1.text
        assert pkg1.json()["target_zone"] == "zt"
        land1 = await pg_client.post(
            f"/api/v1/releases/{REL}/promote/land",
            json={"target_zone": "zt",
                  "incoming_manifest_digest": pkg1.json()["package_digest"]},
        )
        assert land1.status_code == 200, land1.text
        assert land1.json()["current_zone"] == "zt"

        # hop 2: zt → zpe (тот же артефакт, тот же trivy PASS, тот же SBOM)
        pkg2 = await pg_client.post(f"/api/v1/releases/{REL}/promote")
        assert pkg2.status_code == 200, pkg2.text
        assert pkg2.json()["target_zone"] == "zpe"
        assert pkg2.json()["source_zone"] == "zt"
        assert pkg2.json()["package_digest"] != pkg1.json()["package_digest"]
        land2 = await pg_client.post(
            f"/api/v1/releases/{REL}/promote/land",
            json={"target_zone": "zpe",
                  "incoming_manifest_digest": pkg2.json()["package_digest"]},
        )
        assert land2.status_code == 200, land2.text
        assert land2.json()["current_zone"] == "zpe"

        rows = await _ledger_rows(RUN)
        pack_rows = [r for r in rows if r["provenance_json"].get(
            "source") == "cosmo-promotion-package"]
        land_rows = [r for r in rows if r["provenance_json"].get(
            "source") == "cosmo-promotion-landing"]
        assert len(pack_rows) == 2  # zt + zpe
        assert len(land_rows) == 2
        zones = sorted(r["provenance_json"]["target_zone"] for r in land_rows)
        assert zones == ["zpe", "zt"]

        # В финальной зоне промоушен дальше невозможен.
        final = await pg_client.post(f"/api/v1/releases/{REL}/promote")
        assert final.status_code == 400, final.text