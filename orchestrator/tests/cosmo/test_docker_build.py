# -*- coding: utf-8 -*-
"""COS-162: build first-class — docker_build шаг + canonical digest-tag.

Покрытие:
  - domain: canonical tag (COS-142 контракт), no-``latest``, строгий
    semver/slug/sha256, полная ``canonical_image_ref``;
  - ``render_docker_build_commands``: build под qualified-тегом → push по
    тегу → manifest-digest из вывода push → канонический маркер (no-``latest``);
  - ``generate_pipeline_yaml``: шаг ``docker_build`` разворачивается в
    ``docker build`` + ``docker push`` c volumes docker.sock (не kaniko);
  - durable registry_audit Evidence (``record_registry_push``): digest
    переживает рестарт процесса, тип ``decision`` + маркер
    ``cosmo-registry-audit``; negative — alg-неполный digest отклонён.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
import pytest_asyncio
import yaml

_och = Path(__file__).resolve().parents[1]
if str(_och) not in sys.path:
    sys.path.insert(0, str(_och))

pytestmark = pytest.mark.asyncio

from orchestrator.cosmo.domain.docker_build import (  # noqa: E402
    DockerBuildError,
    DockerBuildResult,
    DockerBuildSpec,
    canonical_image_ref,
    is_canonical_digest,
    render_docker_build_commands,
)
from orchestrator.cosmo.adapters.execution_woodpecker import (  # noqa: E402
    WoodpeckerAdapter,
)

import _testpg  # noqa: E402
from _durable_probe import get_in_fresh_process  # noqa: E402

_PG_URL = _testpg.TEST_PG_URL

DOMAIN = "cos162-dom"
PLAN = "cos162-plan"
RUN = "cos162run0001"

DIGEST = "sha256:" + "ab" * 32


# ── domain: canonical tag ────────────────────────────────────────────────────

class TestCanonicalTag:
    def test_canonical_image_ref_roundtrip(self):
        ref = canonical_image_ref(
            "cosmo-testapp", "0.1.0", DIGEST,
            registry="registry-zr:5000",
        )
        assert ref == f"registry-zr:5000/cosmoport/zr/cosmo-testapp:0.1.0@{DIGEST}"

    def test_latest_is_forbidden(self):
        with pytest.raises(Exception):
            canonical_image_ref(
                "cosmo-testapp", "latest", DIGEST, registry="r:5000",
            )

    def test_bad_semver_forbidden(self):
        with pytest.raises(Exception):
            canonical_image_ref(
                "cosmo-testapp", "not-semver", DIGEST, registry="r:5000",
            )

    def test_uppercase_name_forbidden(self):
        with pytest.raises(Exception):
            canonical_image_ref(
                "Cosmo-TestApp", "0.1.0", DIGEST, registry="r:5000",
            )

    def test_non_sha256_digest_forbidden(self):
        with pytest.raises(Exception):
            canonical_image_ref(
                "cosmo-testapp", "0.1.0", "sha1:" + "ab" * 20, registry="r:5000",
            )

    def test_is_canonical_digest(self):
        assert is_canonical_digest(DIGEST)
        assert not is_canonical_digest("sha256:" + "AB" * 32)  # uppercase
        assert not is_canonical_digest("latest")

    def test_docker_build_result_canonical_ref(self):
        r = DockerBuildResult(
            image_name="cosmo-testapp", version="0.1.0", digest=DIGEST,
            registry="registry-zr:5000",
        )
        assert r.canonical_ref() == f"cosmo-testapp:0.1.0@{DIGEST}"
        assert r.qualified_image() == "registry-zr:5000/cosmoport/zr/cosmo-testapp"


# ── docker build commands ───────────────────────────────────────────────────

class TestDockerBuildCommands:
    def test_commands_build_tagged_push_and_capture_manifest_digest(self):
        spec = DockerBuildSpec(
            image_name="cosmo-testapp", version="0.1.0", registry="registry-zr:5000",
            dockerfile="apps/cosmo-testapp/Dockerfile",
            context="apps/cosmo-testapp",
        )
        cmds = render_docker_build_commands(spec, ".digest")
        joined = "\n".join(cmds)
        # build идёт сразу под qualified-тегом (push по тегу, не по digest)
        assert ("docker build -f apps/cosmo-testapp/Dockerfile "
                "-t registry-zr:5000/cosmoport/zr/cosmo-testapp:0.1.0 "
                "apps/cosmo-testapp") in joined
        # push строго по тегу (no latest, no @digest reference)
        assert ("docker push registry-zr:5000/cosmoport/zr/cosmo-testapp:0.1.0"
                ) in joined
        # manifest-digest снимается с вывода push в digest_output-файл
        assert "grep -oE 'digest: sha256:[0-9a-f]{64}'" in joined
        assert "> .digest" in joined
        # канонический маркер для runtime-hook (COS-164)
        assert "echo cosmo-testapp:0.1.0@$DIGEST" in joined
        # битые не-маркеры: никакого --iidfile; push только по тегу (не @digest)
        assert "--iidfile" not in joined
        assert "docker push" in joined
        assert "push registry-zr:5000/cosmoport/zr/cosmo-testapp:0.1.0@$DIGEST" not in joined
        assert "latest" not in joined


# ── generate_pipeline_yaml: docker_build шаг ────────────────────────────────

class TestGeneratePipelineYamlDockerBuild:
    def test_docker_build_step_emitted(self):
        adapter = WoodpeckerAdapter()
        batch = {
            "bricks": [
                {
                    "name": "build-image",
                    "definition": {
                        "type": "docker_build",
                        "image_name": "cosmo-testapp",
                        "version": "0.1.0",
                        "registry": "registry-zr:5000",
                        "dockerfile": "apps/cosmo-testapp/Dockerfile",
                        "context": "apps/cosmo-testapp",
                    },
                },
            ],
        }
        out = adapter.generate_pipeline_yaml(batch)
        doc = yaml.safe_load(out)
        step = doc["steps"]["build-image"]
        assert step["image"] == "docker:24-cli"
        assert "/var/run/docker.sock:/var/run/docker.sock" in step["volumes"]
        joined = "\n".join(step["commands"])
        assert "docker build" in joined
        assert "docker push" in joined

    def test_generic_steps_unchanged(self):
        adapter = WoodpeckerAdapter()
        batch = {
            "bricks": [
                {"name": "sast", "definition": {"image": "sonar:latest",
                                                "commands": ["scan"]}},
            ],
        }
        out = adapter.generate_pipeline_yaml(batch)
        doc = yaml.safe_load(out)
        assert doc["steps"]["sast"]["image"] == "sonar:latest"
        assert doc["steps"]["sast"]["commands"] == ["scan"]

    def test_invalid_docker_build_spec_raises(self):
        adapter = WoodpeckerAdapter()
        batch = {
            "bricks": [
                {"name": "b", "definition": {
                    "type": "docker_build",
                    "image_name": "X-Bad",      # uppercase slug
                    "version": "0.1.0",
                    "registry": "r:5000",
                }},
            ],
        }
        with pytest.raises(Exception):
            adapter.generate_pipeline_yaml(batch)


# ── durable registry_audit Evidence ─────────────────────────────────────────

async def _seed_run(run_id: str = RUN) -> None:
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(_PG_URL, echo=False)
    async with engine.begin() as conn:
        await conn.execute(text(
            "INSERT INTO domains (id, label, forge_type, forge_url, "
            "forge_token_ref, rbac_config, quota_max_runs, "
            "quota_max_storage_gb, quota_max_cpu, created_at) "
            "VALUES (:d, 'cos162', 'gitea', 'http://gitea:3000', "
            "'t', '{}'::jsonb, 50, 100, 8, now()) "
            "ON CONFLICT (id) DO NOTHING"
        ), {"d": DOMAIN})
        await conn.execute(text(
            "INSERT INTO apps (id, domain_id, level) "
            "VALUES ('cos162-app', :d, 0) ON CONFLICT (id) DO NOTHING"
        ), {"d": DOMAIN})
        await conn.execute(text(
            "INSERT INTO pipeline_plans (id, app_id, level, scope_id, "
            "compiled_hash, compiled_at) VALUES (:p, 'cos162-app', "
            "'app', :p, 'h', now()) ON CONFLICT (id) DO NOTHING"
        ), {"p": PLAN})
        await conn.execute(text(
            "INSERT INTO runs (id, plan_id, trigger, domain_id, status, "
            "initiator_user_id, initiator_role, findings_refs, created_at) "
            "VALUES (:r, :p, 'manual', :d, 'succeeded', 'system', "
            "'system', '[]'::jsonb, now()) ON CONFLICT (id) DO NOTHING"
        ), {"r": run_id, "p": PLAN, "d": DOMAIN})
    await engine.dispose()


async def _ledger_rows(run_id: str) -> list[dict]:
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(_PG_URL, echo=False)
    async with engine.begin() as conn:
        res = await conn.execute(text(
            "SELECT type, content_ref, content_hash, provenance_json, run_id "
            "FROM evidence_ledger WHERE run_id = :r AND "
            "provenance_json->>'source' = 'cosmo-registry-audit' "
            "ORDER BY created_at ASC, id ASC"
        ), {"r": run_id})
        rows = [dict(r._mapping) for r in res.fetchall()]
    await engine.dispose()
    return rows


class TestDurableRegistryAudit:
    def _result(self) -> DockerBuildResult:
        return DockerBuildResult(
            image_name="cosmo-testapp", version="0.1.0", digest=DIGEST,
            registry="registry-zr:5000",
        )

    async def test_record_registry_push_is_durable(self):
        from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

        import uuid
        run_id = f"cos162run-{uuid.uuid4().hex[:12]}"
        await _seed_run(run_id)
        from orchestrator.cosmo.ledger.build_registry import record_registry_push

        engine = create_async_engine(_PG_URL, echo=False)
        session_maker = async_sessionmaker(engine, expire_on_commit=False)
        async with session_maker() as s:
            entry_id = await record_registry_push(
                s, self._result(), run_id=run_id,
            )
        await engine.dispose()
        assert entry_id

        rows = await _ledger_rows(run_id)
        assert len(rows) == 1
        row = rows[0]
        assert row["type"] == "decision"
        prov = row["provenance_json"]
        assert prov["audit_type"] == "registry_push"
        assert prov["digest"] == DIGEST
        assert prov["canonical_ref"] == f"cosmo-testapp:0.1.0@{DIGEST}"
        assert len(row["content_hash"]) == 64

    async def test_digest_survives_process_restart(self):
        from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

        import uuid
        run_id = f"cos162run-{uuid.uuid4().hex[:12]}"
        await _seed_run(run_id)
        from orchestrator.cosmo.ledger.build_registry import record_registry_push

        engine = create_async_engine(_PG_URL, echo=False)
        session_maker = async_sessionmaker(engine, expire_on_commit=False)
        async with session_maker() as s:
            await record_registry_push(s, self._result(), run_id=run_id)
        await engine.dispose()

        # Свежий процесс: читаем ту же evidence_ledger строку (durable).
        import subprocess, json, os

        probe = (
            "import asyncio, json, os, sys\n"
            "sys.path.insert(0, os.environ['ORCH_ROOT'])\n"
            "from sqlalchemy import text\n"
            "from sqlalchemy.ext.asyncio import create_async_engine\n"
            "async def m():\n"
            "  e = create_async_engine(os.environ['COSMO_DATABASE_URL'])\n"
            "  async with e.begin() as c:\n"
            "    r = await c.execute(text(\"SELECT provenance_json->>'digest' "
            "AS digest, provenance_json->>'canonical_ref' AS ref FROM "
            "evidence_ledger WHERE run_id = :r AND provenance_json->>'source' "
            "= 'cosmo-registry-audit' ORDER BY created_at DESC, id DESC "
            "LIMIT 1\"), {'r': os.environ['RUN']})\n"
            "    row = r.first()\n"
            "    sys.stdout.write(json.dumps([] if row is None else "
            "[row._mapping['digest'], row._mapping['ref']]))\n"
            "  await e.dispose()\n"
            "asyncio.run(m())\n"
        )
        env = dict(os.environ)
        env["ORCH_ROOT"] = str(_och)
        env["COSMO_DATABASE_URL"] = _PG_URL
        env["RUN"] = run_id
        proc = subprocess.run(
            [sys.executable, "-c", probe], cwd=str(_och), env=env,
            capture_output=True, text=True, timeout=120,
        )
        assert proc.returncode == 0, f"probe failed: {proc.stderr}"
        digest, ref = json.loads(proc.stdout.strip().splitlines()[-1])
        assert digest == DIGEST
        assert ref == f"cosmo-testapp:0.1.0@{DIGEST}"