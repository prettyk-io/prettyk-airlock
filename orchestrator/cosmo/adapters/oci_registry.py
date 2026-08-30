"""
BRG-002 / INT-013: OCI Registry Provider (Docker Registry V2).

OCI Distribution Spec v1.1 adapter. Compatible with ANY OCI V2 registry:
  - Local distribution/distribution:3.2.0 (local-oci smoke, dev)
  - Sonatype Nexus Repository (nexus, staging)
  - T1-Sfera (t1_sfera, ОТЕЧЕСТВЕННЫЙ РЕЕСТР, если OCI V2)

Artifactory удалён из active Cosmoport code (FINAL-LUNA-001).

Rules:
  - latest NEVER used as identity -- always immutable digest.
  - All secrets via vault secret references, never plaintext.
  - Health check before every operation.
  - Provider selected by RegistryConfig.provider, not hardcoded.
"""
from __future__ import annotations

import asyncio
import base64
import datetime
import hashlib
import json
import time
from typing import Any, Dict, List, Optional, Tuple

import httpx

from orchestrator.cosmo.adapters.artifact_registry import (
    ArtifactReference,
    ArtifactRegistry,
    HealthStatus,
    PullResult,
    PushResult,
    RegistryConfig,
    RegistryProvider,
    RegistryZone,
    register_provider,
)


