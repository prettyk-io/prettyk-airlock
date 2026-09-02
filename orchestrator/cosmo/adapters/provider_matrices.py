# -*- coding: utf-8 -*-
"""
COS-052: Capability matrices — Git, Harbor/OCI, Nexus/package, MinIO/S3.

Baseline-провайдеры PureK (docs/research/2026-09-01-sfera-openapi-and-registry-boundary.md §4):

| Plane    | Provider            | Ответственность                                  |
|----------|---------------------|--------------------------------------------------|
| Source   | Git (Gitea adapter) | refs, bundles, source identity                   |
| OCI      | Harbor              | images, manifests/layers, SBOM/signatures        |
| Package  | Nexus               | dependencies, coordinates, generic artifacts     |
| Evidence | MinIO/S3            | scan outputs, reports, evidence, большие объекты |

Статусы эпистемические (CapabilityStatus): CONFIRMED — покрыто contract tests
(fake fixtures этой же карточки); DOCUMENTED — заявлено провайдером/спекой.
UNSUPPORTED-операции возвращают OpResult.unsupported() — не fake success.
"""
from __future__ import annotations

from orchestrator.cosmo.adapters.provider_capability import (
    CapabilityReport,
    CapabilityStatus,
    ProviderCapability as PC,
)


def git_provider_matrix(provider_id: str = "gitea") -> CapabilityReport:
    """Git provider: source identity, bundle transfer. NOT a blob storage."""
    m = CapabilityReport(provider_id=provider_id)
    m.set(PC.PROVISION_REPOSITORY, CapabilityStatus.CONFIRMED,
          notes="create repo + org (forge adapter)",
          evidence="cosmo/adapters/forge_gitea.py::create_repo")
    m.set(PC.PROVISION_AREA, CapabilityStatus.CONFIRMED,
          notes="organization = area", evidence="forge_gitea::register_domain")
    m.set(PC.GIT_BUNDLE_TRANSFER, CapabilityStatus.DOCUMENTED,
          notes="git bundle push/pull through repo refs", evidence="legacy TransferReleaseToTest")
    m.set(PC.RAW_PUSH, CapabilityStatus.NOT_SUPPORTED,
          notes="git хранит объекты VCS, не generic blobs")
    m.set(PC.RAW_PULL, CapabilityStatus.NOT_SUPPORTED,
          notes="см. RAW_PUSH")
    m.set(PC.OCI_PUSH, CapabilityStatus.NOT_SUPPORTED)
    m.set(PC.OCI_PULL, CapabilityStatus.NOT_SUPPORTED)
    m.set(PC.EXISTS, CapabilityStatus.DOCUMENTED, notes="repo info / commit status")
    m.set(PC.LIST, CapabilityStatus.CONFIRMED, notes="list_repos", evidence="forge_gitea::list_repos")
    m.set(PC.RESOLVE_DIGEST, CapabilityStatus.NOT_SUPPORTED,
          notes="git SHA — commit identity, не artifact digest")
    m.set(PC.GET_CHECKSUM, CapabilityStatus.NOT_SUPPORTED)
    m.set(PC.COPY_OR_PROMOTE, CapabilityStatus.NOT_SUPPORTED,
          notes="promotion git = mirror/fork, не copy API baseline")
    m.set(PC.SIGNATURE_REF, CapabilityStatus.NOT_SUPPORTED,
          notes="signed commits вне V1 boundary")
    m.set(PC.SBOM_REF, CapabilityStatus.NOT_SUPPORTED)
    m.set(PC.ATTESTATION_REF, CapabilityStatus.NOT_SUPPORTED)
    m.set(PC.HEALTH, CapabilityStatus.CONFIRMED, notes="API ping + token check")
    m.set(PC.QUOTA_REPORT, CapabilityStatus.UNKNOWN, notes="нет подтверждённого контракта")
    m.set(PC.DELETE_REPOSITORY, CapabilityStatus.CONFIRMED, evidence="forge_gitea")
    return m


