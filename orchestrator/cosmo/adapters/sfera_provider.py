# -*- coding: utf-8 -*-
"""
COS-051: SferaProviderAdapter — optional external artifact provider seam.

Строго по evidence (docs/research/2026-09-01-sfera-openapi-and-registry-boundary.md §7.1):

  Подтверждённые легаси-операции (lib/sfera/client.rb, BinaryPusher/Fetcher):
    - POST /api/auth/login                          — bearer auth
    - CORE /app/ppdl/api/rest/core                  — create_area / create_repository / delete
    - PUT  <repo_url>/raw/<repo>/<path>             — raw upload
    - GET  raw tree/file download
    - /v2/...                                       — OCI blobs + manifest (push/pull)
    - Docker tree listing + checksum read (legacy)

  НЕ подтверждено (нужен OpenAPI export, карточка COS-049):
    repository exists/HEAD, tag→digest resolve, promotion/copy API,
    quotas, signatures/attestations, job/status lifecycle, pagination.

  Правило карточки: НЕ выдумывать отсутствующие Sfera endpoints.
  Операции с неподтверждённым маршрутом возвращают
  OpResult.unsupported(...) до получения подтверждённого контракта.

Границы:
  - Sfera artifact provider ≠ SOD transport (не смешивать);
  - provider-specific refs (area keys, repo paths) — НЕ PureK canonical identity;
    canonical identity — immutable digest (sha256) + PackageRevision;
  - credentials только через secret reference / token_provider, никаких plaintext.

COS-069 — offline alignment с legacy contract map
(docs/research/2026-09-02-legacy-sfera-contract-map.md):
  - registry auth split: push = Basic (binary_pusher.rb:51–57),
    pull = Bearer (binary_fetcher.rb:171–181);
  - OCI push digest считается КЛИЕНТОМ (sha256 payload, pusher:120–121),
    серверный Docker-Content-Digest в push-пути не identity, а записывается
    в raw["server_digest_header"] для сверки на live (COS-049);
  - naming репо {code}|{code}-dirty|{code}-raw|{code}-docs и options —
    точная калька REPO_CONFIGS (sfera_repo_configurable.rb:8–50);
  - 409 + ALREADY_EXISTS_ERROR/"already exists" в provisioning →
    idempotent-успех (establish_sfera.rb:125,160);
  - таймаут-профиль legacy зафиксирован константой LEGACY_TIMEOUT_PROFILE
    (client.rb:28–30, pusher:58–59) — наш единый timeout_seconds=30.0
    расходится с upload/registry-профилем; live-профиль отдельная задача.
"""
from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional, Union

from orchestrator.cosmo.adapters.provider_capability import (
    CapabilityReport,
    CapabilityProvider,
    OpResult,
    OpStatus,
    ProviderCapability,
)
from orchestrator.cosmo.adapters.provider_matrices import sfera_matrix

PROVIDER_ID = "sfera"

# Подтверждённые base paths (research §7.1)
AUTH_LOGIN_PATH = "/api/auth/login"
REST_BASE = "/app/ppdl/api/rest"
CORE_BASE = REST_BASE + "/core"
SECURITY_BASE = REST_BASE + "/security-service/v1"

# ── COS-069: legacy-константы из contract map (каждая — файл:строка) ────────

# Точная калька REPO_CONFIGS (sfera_repo_configurable.rb:8–13).
SFERA_REPO_KINDS: dict[str, dict[str, Any]] = {
    "docker": {"format": "docker", "type": "hosted",
               "options": {"validateChecksums": True,
                           "artifactRewritePolicy": "PROHIBITED"}},
    "dirty_docker": {"format": "docker", "type": "hosted",
                     "options": {"validateChecksums": True,
                                 "artifactRewritePolicy": "ALLOWED_ALL"}},
    "raw": {"format": "raw", "type": "hosted",
            "options": {"validateChecksums": True}},
    "docs": {"format": "raw", "type": "hosted",
             "options": {"validateChecksums": True}},
}

# repo_name(project, kind) — sfera_repo_configurable.rb:40–50.
REPO_NAME_SUFFIX: dict[str, str] = {
    "docker": "", "dirty_docker": "-dirty", "raw": "-raw", "docs": "-docs",
}


