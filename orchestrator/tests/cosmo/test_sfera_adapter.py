# -*- coding: utf-8 -*-
"""
COS-051: SferaProviderAdapter contract tests — БЕЗ live Sfera.

Проверяет:
  - adapter импортируется и работает offline (transport seam, никаких сетей);
  - raw push/pull через <repo_url>/raw/... (легаси evidence);
  - OCI push (blobs + manifest через /v2/) и pull (manifest/blob);
  - digest сохраняется как вернул сервер; без server digest — computed с меткой;
  - provisioning: без подтверждённого OpenAPI маршрута → честный UNSUPPORTED;
  - unsupported ops (exists/resolve/promote/quota) → UNSUPPORTED, не fake success;
  - transport failure → TRANSIENT_FAILURE (retryable), не success;
  - auth failure / quota / 404 → корректные категории;
  - provider-specific location_ref не является canonical identity;
  - capability report соответствует evidence (не выдуманные DOCUMENTED);
  - COS-069: auth split push=Basic/pull=Bearer, клиентский push-digest,
    naming {code|-dirty|-raw|-docs}, ALREADY_EXISTS idempotent-семантика,
    legacy timeout-профиль, micro-PR матрицы (contract map §2–§8).
"""
from __future__ import annotations

import pytest

from orchestrator.cosmo.adapters.sfera_provider import (
    CORE_BASE,
    PROVIDER_ID,
    SferaProviderAdapter,
    SferaProviderConfig,
    TransportFailure,
    TransportResponse,
)
from orchestrator.cosmo.adapters.fake_providers import (
    FakeSferaTransport,
    _ScriptedResponse,
    sha256_of,
)
from orchestrator.cosmo.adapters.provider_capability import (
    CapabilityStatus,
    OpStatus,
    ProviderCapability,
)


BASE = "https://sfera.apps.example.cbr.ru"
RAW_BASE = "https://sfera.apps.example.cbr.ru/repo-storage"


def make_adapter(fail_routes: bool = False) -> tuple[SferaProviderAdapter, FakeSferaTransport]:
    transport = FakeSferaTransport()
    config = SferaProviderConfig(
        base_url=BASE,
        raw_repo_base_url=RAW_BASE,
        secret_ref="vault:secret/sfera/service-account",
        token_provider=None,  # anonymous для контрактов; auth тестируется отдельно
    )
    adapter = SferaProviderAdapter(config, transport=transport)
    return adapter, transport


# ══════════════════════════════════════════════════════════════════════════════
# Offline import & capability report
# ══════════════════════════════════════════════════════════════════════════════

def test_adapter_imports_without_live_sfera():
    adapter, _ = make_adapter()
    assert adapter.provider_id == "sfera"
    report = adapter.capability_report()
    assert report.provider_id == "sfera"
    # Не выдуманные статусы:
    assert report.get(ProviderCapability.OCI_PUSH).status == CapabilityStatus.DOCUMENTED
    assert report.get(ProviderCapability.EXISTS).status == CapabilityStatus.UNKNOWN
    assert report.get(ProviderCapability.QUOTA_REPORT).status == CapabilityStatus.UNKNOWN


def test_require_unsupported_raises():
    adapter, _ = make_adapter()
    from orchestrator.cosmo.adapters.provider_capability import UnsupportedCapabilityError
    with pytest.raises(UnsupportedCapabilityError):
        adapter.require(ProviderCapability.EXISTS)


# ══════════════════════════════════════════════════════════════════════════════
# Raw push/pull (evidence: PUT <repo_url>/raw/<repo>/<path>)
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_raw_push_success_preserves_digest():
    adapter, transport = make_adapter()
    payload = b"release metadata envelope bytes"
    transport.expect("PUT", f"{RAW_BASE}/", _ScriptedResponse(
        status_code=201,
        headers={"ETag": f'"{sha256_of(payload)}"'},
    ))
    r = await adapter.op_push("releases/rel-1/metadata.json", payload)
    assert r.status == OpStatus.OK
    assert r.location_ref == "releases/rel-1/metadata.json"
    assert r.raw["http_status"] == 201
    # Вызов ушёл на подтверждённый путь (PUT raw):
    put_calls = [c for c in transport.calls if c["method"] == "PUT"]
    assert len(put_calls) == 1
    assert put_calls[0]["url"].startswith(RAW_BASE)
    assert put_calls[0]["data"] == payload