def harbor_oci_matrix(provider_id: str = "harbor") -> CapabilityReport:
    """Harbor: OCI Distribution V2, digest-preserving promotion, cosign/SBOM refs."""
    m = CapabilityReport(provider_id=provider_id)
    m.set(PC.PROVISION_REPOSITORY, CapabilityStatus.DOCUMENTED,
          notes="project/repo creation через Harbor API")
    m.set(PC.PROVISION_AREA, CapabilityStatus.DOCUMENTED, notes="Harbor project")
    m.set(PC.OCI_PUSH, CapabilityStatus.CONFIRMED,
          notes="OCI Distribution Spec v1.1 blob+manifest upload",
          evidence="cosmo/adapters/oci_registry.py")
    m.set(PC.OCI_PULL, CapabilityStatus.CONFIRMED,
          notes="manifest/config/layers, range/resume", evidence="oci_registry.py")
    m.set(PC.RAW_PUSH, CapabilityStatus.NOT_SUPPORTED,
          notes="generic blobs — не роль OCI registry")
    m.set(PC.RAW_PULL, CapabilityStatus.NOT_SUPPORTED)
    m.set(PC.EXISTS, CapabilityStatus.CONFIRMED,
          notes="HEAD manifest by digest", evidence="oci_registry::check_artifact")
    m.set(PC.LIST, CapabilityStatus.CONFIRMED, notes="tags list", evidence="oci_registry::list_tags")
    m.set(PC.RESOLVE_DIGEST, CapabilityStatus.CONFIRMED,
          notes="tag → immutable digest; mutable tag НЕ identity",
          evidence="oci_registry::resolve_digest")
    m.set(PC.GET_CHECKSUM, CapabilityStatus.CONFIRMED,
          notes="Docker-Content-Digest header", evidence="OCI spec")
    m.set(PC.COPY_OR_PROMOTE, CapabilityStatus.DOCUMENTED,
          notes="digest-preserving promotion ЗР→ЗТ; digest обязателен в target")
    m.set(PC.SIGNATURE_REF, CapabilityStatus.DOCUMENTED, notes="cosign signature tag")
    m.set(PC.SBOM_REF, CapabilityStatus.DOCUMENTED, notes="SBOM as OCI artifact/attachment")
    m.set(PC.ATTESTATION_REF, CapabilityStatus.DOCUMENTED, notes="OCI attestations")
    m.set(PC.HEALTH, CapabilityStatus.CONFIRMED, notes="/v2/ ping", evidence="oci_registry::health")
    m.set(PC.QUOTA_REPORT, CapabilityStatus.DOCUMENTED, notes="Harbor quota API")
    m.set(PC.DELETE_REPOSITORY, CapabilityStatus.DOCUMENTED)
    m.set(PC.GIT_BUNDLE_TRANSFER, CapabilityStatus.NOT_SUPPORTED)
    return m


def nexus_package_matrix(provider_id: str = "nexus") -> CapabilityReport:
    """Nexus: package coordinates, proxy/cache, generic raw; OCI V2 как runtime режим."""
    m = CapabilityReport(provider_id=provider_id)
    m.set(PC.PROVISION_REPOSITORY, CapabilityStatus.DOCUMENTED,
          notes="repo creation (maven/raw/docker formats)")
    m.set(PC.PROVISION_AREA, CapabilityStatus.NOT_SUPPORTED,
          notes="нет area/namespace иерархии как в Sfera")
    m.set(PC.RAW_PUSH, CapabilityStatus.DOCUMENTED,
          notes="generic raw artifacts (deploy/upload)")
    m.set(PC.RAW_PULL, CapabilityStatus.DOCUMENTED, notes="raw download")
    m.set(PC.OCI_PUSH, CapabilityStatus.DOCUMENTED,
          notes="Nexus docker registry mode (OCI V2 compatible)")
    m.set(PC.OCI_PULL, CapabilityStatus.DOCUMENTED, notes="OCI V2 pull")
    m.set(PC.EXISTS, CapabilityStatus.DOCUMENTED, notes="component search/HEAD")
    m.set(PC.LIST, CapabilityStatus.DOCUMENTED,
          notes="component listing; pagination — отдельный контракт, UNKNOWN details")
    m.set(PC.RESOLVE_DIGEST, CapabilityStatus.DOCUMENTED,
          notes="docker mode: tag→digest; maven: checksum metadata")
    m.set(PC.GET_CHECKSUM, CapabilityStatus.DOCUMENTED, notes=".sha1/.sha256 metadata files")
    m.set(PC.COPY_OR_PROMOTE, CapabilityStatus.NOT_SUPPORTED,
          notes="нет нативного repo-to-repo copy в baseline контракте; "
                "promotion = pull+push отдельными операциями")
    m.set(PC.SIGNATURE_REF, CapabilityStatus.NOT_SUPPORTED,
          notes="signature storage — вне Nexus package semantics V1")
    m.set(PC.SBOM_REF, CapabilityStatus.NOT_SUPPORTED,
          notes="SBOM хранится как обычный raw/evidence объект")
    m.set(PC.ATTESTATION_REF, CapabilityStatus.NOT_SUPPORTED)
    m.set(PC.HEALTH, CapabilityStatus.DOCUMENTED, notes="status/warming check")
    m.set(PC.QUOTA_REPORT, CapabilityStatus.UNKNOWN)
    m.set(PC.DELETE_REPOSITORY, CapabilityStatus.DOCUMENTED)
    m.set(PC.GIT_BUNDLE_TRANSFER, CapabilityStatus.NOT_SUPPORTED)
    return m


