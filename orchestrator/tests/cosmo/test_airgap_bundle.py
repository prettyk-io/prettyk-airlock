# -*- coding: utf-8 -*-
"""COS-148: airgap bundle integrity — офлайн-манифест и верификация.

Покрытие:
  - DTO: безопасный ``filename`` (traversal/absolute/backslash/NUL/пустые
    сегменты — reject), sha256-формат, неотрицательный размер, ``extra=forbid``;
  - чистая логика (без БД и сети): ``compute_package_digest_pin``
    порядок-независим, ``compare_archive`` выявляет missing/corrupted/
    unregistered;
  - POST /api/v1/artifacts/airgap/verify:
      * корректный пакет → ``verified=true`` + крипто-запись в ledger
        (``airgap_type='AIRGAP_VERIFIED'``);
      * модифицированный файл → ``corrupted_files``;
      * отсутствующий файл → ``missing_files``;
      * лишний/недоверенный файл → ``unregistered_files``;
      * расхождение ``package_digest_pin`` → ``errors`` + ``verified=false``;
      * нет локального релиза → вердикт считается, ledger-запись не создаётся
        (честная граница офлайн-контура);
      * без аутентификации → 401;
  - GET /api/v1/artifacts/airgap/{package_id}: статус проверки, 404 иначе.

Запуск:  pytest .../test_airgap_bundle.py -q
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

from orchestrator.cosmo.domain.airgap_bundle import (  # noqa: E402
    AirgapFileChecksum,
    AirgapPackageManifest,
    AirgapVerifyRequest,
)
from orchestrator.cosmo.ledger.airgap_verifier import (  # noqa: E402
    compare_archive,
    compute_package_digest_pin,
)

import _testpg  # noqa: E402
from _durable_probe import get_in_fresh_process  # noqa: E402

DOMAIN = "cos148-dom"
PLAN = "cos148-plan"
RUN = "cos148run0001"
REL = "cos148rel0001"

PKG = "airgap-pkg-cos148"
H_A = "a" * 64
H_B = "b" * 64

_PG_URL = _testpg.TEST_PG_URL


def _file(filename: str = "images/api.tar", sha256: str = H_A,
          size_bytes: int = 1024) -> dict:
    return {"filename": filename, "sha256": sha256, "size_bytes": size_bytes}


def _manifest(files: list[dict] | None = None, pin: str | None = None,
              package_id: str = PKG, release_id: str = REL) -> dict:
    files = [_file()] if files is None else files
    return {
        "package_id": package_id,
        "release_id": release_id,
        "created_at": "2026-09-19T12:00:00Z",
        "files": files,
        "package_digest_pin": pin or compute_package_digest_pin(
            [AirgapFileChecksum(**f) for f in files]
        ),
    }


def _request(files: list[dict] | None = None, archive: list[dict] | None = None,
             pin: str | None = None, package_id: str = PKG,
             release_id: str = REL) -> dict:
    files = [_file()] if files is None else files
    return {
        "manifest": _manifest(
            files, pin, package_id=package_id, release_id=release_id,
        ),
        "archive_files": [_file()] if archive is None else archive,
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


# ── DTO unit ─────────────────────────────────────────────────────────────

class TestAirgapDto:
    def test_valid_checksum(self):
        checksum = AirgapFileChecksum(**_file())
        assert checksum.filename == "images/api.tar"
        assert checksum.normalized_sha256() == H_A
        assert checksum.size_bytes == 1024

    def test_prefixed_sha256_accepted_and_normalized(self):
        checksum = AirgapFileChecksum(**_file(sha256=f"sha256:{H_A.upper()}"))
        assert checksum.normalized_sha256() == H_A

    @pytest.mark.parametrize(
        "filename",
        [
            "../etc/passwd",
            "images/../../etc/passwd",
            "/etc/passwd",
            "images\\api.tar",
            "images//api.tar",
            "./api.tar",
            "C:/windows/system32",
            "api.tar\x00",
            "",
            "   ",
        ],
    )
    def test_unsafe_filename_rejected(self, filename: str):
        with pytest.raises(ValidationError):
            AirgapFileChecksum(**_file(filename=filename))

    @pytest.mark.parametrize(
        "sha256",
        ["deadbeef", "sha256:" + "a" * 63, "md5:" + "a" * 32, "z" * 64, ""],
    )
    def test_bad_sha256_rejected(self, sha256: str):
        with pytest.raises(ValidationError):
            AirgapFileChecksum(**_file(sha256=sha256))

    def test_negative_size_rejected(self):
        with pytest.raises(ValidationError):
            AirgapFileChecksum(**_file(size_bytes=-1))

    def test_zero_size_accepted(self):
        assert AirgapFileChecksum(**_file(size_bytes=0)).size_bytes == 0

    def test_extra_field_rejected(self):
        with pytest.raises(ValidationError):
            AirgapFileChecksum(**_file(), mtime="now")

    def test_bad_pin_rejected(self):
        with pytest.raises(ValidationError):
            AirgapPackageManifest(
                package_id=PKG, release_id=REL, created_at="t",
                files=[], package_digest_pin="nope",
            )

    def test_unsafe_package_id_rejected(self):
        with pytest.raises(ValidationError):
            AirgapPackageManifest(
                package_id="../escape", release_id=REL, created_at="t",
                files=[], package_digest_pin=H_A,
            )

    def test_request_roundtrip(self):
        req = AirgapVerifyRequest.model_validate(_request())
        assert req.manifest.package_id == PKG
        assert len(req.archive_files) == 1


# ── чистая логика (без БД/сети) ──────────────────────────────────────────

class TestAirgapPureLogic:
    def test_pin_order_independent(self):
        files = [
            AirgapFileChecksum(**_file("a.tar", H_A, 10)),
            AirgapFileChecksum(**_file("b.tar", H_B, 20)),
            AirgapFileChecksum(**_file("c.tar", H_A, 30)),
        ]
        assert compute_package_digest_pin(files) == compute_package_digest_pin(
            list(reversed(files)),
        )

    def test_pin_sensitive_to_content_and_size(self):
        base = [AirgapFileChecksum(**_file("a.tar", H_A, 10))]
        assert compute_package_digest_pin(base) != compute_package_digest_pin(
            [AirgapFileChecksum(**_file("a.tar", H_B, 10))],
        )
        assert compute_package_digest_pin(base) != compute_package_digest_pin(
            [AirgapFileChecksum(**_file("a.tar", H_A, 11))],
        )

    def test_pin_format(self):
        pin = compute_package_digest_pin([])
        assert pin.startswith("sha256:")
        assert len(pin) == 71

    def test_compare_detects_all_three_classes(self):
        manifest = [
            AirgapFileChecksum(**_file("keep.tar", H_A, 10)),
            AirgapFileChecksum(**_file("gone.tar", H_A, 10)),
            AirgapFileChecksum(**_file("tampered.tar", H_A, 10)),
        ]
        archive = [
            AirgapFileChecksum(**_file("keep.tar", H_A, 10)),
            AirgapFileChecksum(**_file("tampered.tar", H_B, 10)),
            AirgapFileChecksum(**_file("extra.tar", H_A, 10)),
        ]
        missing, corrupted, unregistered, errors = compare_archive(
            manifest, archive,
        )
        assert missing == ["gone.tar"]
        assert corrupted == ["tampered.tar"]
        assert unregistered == ["extra.tar"]
        assert errors == []

    def test_compare_flags_size_only_change_as_corrupted(self):
        manifest = [AirgapFileChecksum(**_file("a.tar", H_A, 10))]
        archive = [AirgapFileChecksum(**_file("a.tar", H_A, 11))]
        missing, corrupted, _, errors = compare_archive(manifest, archive)
        assert (missing, corrupted, errors) == ([], ["a.tar"], [])

    def test_compare_flags_duplicate_filenames(self):
        manifest = [
            AirgapFileChecksum(**_file("dup.tar", H_A, 10)),
            AirgapFileChecksum(**_file("dup.tar", H_B, 20)),
        ]
        _, _, _, errors = compare_archive(manifest, [])
        assert any("duplicate filenames in manifest" in e for e in errors)

    def test_compare_identical_sets_is_clean(self):
        files = [AirgapFileChecksum(**_file("a.tar", H_A, 10))]
        assert compare_archive(files, files) == ([], [], [], [])


# ── Route tests ──────────────────────────────────────────────────────────

class TestAirgapVerifyRoute:
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
                "VALUES (:d, 'cos148', 'gitea', 'http://gitea:3000', "
                "'t', '{}'::jsonb, 50, 100, 8, now()) "
                "ON CONFLICT (id) DO NOTHING"
            ), {"d": DOMAIN})
            await conn.execute(text(
                "INSERT INTO apps (id, domain_id, level) "
                "VALUES ('cos148-app', :d, 0) ON CONFLICT (id) DO NOTHING"
            ), {"d": DOMAIN})
            await conn.execute(text(
                "INSERT INTO pipeline_plans (id, app_id, level, scope_id, "
                "compiled_hash, compiled_at) VALUES (:p, 'cos148-app', "
                "'app', :p, 'h', now()) ON CONFLICT (id) DO NOTHING"
            ), {"p": PLAN})
            await conn.execute(text(
                "INSERT INTO runs (id, plan_id, trigger, domain_id, status, "
                "initiator_user_id, initiator_role, findings_refs, created_at) "
                "VALUES (:r, :p, 'manual', :d, 'succeeded', 'system', "
                "'system', '[]'::jsonb, now()) ON CONFLICT (id) DO NOTHING"
            ), {"r": RUN, "p": PLAN, "d": DOMAIN})
            await conn.execute(text(
                "INSERT INTO releases (id, domain_id, plan_id, status, "
                "current_zone, version, run_ids, approvals, artifacts, "
                "transfer_history, created_at) VALUES (:rel, :d, :p, "
                "'deployed', 'zr', '1.0.0', CAST(:rids AS jsonb), "
                "'[]'::jsonb, '[]'::jsonb, '[]'::jsonb, now()) "
                "ON CONFLICT (id) DO NOTHING"
            ), {"rel": REL, "d": DOMAIN, "p": PLAN, "rids": f'["{RUN}"]'})
        await engine.dispose()

    async def test_valid_package_is_verified_and_anchored(
        self, pg_client: AsyncClient,
    ):
        res = await pg_client.post(
            "/api/v1/artifacts/airgap/verify", json=_request(),
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["verified"] is True
        assert body["package_id"] == PKG
        assert body["missing_files"] == []
        assert body["corrupted_files"] == []
        assert body["unregistered_files"] == []
        assert body["errors"] == []

        rows = await _ledger_rows(RUN)
        assert len(rows) == 1
        row = rows[0]
        assert row["type"] == "decision"
        prov = row["provenance_json"]
        assert prov["source"] == "cosmo-airgap-verifier"
        assert prov["airgap_type"] == "AIRGAP_VERIFIED"
        assert prov["verified"] is True
        assert prov["package_id"] == PKG
        assert prov["release_id"] == REL
        assert prov["computed_digest_pin"] == prov["package_digest_pin"]
        assert prov["files_expected"] == 1
        assert len(prov["provenance_hash"]) == 64

    async def test_corrupted_file_detected(self, pg_client: AsyncClient):
        res = await pg_client.post(
            "/api/v1/artifacts/airgap/verify",
            json=_request(archive=[_file(sha256=H_B)]),
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["verified"] is False
        assert body["corrupted_files"] == ["images/api.tar"]

    async def test_missing_file_detected(self, pg_client: AsyncClient):
        manifest = [_file("images/api.tar", H_A, 10), _file("images/web.tar", H_B, 20)]
        res = await pg_client.post(
            "/api/v1/artifacts/airgap/verify",
            json=_request(files=manifest, archive=[_file("images/api.tar", H_A, 10)]),
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["verified"] is False
        assert body["missing_files"] == ["images/web.tar"]

    async def test_unregistered_file_detected(self, pg_client: AsyncClient):
        res = await pg_client.post(
            "/api/v1/artifacts/airgap/verify",
            json=_request(archive=[_file(), _file("images/sneaky.tar", H_B, 5)]),
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["verified"] is False
        assert body["unregistered_files"] == ["images/sneaky.tar"]

    async def test_pin_mismatch_detected(self, pg_client: AsyncClient):
        res = await pg_client.post(
            "/api/v1/artifacts/airgap/verify",
            json=_request(pin=H_B),
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["verified"] is False
        assert any("package_digest_pin mismatch" in e for e in body["errors"])

    async def test_failed_verdict_is_still_recorded(self, pg_client: AsyncClient):
        await pg_client.post(
            "/api/v1/artifacts/airgap/verify",
            json=_request(archive=[_file(sha256=H_B)]),
        )
        rows = await _ledger_rows(RUN)
        assert len(rows) == 1
        prov = rows[0]["provenance_json"]
        assert prov["verified"] is False
        assert prov["corrupted_files"] == ["images/api.tar"]

    async def test_unknown_release_is_not_anchored(self, pg_client: AsyncClient):
        res = await pg_client.post(
            "/api/v1/artifacts/airgap/verify",
            json=_request(package_id="airgap-pkg-orphan",
                          release_id="cos148-ghost-rel"),
        )
        assert res.status_code == 200, res.text
        assert res.json()["verified"] is True
        # офлайн-вердикт честный, но якорить нечем — ledger не пишется
        assert await _ledger_rows(RUN) == []
        # COS-152 честный edge: non-durable пакет не читается из ledger → 404
        res = await pg_client.get(
            "/api/v1/artifacts/airgap/airgap-pkg-orphan",
        )
        assert res.status_code == 404, res.text

    async def test_get_returns_status(self, pg_client: AsyncClient):
        posted = await pg_client.post(
            "/api/v1/artifacts/airgap/verify", json=_request(),
        )
        assert posted.status_code == 200, posted.text
        res = await pg_client.get(f"/api/v1/artifacts/airgap/{PKG}")
        assert res.status_code == 200, res.text
        assert res.json() == posted.json()

    async def test_get_reads_latest_anchor(self, pg_client: AsyncClient):
        """COS-152: latest wins — читается последний якорённый вердикт."""
        first = await pg_client.post(
            "/api/v1/artifacts/airgap/verify", json=_request(),
        )
        assert first.status_code == 200, first.text
        assert first.json()["verified"] is True
        second = await pg_client.post(
            "/api/v1/artifacts/airgap/verify",
            json=_request(archive=[_file(sha256=H_B)]),
        )
        assert second.status_code == 200, second.text
        assert second.json()["verified"] is False
        res = await pg_client.get(f"/api/v1/artifacts/airgap/{PKG}")
        assert res.status_code == 200, res.text
        assert res.json()["verified"] is False
        assert res.json()["corrupted_files"] == ["images/api.tar"]

    async def test_get_survives_process_restart(self, pg_client: AsyncClient):
        """COS-152: durable read — свежий процесс видит вердикт из ledger."""
        posted = await pg_client.post(
            "/api/v1/artifacts/airgap/verify", json=_request(),
        )
        assert posted.status_code == 200, posted.text

        status, body = get_in_fresh_process(
            f"/api/v1/artifacts/airgap/{PKG}", _PG_URL,
        )
        assert status == 200, body
        assert body["verified"] is True
        assert body["package_id"] == PKG

    async def test_get_unknown_package_404(self, pg_client: AsyncClient):
        res = await pg_client.get("/api/v1/artifacts/airgap/airgap-ghost")
        assert res.status_code == 404, res.text

    async def test_verify_requires_principal(self, pg_client: AsyncClient):
        from orchestrator.cosmo.api.deps import get_current_principal
        from orchestrator.cosmo.api.main import app

        app.dependency_overrides.pop(get_current_principal, None)
        res = await pg_client.post(
            "/api/v1/artifacts/airgap/verify", json=_request(),
        )
        assert res.status_code == 401, res.text

    async def test_read_requires_principal(self, pg_client: AsyncClient):
        from orchestrator.cosmo.api.deps import get_current_principal
        from orchestrator.cosmo.api.main import app

        app.dependency_overrides.pop(get_current_principal, None)
        res = await pg_client.get(f"/api/v1/artifacts/airgap/{PKG}")
        assert res.status_code == 401, res.text
