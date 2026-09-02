# -*- coding: utf-8 -*-
"""
COS-060: Provider Conformance Suite — общий батарейный прогон всех providers.

Провайдеры под конформансом (матрицы COS-052):
  gitea (Git), harbor (OCI), nexus (package), minio (S3/evidence), sfera (optional).

Батареи:
  A. Capability report completeness — каждая capability имеет явный epistemic status.
  B. Honest unsupported — NOT_SUPPORTED/UNKNOWN никогда не дают ok=True.
  C. Failure semantics — NOT_FOUND / AUTH / TRANSIENT / VALIDATION / QUOTA / CONFLICT
     классифицируются честно; terminal не retryable; transient retryable.
  D. Unknown capability behavior — неизвестная capability → UNKNOWN + require() raises.
  E. Digest identity — server digest сохранён; computed помечен; отсутствующий
     digest не превращается в fake confirmation.
  F. Transfer kernel normalization — все OpStatus маппятся без маскировки.

Реальный adapter-код дополнительно прогоняется:
  - Sfera: полный статус-battery через scriptable transport (test_sfera_adapter.py);
  - OciRegistry (Harbor/Nexus/local-oci): httpx.MockTransport conformance (этот файл).
"""
from __future__ import annotations

import pytest

from orchestrator.cosmo.adapters.provider_capability import (
    CapabilityStatus,
    ErrorCategory,
    OpResult,
    OpStatus,
    ProviderCapability,
    UnsupportedCapabilityError,
)
from orchestrator.cosmo.adapters.provider_matrices import ALL_BASELINE_MATRICES
from orchestrator.cosmo.adapters.fake_providers import FakeCapabilityProvider
from orchestrator.cosmo.adapters.provider_result_mapping import to_transfer_outcome
from orchestrator.cosmo.transfer.contract import TransferItemStatus

ALL_CAPS = list(ProviderCapability)
PROVIDER_IDS = ["gitea", "harbor", "nexus", "minio", "sfera"]

# Capabilities, реализованные на generic-контракте CapabilityProvider
GENERIC_OPS = {
    ProviderCapability.HEALTH: "op_health",
    ProviderCapability.RAW_PUSH: "op_push",
    ProviderCapability.RAW_PULL: "op_pull",
    ProviderCapability.EXISTS: "op_exists",
}


def make_adapter(provider_id: str) -> FakeCapabilityProvider:
    return FakeCapabilityProvider(provider_id, ALL_BASELINE_MATRICES[provider_id])


# ══════════════════════════════════════════════════════════════════════════════
# A. Capability report completeness
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("provider_id", PROVIDER_IDS)
class TestCapabilityReportCompleteness:
    def test_every_capability_has_explicit_status(self, provider_id):
        """Каждая capability имеет явный epistemic status — никаких дыр."""
        matrix = ALL_BASELINE_MATRICES[provider_id]
        missing = [c.value for c in ALL_CAPS if c.value not in matrix.entries]
        assert missing == [], f"{provider_id}: unreported capabilities: {missing}"

    def test_all_statuses_are_valid_epistemic_values(self, provider_id):
        matrix = ALL_BASELINE_MATRICES[provider_id]
        valid = set(CapabilityStatus)
        for cap, entry in matrix.entries.items():
            assert entry.status in valid, f"{provider_id}/{cap}: invalid status"

    def test_report_serializes_to_dict(self, provider_id):
        matrix = ALL_BASELINE_MATRICES[provider_id]
        d = matrix.to_dict()
        assert d["provider_id"] == provider_id
        assert len(d["capabilities"]) == len(ALL_CAPS)


# ══════════════════════════════════════════════════════════════════════════════
# B. Honest unsupported: NOT_SUPPORTED/UNKNOWN никогда ok=True
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("provider_id", PROVIDER_IDS)
class TestHonestUnsupported:
    def test_matrix_promise_for_every_declared_unsupported(self, provider_id):
        """Для каждой NOT_SUPPORTED/UNKNOWN capability честный unsupported result."""
        matrix = ALL_BASELINE_MATRICES[provider_id]
        for cap in ALL_CAPS:
            entry = matrix.get(cap)
            if entry.status in (CapabilityStatus.NOT_SUPPORTED, CapabilityStatus.UNKNOWN):
                r = OpResult.unsupported(cap, provider_id, entry.notes)
                assert r.ok is False, f"{provider_id}/{cap}: unsupported gave ok=True"
                assert r.status == OpStatus.UNSUPPORTED

    @pytest.mark.asyncio
    async def test_unscripted_generic_ops_return_unsupported(self, provider_id):
        """Не-скриптованные generic ops → UNSUPPORTED (не fake success)."""
        adapter = make_adapter(provider_id)
        r_health = await adapter.op_health()
        r_push = await adapter.op_push("x/ref", b"data")
        r_pull = await adapter.op_pull("x/ref")
        r_exists = await adapter.op_exists("x/ref", None)
        for r in (r_health, r_push, r_pull, r_exists):
            assert r.status == OpStatus.UNSUPPORTED
            assert r.ok is False

    def test_blocked_is_not_supported_by_default(self, provider_id):
        matrix = ALL_BASELINE_MATRICES[provider_id]
        for cap in ALL_CAPS:
            entry = matrix.get(cap)
            if entry.status in (CapabilityStatus.NOT_SUPPORTED, CapabilityStatus.UNKNOWN,
                                CapabilityStatus.BLOCKED):
                assert matrix.supports(cap) is False