def minio_s3_matrix(provider_id: str = "minio") -> CapabilityReport:
    """MinIO/S3: evidence blobs, immutable objects, object-lock; НЕ package registry."""
    m = CapabilityReport(provider_id=provider_id)
    m.set(PC.PROVISION_REPOSITORY, CapabilityStatus.DOCUMENTED, notes="bucket creation")
    m.set(PC.PROVISION_AREA, CapabilityStatus.NOT_SUPPORTED)
    m.set(PC.RAW_PUSH, CapabilityStatus.CONFIRMED,
          notes="PUT object; sha256 content hash = immutable ref",
          evidence="cosmo/infra/minio_client.py")
    m.set(PC.RAW_PULL, CapabilityStatus.CONFIRMED, notes="GET object")
    m.set(PC.OCI_PUSH, CapabilityStatus.NOT_SUPPORTED, notes="не OCI registry")
    m.set(PC.OCI_PULL, CapabilityStatus.NOT_SUPPORTED)
    m.set(PC.EXISTS, CapabilityStatus.CONFIRMED, notes="HEAD object (etag/sha256)")
    m.set(PC.LIST, CapabilityStatus.CONFIRMED, notes="objects listing, pagination native")
    m.set(PC.RESOLVE_DIGEST, CapabilityStatus.CONFIRMED,
          notes="content sha256 при upload; etag ≠ sha256 для multipart — осторожно")
    m.set(PC.GET_CHECKSUM, CapabilityStatus.DOCUMENTED,
          notes="sha256 metadata/etag; multipart требует отдельной фиксации digest")
    m.set(PC.COPY_OR_PROMOTE, CapabilityStatus.DOCUMENTED,
          notes="server-side copy bucket-to-bucket с сохранением digest")
    m.set(PC.SIGNATURE_REF, CapabilityStatus.NOT_SUPPORTED,
          notes="signature хранится как объект, не нативная capability")
    m.set(PC.SBOM_REF, CapabilityStatus.NOT_SUPPORTED,
          notes="SBOM = обычный объект evidence")
    m.set(PC.ATTESTATION_REF, CapabilityStatus.NOT_SUPPORTED)
    m.set(PC.HEALTH, CapabilityStatus.CONFIRMED, notes="S3 health/bucket check")
    m.set(PC.QUOTA_REPORT, CapabilityStatus.DOCUMENTED, notes="bucket usage stats")
    m.set(PC.DELETE_REPOSITORY, CapabilityStatus.DOCUMENTED, notes="bucket delete (версионирование/lock)")
    m.set(PC.GIT_BUNDLE_TRANSFER, CapabilityStatus.NOT_SUPPORTED,
          notes="bundle может храниться как объект, но это RAW_PUSH, не git capability")
    return m


