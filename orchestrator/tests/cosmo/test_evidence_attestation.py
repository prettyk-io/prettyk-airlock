# -*- coding: utf-8 -*-
"""COS-147: PK-C-003.4 — release evidence attestation bundle (provenance).

Покрытие:
  - DTO конверта ``cosmo-attestation@1``: формат, sha256-поля, ``extra=forbid``,
    детерминированный ``provenance_bundle_hash`` (и его чувствительность);
  - POST /api/v1/artifacts/attestation/bundle:
      * полный набор свидетельств (манифест COS-142 + SBOM COS-138 +
        клиренс COS-141) → ``verified=true``, root-хэш сходится с пересчётом;
      * крипто-запись в ledger (``attestation_type='RELEASE_ATTESTATION_BUNDLE'``,
        ``content_hash == root``, ``chain_of_custody`` заполнен);
      * разрыв цепочки (манифест не покрывает digest артефакта релиза) →
        ``verified=false`` (вердикт, не 5xx) + mismatches в ledger;
      * нет свидетельств вообще → 422; нет прогонов для якоря → 422;
      * неизвестный релиз → 404; без аутентификации → 401;
  - GET /api/v1/artifacts/attestation/{release_id}: чтение конверта, 404 иначе.

Свидетельства строятся реальными маршрутами соседних гейтов (интеграция):
COS-142 ``/artifacts/manifest/verify``, COS-138 ``/releases/{id}/sbom/attach``,
COS-141 ``/hub/clearance/ingest``.

Запуск:  pytest .../test_evidence_attestation.py -q
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

from orchestrator.cosmo.domain.evidence_attestation import (  # noqa: E402
    EvidenceAttestationBundle,
    EvidenceAttestationPredicate,
    EvidenceAttestationSubject,
    compute_provenance_bundle_hash,
)

import _testpg  # noqa: E402
from _durable_probe import get_in_fresh_process  # noqa: E402

DOMAIN = "cos147-dom"
PLAN = "cos147-plan"
RUN = "cos147run0001"
RUN2 = "cos147run0002"
RUN3 = "cos147run0003"
REL = "cos147rel0001"
REL_MISMATCH = "cos147rel0002"
REL_NORUN = "cos147rel0003"
REL_NOEVID = "cos147rel0004"

ART_NAME = "api-image.tar"
BUNDLE = "bundle-cos147"

DIG_A = "a" * 64
DIG_B = "b" * 64

_PG_URL = _testpg.TEST_PG_URL


def _manifest_body(digest: str = DIG_A, run_id: str = RUN,
                   bundle_id: str = BUNDLE) -> dict:
    return {
        "bundle_id": bundle_id,
        "release_version": "1.2.3",
        "profile": "hardened@1",
        "artifacts": [
            {"name": ART_NAME, "version": "1.2.3",
             "digest": f"sha256:{digest}"},
        ],
        "created_at": "2026-09-19T10:00:00Z",
        "run_id": run_id,
    }


def _sbom_body(digest: str = DIG_A) -> dict:
    ref = f"sha256:{digest}"
    return {
        "sbom": {
            "format": "spdx-json",
            "syft_version": "1.5.0",
            "artifact_digest": ref,
            "packages_count": 1,
            "packages": [
                {"name": "openssl", "version": "3.0.0", "type": "apk"},
            ],
        },
        "vulnerabilities": {
            "scanner_version": "0.80.0",
            "artifact_digest": ref,
            "critical_count": 0,
            "high_count": 0,
            "medium_count": 0,
            "low_count": 0,
            "findings": [],
        },
        "artifact_digest": ref,
    }


def _clearance_body(release_id: str, run_id: str) -> dict:
    return {
        "evaluation_id": f"eval-{release_id}",
        "release_id": release_id,
        "run_id": run_id,
        "evaluated_at": "2026-09-19T10:05:00Z",
        "policy_version": "qg-policy-1",
        "security_execution_verdict": "PASS",
        "act_ref": f"act://{release_id}",
        "qg_clearance": "PASS_GRANTED",
        "verdict": "PASS",
        "ready_for_transfer": True,
        "qualifying_context": True,
        "ok_to_transfer": True,
    }


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


def _attestation_rows(rows: list[dict]) -> list[dict]:
    return [
        r for r in rows
        if (r["provenance_json"] or {}).get("attestation_type")
        == "RELEASE_ATTESTATION_BUNDLE"
    ]


# ── DTO unit ─────────────────────────────────────────────────────────────

class TestEvidenceAttestationDto:
    def _subject(self, digest: str = f"sha256:{DIG_A}") -> EvidenceAttestationSubject:
        return EvidenceAttestationSubject(name=ART_NAME, digest=digest)

    def _predicate(self, **over: object) -> EvidenceAttestationPredicate:
        body = {
            "release_id": REL,
            "bundle_id": BUNDLE,
            "profile": "hardened@1",
            "manifest_digest_pin": f"sha256:{DIG_B}",
            "sbom_digest": DIG_A,
            "hub_clearance_status": "PASS_GRANTED",
            "hub_evaluation_id": f"eval-{REL}",
            "timestamp": "2026-09-19T10:10:00Z",
        }
        body.update(over)
        return EvidenceAttestationPredicate(**body)

    def test_bundle_defaults_to_canonical_format(self):
        bundle = EvidenceAttestationBundle(
            subject=self._subject(),
            predicate=self._predicate(),
            provenance_bundle_hash=f"sha256:{DIG_B}",
            verified=True,
        )
        assert bundle.format == "cosmo-attestation@1"
        assert bundle.subject.normalized_digest() == f"sha256:{DIG_A}"

    @pytest.mark.parametrize("digest", ["deadbeef", "sha256:" + "A" * 64, "", "x" * 64])
    def test_subject_digest_must_be_lowercase_sha256(self, digest: str):
        with pytest.raises(ValidationError):
            self._subject(digest)

    def test_subject_accepts_bare_hex(self):
        subject = self._subject(DIG_A)
        assert subject.normalized_digest() == f"sha256:{DIG_A}"

    def test_unknown_format_rejected(self):
        with pytest.raises(ValidationError):
            EvidenceAttestationBundle(
                format="cosmo-attestation@2",
                subject=self._subject(),
                predicate=self._predicate(),
                provenance_bundle_hash=f"sha256:{DIG_B}",
                verified=True,
            )

    def test_predicate_requires_profile(self):
        with pytest.raises(ValidationError):
            self._predicate(profile="")

    def test_predicate_requires_release_id(self):
        with pytest.raises(ValidationError):
            self._predicate(release_id="")

    def test_predicate_requires_timestamp(self):
        with pytest.raises(ValidationError):
            self._predicate(timestamp="")

    def test_bad_manifest_pin_rejected(self):
        with pytest.raises(ValidationError):
            self._predicate(manifest_digest_pin="not-a-pin")

    def test_extra_field_rejected(self):
        with pytest.raises(ValidationError):
            EvidenceAttestationBundle(
                subject=self._subject(),
                predicate=self._predicate(),
                provenance_bundle_hash=f"sha256:{DIG_B}",
                verified=True,
                signature="x",
            )

    def test_root_hash_deterministic(self):
        subject, predicate = self._subject(), self._predicate()
        first = compute_provenance_bundle_hash(subject, predicate)
        second = compute_provenance_bundle_hash(
            EvidenceAttestationSubject(**subject.model_dump()),
            EvidenceAttestationPredicate(**predicate.model_dump()),
        )
        assert first == second
        assert first.startswith("sha256:")
        assert len(first) == 71

    @pytest.mark.parametrize(
        "change",
        [
            {"bundle_id": "other-bundle"},
            {"profile": "airgap@1"},
            {"manifest_digest_pin": f"sha256:{DIG_A}"},
            {"sbom_digest": DIG_B},
            {"hub_clearance_status": "REJECTED"},
            {"hub_evaluation_id": "eval-other"},
            {"timestamp": "2026-09-19T11:00:00Z"},
        ],
    )
    def test_root_hash_sensitive_to_each_field(self, change: dict):
        base = compute_provenance_bundle_hash(self._subject(), self._predicate())
        changed = compute_provenance_bundle_hash(
            self._subject(), self._predicate(**change),
        )
        assert base != changed

    def test_root_hash_sensitive_to_subject(self):
        base = compute_provenance_bundle_hash(self._subject(), self._predicate())
        changed = compute_provenance_bundle_hash(
            self._subject(f"sha256:{DIG_B}"), self._predicate(),
        )
        assert base != changed


# ── Route tests ──────────────────────────────────────────────────────────

class TestAttestationBundleRoute:
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
                "VALUES (:d, 'cos147', 'gitea', 'http://gitea:3000', "
                "'t', '{}'::jsonb, 50, 100, 8, now()) "
                "ON CONFLICT (id) DO NOTHING"
            ), {"d": DOMAIN})
            await conn.execute(text(
                "INSERT INTO apps (id, domain_id, level) "
                "VALUES ('cos147-app', :d, 0) ON CONFLICT (id) DO NOTHING"
            ), {"d": DOMAIN})
            await conn.execute(text(
                "INSERT INTO pipeline_plans (id, app_id, level, scope_id, "
                "compiled_hash, compiled_at) VALUES (:p, 'cos147-app', "
                "'app', :p, 'h', now()) ON CONFLICT (id) DO NOTHING"
            ), {"p": PLAN})
            for rid in (RUN, RUN2, RUN3):
                await conn.execute(text(
                    "INSERT INTO runs (id, plan_id, trigger, domain_id, status, "
                    "initiator_user_id, initiator_role, findings_refs, created_at) "
                    "VALUES (:r, :p, 'manual', :d, 'succeeded', 'system', "
                    "'system', '[]'::jsonb, now()) ON CONFLICT (id) DO NOTHING"
                ), {"r": rid, "p": PLAN, "d": DOMAIN})
            releases = (
                # (id, run_ids, artifacts)
                (REL, f'["{RUN}"]', f'[{{"name": "{ART_NAME}", "sha256": "{DIG_A}"}}]'),
                (REL_MISMATCH, f'["{RUN2}"]',
                 f'[{{"name": "{ART_NAME}", "sha256": "{DIG_B}"}}]'),
                (REL_NORUN, "[]", f'[{{"name": "{ART_NAME}", "sha256": "{DIG_A}"}}]'),
                (REL_NOEVID, f'["{RUN3}"]', "[]"),
            )
            for rel_id, run_ids, artifacts in releases:
                await conn.execute(text(
                    "INSERT INTO releases (id, domain_id, plan_id, status, "
                    "current_zone, version, run_ids, approvals, artifacts, "
                    "transfer_history, created_at) VALUES (:rel, :d, :p, "
                    "'deployed', 'zr', '1.2.3', CAST(:rids AS jsonb), "
                    "'[]'::jsonb, CAST(:arts AS jsonb), '[]'::jsonb, now()) "
                    "ON CONFLICT (id) DO NOTHING"
                ), {"rel": rel_id, "d": DOMAIN, "p": PLAN,
                    "rids": run_ids, "arts": artifacts})
        await engine.dispose()

        # Свидетельство 1 — манифест бандла (COS-142), привязан к прогону релиза.
        res = await pg_client.post(
            "/api/v1/artifacts/manifest/verify", json=_manifest_body(),
        )
        assert res.status_code == 200, res.text
        assert res.json()["ledger_entry_id"], res.text

        # Свидетельство 2 — аттестация SBOM (COS-138).
        res = await pg_client.post(
            f"/api/v1/releases/{REL}/sbom/attach", json=_sbom_body(),
        )
        assert res.status_code == 201, res.text

        # Свидетельство 3 — клиренс Quality Gate (COS-141).
        res = await pg_client.post(
            "/api/v1/hub/clearance/ingest", json=_clearance_body(REL, RUN),
        )
        assert res.status_code == 200, res.text

        # Для mismatch-релиза: манифест покрывает ДРУГОЙ digest (A), а релиз
        # закреплён на B → цепочка разрывается детерминированно.
        res = await pg_client.post(
            "/api/v1/artifacts/manifest/verify",
            json=_manifest_body(digest=DIG_A, run_id=RUN2, bundle_id="bundle-mismatch"),
        )
        assert res.status_code == 200, res.text
        res = await pg_client.post(
            f"/api/v1/releases/{REL_MISMATCH}/sbom/attach",
            json=_sbom_body(DIG_B),
        )
        assert res.status_code == 201, res.text

    async def test_full_bundle_is_verified(self, pg_client: AsyncClient):
        res = await pg_client.post(
            "/api/v1/artifacts/attestation/bundle", json={"release_id": REL},
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["format"] == "cosmo-attestation@1"
        assert body["verified"] is True
        assert body["subject"]["name"] == ART_NAME
        assert body["subject"]["digest"] == f"sha256:{DIG_A}"
        pred = body["predicate"]
        assert pred["release_id"] == REL
        assert pred["bundle_id"] == BUNDLE
        assert pred["profile"] == "hardened@1"
        assert pred["manifest_digest_pin"].startswith("sha256:")
        assert len(pred["sbom_digest"]) == 64
        assert pred["hub_clearance_status"] == "PASS_GRANTED"
        assert pred["hub_evaluation_id"] == f"eval-{REL}"
        assert pred["timestamp"]

    async def test_root_hash_matches_recomputation(self, pg_client: AsyncClient):
        res = await pg_client.post(
            "/api/v1/artifacts/attestation/bundle", json={"release_id": REL},
        )
        body = res.json()
        expected = compute_provenance_bundle_hash(
            EvidenceAttestationSubject(**body["subject"]),
            EvidenceAttestationPredicate(**body["predicate"]),
        )
        assert body["provenance_bundle_hash"] == expected

    async def test_bundle_is_anchored_in_ledger(self, pg_client: AsyncClient):
        res = await pg_client.post(
            "/api/v1/artifacts/attestation/bundle", json={"release_id": REL},
        )
        assert res.status_code == 200, res.text
        root = res.json()["provenance_bundle_hash"]

        rows = _attestation_rows(await _ledger_rows(RUN))
        assert len(rows) == 1
        row = rows[0]
        assert row["type"] == "decision"
        assert row["content_hash"] == root.split(":", 1)[1]
        prov = row["provenance_json"]
        assert prov["source"] == "cosmo-attestation-packager"
        assert prov["attestation_type"] == "RELEASE_ATTESTATION_BUNDLE"
        assert prov["verified"] is True
        assert prov["release_id"] == REL
        assert prov["provenance_bundle_hash"] == root
        coc = prov["chain_of_custody"]
        assert coc["subject_digest"] == DIG_A
        assert coc["mismatches"] == []
        assert coc["sbom_artifact_digest"] == DIG_A
        assert len(prov["evidence_ledger_ids"]["manifest"]) > 0
        assert len(prov["evidence_ledger_ids"]["sbom"]) > 0
        assert len(prov["evidence_ledger_ids"]["clearance"]) > 0
        assert len(prov["provenance_hash"]) == 64

    async def test_chain_break_is_verdict_not_error(self, pg_client: AsyncClient):
        res = await pg_client.post(
            "/api/v1/artifacts/attestation/bundle",
            json={"release_id": REL_MISMATCH},
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["verified"] is False
        assert body["subject"]["digest"] == f"sha256:{DIG_B}"

        rows = _attestation_rows(await _ledger_rows(RUN2))
        assert len(rows) == 1
        coc = rows[0]["provenance_json"]["chain_of_custody"]
        assert rows[0]["provenance_json"]["verified"] is False
        assert coc["subject_digest"] == DIG_B
        assert any("do not cover subject digest" in m for m in coc["mismatches"])

    async def test_no_evidence_is_rejected_422(self, pg_client: AsyncClient):
        res = await pg_client.post(
            "/api/v1/artifacts/attestation/bundle", json={"release_id": REL_NOEVID},
        )
        assert res.status_code == 422, res.text
        assert "no artifact digest to attest" in res.text

    async def test_release_without_runs_is_rejected_422(self, pg_client: AsyncClient):
        res = await pg_client.post(
            "/api/v1/artifacts/attestation/bundle", json={"release_id": REL_NORUN},
        )
        assert res.status_code == 422, res.text
        assert "no runs to anchor" in res.text

    async def test_unknown_release_404(self, pg_client: AsyncClient):
        res = await pg_client.post(
            "/api/v1/artifacts/attestation/bundle", json={"release_id": "cos147-ghost"},
        )
        assert res.status_code == 404, res.text

    async def test_get_reads_back_bundle(self, pg_client: AsyncClient):
        posted = await pg_client.post(
            "/api/v1/artifacts/attestation/bundle", json={"release_id": REL},
        )
        assert posted.status_code == 200, posted.text
        res = await pg_client.get(f"/api/v1/artifacts/attestation/{REL}")
        assert res.status_code == 200, res.text
        assert res.json() == posted.json()

    async def test_get_reads_latest_anchor(self, pg_client: AsyncClient):
        """COS-152: latest wins — читается последняя якорённая запись."""
        first = await pg_client.post(
            "/api/v1/artifacts/attestation/bundle", json={"release_id": REL},
        )
        assert first.status_code == 200, first.text
        second = await pg_client.post(
            "/api/v1/artifacts/attestation/bundle", json={"release_id": REL},
        )
        assert second.status_code == 200, second.text
        assert (
            first.json()["provenance_bundle_hash"]
            != second.json()["provenance_bundle_hash"]
        )
        res = await pg_client.get(f"/api/v1/artifacts/attestation/{REL}")
        assert res.status_code == 200, res.text
        assert (
            res.json()["provenance_bundle_hash"]
            == second.json()["provenance_bundle_hash"]
        )

    async def test_get_survives_process_restart(self, pg_client: AsyncClient):
        """COS-152: durable read — свежий процесс видит конверт из ledger."""
        posted = await pg_client.post(
            "/api/v1/artifacts/attestation/bundle", json={"release_id": REL},
        )
        assert posted.status_code == 200, posted.text

        status, body = get_in_fresh_process(
            f"/api/v1/artifacts/attestation/{REL}", _PG_URL,
        )
        assert status == 200, body
        assert body["format"] == "cosmo-attestation@1"
        assert body["verified"] is True
        assert body["predicate"]["release_id"] == REL
        assert (
            body["provenance_bundle_hash"]
            == posted.json()["provenance_bundle_hash"]
        )

    async def test_get_unknown_bundle_404(self, pg_client: AsyncClient):
        res = await pg_client.get("/api/v1/artifacts/attestation/cos147-ghost")
        assert res.status_code == 404, res.text

    async def test_build_requires_principal(self, pg_client: AsyncClient):
        from orchestrator.cosmo.api.deps import get_current_principal
        from orchestrator.cosmo.api.main import app

        app.dependency_overrides.pop(get_current_principal, None)
        res = await pg_client.post(
            "/api/v1/artifacts/attestation/bundle", json={"release_id": REL},
        )
        assert res.status_code == 401, res.text

    async def test_read_requires_principal(self, pg_client: AsyncClient):
        from orchestrator.cosmo.api.deps import get_current_principal
        from orchestrator.cosmo.api.main import app

        app.dependency_overrides.pop(get_current_principal, None)
        res = await pg_client.get(f"/api/v1/artifacts/attestation/{REL}")
        assert res.status_code == 401, res.text
