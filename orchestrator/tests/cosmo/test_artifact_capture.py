# -*- coding: utf-8 -*-
"""COS-164: runtime-hook авто-digest — маркер docker_build → durable ArtifactRecord.

Покрытие:
  - domain: ``parse_docker_build_marker`` / ``find_docker_build_digest`` —
    канонический маркер COS-142, неканон (uppercase-hex / sha1 / latest)
    отклоняется;
  - ``docker_build_specs``: извлечение спецификаций docker_build из
    ``batch.bricks_refs`` (generic-шаги игнорируются);
  - ``capture_artifact_records``: durable write через ``record_artifact_record``
    (run_id-якорь, канонический ref), нет шага → no-op, шаг без маркера →
    ``MissingDockerBuildDigestError`` (не выдуманный digest).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_och = Path(__file__).resolve().parents[3]  # repo root
if str(_och) not in sys.path:
    sys.path.insert(0, str(_och))

pytestmark = pytest.mark.asyncio

from orchestrator.cosmo.domain.docker_build import (  # noqa: E402
    find_docker_build_digest,
    parse_docker_build_marker,
)
from orchestrator.cosmo.control_plane.artifact_capture import (  # noqa: E402
    MissingDockerBuildDigestError,
    capture_artifact_records,
    docker_build_specs,
)
from orchestrator.cosmo.ledger.artifact_record import latest_artifact_record  # noqa: E402

import _testpg  # noqa: E402

_PG_URL = _testpg.TEST_PG_URL

DOMAIN = "cos164-dom"
PLAN = "cos164-plan"

DIGEST = "sha256:" + "ab" * 32
VERSION = "0.1.0"
NAME = "cosmo-testapp"


# ── domain: marker parsing ───────────────────────────────────────────────────

class TestMarkerParsing:
    def test_parse_canonical_marker(self):
        assert parse_docker_build_marker(
            f"{NAME}:{VERSION}@{DIGEST}"
        ) == (NAME, VERSION, DIGEST)

    def test_parse_marker_with_echo_prefix(self):
        assert parse_docker_build_marker(
            f"echo {NAME}:{VERSION}@{DIGEST}"
        ) == (NAME, VERSION, DIGEST)

    def test_parse_uppercase_hex_rejected(self):
        assert parse_docker_build_marker(
            f"{NAME}:{VERSION}@sha256:{'AB' * 32}"
        ) is None

    def test_parse_sha1_rejected(self):
        assert parse_docker_build_marker(
            f"{NAME}:{VERSION}@sha1:{'ab' * 20}"
        ) is None

    def test_parse_latest_rejected(self):
        assert parse_docker_build_marker(f"{NAME}:latest@{DIGEST}") is None

    def test_parse_empty_rejected(self):
        assert parse_docker_build_marker("") is None
        assert parse_docker_build_marker("no marker here") is None

    def test_find_digest_across_steps(self):
        logs = {
            "build-image": ["set -eux", f"echo {NAME}:{VERSION}@{DIGEST}"],
            "scan": ["nothing to see"],
        }
        assert find_docker_build_digest(logs, NAME, VERSION) == DIGEST

    def test_find_digest_other_image_not_matched(self):
        logs = {"build": [f"other-app:{VERSION}@{DIGEST}"]}
        assert find_docker_build_digest(logs, NAME, VERSION) is None


class TestDockerBuildSpecs:
    def test_extracts_only_docker_build(self):
        bricks = [
            {"name": "build", "definition": {
                "type": "docker_build", "image_name": NAME, "version": VERSION,
                "registry": "registry-zr:5000",
            }},
            {"name": "sast", "definition": {"image": "sonar:latest",
                                            "commands": ["scan"]}},
        ]
        specs = docker_build_specs(bricks)
        assert len(specs) == 1
        assert specs[0].image_name == NAME
        assert specs[0].version == VERSION

    def test_empty_bricks(self):
        assert docker_build_specs([]) == []
        assert docker_build_specs(None) == []


# ── durable capture ──────────────────────────────────────────────────────────

async def _seed_run(run_id: str, batch_id: str | None = None) -> None:
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(_PG_URL, echo=False)
    async with engine.begin() as conn:
        await conn.execute(text(
            "INSERT INTO domains (id, label, forge_type, forge_url, "
            "forge_token_ref, rbac_config, quota_max_runs, "
            "quota_max_storage_gb, quota_max_cpu, created_at) "
            "VALUES (:d, 'cos164', 'gitea', 'http://gitea:3000', "
            "'t', '{}'::jsonb, 50, 100, 8, now()) "
            "ON CONFLICT (id) DO NOTHING"
        ), {"d": DOMAIN})
        await conn.execute(text(
            "INSERT INTO apps (id, domain_id, level) "
            "VALUES ('cos164-app', :d, 0) ON CONFLICT (id) DO NOTHING"
        ), {"d": DOMAIN})
        await conn.execute(text(
            "INSERT INTO pipeline_plans (id, app_id, level, scope_id, "
            "compiled_hash, compiled_at) VALUES (:p, 'cos164-app', "
            "'app', :p, 'h', now()) ON CONFLICT (id) DO NOTHING"
        ), {"p": PLAN})
        await conn.execute(text(
            "INSERT INTO runs (id, plan_id, trigger, domain_id, status, "
            "initiator_user_id, initiator_role, findings_refs, created_at) "
            "VALUES (:r, :p, 'manual', :d, 'succeeded', 'system', "
            "'system', '[]'::jsonb, now()) ON CONFLICT (id) DO NOTHING"
        ), {"r": run_id, "p": PLAN, "d": DOMAIN})
        if batch_id:
            await conn.execute(text(
                "INSERT INTO batches (id, plan_id, type, status, bricks_refs, "
                "artifacts, evidence_refs) VALUES (:b, :p, 'build', 'passed', "
                "'[]'::jsonb, '[]'::jsonb, '[]'::jsonb) "
                "ON CONFLICT (id) DO NOTHING"
            ), {"b": batch_id, "p": PLAN})
    await engine.dispose()


def _bricks() -> list[dict]:
    return [
        {"name": "build-image", "definition": {
            "type": "docker_build", "image_name": NAME, "version": VERSION,
            "registry": "registry-zr:5000",
        }},
    ]


class TestCaptureArtifactRecords:
    async def test_capture_writes_durable_record(self):
        import uuid
        from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

        run_id = f"cos164run-{uuid.uuid4().hex[:12]}"
        batch_id = f"cos164bat-{uuid.uuid4().hex[:12]}"
        await _seed_run(run_id, batch_id)

        logs = {"build-image": [f"echo {NAME}:{VERSION}@{DIGEST}"]}

        engine = create_async_engine(_PG_URL, echo=False)
        session_maker = async_sessionmaker(engine, expire_on_commit=False)
        async with session_maker() as s:
            entry_ids = await capture_artifact_records(
                s, run_id=run_id, batch_id=batch_id,
                bricks=_bricks(), logs=logs,
            )
        assert len(entry_ids) == 1

        async with session_maker() as s:
            fetched = await latest_artifact_record(s, NAME, VERSION)
        await engine.dispose()

        assert fetched is not None
        assert fetched.digest == DIGEST
        assert fetched.canonical_ref() == f"{NAME}:{VERSION}@{DIGEST}"
        assert fetched.run_id == run_id

    async def test_no_docker_build_is_noop(self):
        from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

        engine = create_async_engine(_PG_URL, echo=False)
        session_maker = async_sessionmaker(engine, expire_on_commit=False)
        async with session_maker() as s:
            entry_ids = await capture_artifact_records(
                s, run_id="any", batch_id="b",
                bricks=[{"name": "sast", "definition": {"image": "x"}}],
                logs={},
            )
        await engine.dispose()
        assert entry_ids == []

    async def test_missing_digest_raises_honest(self):
        from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

        engine = create_async_engine(_PG_URL, echo=False)
        session_maker = async_sessionmaker(engine, expire_on_commit=False)
        async with session_maker() as s:
            with pytest.raises(MissingDockerBuildDigestError):
                await capture_artifact_records(
                    s, run_id="any", batch_id="b",
                    bricks=_bricks(),
                    logs={"build-image": ["docker push failed", "exit 1"]},
                )
        await engine.dispose()
