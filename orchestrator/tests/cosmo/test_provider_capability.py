# -*- coding: utf-8 -*-
"""
COS-052: Provider capability matrix tests.

Проверяет:
  - матрицы покрывают Git, Harbor/OCI, Nexus, MinIO/S3 (+ optional Sfera);
  - каждая матрица отчётна по ВСЕМ ProviderCapability (нет дыр в отчётности);
  - unsupported capability → честный OpResult.unsupported, не fake success;
  - error category mapping в TransferFailureClass;
  - provider-specific location_ref ≠ PureK canonical identity (digest);
  - FakeCapabilityProvider как reusable fixture без внешних сервисов.
"""
from __future__ import annotations

import pytest

from orchestrator.cosmo.adapters.provider_capability import (
    CapabilityProvider,
    CapabilityReport,
    CapabilityStatus,
    ErrorCategory,
    OpResult,
    OpStatus,
    ProviderCapability,
    UnsupportedCapabilityError,
)
from orchestrator.cosmo.adapters.provider_matrices import (
    ALL_BASELINE_MATRICES,
    git_provider_matrix,
    harbor_oci_matrix,
    minio_s3_matrix,
    nexus_package_matrix,
    sfera_matrix,
)
from orchestrator.cosmo.adapters.fake_providers import (
    FakeCapabilityProvider,
    sha256_of,
)

ALL_CAPS = list(ProviderCapability)


# ══════════════════════════════════════════════════════════════════════════════
# Coverage: все baseline-провайдеры отчитываются по всем capability
# ══════════════════════════════════════════════════════════════════════════════

class TestMatrixCoverage:
    @pytest.mark.parametrize("provider_id", [
        "gitea", "harbor", "nexus", "minio", "sfera",
    ])
    def test_matrix_reports_every_capability(self, provider_id):
        report = ALL_BASELINE_MATRICES[provider_id]
        missing = [c.value for c in ALL_CAPS if c.value not in report.entries]
        assert missing == [], f"{provider_id}: missing capability report entries: {missing}"

    def test_all_four_baseline_providers_present(self):
        assert set(ALL_BASELINE_MATRICES) == {"gitea", "harbor", "nexus", "minio", "sfera"}

    def test_harbor_supports_oci_push_pull_and_digest(self):
        m = harbor_oci_matrix()
        assert m.supports(ProviderCapability.OCI_PUSH)
        assert m.supports(ProviderCapability.OCI_PULL)
        assert m.supports(ProviderCapability.RESOLVE_DIGEST)
        assert m.supports(ProviderCapability.SIGNATURE_REF)
        assert m.supports(ProviderCapability.SBOM_REF)

    def test_git_provider_is_not_blob_storage(self):
        m = git_provider_matrix()
        assert not m.supports(ProviderCapability.OCI_PUSH)
        assert not m.supports(ProviderCapability.RAW_PUSH)
        assert m.supports(ProviderCapability.PROVISION_REPOSITORY)

    def test_nexus_promotion_is_not_native(self):
        m = nexus_package_matrix()
        # честно: нет нативного copy API → NOT_SUPPORTED, promotion = pull+push
        assert m.get(ProviderCapability.COPY_OR_PROMOTE).status == CapabilityStatus.NOT_SUPPORTED

    def test_minio_raw_and_digest_but_not_oci(self):
        m = minio_s3_matrix()
        assert m.supports(ProviderCapability.RAW_PUSH)
        assert m.supports(ProviderCapability.RAW_PULL)
        assert not m.supports(ProviderCapability.OCI_PUSH)
        assert not m.supports(ProviderCapability.OCI_PULL)

    def test_sfera_unknowns_are_honest(self):
        """Нет подтверждённого контракта → UNKNOWN, а не выдуманный DOCUMENTED."""
        m = sfera_matrix()
        for cap in (ProviderCapability.EXISTS, ProviderCapability.RESOLVE_DIGEST,
                    ProviderCapability.COPY_OR_PROMOTE, ProviderCapability.QUOTA_REPORT,
                    ProviderCapability.SIGNATURE_REF, ProviderCapability.SBOM_REF):
            assert m.get(cap).status == CapabilityStatus.UNKNOWN, cap
        # подтверждено легаси-клиентом:
        assert m.get(ProviderCapability.PROVISION_AREA).status == CapabilityStatus.DOCUMENTED
        assert m.get(ProviderCapability.OCI_PUSH).status == CapabilityStatus.DOCUMENTED
        assert m.get(ProviderCapability.OCI_PULL).status == CapabilityStatus.DOCUMENTED


# ══════════════════════════════════════════════════════════════════════════════
# Честность: unsupported ≠ fake success
# ══════════════════════════════════════════════════════════════════════════════

class TestHonestUnsupported:
    @pytest.mark.asyncio
    async def test_unsupported_returns_unsupported_not_ok(self):
        fake = FakeCapabilityProvider("gitea", git_provider_matrix())
        result = await fake.op_push("some/ref", b"data")  # git не поддерживает raw push
        assert result.status == OpStatus.UNSUPPORTED
        assert result.ok is False
        assert result.detail != ""

    @pytest.mark.asyncio
    async def test_unscripted_fake_never_fakes_success(self):
        """Fake без скрипта возвращает UNSUPPORTED — не OK, не 200, не заглушку."""
        fake = FakeCapabilityProvider("minio", minio_s3_matrix())
        r1 = await fake.op_health()
        r2 = await fake.op_pull("x")
        r3 = await fake.op_exists("x", "sha256:" + "0" * 64)
        for r in (r1, r2, r3):
            assert r.status == OpStatus.UNSUPPORTED

    def test_require_guard_raises_honest_error(self):
        fake = FakeCapabilityProvider("gitea", git_provider_matrix())
        with pytest.raises(UnsupportedCapabilityError):
            fake.require(ProviderCapability.OCI_PUSH)

    def test_opresult_unsupported_factory(self):
        r = OpResult.unsupported(ProviderCapability.QUOTA_REPORT, "nexus")
        assert r.status == OpStatus.UNSUPPORTED
        assert r.ok is False
        assert "does not support" in r.detail