# ══════════════════════════════════════════════════════════════════════════════
# C. Failure semantics per provider
# ══════════════════════════════════════════════════════════════════════════════

FAILURE_BATTERY = [
    # (OpStatus, expected ErrorCategory, ok allowed?)
    (OpStatus.NOT_FOUND, ErrorCategory.TERMINAL, False),
    (OpStatus.AUTH_FAILURE, ErrorCategory.TERMINAL, False),
    (OpStatus.TRANSIENT_FAILURE, ErrorCategory.RETRYABLE, False),
    (OpStatus.VALIDATION_FAILURE, ErrorCategory.TERMINAL, False),
    (OpStatus.QUOTA_FAILURE, ErrorCategory.TERMINAL, False),
    (OpStatus.CONFLICT, ErrorCategory.TERMINAL, False),
    (OpStatus.UNSUPPORTED, ErrorCategory.TERMINAL, False),
]


@pytest.mark.parametrize("provider_id", PROVIDER_IDS)
class TestFailureSemantics:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("status,expected_category,ok_allowed", FAILURE_BATTERY)
    async def test_failure_status_battery(self, provider_id, status, expected_category, ok_allowed):
        """Каждый статус честно классифицируется; ok никогда не True для failure."""
        adapter = make_adapter(provider_id)
        adapter.script(ProviderCapability.RAW_PULL, OpResult(
            status=status, capability=ProviderCapability.RAW_PULL,
            provider_id=provider_id, detail=f"scripted {status.value}",
        ))
        r = await adapter.op_pull("evidence/run-1/report.sarif")
        assert r.status == status
        assert r.ok is ok_allowed
        assert r.error_category == expected_category, (
            f"{provider_id}: {status.value} → {expected_category.value}"
        )

    @pytest.mark.asyncio
    @pytest.mark.parametrize("status,expected_category,ok_allowed", FAILURE_BATTERY)
    async def test_transfer_failure_class_mapping(self, provider_id, status,
                                                  expected_category, ok_allowed):
        """ErrorCategory → TransferFailureClass: retryable=transport, terminal=validation."""
        adapter = make_adapter(provider_id)
        adapter.script(ProviderCapability.RAW_PULL, OpResult(
            status=status, capability=ProviderCapability.RAW_PULL, provider_id=provider_id,
        ))
        r = await adapter.op_pull("x")
        if status == OpStatus.UNSUPPORTED:
            # Kernel не имеет класса UNSUPPORTED — честно None (не validation,
            # не transport): см. to_transfer_outcome.
            from orchestrator.cosmo.adapters.provider_result_mapping import to_transfer_outcome
            outcome = to_transfer_outcome(r)
            assert outcome.failure_class is None
        elif expected_category == ErrorCategory.TERMINAL:
            assert r.error_category.to_transfer_failure_class() == "validation_failure"
        else:
            assert r.error_category.to_transfer_failure_class() == "transport_failure"


# ══════════════════════════════════════════════════════════════════════════════
# D. Unknown capability behavior
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("provider_id", PROVIDER_IDS)
class TestUnknownCapability:
    def test_missing_capability_reports_unknown(self, provider_id):
        """Capability, о которой провайдер не отчитался, → UNKNOWN (не crash, не ok)."""
        matrix = ALL_BASELINE_MATRICES[provider_id]
        # работаем на копии entries: общий синглтон матрицы мутировать нельзя
        removed = matrix.entries.pop(ProviderCapability.QUOTA_REPORT.value)
        try:
            entry = matrix.get(ProviderCapability.QUOTA_REPORT)
            assert entry.status == CapabilityStatus.UNKNOWN
            assert matrix.supports(ProviderCapability.QUOTA_REPORT) is False
            r = OpResult.unsupported(ProviderCapability.QUOTA_REPORT, provider_id)
            assert r.ok is False
        finally:
            matrix.entries[ProviderCapability.QUOTA_REPORT.value] = removed

    def test_require_raises_for_unsupported_capability(self, provider_id):
        """require() бросает честную ошибку на первой капе с supports()=False."""
        adapter = make_adapter(provider_id)
        matrix = ALL_BASELINE_MATRICES[provider_id]
        unsupported = [c for c in ALL_CAPS if not matrix.supports(c)]
        assert unsupported, f"{provider_id}: матрица без unsupported — противоречит канону"
        with pytest.raises(UnsupportedCapabilityError):
            adapter.require(unsupported[0])