@pytest.mark.asyncio
async def test_raw_push_computes_digest_when_server_silent():
    """Сервер не вернул digest → считаем sha256 payload и помечаем источник."""
    adapter, transport = make_adapter()
    payload = b"no etag from server"
    transport.expect("PUT", f"{RAW_BASE}/", _ScriptedResponse(status_code=201))
    r = await adapter.op_push("releases/rel-2/bundle.git", payload)
    assert r.status == OpStatus.OK
    assert r.digest == sha256_of(payload)
    assert r.raw["digest_source"] == "computed_payload"


@pytest.mark.asyncio
async def test_raw_pull_success():
    adapter, transport = make_adapter()
    body = b"git bundle content"
    transport.expect("GET", f"{RAW_BASE}/releases/rel-1/", _ScriptedResponse(
        status_code=200, body=body,
    ))
    r = await adapter.op_pull("releases/rel-1/bundle.git")
    assert r.status == OpStatus.OK
    assert r.raw["body"] == body
    assert r.raw["body_bytes"] == len(body)


@pytest.mark.asyncio
async def test_raw_pull_404_is_not_found_not_error():
    adapter, transport = make_adapter()
    transport.expect("GET", f"{RAW_BASE}/", _ScriptedResponse(status_code=404))
    r = await adapter.op_pull("releases/missing.git")
    assert r.status == OpStatus.NOT_FOUND
    assert r.ok is False


# ══════════════════════════════════════════════════════════════════════════════
# OCI push/pull (evidence: BinaryPusher / BinaryFetcher, /v2/)
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_oci_push_digest_computed_client_side_server_header_recorded():
    """COS-069 (contract map §4, pusher:120–121): digest манифеста считается
    КЛИЕНТОМ; серверный Docker-Content-Digest — не identity, а сверочный факт
    в raw["server_digest_header"] (live-профиль сверяет, COS-049)."""
    adapter, transport = make_adapter()
    layer = b"layer-bytes"
    digest = sha256_of(layer)
    manifest = {"schemaVersion": 2, "layers": [{"digest": digest, "size": len(layer)}]}
    manifest_bytes = __import__("json").dumps(manifest, sort_keys=True).encode()
    client_digest = sha256_of(manifest_bytes)
    bogus_server = "sha256:" + "f" * 64   # сервер «не согласен» — identity всё равно клиентская

    transport.expect("POST", f"{BASE}/v2/app/blobs/uploads/", _ScriptedResponse(
        status_code=202, headers={"Location": f"{BASE}/v2/app/blobs/uploads/upload-1"},
    ))
    transport.expect("PUT", f"{BASE}/v2/app/blobs/uploads/upload-1", _ScriptedResponse(
        status_code=201, headers={"Docker-Content-Digest": digest},
    ))
    transport.expect("PUT", f"{BASE}/v2/app/manifests/", _ScriptedResponse(
        status_code=201, headers={"Docker-Content-Digest": bogus_server},
    ))

    r = await adapter.oci_push("app", "1.0.0", manifest, blobs=[(digest, layer)])
    assert r.status == OpStatus.OK
    assert r.digest == client_digest                      # клиентский sha256 — identity
    assert r.raw["digest_source"] == "computed_payload"
    assert r.raw["server_digest_header"] == bogus_server  # сервер записан, не использован
    assert r.location_ref == "app:1.0.0"
    # blob PUT должен содержать digest query (OCI spec):
    blob_put = [c for c in transport.calls
                if c["method"] == "PUT" and "blobs/uploads" in c["url"]]
    assert len(blob_put) == 1
    assert f"digest={digest}" in blob_put[0]["url"]


@pytest.mark.asyncio
async def test_oci_pull_manifest_with_digest():
    adapter, transport = make_adapter()
    manifest = {"schemaVersion": 2, "config": {}}
    body = __import__("json").dumps(manifest).encode()
    transport.expect("GET", f"{BASE}/v2/app/manifests/", _ScriptedResponse(
        status_code=200, body=body,
        headers={"Docker-Content-Digest": sha256_of(body),
                 "Content-Type": "application/vnd.oci.image.manifest.v1+json"},
    ))
    r = await adapter.oci_pull("app", "1.0.0")
    assert r.status == OpStatus.OK
    assert r.digest == sha256_of(body)
    assert r.raw["manifest"]["schemaVersion"] == 2


