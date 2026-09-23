# -*- coding: utf-8 -*-
"""COS-163: durable-метаданные артефакта — write + read-through + restart-survival.

Покрытие:
  - domain (``ArtifactRecord``): canonical_ref (COS-142), no-latest,
    строгий semver/slug/sha256, детерминированный content_hash;
  - ``record_artifact_record``: durable write (type='decision', маркер
    ``cosmo-artifact-record``), digest+manifest+SBOM в provenance, требует
    run_id (не «в никуда»);
  - ``latest_artifact_record``: read-through durable (latest wins, не
    in-memory), переживает рестарт процесса;
  - целостность: повреждённый record_hash → отказ чтения (None).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_och = Path(__file__).resolve().parents[3]  # repo root — для import + subprocess probe
if str(_och) not in sys.path:
    sys.path.insert(0, str(_och))

pytestmark = pytest.mark.asyncio

from orchestrator.cosmo.domain.artifact_record import (  # noqa: E402
    ArtifactRecord,
    artifact_record_content_hash,
)
from orchestrator.cosmo.ledger.artifact_record import (  # noqa: E402
    ARTIFACT_RECORD_SOURCE,
    ARTIFACT_RECORD_TYPE,
    latest_artifact_record,
    record_artifact_record,
)

import _testpg  # noqa: E402

_PG_URL = _testpg.TEST_PG_URL

DOMAIN = "cos163-dom"
PLAN = "cos163-plan"

DIGEST = "sha256:" + "cd" * 32
DIGEST_2 = "sha256:" + "ee" * 32


def _record(digest: str = DIGEST, **kw) -> ArtifactRecord:
    base = dict(
        name="cosmo-testapp",
        version="0.1.0",
        digest=digest,
        registry="registry-zr:5000",
        repository="cosmoport",
        namespace="zr",
    )
    base.update(kw)
    return ArtifactRecord(**base)


# ── domain: canonical ref + content hash ─────────────────────────────────────

class TestArtifactRecordDomain:
    def test_canonical_ref_matches_cos162(self):
        r = _record()
        assert r.canonical_ref() == f"cosmo-testapp:0.1.0@{DIGEST}"

    def test_qualified_image(self):
        r = _record()
        assert r.qualified_image() == "registry-zr:5000/cosmoport/zr/cosmo-testapp"

    def test_latest_forbidden(self):
        with pytest.raises(Exception):
            _record(version="latest")

    def test_bad_semver_forbidden(self):
        with pytest.raises(Exception):
            _record(version="not-semver")

    def test_uppercase_name_forbidden(self):
        with pytest.raises(Exception):
            _record(name="Cosmo-TestApp")

    def test_non_sha256_digest_forbidden(self):
        with pytest.raises(Exception):
            _record(digest="sha1:" + "ab" * 20)

    def test_content_hash_deterministic(self):
        a = _record()
        b = _record()
        assert artifact_record_content_hash(a) == artifact_record_content_hash(b)
        assert artifact_record_content_hash(a) != artifact_record_content_hash(
            _record(digest=DIGEST_2)
        )


# ── durable write + read-through ─────────────────────────────────────────────

async def _seed_run(run_id: str) -> None:
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(_PG_URL, echo=False)
    async with engine.begin() as conn:
        await conn.execute(text(
            "INSERT INTO domains (id, label, forge_type, forge_url, "
            "forge_token_ref, rbac_config, quota_max_runs, "
            "quota_max_storage_gb, quota_max_cpu, created_at) "
            "VALUES (:d, 'cos163', 'gitea', 'http://gitea:3000', "
            "'t', '{}'::jsonb, 50, 100, 8, now()) "
            "ON CONFLICT (id) DO NOTHING"
        ), {"d": DOMAIN})
        await conn.execute(text(
            "INSERT INTO apps (id, domain_id, level) "
            "VALUES ('cos163-app', :d, 0) ON CONFLICT (id) DO NOTHING"
        ), {"d": DOMAIN})
        await conn.execute(text(
            "INSERT INTO pipeline_plans (id, app_id, level, scope_id, "
            "compiled_hash, compiled_at) VALUES (:p, 'cos163-app', "
            "'app', :p, 'h', now()) ON CONFLICT (id) DO NOTHING"
        ), {"p": PLAN})
        await conn.execute(text(
            "INSERT INTO runs (id, plan_id, trigger, domain_id, status, "
            "initiator_user_id, initiator_role, findings_refs, created_at) "
            "VALUES (:r, :p, 'manual', :d, 'succeeded', 'system', "
            "'system', '[]'::jsonb, now()) ON CONFLICT (id) DO NOTHING"
        ), {"r": run_id, "p": PLAN, "d": DOMAIN})
    await engine.dispose()


class TestArtifactRecordDurable:
    async def test_record_and_read_back(self):
        import uuid
        from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

        run_id = f"cos163run-{uuid.uuid4().hex[:12]}"
        await _seed_run(run_id)

        manifest = {"schemaVersion": 2, "layers": [{"digest": DIGEST}]}
        record = _record(
            manifest=manifest,
            sbom_ref="cyclonedx://cosmoport/zr/cosmo-testapp/0.1.0/sbom.json",
            run_id=run_id,
        )

        engine = create_async_engine(_PG_URL, echo=False)
        session_maker = async_sessionmaker(engine, expire_on_commit=False)
        async with session_maker() as s:
            entry_id = await record_artifact_record(s, record)
        assert entry_id
        async with session_maker() as s:
            fetched = await latest_artifact_record(s, "cosmo-testapp", "0.1.0")
        await engine.dispose()

        assert fetched is not None
        assert fetched.digest == DIGEST
        assert fetched.canonical_ref() == f"cosmo-testapp:0.1.0@{DIGEST}"
        assert fetched.manifest == manifest
        assert fetched.sbom_ref is not None
        assert fetched.run_id == run_id

    async def test_manifest_and_sbom_preserved(self):
        import uuid
        from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
        from sqlalchemy import text

        run_id = f"cos163run-{uuid.uuid4().hex[:12]}"
        await _seed_run(run_id)

        manifest = {"config": {"digest": DIGEST}, "layers": []}
        record = _record(manifest=manifest, sbom_ref=None, run_id=run_id)

        engine = create_async_engine(_PG_URL, echo=False)
        session_maker = async_sessionmaker(engine, expire_on_commit=False)
        async with session_maker() as s:
            await record_artifact_record(s, record)
        await engine.dispose()

        engine = create_async_engine(_PG_URL, echo=False)
        async with engine.begin() as conn:
            res = await conn.execute(text(
                "SELECT provenance_json FROM evidence_ledger "
                "WHERE run_id = :r AND provenance_json->>'source' = :src "
                "AND provenance_json->>'artifact_type' = :t"
            ), {"r": run_id, "src": ARTIFACT_RECORD_SOURCE, "t": ARTIFACT_RECORD_TYPE})
            rows = res.fetchall()
        await engine.dispose()
        assert len(rows) == 1
        prov = rows[0][0]
        assert prov["manifest"] == manifest
        assert prov["sbom_ref"] is None
        assert prov["digest"] == DIGEST
        assert prov["canonical_ref"] == f"cosmo-testapp:0.1.0@{DIGEST}"

    async def test_latest_wins_by_digest(self):
        import uuid
        from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

        run_id = f"cos163run-{uuid.uuid4().hex[:12]}"
        await _seed_run(run_id)

        engine = create_async_engine(_PG_URL, echo=False)
        session_maker = async_sessionmaker(engine, expire_on_commit=False)
        async with session_maker() as s:
            await record_artifact_record(s, _record(run_id=run_id))
            await record_artifact_record(
                s, _record(digest=DIGEST_2, run_id=run_id),
            )
        async with session_maker() as s:
            fetched = await latest_artifact_record(s, "cosmo-testapp", "0.1.0")
        await engine.dispose()

        assert fetched is not None
        assert fetched.digest == DIGEST_2

    async def test_record_without_run_id_raises(self):
        from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

        engine = create_async_engine(_PG_URL, echo=False)
        session_maker = async_sessionmaker(engine, expire_on_commit=False)
        async with session_maker() as s:
            with pytest.raises(ValueError, match="run_id"):
                await record_artifact_record(s, _record())
        await engine.dispose()

    async def test_record_with_unknown_run_raises(self):
        from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

        engine = create_async_engine(_PG_URL, echo=False)
        session_maker = async_sessionmaker(engine, expire_on_commit=False)
        async with session_maker() as s:
            with pytest.raises(ValueError, match="not found"):
                await record_artifact_record(s, _record(run_id="ghost-run"))
        await engine.dispose()

    async def test_missing_record_returns_none(self):
        from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

        engine = create_async_engine(_PG_URL, echo=False)
        session_maker = async_sessionmaker(engine, expire_on_commit=False)
        async with session_maker() as s:
            fetched = await latest_artifact_record(s, "nope", "0.0.1")
        await engine.dispose()
        assert fetched is None


class TestRestartSurvival:
    async def test_record_survives_process_restart(self):
        import uuid
        from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

        run_id = f"cos163run-{uuid.uuid4().hex[:12]}"
        await _seed_run(run_id)

        manifest = {"layers": [{"digest": DIGEST}]}
        record = _record(manifest=manifest, run_id=run_id)

        engine = create_async_engine(_PG_URL, echo=False)
        session_maker = async_sessionmaker(engine, expire_on_commit=False)
        async with session_maker() as s:
            await record_artifact_record(s, record)
        await engine.dispose()

        # Свежий процесс: read-through latest_artifact_record из PG
        # (durable, не in-memory) реконструирует ту же запись.
        import json
        import os
        import subprocess

        probe = (
            "import asyncio, json, os, sys\n"
            "sys.path.insert(0, os.environ['ORCH_ROOT'])\n"
            "from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker\n"
            "from orchestrator.cosmo.ledger.artifact_record import latest_artifact_record\n"
            "async def m():\n"
            "  e = create_async_engine(os.environ['COSMO_DATABASE_URL'])\n"
            "  sm = async_sessionmaker(e, expire_on_commit=False)\n"
            "  async with sm() as s:\n"
            "    r = await latest_artifact_record(s, 'cosmo-testapp', '0.1.0')\n"
            "  await e.dispose()\n"
            "  if r is None:\n"
            "    sys.stdout.write(json.dumps(None))\n"
            "  else:\n"
            "    sys.stdout.write(json.dumps([r.digest, r.canonical_ref(), "
            "bool(r.manifest)]))\n"
            "asyncio.run(m())\n"
        )
        env = dict(os.environ)
        env["ORCH_ROOT"] = str(_och)
        env["COSMO_DATABASE_URL"] = _PG_URL
        proc = subprocess.run(
            [sys.executable, "-c", probe], cwd=str(_och), env=env,
            capture_output=True, text=True, timeout=120,
        )
        assert proc.returncode == 0, f"probe failed: {proc.stderr}"
        out = json.loads(proc.stdout.strip().splitlines()[-1])
        assert out is not None
        assert out[0] == DIGEST
        assert out[1] == f"cosmo-testapp:0.1.0@{DIGEST}"
        assert out[2] is True


class TestIntegrity:
    async def test_tampered_record_hash_returns_none(self):
        import uuid
        from sqlalchemy import text
        from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

        run_id = f"cos163run-{uuid.uuid4().hex[:12]}"
        await _seed_run(run_id)

        engine = create_async_engine(_PG_URL, echo=False)
        session_maker = async_sessionmaker(engine, expire_on_commit=False)
        async with session_maker() as s:
            await record_artifact_record(s, _record(run_id=run_id))

        # Тампер: переписать record_hash на мусор (подмена payload без
        # переподписи) — чтение обязано отказать (None), не вернуть подделку.
        async with engine.begin() as conn:
            await conn.execute(text(
                "UPDATE evidence_ledger SET provenance_json = "
                "provenance_json || '{\"record_hash\": \"deadbeef\"}'::jsonb "
                "WHERE run_id = :r AND provenance_json->>'source' = :src"
            ), {"r": run_id, "src": ARTIFACT_RECORD_SOURCE})

        async with session_maker() as s:
            fetched = await latest_artifact_record(s, "cosmo-testapp", "0.1.0")
        await engine.dispose()
        assert fetched is None