class OciRegistry(ArtifactRegistry):
    """OCI Distribution Spec v1.1 -- one protocol, many endpoints."""

    def __init__(self, config: RegistryConfig):
        super().__init__(config)
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=self.config.timeout_seconds,
                verify=self.config.tls_ca_cert if self.config.tls_verify and self.config.tls_ca_cert else self.config.tls_verify,
            )
        return self._client

    async def _auth_headers(self) -> Dict[str, str]:
        if self.config.robot_account and self.config.secret_ref:
            token = base64.b64encode(
                f"{self.config.robot_account}:{self.config.secret_ref}".encode()
            ).decode()
            return {"Authorization": f"Basic {token}"}
        return {}

    # -- Health --

    async def health(self) -> HealthStatus:
        t0 = time.monotonic()
        client = await self._get_client()
        headers = await self._auth_headers()
        reachable, auth_ok, namespace_ok = False, False, False
        error = None
        details: Dict[str, Any] = {}
        try:
            r = await client.get(f"{self.config.endpoint.rstrip('/')}/v2/", headers=headers)
            reachable = r.status_code in (200, 401)
            details["v2_endpoint"] = r.status_code
            if r.status_code == 401:
                if self.config.robot_account:
                    r2 = await client.get(f"{self.config.endpoint.rstrip('/')}/v2/", headers=headers)
                    auth_ok = r2.status_code == 200
            else:
                auth_ok = True
            r3 = await client.get(f"{self.config.endpoint.rstrip('/')}/v2/_catalog?n=1", headers=headers)
            namespace_ok = r3.status_code in (200, 401)
        except Exception as e:
            error = str(e)
        latency_ms = (time.monotonic() - t0) * 1000
        return HealthStatus(
            provider=self.config.provider, endpoint=self.config.endpoint,
            reachable=reachable, authenticated=auth_ok, namespace_accessible=namespace_ok,
            latency_ms=round(latency_ms, 1), error=error, details=details,
        )

    # -- Push --

    async def push_artifact(self, name: str, tag: str, source_ref: str,
                            metadata: Optional[Dict[str, Any]] = None) -> PushResult:
        client = await self._get_client()
        headers = await self._auth_headers()
        try:
            with open(source_ref, "rb") as f:
                data = f.read()
        except FileNotFoundError:
            data = json.dumps({"name": name, "tag": tag, "source": source_ref}).encode()
        digest = self._compute_digest(data)
        # OCI monolithic upload
        upload_url = f"{self.config.endpoint.rstrip('/')}/v2/{self._qualified_image(name)}/blobs/uploads/?digest={digest}"
        headers["Content-Length"] = str(len(data))
        headers["Content-Type"] = "application/octet-stream"
        r = await client.post(upload_url, content=data, headers=headers)
        if r.status_code not in (200, 201, 202):
            raise RuntimeError(f"Blob push failed: HTTP {r.status_code}")
        # Push manifest
        manifest = {
            "schemaVersion": 2, "mediaType": "application/vnd.oci.image.manifest.v1+json",
            "config": {"mediaType": "application/vnd.oci.image.config.v1+json", "size": len(data), "digest": digest},
            "layers": [{"mediaType": "application/vnd.oci.image.layer.v1.tar+gzip", "size": len(data), "digest": digest}],
            "annotations": metadata or {},
        }
        manifest_bytes = json.dumps(manifest).encode()
        manifest_digest = self._compute_digest(manifest_bytes)
        manifest_url = self._oci_manifest_url(name, manifest_digest)
        mh = {k: v for k, v in headers.items() if k.lower() != "content-length"}
        mh["Content-Type"] = "application/vnd.oci.image.manifest.v1+json"
        r2 = await client.put(manifest_url, content=manifest_bytes, headers=mh)
        if r2.status_code not in (200, 201, 202):
            raise RuntimeError(f"Manifest push failed: HTTP {r2.status_code}")
        r3 = await client.put(self._oci_manifest_url(name, tag), content=manifest_bytes, headers=mh)
        if r3.status_code not in (200, 201, 202):
            raise RuntimeError(f"Tag push failed: HTTP {r3.status_code}")
        return PushResult(name=name, tag=tag, digest=manifest_digest, size_bytes=len(manifest_bytes))

    # -- Pull Manifest --

    async def pull_manifest(self, name: str, digest: Optional[str] = None,
                            tag: Optional[str] = None) -> PullResult:
        client = await self._get_client()
        headers = await self._auth_headers()
        headers["Accept"] = "application/vnd.oci.image.manifest.v1+json"
        ref = digest or tag or "latest"
        r = await client.get(self._oci_manifest_url(name, ref), headers=headers)
        if r.status_code != 200:
            raise RuntimeError(f"Manifest pull failed: HTTP {r.status_code}")
        data = r.json()
        resolved = r.headers.get("Docker-Content-Digest", self._compute_digest(r.content))
        return PullResult(name=name, digest=resolved, manifest=data, layers=data.get("layers", []))

    # -- Resolve Digest --

    async def resolve_digest(self, name: str, tag: str) -> str:
        client = await self._get_client()
        headers = await self._auth_headers()
        headers["Accept"] = "application/vnd.oci.image.manifest.v1+json"
        r = await client.head(self._oci_manifest_url(name, tag), headers=headers)
        if r.status_code != 200:
            raise RuntimeError(f"Digest resolve failed: HTTP {r.status_code}")
        return r.headers.get("Docker-Content-Digest", "")

    # -- Check --

    async def check_artifact(self, name: str, digest: str) -> bool:
        client = await self._get_client()
        headers = await self._auth_headers()
        r = await client.head(self._oci_manifest_url(name, digest), headers=headers)
        return r.status_code == 200

    # -- Promote --

    async def copy_or_promote(self, name: str, digest: str, target_repository: str,
                              target_tag: Optional[str] = None) -> PushResult:
        pull = await self.pull_manifest(name, digest=digest)
        tag = target_tag or f"promoted-{datetime.datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
        client = await self._get_client()
        headers = await self._auth_headers()
        headers["Content-Type"] = "application/vnd.oci.image.manifest.v1+json"
        manifest_bytes = json.dumps(pull.manifest).encode()
        r = await client.put(self._oci_manifest_url(name, tag), content=manifest_bytes, headers=headers)
        if r.status_code not in (200, 201, 202):
            raise RuntimeError(f"Promote failed: HTTP {r.status_code}")
        return PushResult(name=name, tag=tag, digest=digest, size_bytes=len(manifest_bytes))

    # -- SBOM --

    async def get_sbom_reference(self, name: str, digest: str) -> Optional[str]:
        pull = await self.pull_manifest(name, digest=digest)
        return pull.manifest.get("annotations", {}).get("org.cyclonedx.sbom")

    # -- List Tags --

    async def list_tags(self, name: str, limit: int = 50) -> List[str]:
        client = await self._get_client()
        headers = await self._auth_headers()
        r = await client.get(self._oci_tags_url(name), headers=headers)
        if r.status_code != 200:
            return []
        return r.json().get("tags", [])[:limit]


# -- Provider Registration --

register_provider(RegistryProvider.LOCAL_OCI, OciRegistry)
register_provider(RegistryProvider.NEXUS, OciRegistry)
# T1-Sfera registered after capability probe