@pytest.mark.asyncio
async def test_oci_blob_pull():
    adapter, transport = make_adapter()
    layer = b"blob-content"
    transport.expect("GET", f"{BASE}/v2/app/blobs/", _ScriptedResponse(
        status_code=200, body=layer,
    ))
    r = await adapter.oci_blob_pull("app", sha256_of(layer))
    assert r.status == OpStatus.OK
    assert r.raw["body"] == layer


@pytest.mark.asyncio
async def test_oci_push_fails_when_blob_upload_rejected():
    """Ошибка blob upload → НЕ manifest PUT, честный failure (не partial success)."""
    adapter, transport = make_adapter()
    transport.expect("POST", f"{BASE}/v2/app/blobs/uploads/", _ScriptedResponse(
        status_code=503,
    ))
    r = await adapter.oci_push("app", "1.0.0", {"schemaVersion": 2},
                               blobs=[(sha256_of(b"x"), b"x")])
    assert r.status == OpStatus.TRANSIENT_FAILURE
    # manifest не отправлялся — ошибка не маскируется под успех:
    assert not any(c["url"].endswith("/manifests/1.0.0") for c in transport.calls)


# ══════════════════════════════════════════════════════════════════════════════
# Provisioning: без подтверждённого OpenAPI — честный UNSUPPORTED
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_provision_area_unsupported_without_confirmed_endpoint():
    """Не выдумываем endpoint: нет подтверждённого маршрута → UNSUPPORTED."""
    adapter, transport = make_adapter()
    r = await adapter.provision_area("area-key-1", "Project Area")
    assert r.status == OpStatus.UNSUPPORTED
    assert "OpenAPI" in r.detail
    assert transport.calls == []  # ни один HTTP вызов не сделан


@pytest.mark.asyncio
async def test_provision_area_works_when_endpoint_confirmed():
    """Когда маршрут подтверждён (конфиг) — операция выполняется через CORE base."""
    adapter, transport = make_adapter()
    adapter.config.areas_path = "/areas"  # гипотетическое подтверждение OpenAPI
    transport.expect("POST", f"{BASE}{CORE_BASE}/areas", _ScriptedResponse(
        status_code=201, json={"key": "area-key-1"},
    ))
    r = await adapter.provision_area("area-key-1", "Project Area")
    assert r.status == OpStatus.OK
    assert r.location_ref == "area:area-key-1"
    assert transport.calls[0]["url"].startswith(f"{BASE}{CORE_BASE}")


@pytest.mark.asyncio
async def test_provision_repository_unsupported_without_confirmed_endpoint():
    adapter, _ = make_adapter()
    r = await adapter.provision_repository(
        "raw-releases", area_key="a-1", repo_format="raw")
    assert r.status == OpStatus.UNSUPPORTED


# ══════════════════════════════════════════════════════════════════════════════
# Честные unsupported и failure категории
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_exists_resolve_promote_quota_are_unsupported():
    adapter, _ = make_adapter()
    assert (await adapter.op_exists("x")).status == OpStatus.UNSUPPORTED
    assert (await adapter.resolve_digest("app", "1.0.0")).status == OpStatus.UNSUPPORTED
    assert (await adapter.copy_or_promote("app:1.0.0", "repo-2")).status == OpStatus.UNSUPPORTED
    assert (await adapter.quota_report()).status == OpStatus.UNSUPPORTED


@pytest.mark.asyncio
async def test_transport_failure_is_transient_not_success():
    """Ошибка provider не маскируется под transfer success."""
    adapter, transport = make_adapter()
    transport.fail_on("PUT", RAW_BASE)
    r = await adapter.op_push("releases/rel-1/metadata.json", b"data")
    assert r.status == OpStatus.TRANSIENT_FAILURE
    assert r.ok is False
    assert r.error_category.value == "retryable"