# ══════════════════════════════════════════════════════════════════════════════
# Error categories → transfer failure classes
# ══════════════════════════════════════════════════════════════════════════════

class TestErrorCategories:
    def test_transient_maps_to_transport_failure(self):
        r = OpResult(status=OpStatus.TRANSIENT_FAILURE,
                     capability=ProviderCapability.HEALTH, provider_id="x")
        assert r.error_category == ErrorCategory.RETRYABLE
        assert r.error_category.to_transfer_failure_class() == "transport_failure"

    def test_validation_maps_to_validation_failure(self):
        r = OpResult(status=OpStatus.VALIDATION_FAILURE,
                     capability=ProviderCapability.OCI_PUSH, provider_id="x")
        assert r.error_category == ErrorCategory.TERMINAL
        assert r.error_category.to_transfer_failure_class() == "validation_failure"

    def test_auth_and_quota_are_terminal(self):
        for st in (OpStatus.AUTH_FAILURE, OpStatus.QUOTA_FAILURE):
            r = OpResult(status=st, capability=ProviderCapability.RAW_PUSH, provider_id="x")
            assert r.error_category == ErrorCategory.TERMINAL


# ══════════════════════════════════════════════════════════════════════════════
# Canonical identity: provider refs ≠ PureK identity
# ══════════════════════════════════════════════════════════════════════════════

class TestCanonicalIdentity:
    @pytest.mark.asyncio
    async def test_provider_ref_is_not_canonical_digest(self):
        """location_ref — provider-specific путь; canonical — только digest."""
        fake = FakeCapabilityProvider("nexus", nexus_package_matrix())
        fake.script(ProviderCapability.RAW_PUSH, OpResult(
            status=OpStatus.OK, capability=ProviderCapability.RAW_PUSH,
            provider_id="nexus", location_ref="maven-closed/com/acme/app/1.0.jar",
            digest=sha256_of(b"jar-bytes"),
        ))
        r = await fake.op_push("com/acme/app/1.0.jar", b"jar-bytes")
        assert r.ok
        assert r.location_ref == "maven-closed/com/acme/app/1.0.jar"  # provider-specific
        assert r.digest.startswith("sha256:")                          # canonical
        # Смена provider-specific location не меняет canonical digest:
        assert r.digest == sha256_of(b"jar-bytes")

    @pytest.mark.asyncio
    async def test_digest_preserved_from_server_not_recomputed(self):
        """Digest, вернувшийся от провайдера, сохраняется как есть (minio RAW_PULL)."""
        fake = FakeCapabilityProvider("minio", minio_s3_matrix())
        server_digest = "sha256:" + "f" * 64
        fake.script(ProviderCapability.RAW_PULL, OpResult(
            status=OpStatus.OK, capability=ProviderCapability.RAW_PULL,
            provider_id="minio", digest=server_digest,
        ))
        r = await fake.op_pull("evidence/run-1/report.sarif")
        assert r.digest == server_digest

    @pytest.mark.asyncio
    async def test_signature_and_sbom_refs_preserved(self):
        """Signature/SBOM refs проходят через OpResult без подмены."""
        fake = FakeCapabilityProvider("minio", minio_s3_matrix())
        fake.script(ProviderCapability.RAW_PULL, OpResult(
            status=OpStatus.OK, capability=ProviderCapability.RAW_PULL,
            provider_id="minio", digest="sha256:" + "a" * 64,
            signature_ref="sha256-aaaa.sig",
            sbom_ref="sha256-bbbb.cdx.json",
        ))
        r = await fake.op_pull("evidence/run-1/bundle")
        assert r.signature_ref == "sha256-aaaa.sig"
        assert r.sbom_ref == "sha256-bbbb.cdx.json"


# ══════════════════════════════════════════════════════════════════════════════
# Reusable fixtures: fake providers без внешних сервисов
# ══════════════════════════════════════════════════════════════════════════════

class TestFakeProviderFixtures:
    @pytest.mark.asyncio
    async def test_scripted_success(self):
        fake = FakeCapabilityProvider("minio", minio_s3_matrix())
        fake.script(ProviderCapability.RAW_PUSH, OpResult(
            status=OpStatus.OK, capability=ProviderCapability.RAW_PUSH,
            provider_id="minio", digest=sha256_of(b"evidence"),
        ))
        r = await fake.op_push("evidence/run-1/report.sarif", b"evidence")
        assert r.ok
        assert len(fake.calls) == 1

    @pytest.mark.asyncio
    async def test_scripted_exception_propagates(self):
        """Ошибка провайдера не маскируется под transfer success."""
        fake = FakeCapabilityProvider("nexus", nexus_package_matrix())
        fake.script(ProviderCapability.RAW_PUSH, RuntimeError("connection reset"))
        with pytest.raises(RuntimeError):
            await fake.op_push("x", b"y")