def repo_name_for_project(project_code: str, kind: str) -> str:
    """Легаси naming: {code} | {code}-dirty | {code}-raw | {code}-docs."""
    if kind not in REPO_NAME_SUFFIX:
        raise ValueError(f"Kind '{kind}' is not supported")
    return f"{project_code}{REPO_NAME_SUFFIX[kind]}"


def repo_configs_for_project(project_code: str) -> dict[str, dict[str, Any]]:
    """Все 4 репо-конфига с легаси naming и options (concern:23–35)."""
    out: dict[str, dict[str, Any]] = {}
    for kind, cfg in SFERA_REPO_KINDS.items():
        out[kind] = {**cfg, "name": repo_name_for_project(project_code, kind)}
    return out


# Таймауты legacy (contract map §2: client.rb:28–30, binary_pusher.rb:58–59).
# Расхождение с нашими едиными timeout_seconds=30.0 зафиксировано честно:
# upload- и registry-профили в adapter пока НЕ смоделированы (live-gate COS-049).
LEGACY_TIMEOUT_PROFILE: dict[str, int] = {
    "open_seconds": 10,
    "read_seconds": 30,
    "upload_read_seconds": 200,
    "registry_timeout_seconds": 3600,
    "registry_open_seconds": 600,
}

# ── Transport seam ──────────────────────────────────────────────────────────

SferaTransport = Callable[[str, str, dict[str, Any], Optional[bytes]],
                          Awaitable["TransportResponse"]]


@dataclass
class TransportResponse:
    """Минимальный HTTP-ответ для transport seam (httpx-agnostic)."""
    status_code: int
    headers: dict[str, str] = field(default_factory=dict)
    body: bytes = b""
    json: Optional[Any] = None

    def json_or_empty(self) -> Any:
        if self.json is not None:
            return self.json
        import json as _json
        try:
            return _json.loads(self.body.decode("utf-8")) if self.body else {}
        except Exception:
            return {}


class TransportFailure(Exception):
    """Сетевой/транспортный сбой → TRANSIENT_FAILURE (retryable), не success."""


@dataclass
class SferaProviderConfig:
    """Конфиг Sfera adapter. Секреты — только через token_provider/secret_ref."""
    base_url: str                                   # https://sfera.apps...
    secret_ref: str = ""                            # vault:secret/... (аудит-ссылка, не секрет)
    token_provider: Optional[Callable[[], Awaitable[str]]] = None

    # COS-069: registry push = Basic auth (binary_pusher.rb:51–57).
    # Провайдер возвращает (username, password); секреты — только через callable,
    # никаких plaintext. Если не задан → push-путь падает обратно на Bearer/anonymous
    # (fallback виден в raw["registry_auth_mode"], live-gate обязан выставить Basic).
    basic_auth_provider: Optional[Callable[[], Awaitable[tuple[str, str]]]] = None

    # Raw repositories: PUT <raw_repo_base>/<repo>/<path> — задаётся per-repo
    raw_repo_base_url: str = ""

    # Точные маршруты внутри CORE API НЕ подтверждены легаси-процитированием:
    # пока нет OpenAPI — None → операции честно возвращают UNSUPPORTED.
    areas_path: Optional[str] = None                # e.g. '/areas' — требуется подтверждение
    repositories_path: Optional[str] = None         # e.g. '/repositories' — требуется подтверждение

    # COS-060: TLS/mTLS configuration seam (верификация до сетевых операций)
    tls: Optional[Any] = None                       # TLSConfig (adapters/tls_config.py)

    timeout_seconds: float = 30.0
    tls_verify: bool = True

    def full_url(self, path: str) -> str:
        return f"{self.base_url.rstrip('/')}/{path.lstrip('/')}"


# ── Adapter ─────────────────────────────────────────────────────────────────