@pytest.mark.asyncio
async def test_health_reports_reachable_without_auth():
    adapter, transport = make_adapter()
    transport.expect("GET", f"{BASE}/v2/", _ScriptedResponse(status_code=200))
    r = await adapter.op_health()
    assert r.status == OpStatus.OK
    assert r.raw["reachable"] is True
    assert r.raw["auth_configured"] is False


@pytest.mark.asyncio
async def test_health_401_means_reachable_but_unauthenticated():
    adapter, transport = make_adapter()
    transport.expect("GET", f"{BASE}/v2/", _ScriptedResponse(status_code=401))
    r = await adapter.op_health()
    assert r.status == OpStatus.OK
    assert r.raw["reachable"] is True
    assert r.raw["auth_configured"] is False


@pytest.mark.asyncio
async def test_health_with_token_provider_uses_bearer():
    adapter, transport = make_adapter()

    async def token() -> str:
        return "secret-token-value"

    adapter.config.token_provider = token
    transport.expect("GET", f"{BASE}/v2/", _ScriptedResponse(status_code=200))
    r = await adapter.op_health()
    assert r.status == OpStatus.OK
    assert r.raw["authenticated"] is True
    health_calls = [c for c in transport.calls if c["method"] == "GET"]
    assert health_calls[-1]["headers"]["Authorization"] == "Bearer secret-token-value"


@pytest.mark.asyncio
async def test_no_transport_is_honest_transient():
    """Adapter без транспорта — offline seam: честный transient, не success."""
    config = SferaProviderConfig(base_url=BASE)
    adapter = SferaProviderAdapter(config, transport=None)
    r = await adapter.op_health()
    assert r.status == OpStatus.TRANSIENT_FAILURE
    assert r.ok is False


# ══════════════════════════════════════════════════════════════════════════════
# COS-060: полный failure-status battery на реальном adapter-коде
# ══════════════════════════════════════════════════════════════════════════════