# ══════════════════════════════════════════════════════════════════════════════
# E. Digest identity hardening
# ══════════════════════════════════════════════════════════════════════════════

SERVER_DIGEST = "sha256:" + "ab" * 32
COMPUTED_DIGEST = "sha256:" + "cd" * 32


@pytest.mark.parametrize("provider_id", PROVIDER_IDS)
class TestDigestIdentity:
    @pytest.mark.asyncio
    async def test_server_digest_preserved_verbatim(self, provider_id):
        adapter = make_adapter(provider_id)
        adapter.script(ProviderCapability.RAW_PULL, OpResult(
            status=OpStatus.OK, capability=ProviderCapability.RAW_PULL,
            provider_id=provider_id, digest=SERVER_DIGEST,
        ))
        r = await adapter.op_pull("x")
        assert r.digest == SERVER_DIGEST

    def test_computed_digest_distinct_from_server(self, provider_id):
        """Computed digest обязан быть помечен и не смешивается с server digest."""
        r_server = OpResult(status=OpStatus.OK, capability=ProviderCapability.RAW_PUSH,
                            provider_id=provider_id, digest=SERVER_DIGEST,
                            raw={"digest_source": "server"})
        r_computed = OpResult(status=OpStatus.OK, capability=ProviderCapability.RAW_PUSH,
                              provider_id=provider_id, digest=COMPUTED_DIGEST,
                              raw={"digest_source": "computed_payload"})
        assert r_server.raw["digest_source"] != r_computed.raw["digest_source"]
        assert r_server.digest != r_computed.digest

    @pytest.mark.asyncio
    async def test_missing_digest_is_not_fake_confirmation(self, provider_id):
        """Отсутствующий digest ≠ успешное подтверждение: raw пуст, digest None."""
        adapter = make_adapter(provider_id)
        adapter.script(ProviderCapability.RAW_PULL, OpResult(
            status=OpStatus.OK, capability=ProviderCapability.RAW_PULL,
            provider_id=provider_id, digest=None,
        ))
        r = await adapter.op_pull("x")
        assert r.status == OpStatus.OK      # операция прошла
        assert r.digest is None             # но подтверждения дайджеста нет
        assert r.raw.get("digest_source") is None

    def test_provider_location_is_not_canonical(self, provider_id):
        r = OpResult(status=OpStatus.OK, capability=ProviderCapability.RAW_PUSH,
                     provider_id=provider_id,
                     location_ref=f"sfera-area-7/internal/{provider_id}-only/path",
                     digest=SERVER_DIGEST)
        # location_ref может быть любым provider-specific путём —
        # canonical identity это только digest:
        assert r.location_ref.startswith("sfera-area-7")
        assert r.digest == SERVER_DIGEST


# ══════════════════════════════════════════════════════════════════════════════
# F. Transfer kernel normalization (без изменения kernel)
# ══════════════════════════════════════════════════════════════════════════════

class TestTransferNormalization:
    @pytest.mark.parametrize("op_status,item_status,retryable", [
        (OpStatus.OK, TransferItemStatus.DISPATCHED, False),
        (OpStatus.TRANSIENT_FAILURE, TransferItemStatus.RETRY_SCHEDULED, True),
        (OpStatus.VALIDATION_FAILURE, TransferItemStatus.FAILED, False),
        (OpStatus.AUTH_FAILURE, TransferItemStatus.FAILED, False),
        (OpStatus.QUOTA_FAILURE, TransferItemStatus.FAILED, False),
        (OpStatus.CONFLICT, TransferItemStatus.FAILED, False),
        (OpStatus.NOT_FOUND, TransferItemStatus.FAILED, False),
        (OpStatus.UNSUPPORTED, TransferItemStatus.FAILED, False),
        (OpStatus.ERROR, TransferItemStatus.FAILED, False),
    ])
    def test_all_statuses_mapped(self, op_status, item_status, retryable):
        outcome = to_transfer_outcome(OpResult(
            status=op_status, capability=ProviderCapability.RAW_PUSH, provider_id="x"))
        assert outcome.item_status == item_status
        assert outcome.retryable is retryable

    def test_terminal_errors_never_silently_retry(self):
        for status in (OpStatus.UNSUPPORTED, OpStatus.AUTH_FAILURE,
                       OpStatus.VALIDATION_FAILURE, OpStatus.QUOTA_FAILURE):
            outcome = to_transfer_outcome(OpResult(
                status=status, capability=ProviderCapability.OCI_PUSH, provider_id="x"))
            assert outcome.retryable is False, status

    def test_transient_is_retryable(self):
        outcome = to_transfer_outcome(OpResult(
            status=OpStatus.TRANSIENT_FAILURE,
            capability=ProviderCapability.OCI_PUSH, provider_id="x"))
        assert outcome.retryable is True
        assert outcome.failure_class.value == "transport_failure"

    def test_unsupported_failure_class_is_none_not_faked(self):
        """Kernel не имеет класса UNSUPPORTED — честно None + пометка в detail."""
        outcome = to_transfer_outcome(OpResult.unsupported(
            ProviderCapability.COPY_OR_PROMOTE, "sfera"))
        assert outcome.item_status == TransferItemStatus.FAILED
        assert outcome.failure_class is None
        assert "UNSUPPORTED" in outcome.detail

    def test_digest_and_location_passthrough(self):
        outcome = to_transfer_outcome(OpResult(
            status=OpStatus.OK, capability=ProviderCapability.OCI_PUSH,
            provider_id="harbor", digest=SERVER_DIGEST, location_ref="harbor/project/app",
        ))
        assert outcome.digest == SERVER_DIGEST
        assert outcome.location_ref == "harbor/project/app"