def sfera_matrix(provider_id: str = "sfera") -> CapabilityReport:
    """Sfera/ДиБ — optional external bridge.

    Статусы ТОЛЬКО из подтверждённого легаси evidence
    (research §7.1: client.rb, BinaryPusher/BinaryFetcher, EstablishSfera).
    Ничего не выдумывается: нет подтверждённого контракта → UNKNOWN,
    и операции вернут OpResult.unsupported().
    """
    m = CapabilityReport(provider_id=provider_id)
    m.set(PC.PROVISION_AREA, CapabilityStatus.DOCUMENTED,
          notes="create_area(key, name) — legacy client.rb + EstablishSfera",
          evidence="D:\\cosmo\\cosmoport\\backend lib/sfera/client.rb")
    m.set(PC.PROVISION_REPOSITORY, CapabilityStatus.DOCUMENTED,
          notes="create_repository(format, type, name, area_key, blob_store_ids, options)",
          evidence="lib/sfera/client.rb")
    m.set(PC.DELETE_REPOSITORY, CapabilityStatus.DOCUMENTED, evidence="client.rb")
    m.set(PC.RAW_PUSH, CapabilityStatus.DOCUMENTED,
          notes="PUT <repo_url>/raw/<repo>/<path>", evidence="client.rb")
    m.set(PC.RAW_PULL, CapabilityStatus.DOCUMENTED,
          notes="raw tree/file download", evidence="client.rb")
    m.set(PC.OCI_PUSH, CapabilityStatus.DOCUMENTED,
          notes="Sfera::BinaryPusher — OCI blobs + manifest через /v2/; "
                "registry push = Basic auth (НЕ Bearer), digest считается "
                "клиентом (sha256), серверный заголовок push-путём не identity "
                "(contract map §4)",
          evidence="binary_pusher.rb:51–57,96–138; docs/research/2026-09-02-legacy-sfera-contract-map.md")
    m.set(PC.OCI_PULL, CapabilityStatus.DOCUMENTED,
          notes="Sfera::BinaryFetcher — manifest/config/layers через /v2/; "
                "pull = Bearer (access_token от login), Range-resume + "
                "экспоненциальный retry ×5 (contract map §4)",
          evidence="binary_fetcher.rb:93–169,171–181; docs/research/2026-09-02-legacy-sfera-contract-map.md")
    m.set(PC.GET_CHECKSUM, CapabilityStatus.DOCUMENTED,
          notes="GetDockerImageChecksums — docker tree detail fileInfo; "
                "ВАЖНО: legacy предпочитает sha1 (fileInfo['sha1'] || sha256); "
                "наш adapter sha256-only — sha1 не используется как identity",
          evidence="get_docker_image_checksums.rb:20–23; contract map §6")
    m.set(PC.EXISTS, CapabilityStatus.UNKNOWN,
          notes="нет подтверждённого exists/HEAD контракта — нужен OpenAPI")
    m.set(PC.LIST, CapabilityStatus.DOCUMENTED,
          notes="docker/raw tree listing код-подтверждён: "
                "GET {REST}/docker|raw/tree/{repo}/items[?parentId=] "
                "(parentId-пагинация); фильтры/totals/сортировки — остаются "
                "UNKNOWN до OpenAPI (COS-049)",
          evidence="lib/sfera/client.rb:123–149; contract map §3#6–8")
    m.set(PC.RESOLVE_DIGEST, CapabilityStatus.UNKNOWN,
          notes="нет подтверждённого tag→digest API")
    m.set(PC.COPY_OR_PROMOTE, CapabilityStatus.UNKNOWN,
          notes="нет подтверждённого promotion API; promotion = pull+push нашими op")
    m.set(PC.SIGNATURE_REF, CapabilityStatus.UNKNOWN)
    m.set(PC.SBOM_REF, CapabilityStatus.UNKNOWN)
    m.set(PC.ATTESTATION_REF, CapabilityStatus.UNKNOWN)
    m.set(PC.HEALTH, CapabilityStatus.DOCUMENTED,
          notes="auth login + /v2/ доступность: login код-подтверждён "
                "(POST /api/auth/login → Bearer); /v2/ ping как отдельного "
                "эндпоинта в legacy нет — живость /v2/ подтверждена "
                "HEAD/GET в push/fetch; registry push-auth = Basic "
                "(split-факт в contract map §2)",
          evidence="client.rb:47–57; binary_pusher.rb:51–57; binary_fetcher.rb:171–181; "
                   "contract map §2")
    m.set(PC.QUOTA_REPORT, CapabilityStatus.UNKNOWN, notes="quotas — нужен OpenAPI")
    m.set(PC.GIT_BUNDLE_TRANSFER, CapabilityStatus.NOT_SUPPORTED,
          notes="bundle передаётся как RAW_PUSH объект, не git capability")
    return m


ALL_BASELINE_MATRICES: dict[str, CapabilityReport] = {
    m.provider_id: m for m in (
        git_provider_matrix(),
        harbor_oci_matrix(),
        nexus_package_matrix(),
        minio_s3_matrix(),
        sfera_matrix(),
    )
}