class TestFailureStatusSemantics:
    """Каждый HTTP-ответ маппится в честный OpStatus — через настоящий adapter."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("http_status,expected", [
        (401, OpStatus.AUTH_FAILURE),
        (403, OpStatus.AUTH_FAILURE),
        (404, OpStatus.NOT_FOUND),
        (409, OpStatus.CONFLICT),
        (413, OpStatus.QUOTA_FAILURE),
        (507, OpStatus.QUOTA_FAILURE),
        (422, OpStatus.VALIDATION_FAILURE),
        (500, OpStatus.TRANSIENT_FAILURE),
        (503, OpStatus.TRANSIENT_FAILURE),
    ])
    async def test_raw_push_status_mapping(self, http_status, expected):
        adapter, transport = make_adapter()
        transport.expect("PUT", f"{RAW_BASE}/", _ScriptedResponse(status_code=http_status))
        r = await adapter.op_push("releases/rel-1/metadata.json", b"payload")
        assert r.status == expected
        assert r.ok is False
        if expected in (OpStatus.AUTH_FAILURE, OpStatus.QUOTA_FAILURE,
                        OpStatus.VALIDATION_FAILURE, OpStatus.CONFLICT):
            assert r.error_category.value == "terminal"

    @pytest.mark.asyncio
    async def test_oci_pull_404_is_not_found(self):
        adapter, transport = make_adapter()
        transport.expect("GET", f"{BASE}/v2/app/manifests/", _ScriptedResponse(status_code=404))
        r = await adapter.oci_pull("app", "0.0.1")
        assert r.status == OpStatus.NOT_FOUND
        assert r.ok is False

    @pytest.mark.asyncio
    async def test_oci_pull_500_is_transient(self):
        adapter, transport = make_adapter()
        transport.expect("GET", f"{BASE}/v2/app/manifests/", _ScriptedResponse(status_code=500))
        r = await adapter.oci_pull("app", "1.0.0")
        assert r.status == OpStatus.TRANSIENT_FAILURE
        assert r.error_category.value == "retryable"

    @pytest.mark.asyncio
    async def test_raw_pull_missing_digest_is_not_fake_confirmation(self):
        """200 без digest-заголовков у pull: server digest отсутствует; если
        adapter вычислил sha256 от body — он ЯВНО помечен computed_payload
        и не выдаётся за server-подтверждение целостности."""
        adapter, transport = make_adapter()
        transport.expect("GET", f"{RAW_BASE}/", _ScriptedResponse(
            status_code=200, body=b"bytes without any digest header",
        ))
        r = await adapter.op_pull("releases/rel-1/bundle.git")
        assert r.status == OpStatus.OK
        assert r.raw.get("digest_source") == "computed_payload"  # помечен, не fake
        assert r.digest.startswith("sha256:")

    @pytest.mark.asyncio
    async def test_raw_push_401_with_token_provider(self):
        """Bearer auth: 401 на authed-запрос → AUTH_FAILURE, токен не логируется."""
        adapter, transport = make_adapter()

        async def token() -> str:
            return "super-secret-token-value"

        adapter.config.token_provider = token
        transport.expect("PUT", f"{RAW_BASE}/", _ScriptedResponse(status_code=401))
        r = await adapter.op_push("releases/rel-1/metadata.json", b"payload")
        assert r.status == OpStatus.AUTH_FAILURE
        # токен был отправлен, но не попал в результат/логи adapter'а:
        assert "super-secret-token-value" not in str(r.raw)
        assert "super-secret-token-value" not in r.detail


# ══════════════════════════════════════════════════════════════════════════════
# SOD boundary: Sfera artifact provider ≠ SOD transport
# ══════════════════════════════════════════════════════════════════════════════

def test_sfera_adapter_is_not_transfer_kernel_sod_seam():
    """SferaProviderAdapter не реализует SODTransferAdapter seam — границы раздельные."""
    from orchestrator.cosmo.transfer.contract import SODTransferAdapter
    adapter, _ = make_adapter()
    assert not isinstance(adapter, SODTransferAdapter)


# ══════════════════════════════════════════════════════════════════════════════
# COS-069: offline alignment с legacy contract map
# (docs/research/2026-09-02-legacy-sfera-contract-map.md)
# ══════════════════════════════════════════════════════════════════════════════

class TestRegistryAuthSplit:
    """Registry push = Basic (binary_pusher.rb:51–57), pull = Bearer
    (binary_fetcher.rb:171–181). Split подтверждён на уровне заголовков."""

    @staticmethod
    def _attach_providers(adapter: SferaProviderAdapter) -> None:
        async def token() -> str:
            return "bearer-token-value"

        async def basic() -> tuple[str, str]:
            return ("svc-sfera", "basic-secret-value")

        adapter.config.token_provider = token
        adapter.config.basic_auth_provider = basic

    @pytest.mark.asyncio
    async def test_registry_push_uses_basic_not_bearer(self):
        import base64
        adapter, transport = make_adapter()
        self._attach_providers(adapter)
        transport.expect("POST", f"{BASE}/v2/app/blobs/uploads/", _ScriptedResponse(
            status_code=202, headers={"Location": f"{BASE}/v2/app/blobs/uploads/u1"},
        ))
        transport.expect("PUT", f"{BASE}/v2/app/blobs/uploads/u1", _ScriptedResponse(
            status_code=201,
        ))
        transport.expect("PUT", f"{BASE}/v2/app/manifests/", _ScriptedResponse(
            status_code=201,
        ))
        r = await adapter.oci_push("app", "1.0.0", {"schemaVersion": 2},
                                   blobs=[(sha256_of(b"x"), b"x")])
        assert r.status == OpStatus.OK
        expected_basic = "Basic " + base64.b64encode(
            b"svc-sfera:basic-secret-value").decode("ascii")
        registry_calls = [c for c in transport.calls if "/v2/" in c["url"]]
        assert len(registry_calls) == 3  # POST upload, PUT blob, PUT manifest
        for c in registry_calls:
            assert c["headers"].get("Authorization") == expected_basic
        assert r.raw["registry_auth_mode"] == "basic"

    @pytest.mark.asyncio
    async def test_registry_push_fallback_to_bearer_is_visible_in_raw(self):
        """Без basic_auth_provider push падает обратно на Bearer — fallback
        НЕ маскируется: режим честно фиксируется в raw["registry_auth_mode"]."""
        adapter, transport = make_adapter()

        async def token() -> str:
            return "bearer-token-value"

        adapter.config.token_provider = token
        transport.expect("POST", f"{BASE}/v2/app/blobs/uploads/", _ScriptedResponse(
            status_code=202, headers={"Location": f"{BASE}/v2/app/blobs/uploads/u1"},
        ))
        transport.expect("PUT", f"{BASE}/v2/app/manifests/", _ScriptedResponse(
            status_code=201,
        ))
        r = await adapter.oci_push("app", "1.0.0", {"schemaVersion": 2})
        assert r.status == OpStatus.OK
        assert r.raw["registry_auth_mode"] == "bearer"
        manifest_put = [c for c in transport.calls if c["url"].endswith("/manifests/1.0.0")][0]
        assert manifest_put["headers"]["Authorization"] == "Bearer bearer-token-value"

    @pytest.mark.asyncio
    async def test_registry_pull_uses_bearer_not_basic(self):
        adapter, transport = make_adapter()
        self._attach_providers(adapter)
        body = b'{"schemaVersion": 2}'
        transport.expect("GET", f"{BASE}/v2/app/manifests/", _ScriptedResponse(
            status_code=200, body=body,
            headers={"Docker-Content-Digest": sha256_of(body)},
        ))
        transport.expect("GET", f"{BASE}/v2/app/blobs/", _ScriptedResponse(
            status_code=200, body=b"blob",
        ))
        r1 = await adapter.oci_pull("app", "1.0.0")
        r2 = await adapter.oci_blob_pull("app", sha256_of(b"blob"))
        assert r1.status == OpStatus.OK and r2.status == OpStatus.OK
        for c in [c for c in transport.calls if "/v2/" in c["url"]]:
            assert c["headers"].get("Authorization") == "Bearer bearer-token-value"
            assert not c["headers"].get("Authorization", "").startswith("Basic")


class TestLegacyContractAlignment:
    """Naming/options, ALREADY_EXISTS-семантика и таймаут-профиль — точная
    калька легаси-источников (sfera_repo_configurable.rb:8–50,
    establish_sfera.rb:125,160, client.rb:28–30, pusher:58–59)."""

    def test_repo_names_match_legacy_concern(self):
        from orchestrator.cosmo.adapters.sfera_provider import repo_name_for_project
        assert repo_name_for_project("myproj", "docker") == "myproj"
        assert repo_name_for_project("myproj", "dirty_docker") == "myproj-dirty"
        assert repo_name_for_project("myproj", "raw") == "myproj-raw"
        assert repo_name_for_project("myproj", "docs") == "myproj-docs"
        with pytest.raises(ValueError):
            repo_name_for_project("myproj", "npm")

    def test_repo_configs_match_legacy_concern(self):
        from orchestrator.cosmo.adapters.sfera_provider import repo_configs_for_project
        cfg = repo_configs_for_project("myproj")
        assert set(cfg) == {"docker", "dirty_docker", "raw", "docs"}
        assert cfg["docker"]["name"] == "myproj"
        assert cfg["dirty_docker"]["name"] == "myproj-dirty"
        assert cfg["raw"]["name"] == "myproj-raw"
        assert cfg["docs"]["name"] == "myproj-docs"
        # options — дословно из REPO_CONFIGS (concern:9–12):
        assert cfg["docker"]["options"] == {
            "validateChecksums": True, "artifactRewritePolicy": "PROHIBITED"}
        assert cfg["dirty_docker"]["options"] == {
            "validateChecksums": True, "artifactRewritePolicy": "ALLOWED_ALL"}
        assert cfg["raw"]["options"] == {"validateChecksums": True}
        assert cfg["docs"]["options"] == {"validateChecksums": True}
        # format/type раскладка (concern:9–12):
        assert cfg["docker"]["format"] == "docker" and cfg["docker"]["type"] == "hosted"
        assert cfg["dirty_docker"]["format"] == "docker"
        assert cfg["raw"]["format"] == "raw" and cfg["docs"]["format"] == "raw"

    @pytest.mark.asyncio
    async def test_provision_conflict_with_already_exists_is_idempotent_ok(self):
        """409 + ALREADY_EXISTS_ERROR → idempotent-успех (establish_sfera.rb:125)."""
        adapter, transport = make_adapter()
        adapter.config.areas_path = "/areas"
        transport.expect("POST", f"{BASE}{CORE_BASE}/areas", _ScriptedResponse(
            status_code=409, body=b'{"error": "ALREADY_EXISTS_ERROR"}',
        ))
        r = await adapter.provision_area("myproj", "My Project")
        assert r.status == OpStatus.OK
        assert r.raw["idempotent_already_exists"] is True
        assert r.raw["http_status"] == 409
        assert r.location_ref == "area:myproj"

    @pytest.mark.asyncio
    async def test_provision_conflict_other_body_is_honest_conflict(self):
        """409 БЕЗ already-exists маркера → CONFLICT, идемпотентность не выдумывается."""
        adapter, transport = make_adapter()
        adapter.config.repositories_path = "/repositories"
        transport.expect("POST", f"{BASE}{CORE_BASE}/repositories", _ScriptedResponse(
            status_code=409, body=b'{"error": "NAME_LOCKED_BY_GC"}',
        ))
        r = await adapter.provision_repository(
            "myproj-raw", area_key="cosmo", repo_format="raw")
        assert r.status == OpStatus.CONFLICT
        assert r.ok is False
        assert "idempotent_already_exists" not in r.raw

    @pytest.mark.asyncio
    async def test_provision_repository_text_body_already_exists_is_idempotent_ok(self):
        """Текстовое 'already exists' в body тоже трактуется как legacy-маркер."""
        adapter, transport = make_adapter()
        adapter.config.repositories_path = "/repositories"
        transport.expect("POST", f"{BASE}{CORE_BASE}/repositories", _ScriptedResponse(
            status_code=409, body=b"Repository 'myproj-raw' already exists",
        ))
        r = await adapter.provision_repository(
            "myproj-raw", area_key="cosmo", repo_format="raw")
        assert r.status == OpStatus.OK
        assert r.raw["idempotent_already_exists"] is True

    def test_legacy_timeout_profile_divergence_is_fixated(self):
        """Таймауты legacy зафиксированы константой; наш единый профиль
        расходится с upload/registry — расхождение документировано, не скрыто."""
        from orchestrator.cosmo.adapters.sfera_provider import LEGACY_TIMEOUT_PROFILE
        assert LEGACY_TIMEOUT_PROFILE == {
            "open_seconds": 10,            # client.rb:28
            "read_seconds": 30,            # client.rb:29
            "upload_read_seconds": 200,    # client.rb:30
            "registry_timeout_seconds": 3600,   # binary_pusher.rb:58
            "registry_open_seconds": 600,  # binary_pusher.rb:59
        }
        config = SferaProviderConfig(base_url=BASE)
        assert config.timeout_seconds == LEGACY_TIMEOUT_PROFILE["read_seconds"]
        # Расхождение честно видно: единый таймаут меньше legacy upload/registry.
        assert config.timeout_seconds < LEGACY_TIMEOUT_PROFILE["upload_read_seconds"]
        assert config.timeout_seconds < LEGACY_TIMEOUT_PROFILE["registry_timeout_seconds"]


class TestMatrixMicroPR:
    """COS-069 micro-PR матрицы: вердикты §8 contract map применены."""

    def _report(self):
        adapter, _ = make_adapter()
        return adapter.capability_report()

    def test_list_upgraded_to_documented_with_code_evidence(self):
        entry = self._report().get(ProviderCapability.LIST)
        assert entry.status == CapabilityStatus.DOCUMENTED
        assert "client.rb:123" in entry.doc_reference      # §3#6–8: tree routes
        assert "parentId" in entry.notes                   # пагинация подтверждена

    def test_get_checksum_note_flags_legacy_sha1_preference(self):
        entry = self._report().get(ProviderCapability.GET_CHECKSUM)
        assert entry.status == CapabilityStatus.DOCUMENTED
        assert "sha1" in entry.notes                       # §6: legacy prefers sha1

    def test_oci_notes_carry_auth_split_facts(self):
        report = self._report()
        assert "Basic" in report.get(ProviderCapability.OCI_PUSH).notes
        assert "Bearer" in report.get(ProviderCapability.OCI_PULL).notes

    def test_health_note_refines_evidence_per_contract_map(self):
        entry = self._report().get(ProviderCapability.HEALTH)
        assert entry.status == CapabilityStatus.DOCUMENTED
        assert "contract map" in entry.doc_reference or "contract-map" in entry.doc_reference