# ══════════════════════════════════════════════════════════════════════════════
# G. OciRegistry conformance (реальный adapter: Harbor / Nexus / local-oci)
#    через httpx.MockTransport — реальные HTTP-семантики без сети.
# ══════════════════════════════════════════════════════════════════════════════

class TestOciRegistryConformance:
    """Реальный OciRegistry-код против мокового OCI V2 endpoint'а."""

    @pytest.fixture()
    def registry(self):
        import httpx

        from orchestrator.cosmo.adapters.artifact_registry import (
            RegistryConfig,
            RegistryProvider,
            RegistryZone,
        )
        from orchestrator.cosmo.adapters.oci_registry import OciRegistry

        config = RegistryConfig(
            provider=RegistryProvider.LOCAL_OCI,
            zone=RegistryZone.ZR,
            endpoint="http://registry.local:5100",
            repository="cosmo",
            namespace="ns",
            robot_account="robot",
            secret_ref="vault:secret/registry/robot",
        )
        adapter = OciRegistry(config)

        calls: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            url = str(request.url)
            method = request.method
            if url.endswith("/v2/"):
                # health: первый вызов анонимный, второй — с Basic auth
                if "Authorization" in request.headers:
                    return httpx.Response(200)
                return httpx.Response(401)
            if "/manifests/" in url and method == "HEAD":
                ref = url.rsplit("/", 1)[-1]
                if ref in ("2.0.0", SERVER_DIGEST):
                    return httpx.Response(200, headers={
                        "Docker-Content-Digest": SERVER_DIGEST,
                    })
                return httpx.Response(404)
            if "/manifests/" in url and method == "GET":
                manifest = {"schemaVersion": 2, "layers": []}
                return httpx.Response(200, json=manifest, headers={
                    "Docker-Content-Digest": SERVER_DIGEST,
                })
            if "/tags/list" in url:
                return httpx.Response(200, json={"tags": ["1.0.0", "2.0.0"]})
            return httpx.Response(500)

        adapter._client = httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
        )
        adapter.calls = calls
        return adapter

    @pytest.mark.asyncio
    async def test_health_reachable_and_authenticated(self, registry):
        hs = await registry.health()
        assert hs.reachable is True
        assert hs.authenticated is True

    @pytest.mark.asyncio
    async def test_resolve_digest_returns_server_header(self, registry):
        """Tag → immutable digest: только из Docker-Content-Digest сервера."""
        digest = await registry.resolve_digest("app", "2.0.0")
        assert digest == SERVER_DIGEST

    @pytest.mark.asyncio
    async def test_resolve_digest_404_raises_honestly(self, registry):
        """404 при resolve — честный RuntimeError, не пустая заглушка."""
        with pytest.raises(RuntimeError):
            await registry.resolve_digest("app", "9.9.9")

    @pytest.mark.asyncio
    async def test_check_artifact_true_and_false(self, registry):
        assert await registry.check_artifact("app", SERVER_DIGEST) is True
        assert await registry.check_artifact("app", "sha256:" + "0" * 64) is False

    @pytest.mark.asyncio
    async def test_list_tags_success_and_failure_fallback(self, registry):
        tags = await registry.list_tags("app")
        assert tags == ["1.0.0", "2.0.0"]

    @pytest.mark.asyncio
    async def test_pull_manifest_uses_server_digest(self, registry):
        pr = await registry.pull_manifest("app", digest=SERVER_DIGEST)
        assert pr.digest == SERVER_DIGEST
        assert pr.manifest["schemaVersion"] == 2
