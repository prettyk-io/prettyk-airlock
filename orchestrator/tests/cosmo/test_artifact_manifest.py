# -*- coding: utf-8 -*-
"""COS-142: PK-C-003.4 — canonical tags + bundle manifest digest-pin.

Покрытие:
  - DTO canonical tag: строгий slug имени, semver-версия, отказ при ``latest``,
    канонический ``sha256:<64 lowercase hex>`` digest, ``canonical_ref()``;
  - DTO манифеста: непустой набор артефактов, закрытый набор профилей,
    нормализация ``expected_digest_pin``, ``extra=forbid``;
  - детерминированный ``digest_pin``: независим от порядка артефактов,
    чувствителен к профилю/версии/digest;
  - POST /api/v1/artifacts/manifest/verify:
      * валидный манифест → ``valid=true`` + pin + счётчик;
      * расхождение ``expected_digest_pin`` → ``valid=false`` + errors (не 5xx),
        запись в ledger НЕ создаётся;
      * ``latest`` / невалидный digest → 422 (отказ на границе контракта);
      * ``run_id`` → крипто-запись в ledger (``type='decision'``, маркер
        ``manifest_type='BUNDLE_MANIFEST'``, ``content_hash=manifest_hash``);
      * неизвестный ``run_id`` → ``valid=false`` без ledger-записи;
      * без аутентификации → 401;
  - GET /api/v1/artifacts/manifest/{bundle_id}: чтение подтверждённого
    манифеста, 404 для неподтверждённого.

Запуск:  pytest .../test_artifact_manifest.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import AsyncClient
from pydantic import ValidationError

_orch = Path(__file__).resolve().parents[1]
if str(_orch) not in sys.path:
    sys.path.insert(0, str(_orch))

pytestmark = pytest.mark.asyncio

from orchestrator.cosmo.domain.artifact_manifest import (  # noqa: E402
    ArtifactBundleManifest,
    CanonicalArtifactTag,
    manifest_content_hash,
)
from orchestrator.cosmo.ledger.manifest_verifier import (  # noqa: E402
    compute_digest_pin,
)

import _testpg  # noqa: E402
from _durable_probe import get_in_fresh_process  # noqa: E402

DOMAIN = "cos142-dom"
PLAN = "cos142-plan"
RUN = "cos142run0001"

_DIG_A = "sha256:" + "a" * 64
_DIG_B = "sha256:" + "b" * 64

_PG_URL = _testpg.TEST_PG_URL

BUNDLE = "bundle-cos142"


def _tag(name: str = "api", version: str = "1.2.3",
         digest: str = _DIG_A) -> dict:
    return {"name": name, "version": version, "digest": digest}


def _manifest(**over: object) -> dict:
    body = {
        "bundle_id": BUNDLE,
        "release_version": "1.2.3",
        "profile": "ordinary@1",
        "artifacts": [_tag()],
        "created_at": "2026-09-19T10:00:00Z",
    }
    body.update(over)
    return body


def _refs(artifacts: list[dict]) -> list[str]:
    return sorted(f"{a['name']}:{a['version']}@{a['digest']}" for a in artifacts)


async def _ledger_rows(run_id: str) -> list[dict]:
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(_PG_URL, echo=False)
    try:
        async with engine.connect() as conn:
            res = await conn.execute(
                text(
                    "SELECT id, type, content_hash, content_ref, provenance_json "
                    "FROM evidence_ledger WHERE run_id = :rid "
                    "ORDER BY created_at ASC"
                ),
                {"rid": run_id},
            )
            return [dict(r) for r in res.mappings().all()]
    finally:
        await engine.dispose()


# ── DTO unit: canonical tag ──────────────────────────────────────────────

class TestCanonicalArtifactTag:
    def test_canonical_ref_format(self):
        tag = CanonicalArtifactTag(**_tag())
        assert tag.canonical_ref() == f"api:1.2.3@{_DIG_A}"

    @pytest.mark.parametrize(
        "version",
        ["latest", "1.2.3-latest", "LATEST", "1.2.3-latest.1", "latest-1.0.0"],
    )
    def test_floating_latest_rejected(self, version: str):
        with pytest.raises(ValidationError):
            CanonicalArtifactTag(**_tag(version=version))

    @pytest.mark.parametrize("version", ["1.2", "1", "v1.2.3", "1.2.3.4", "", "x.y.z"])
    def test_non_semver_version_rejected(self, version: str):
        with pytest.raises(ValidationError):
            CanonicalArtifactTag(**_tag(version=version))

    @pytest.mark.parametrize("version", ["1.2.3", "0.0.1", "1.2.3-rc.1", "1.2.3+build.7"])
    def test_pinned_semver_accepted(self, version: str):
        assert CanonicalArtifactTag(**_tag(version=version)).version == version

    @pytest.mark.parametrize(
        "digest",
        [
            "a" * 64,                      # без sha256:-префикса
            "sha256:" + "A" * 64,          # uppercase hex
            "sha256:" + "a" * 63,          # короткий
            "sha256:" + "a" * 65,          # длинный
            "md5:" + "a" * 32,             # чужой алгоритм
            "sha256:" + "z" * 64,          # не hex
            "",
        ],
    )
    def test_non_canonical_digest_rejected(self, digest: str):
        with pytest.raises(ValidationError):
            CanonicalArtifactTag(**_tag(digest=digest))

    @pytest.mark.parametrize("name", ["API", "owner/api", "../etc", "a b", "", ".api", "-api"])
    def test_non_slug_name_rejected(self, name: str):
        with pytest.raises(ValidationError):
            CanonicalArtifactTag(**_tag(name=name))

    @pytest.mark.parametrize("name", ["api", "api-gateway", "api.v2", "web_ui"])
    def test_slug_name_accepted(self, name: str):
        assert CanonicalArtifactTag(**_tag(name=name)).name == name

    def test_extra_field_rejected(self):
        with pytest.raises(ValidationError):
            CanonicalArtifactTag(
                name="api", version="1.2.3", digest=_DIG_A, tag="extra",
            )


# ── DTO unit: manifest ───────────────────────────────────────────────────

class TestArtifactBundleManifestDto:
    def test_valid_manifest(self):
        man = ArtifactBundleManifest.model_validate(_manifest())
        assert man.bundle_id == BUNDLE
        assert man.profile == "ordinary@1"
        assert man.artifacts[0].canonical_ref() == f"api:1.2.3@{_DIG_A}"
        assert man.expected_digest_pin is None
        assert man.run_id is None

    @pytest.mark.parametrize("profile", ["ordinary@1", "hardened@1", "airgap@1"])
    def test_closed_profile_set_accepted(self, profile: str):
        man = ArtifactBundleManifest.model_validate(_manifest(profile=profile))
        assert man.profile == profile

    @pytest.mark.parametrize("profile", ["dev@1", "ordinary", "ordinary@2", "", "prod"])
    def test_unknown_profile_rejected(self, profile: str):
        with pytest.raises(ValidationError):
            ArtifactBundleManifest.model_validate(_manifest(profile=profile))

    def test_empty_artifacts_rejected(self):
        with pytest.raises(ValidationError):
            ArtifactBundleManifest.model_validate(_manifest(artifacts=[]))

    def test_release_version_latest_rejected(self):
        with pytest.raises(ValidationError):
            ArtifactBundleManifest.model_validate(
                _manifest(release_version="latest")
            )

    def test_unsafe_bundle_id_rejected(self):
        with pytest.raises(ValidationError):
            ArtifactBundleManifest.model_validate(
                _manifest(bundle_id="../escape")
            )

    def test_expected_pin_normalized(self):
        man = ArtifactBundleManifest.model_validate(
            _manifest(expected_digest_pin="a" * 64)
        )
        assert man.expected_digest_pin == _DIG_A

    def test_malformed_expected_pin_rejected(self):
        with pytest.raises(ValidationError):
            ArtifactBundleManifest.model_validate(
                _manifest(expected_digest_pin="sha256:nothex")
            )

    def test_extra_field_rejected(self):
        with pytest.raises(ValidationError):
            ArtifactBundleManifest.model_validate(_manifest(signature="x"))

    def test_canonical_refs_sorted(self):
        man = ArtifactBundleManifest.model_validate(_manifest(artifacts=[
            _tag(name="web"), _tag(name="api"), _tag(name="worker"),
        ]))
        refs = man.canonical_refs()
        assert refs == sorted(refs)
        assert refs[0].startswith("api:")

    def test_content_hash_deterministic(self):
        a = manifest_content_hash(
            ArtifactBundleManifest.model_validate(_manifest())
        )
        b = manifest_content_hash(
            ArtifactBundleManifest.model_validate(_manifest())
        )
        c = manifest_content_hash(
            ArtifactBundleManifest.model_validate(_manifest(artifacts=[
                _tag(digest=_DIG_B),
            ]))
        )
        assert a == b
        assert a != c
        assert len(a) == 64


# ── digest_pin ───────────────────────────────────────────────────────────

class TestDigestPin:
    def test_format(self):
        pin = compute_digest_pin("ordinary@1", _refs([_tag()]))
        assert pin.startswith("sha256:")
        assert len(pin) == 71

    def test_order_independent(self):
        refs = _refs([_tag(name="api"), _tag(name="web"), _tag(name="worker")])
        assert compute_digest_pin("ordinary@1", refs) == compute_digest_pin(
            "ordinary@1", list(reversed(refs)),
        )

    def test_sensitive_to_profile(self):
        refs = _refs([_tag()])
        assert compute_digest_pin("ordinary@1", refs) != compute_digest_pin(
            "airgap@1", refs,
        )

    def test_sensitive_to_version_and_digest(self):
        base = _refs([_tag()])
        assert compute_digest_pin("ordinary@1", base) != compute_digest_pin(
            "ordinary@1", _refs([_tag(version="1.2.4")]),
        )
        assert compute_digest_pin("ordinary@1", base) != compute_digest_pin(
            "ordinary@1", _refs([_tag(digest=_DIG_B)]),
        )


# ── Route tests ──────────────────────────────────────────────────────────

class TestManifestVerifyRoute:
    """Route-тесты на реальном PG через pg_client (admin principal)."""

    @pytest_asyncio.fixture(autouse=True)
    async def _seed(self, pg_client: AsyncClient):
        from sqlalchemy import text
        from sqlalchemy.ext.asyncio import create_async_engine

        engine = create_async_engine(_PG_URL, echo=False)
        async with engine.begin() as conn:
            await conn.execute(text(
                "INSERT INTO domains (id, label, forge_type, forge_url, "
                "forge_token_ref, rbac_config, quota_max_runs, "
                "quota_max_storage_gb, quota_max_cpu, created_at) "
                "VALUES (:d, 'cos142', 'gitea', 'http://gitea:3000', "
                "'t', '{}'::jsonb, 50, 100, 8, now()) "
                "ON CONFLICT (id) DO NOTHING"
            ), {"d": DOMAIN})
            await conn.execute(text(
                "INSERT INTO apps (id, domain_id, level) "
                "VALUES ('cos142-app', :d, 0) ON CONFLICT (id) DO NOTHING"
            ), {"d": DOMAIN})
            await conn.execute(text(
                "INSERT INTO pipeline_plans (id, app_id, level, scope_id, "
                "compiled_hash, compiled_at) VALUES (:p, 'cos142-app', "
                "'app', :p, 'h', now()) ON CONFLICT (id) DO NOTHING"
            ), {"p": PLAN})
            await conn.execute(text(
                "INSERT INTO runs (id, plan_id, trigger, domain_id, status, "
                "initiator_user_id, initiator_role, findings_refs, created_at) "
                "VALUES (:r, :p, 'manual', :d, 'succeeded', 'system', "
                "'system', '[]'::jsonb, now()) ON CONFLICT (id) DO NOTHING"
            ), {"r": RUN, "p": PLAN, "d": DOMAIN})
        await engine.dispose()

    async def test_verify_valid_manifest_without_anchor(self, pg_client: AsyncClient):
        res = await pg_client.post(
            "/api/v1/artifacts/manifest/verify", json=_manifest(),
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["valid"] is True
        assert body["bundle_id"] == BUNDLE
        assert body["artifacts_count"] == 1
        assert body["errors"] == []
        assert body["ledger_entry_id"] is None
        assert body["digest_pin"] == compute_digest_pin(
            "ordinary@1", _refs([_tag()]),
        )
        # без run_id ledger не трогаем — нечем якорить
        assert await _ledger_rows(RUN) == []

    async def test_verify_with_correct_expected_pin(self, pg_client: AsyncClient):
        pin = compute_digest_pin("ordinary@1", _refs([_tag()]))
        res = await pg_client.post(
            "/api/v1/artifacts/manifest/verify",
            json=_manifest(expected_digest_pin=pin),
        )
        assert res.status_code == 200, res.text
        assert res.json()["valid"] is True
        assert res.json()["digest_pin"] == pin

    async def test_pin_mismatch_is_verdict_not_error(self, pg_client: AsyncClient):
        res = await pg_client.post(
            "/api/v1/artifacts/manifest/verify",
            json=_manifest(expected_digest_pin=_DIG_B),
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["valid"] is False
        assert body["ledger_entry_id"] is None
        assert any("digest_pin mismatch" in e for e in body["errors"])
        assert await _ledger_rows(RUN) == []

    async def test_latest_tag_rejected_422(self, pg_client: AsyncClient):
        res = await pg_client.post(
            "/api/v1/artifacts/manifest/verify",
            json=_manifest(artifacts=[_tag(version="latest")]),
        )
        assert res.status_code == 422, res.text

    async def test_bad_digest_rejected_422(self, pg_client: AsyncClient):
        res = await pg_client.post(
            "/api/v1/artifacts/manifest/verify",
            json=_manifest(artifacts=[_tag(digest="sha256:" + "A" * 64)]),
        )
        assert res.status_code == 422, res.text

    async def test_empty_artifacts_rejected_422(self, pg_client: AsyncClient):
        res = await pg_client.post(
            "/api/v1/artifacts/manifest/verify",
            json=_manifest(artifacts=[]),
        )
        assert res.status_code == 422, res.text

    async def test_verify_anchors_ledger(self, pg_client: AsyncClient):
        artifacts = [_tag(name="api"), _tag(name="web", version="2.0.0")]
        payload = _manifest(artifacts=artifacts, run_id=RUN)
        res = await pg_client.post(
            "/api/v1/artifacts/manifest/verify", json=payload,
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["valid"] is True
        assert body["ledger_entry_id"]
        assert body["artifacts_count"] == 2

        rows = await _ledger_rows(RUN)
        assert len(rows) == 1
        row = rows[0]
        assert row["id"] == body["ledger_entry_id"]
        assert row["type"] == "decision"
        assert row["content_hash"] == manifest_content_hash(
            ArtifactBundleManifest.model_validate(payload)
        )
        prov = row["provenance_json"]
        assert prov["source"] == "cosmo-manifest-verifier"
        assert prov["manifest_type"] == "BUNDLE_MANIFEST"
        assert prov["contract"] == "PK-C-003.4"
        assert prov["bundle_id"] == BUNDLE
        assert prov["digest_pin"] == body["digest_pin"]
        assert prov["canonical_refs"] == _refs(artifacts)
        assert prov["profile"] == "ordinary@1"
        assert len(prov["provenance_hash"]) == 64
        assert RUN in row["content_ref"] or BUNDLE in row["content_ref"]

    async def test_unknown_run_is_not_anchored(self, pg_client: AsyncClient):
        res = await pg_client.post(
            "/api/v1/artifacts/manifest/verify",
            json=_manifest(run_id="cos142run-ghost"),
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["valid"] is False
        assert body["ledger_entry_id"] is None
        assert any("not found to anchor" in e for e in body["errors"])
        assert await _ledger_rows(RUN) == []

    async def test_get_reads_back_verified_manifest(self, pg_client: AsyncClient):
        posted = await pg_client.post(
            "/api/v1/artifacts/manifest/verify",
            json=_manifest(run_id=RUN),
        )
        assert posted.status_code == 200, posted.text
        assert posted.json()["ledger_entry_id"]
        res = await pg_client.get(f"/api/v1/artifacts/manifest/{BUNDLE}")
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["bundle_id"] == BUNDLE
        assert body["profile"] == "ordinary@1"
        assert body["artifacts"][0]["digest"] == _DIG_A
        assert body["run_id"] == RUN

    async def test_get_reads_latest_anchor(self, pg_client: AsyncClient):
        """COS-152: latest wins — читается последняя якорённая запись."""
        await pg_client.post(
            "/api/v1/artifacts/manifest/verify",
            json=_manifest(artifacts=[_tag(digest=_DIG_A)], run_id=RUN),
        )
        second = _manifest(artifacts=[_tag(digest=_DIG_B)], run_id=RUN)
        await pg_client.post("/api/v1/artifacts/manifest/verify", json=second)
        res = await pg_client.get(f"/api/v1/artifacts/manifest/{BUNDLE}")
        assert res.status_code == 200, res.text
        assert res.json()["artifacts"][0]["digest"] == _DIG_B

    async def test_get_survives_process_restart(self, pg_client: AsyncClient):
        """COS-152: durable read — свежий процесс видит якорь из ledger."""
        posted = await pg_client.post(
            "/api/v1/artifacts/manifest/verify",
            json=_manifest(run_id=RUN),
        )
        assert posted.status_code == 200, posted.text
        assert posted.json()["ledger_entry_id"]

        status, body = get_in_fresh_process(
            f"/api/v1/artifacts/manifest/{BUNDLE}", _PG_URL,
        )
        assert status == 200, body
        assert body["bundle_id"] == BUNDLE
        assert body["profile"] == "ordinary@1"
        assert body["artifacts"][0]["digest"] == _DIG_A
        assert body["run_id"] == RUN

    async def test_non_anchored_manifest_is_not_durable_404(
        self, pg_client: AsyncClient,
    ):
        """COS-152 честный edge: без run_id якоря нет → GET 404, не фейк."""
        await pg_client.post(
            "/api/v1/artifacts/manifest/verify", json=_manifest(),
        )
        res = await pg_client.get(f"/api/v1/artifacts/manifest/{BUNDLE}")
        assert res.status_code == 404, res.text

    async def test_get_unknown_manifest_404(self, pg_client: AsyncClient):
        res = await pg_client.get("/api/v1/artifacts/manifest/bundle-ghost")
        assert res.status_code == 404, res.text

    async def test_mismatch_manifest_is_not_readable(self, pg_client: AsyncClient):
        await pg_client.post(
            "/api/v1/artifacts/manifest/verify",
            json=_manifest(expected_digest_pin=_DIG_B),
        )
        res = await pg_client.get(f"/api/v1/artifacts/manifest/{BUNDLE}")
        assert res.status_code == 404, res.text

    async def test_verify_requires_principal(self, pg_client: AsyncClient):
        from orchestrator.cosmo.api.deps import get_current_principal
        from orchestrator.cosmo.api.main import app

        app.dependency_overrides.pop(get_current_principal, None)
        res = await pg_client.post(
            "/api/v1/artifacts/manifest/verify", json=_manifest(),
        )
        assert res.status_code == 401, res.text

    async def test_read_requires_principal(self, pg_client: AsyncClient):
        from orchestrator.cosmo.api.deps import get_current_principal
        from orchestrator.cosmo.api.main import app

        app.dependency_overrides.pop(get_current_principal, None)
        res = await pg_client.get(f"/api/v1/artifacts/manifest/{BUNDLE}")
        assert res.status_code == 401, res.text