class SferaProviderAdapter(CapabilityProvider):
    """Optional Sfera/ДиБ artifact provider: provisioning, raw, OCI.

    Импортируется и тестируется БЕЗ live Sfera: транспорт инжектируется
    (SferaTransport). По умолчанию транспорт не задан → все сетевые
    операции возвращают TRANSIENT/UNSUPPORTED честно, не крашатся.
    """

    def __init__(
        self,
        config: SferaProviderConfig,
        transport: Optional[SferaTransport] = None,
        matrix: Optional[CapabilityReport] = None,
    ) -> None:
        self.config = config
        self._transport = transport
        self._matrix = matrix or sfera_matrix()

    # ── CapabilityProvider contract ────────────────────────────────

    @property
    def provider_id(self) -> str:
        return PROVIDER_ID

    def capability_report(self) -> CapabilityReport:
        return self._matrix

    # ── Внутреннее ─────────────────────────────────────────────────

    def _resolve_auth_mode(self, auth: Union[bool, str]) -> str:
        """Фактический режим авторизации по конфигу — без сетевого вызова.

        "basic" (registry push) требует basic_auth_provider; без него —
        документированный fallback на Bearer/anonymous, видимый в raw.
        """
        if auth == "basic":
            if self.config.basic_auth_provider is not None:
                return "basic"
            return "bearer" if self.config.token_provider is not None else "anonymous"
        if auth:
            return "bearer" if self.config.token_provider is not None else "anonymous"
        return "anonymous"

    async def _request(
        self,
        method: str,
        path_or_url: str,
        *,
        headers: Optional[dict[str, str]] = None,
        data: Optional[bytes] = None,
        auth: Union[bool, str] = True,
    ) -> TransportResponse:
        if self._transport is None:
            raise TransportFailure("no transport configured (offline seam)")
        hdrs: dict[str, str] = dict(headers or {})
        mode = self._resolve_auth_mode(auth)
        if mode == "basic":
            username, password = await self.config.basic_auth_provider()  # type: ignore[misc]
            cred = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
            hdrs["Authorization"] = f"Basic {cred}"
        elif mode == "bearer":
            token = await self.config.token_provider()  # type: ignore[misc]
            hdrs["Authorization"] = f"Bearer {token}"
        url = self.config.full_url(path_or_url) if not path_or_url.startswith("http") else path_or_url
        resp = await self._transport(method, url, hdrs, data)
        # Нормализация: транспорт может вернуть любой объект с интерфейсом
        # TransportResponse (httpx-agnostic); приводим к TransportResponse.
        if isinstance(resp, TransportResponse):
            return resp
        return TransportResponse(
            status_code=resp.status_code,
            headers=dict(resp.headers or {}),
            body=resp.body or b"",
            json=getattr(resp, "json", None),
        )

    @staticmethod
    def _body_indicates_already_exists(resp: TransportResponse) -> bool:
        """Легаси-ошибка ALREADY_EXISTS_ERROR / 'already exists'
        (contract map §3, establish_sfera.rb:125,160)."""
        text = (resp.body or b"").decode("utf-8", "replace")
        if resp.json is not None:
            import json as _json
            try:
                text += " " + _json.dumps(resp.json, ensure_ascii=False)
            except Exception:
                pass
        lowered = text.lower()
        return "already_exists" in lowered or "already exists" in lowered

    @staticmethod
    def _result_from_response(
        capability: ProviderCapability,
        resp: TransportResponse,
        *,
        location_ref: Optional[str] = None,
        payload: Optional[bytes] = None,
        idempotent_conflict: bool = False,
    ) -> OpResult:
        """Честный маппинг HTTP → OpResult. Digest — как вернул сервер.

        idempotent_conflict=True (только provisioning): 409 c
        ALREADY_EXISTS_ERROR/'already exists' → idempotent-успех, как в
        legacy-оркестрации; 409 с другим телом остаётся CONFLICT.
        """
        if 200 <= resp.status_code < 300:
            digest = (resp.headers.get("Docker-Content-Digest")
                      or resp.headers.get("ETag") or None)
            if digest:
                digest = digest.strip('"')  # ETag приходит в кавычках
            digest_source = "server"
            if digest is None and payload is not None:
                digest = "sha256:" + hashlib.sha256(payload).hexdigest()
                digest_source = "computed_payload"
            raw: dict[str, Any] = {"http_status": resp.status_code}
            if digest is not None:
                raw["digest_source"] = digest_source
            return OpResult(
                status=OpStatus.OK,
                capability=capability,
                provider_id=PROVIDER_ID,
                digest=digest,
                location_ref=location_ref,
                raw=raw,
            )
        if resp.status_code in (401, 403):
            return OpResult(status=OpStatus.AUTH_FAILURE, capability=capability,
                            provider_id=PROVIDER_ID, detail=f"HTTP {resp.status_code}")
        if resp.status_code == 404:
            return OpResult(status=OpStatus.NOT_FOUND, capability=capability,
                            provider_id=PROVIDER_ID, detail="HTTP 404")
        if resp.status_code == 409:
            if idempotent_conflict and SferaProviderAdapter._body_indicates_already_exists(resp):
                return OpResult(
                    status=OpStatus.OK,
                    capability=capability,
                    provider_id=PROVIDER_ID,
                    location_ref=location_ref,
                    raw={"http_status": 409, "idempotent_already_exists": True},
                )
            return OpResult(status=OpStatus.CONFLICT, capability=capability,
                            provider_id=PROVIDER_ID, detail="HTTP 409")
        if resp.status_code == 413 or resp.status_code == 507:
            return OpResult(status=OpStatus.QUOTA_FAILURE, capability=capability,
                            provider_id=PROVIDER_ID, detail=f"HTTP {resp.status_code}")
        if resp.status_code == 422:
            return OpResult(status=OpStatus.VALIDATION_FAILURE, capability=capability,
                            provider_id=PROVIDER_ID, detail="HTTP 422")
        if resp.status_code >= 500:
            return OpResult(status=OpStatus.TRANSIENT_FAILURE, capability=capability,
                            provider_id=PROVIDER_ID, detail=f"HTTP {resp.status_code}")
        return OpResult(status=OpStatus.ERROR, capability=capability,
                        provider_id=PROVIDER_ID, detail=f"HTTP {resp.status_code}")

    # ── Health (auth login + OCI v2 ping) ──────────────────────────

    async def op_health(self) -> OpResult:
        try:
            resp = await self._request("GET", "/v2/", auth=False)
            reachable = resp.status_code in (200, 401)  # 401 = жив, ждёт auth
            if not reachable:
                return OpResult(status=OpStatus.TRANSIENT_FAILURE,
                                capability=ProviderCapability.HEALTH,
                                provider_id=PROVIDER_ID,
                                detail=f"/v2/ HTTP {resp.status_code}")
            auth_ok = False
            if self.config.token_provider is not None:
                r2 = await self._request("GET", "/v2/")
                auth_ok = r2.status_code == 200
            return OpResult(
                status=OpStatus.OK,
                capability=ProviderCapability.HEALTH,
                provider_id=PROVIDER_ID,
                raw={"reachable": True, "authenticated": auth_ok,
                     "auth_configured": self.config.token_provider is not None},
            )
        except TransportFailure as exc:
            return OpResult(status=OpStatus.TRANSIENT_FAILURE,
                            capability=ProviderCapability.HEALTH,
                            provider_id=PROVIDER_ID, detail=str(exc))

    # ── Provisioning (evidence: client.rb create_area/create_repository) ──

    async def provision_area(self, key: str, name: str) -> OpResult:
        """create_area(key, name). Маршрут внутри CORE не подтверждён →
        честный UNSUPPORTED пока areas_path не задан из подтверждённого OpenAPI."""
        if not self.config.areas_path:
            return OpResult.unsupported(
                ProviderCapability.PROVISION_AREA, PROVIDER_ID,
                "area creation endpoint requires confirmed OpenAPI export (COS-049)",
            )
        try:
            resp = await self._request("POST", CORE_BASE + self.config.areas_path,
                                       headers={"Content-Type": "application/json"},
                                       data=_json_bytes({"key": key, "name": name}))
            return self._result_from_response(ProviderCapability.PROVISION_AREA, resp,
                                              location_ref=f"area:{key}",
                                              idempotent_conflict=True)
        except TransportFailure as exc:
            return OpResult(status=OpStatus.TRANSIENT_FAILURE,
                            capability=ProviderCapability.PROVISION_AREA,
                            provider_id=PROVIDER_ID, detail=str(exc))

    async def provision_repository(
        self,
        name: str,
        *,
        area_key: str,
        repo_format: str,          # 'docker' | 'raw' | 'maven' (legacy evidence)
        repo_type: str = "hosted",
        blob_store_ids: Optional[list[str]] = None,
        options: Optional[dict[str, Any]] = None,
    ) -> OpResult:
        """create_repository(...) — формат легаси-клиента; маршрут требует подтверждения."""
        if not self.config.repositories_path:
            return OpResult.unsupported(
                ProviderCapability.PROVISION_REPOSITORY, PROVIDER_ID,
                "repository creation endpoint requires confirmed OpenAPI export (COS-049)",
            )
        payload = {
            "format": repo_format,
            "type": repo_type,
            "name": name,
            "area_key": area_key,
            "blob_store_ids": blob_store_ids or [],
            "options": options or {},
        }
        try:
            resp = await self._request("POST", CORE_BASE + self.config.repositories_path,
                                       headers={"Content-Type": "application/json"},
                                       data=_json_bytes(payload))
            return self._result_from_response(ProviderCapability.PROVISION_REPOSITORY, resp,
                                              location_ref=f"{area_key}/{name}",
                                              idempotent_conflict=True)
        except TransportFailure as exc:
            return OpResult(status=OpStatus.TRANSIENT_FAILURE,
                            capability=ProviderCapability.PROVISION_REPOSITORY,
                            provider_id=PROVIDER_ID, detail=str(exc))

    # ── Raw push/pull (evidence: PUT <repo_url>/raw/<repo>/<path>) ──

    async def op_push(self, ref: str, data: bytes, *,
                      media_type: str = "application/octet-stream") -> OpResult:
        """Raw upload: PUT <raw_repo_base>/<ref>. ref = '<repo>/<path>'."""
        if not self.config.raw_repo_base_url:
            return OpResult.unsupported(
                ProviderCapability.RAW_PUSH, PROVIDER_ID,
                "raw_repo_base_url is not configured",
            )
        url = f"{self.config.raw_repo_base_url.rstrip('/')}/{ref.lstrip('/')}"
        try:
            resp = await self._request("PUT", url,
                                       headers={"Content-Type": media_type},
                                       data=data, auth=False)  # raw repo URL — scoped cred
            return self._result_from_response(ProviderCapability.RAW_PUSH, resp,
                                              location_ref=ref, payload=data)
        except TransportFailure as exc:
            return OpResult(status=OpStatus.TRANSIENT_FAILURE,
                            capability=ProviderCapability.RAW_PUSH,
                            provider_id=PROVIDER_ID, detail=str(exc))

    async def op_pull(self, ref: str) -> OpResult:
        """Raw download: GET <raw_repo_base>/<ref>."""
        if not self.config.raw_repo_base_url:
            return OpResult.unsupported(
                ProviderCapability.RAW_PULL, PROVIDER_ID,
                "raw_repo_base_url is not configured",
            )
        url = f"{self.config.raw_repo_base_url.rstrip('/')}/{ref.lstrip('/')}"
        try:
            resp = await self._request("GET", url, auth=False)
            result = self._result_from_response(ProviderCapability.RAW_PULL, resp,
                                                location_ref=ref,
                                                payload=resp.body or None)
            result.raw["body_bytes"] = len(resp.body) if resp.body else 0
            result.raw["body"] = resp.body if resp.body else b""
            return result
        except TransportFailure as exc:
            return OpResult(status=OpStatus.TRANSIENT_FAILURE,
                            capability=ProviderCapability.RAW_PULL,
                            provider_id=PROVIDER_ID, detail=str(exc))

    # ── OCI push/pull (evidence: BinaryPusher / BinaryFetcher через /v2/) ──

    async def oci_push(self, repo_name: str, tag: str, manifest: dict[str, Any],
                       blobs: Optional[list[tuple[str, bytes]]] = None) -> OpResult:
        """OCI push: blob uploads (POST upload → PUT with digest) → PUT manifest.

        COS-069 (contract map §4):
          - весь registry push-путь = Basic auth (binary_pusher.rb:51–57);
            без basic_auth_provider — задокументированный fallback
            (Bearer/anonymous), режим фиксируется в raw["registry_auth_mode"];
          - digest манифеста считается КЛИЕНТОМ (sha256 payload, pusher:120–121);
            серверный Docker-Content-Digest не identity, а сверочный факт в
            raw["server_digest_header"] — live-профиль обязан сверить (COS-049).
        """
        base = f"/v2/{repo_name}"
        registry_auth_mode = self._resolve_auth_mode("basic")
        try:
            for digest, blob in (blobs or []):
                up = await self._request("POST", f"{base}/blobs/uploads/", auth="basic")
                if up.status_code not in (200, 202):
                    return self._result_from_response(ProviderCapability.OCI_PUSH, up)
                location = up.headers.get("Location", "")
                sep = "&" if "?" in location else "?"
                put = await self._request(
                    "PUT", f"{location}{sep}digest={digest}",
                    headers={"Content-Type": "application/octet-stream"},
                    data=blob, auth="basic",
                )
                if not (200 <= put.status_code < 300):
                    return self._result_from_response(ProviderCapability.OCI_PUSH, put)

            manifest_bytes = _json_bytes(manifest)
            mt = "application/vnd.oci.image.manifest.v1+json"
            put_m = await self._request(
                "PUT", f"{base}/manifests/{tag}",
                headers={"Content-Type": mt}, data=manifest_bytes, auth="basic",
            )
            result = self._result_from_response(ProviderCapability.OCI_PUSH, put_m,
                                                location_ref=f"{repo_name}:{tag}",
                                                payload=manifest_bytes)
            if result.ok:
                server_header = (put_m.headers.get("Docker-Content-Digest")
                                 or put_m.headers.get("ETag") or "").strip('"')
                if server_header:
                    result.raw["server_digest_header"] = server_header
                # Legacy pusher считает digest клиентом — sha256 от отправленных байтов:
                result.digest = "sha256:" + hashlib.sha256(manifest_bytes).hexdigest()
                result.raw["digest_source"] = "computed_payload"
                result.raw["registry_auth_mode"] = registry_auth_mode
            return result
        except TransportFailure as exc:
            return OpResult(status=OpStatus.TRANSIENT_FAILURE,
                            capability=ProviderCapability.OCI_PUSH,
                            provider_id=PROVIDER_ID, detail=str(exc))

    async def oci_pull(self, repo_name: str, ref: str) -> OpResult:
        """OCI pull: GET manifest по tag/digest (BinaryFetcher evidence)."""
        try:
            resp = await self._request(
                "GET", f"/v2/{repo_name}/manifests/{ref}",
                headers={"Accept": "application/vnd.oci.image.manifest.v1+json"},
            )
            result = self._result_from_response(ProviderCapability.OCI_PULL, resp,
                                                location_ref=f"{repo_name}:{ref}",
                                                payload=resp.body or None)
            if result.ok:
                result.raw["manifest"] = resp.json_or_empty()
            return result
        except TransportFailure as exc:
            return OpResult(status=OpStatus.TRANSIENT_FAILURE,
                            capability=ProviderCapability.OCI_PULL,
                            provider_id=PROVIDER_ID, detail=str(exc))

    async def oci_blob_pull(self, repo_name: str, digest: str) -> OpResult:
        try:
            # COS-069: registry pull = Bearer (binary_fetcher.rb:171–181);
            # без token_provider — anonymous (offline-контракты).
            resp = await self._request("GET", f"/v2/{repo_name}/blobs/{digest}", auth=True)
            result = self._result_from_response(ProviderCapability.OCI_PULL, resp,
                                                location_ref=f"{repo_name}@{digest}")
            if result.ok:
                result.raw["body"] = resp.body
            return result
        except TransportFailure as exc:
            return OpResult(status=OpStatus.TRANSIENT_FAILURE,
                            capability=ProviderCapability.OCI_PULL,
                            provider_id=PROVIDER_ID, detail=str(exc))

    # ── Честно unsupported до подтверждённого OpenAPI ──────────────

    async def op_exists(self, ref: str, digest: Optional[str] = None) -> OpResult:
        return OpResult.unsupported(
            ProviderCapability.EXISTS, PROVIDER_ID,
            "no confirmed exists/HEAD contract — requires OpenAPI export (COS-049)",
        )

    async def resolve_digest(self, repo_name: str, tag: str) -> OpResult:
        return OpResult.unsupported(
            ProviderCapability.RESOLVE_DIGEST, PROVIDER_ID,
            "no confirmed tag→digest API — requires OpenAPI export (COS-049)",
        )

    async def copy_or_promote(self, source_ref: str, target_repository: str) -> OpResult:
        return OpResult.unsupported(
            ProviderCapability.COPY_OR_PROMOTE, PROVIDER_ID,
            "no confirmed promotion API; promotion = oci_pull + oci_push клиентской стороной",
        )

    async def quota_report(self) -> OpResult:
        return OpResult.unsupported(
            ProviderCapability.QUOTA_REPORT, PROVIDER_ID,
            "no confirmed quota contract — requires OpenAPI export (COS-049)",
        )


def _json_bytes(payload: dict[str, Any]) -> bytes:
    import json
    return json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
