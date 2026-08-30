"""
BRG-001: Artifact Registry Provider Abstraction.

Neutral `ArtifactRegistry` adapter contract. Свой registry не пишем.
Поддерживаемые провайдеры:
  - nexus        (Sonatype Nexus Repository — OCI/Docker Registry V2)
  - t1_sfera     (Отечественный Т1-Сфера — OCI/Docker Registry V2 или REST API)

Выбор провайдера задаётся конфигурацией. Никакого хардкода.
Все ссылки на секреты — через secret references (vault:secret/...).
"""

from __future__ import annotations

import datetime
import hashlib
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple


class RegistryProvider(str, Enum):
    """Поддерживаемые провайдеры artifact registry."""
    LOCAL_OCI = "local-oci"    # distribution:3.2.0 — локальный OCI smoke (dev)
    NEXUS = "nexus"            # Sonatype Nexus Repository
    T1_SFERA = "t1_sfera"       # Т1-Сфера (UNKNOWN до capability probe)


class RegistryZone(str, Enum):
    """Зона размещения registry."""
    ZR = "zr"       # Разработка
    ZT = "zt"       # Тестирование
    ZPE = "zpe"     # Промышленная эксплуатация


# ── Data structures ──────────────────────────────────────────────────────

@dataclass
class RegistryConfig:
    """Конфигурация подключения к artifact registry."""
    provider: RegistryProvider
    zone: RegistryZone = RegistryZone.ZR
    endpoint: str = "http://localhost:5100"                  # base URL registry
    repository: str = "cosmoport"
    namespace: str = "default"
    robot_account: str = ""                                  # service account username
    secret_ref: str = ""                                     # vault:secret/... или openbao:secret/...
    tls_verify: bool = True
    tls_ca_cert: Optional[str] = None                        # путь к CA cert для самоподписанных
    timeout_seconds: int = 30
    labels: Dict[str, str] = field(default_factory=dict)


@dataclass
class ArtifactManifest:
    """Манифест артефакта (OCI image manifest / Helm chart / SBOM)."""
    name: str                                                # e.g. "cosmo-api"
    tag: str                                                 # e.g. "2.0.0-alpha"
    digest: str                                              # sha256:abc...
    media_type: str = "application/vnd.oci.image.manifest.v1+json"
    size_bytes: int = 0
    platform: str = "linux/amd64"
    annotations: Dict[str, str] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat())


@dataclass
class ArtifactReference:
    """Ссылка на артефакт для Build/Release/Deployment."""
    registry_id: str                                         # ID registry-конфигурации
    provider: RegistryProvider
    repository: str
    name: str
    tag: str
    immutable_digest: str                                    # sha256:... — канонический идентификатор
    media_type: str = "application/vnd.oci.image.manifest.v1+json"
    size_bytes: int = 0
    sbom_ref: Optional[str] = None                           # ссылка на SBOM (CycloneDX)
    scan_refs: List[str] = field(default_factory=list)       # ссылки на сканы (Trivy, KCS, etc.)
    signature_ref: Optional[str] = None                      # ссылка на подпись (cosign)



@dataclass
class HealthStatus:
    """Результат проверки здоровья registry."""
    provider: RegistryProvider
    endpoint: str
    reachable: bool
    authenticated: bool
    namespace_accessible: bool
    latency_ms: float
    error: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PushResult:
    """Результат операции push."""
    name: str
    tag: str
    digest: str
    size_bytes: int
    pushed_at: str = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat())


@dataclass
class PullResult:
    """Результат операции pull."""
    name: str
    digest: str
    manifest: dict
    layers: List[Dict[str, Any]]
    pulled_at: str = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat())


# ── Abstract Provider ────────────────────────────────────────────────────

class ArtifactRegistry(ABC):
    """
    Нейтральный адаптер artifact registry (BRG-001).
    Выбор провайдера — через RegistryConfig.provider.
    """

    def __init__(self, config: RegistryConfig):
        self.config = config

    # ── Основной контракт ─────────────────────────────────────────────

    @abstractmethod
    async def health(self) -> HealthStatus:
        """Проверить доступность и аутентификацию registry."""
        ...

    @abstractmethod
    async def push_artifact(
        self,
        name: str,
        tag: str,
        source_ref: str,           # local image ref or blob path
        metadata: Optional[Dict[str, Any]] = None,
    ) -> PushResult:
        """Загрузить артефакт в registry."""
        ...

    @abstractmethod
    async def pull_manifest(
        self,
        name: str,
        digest: Optional[str] = None,
        tag: Optional[str] = None,
    ) -> PullResult:
        """Получить манифест артефакта по digest или tag."""
        ...

    @abstractmethod
    async def resolve_digest(
        self,
        name: str,
        tag: str,
    ) -> str:
        """Получить immutable digest по tag (запрещено использовать mutable tag как идентификатор)."""
        ...

    @abstractmethod
    async def check_artifact(
        self,
        name: str,
        digest: str,
    ) -> bool:
        """Проверить существование артефакта с указанным digest."""
        ...

    @abstractmethod
    async def copy_or_promote(
        self,
        name: str,
        digest: str,
        target_repository: str,
        target_tag: Optional[str] = None,
    ) -> PushResult:
        """Скопировать (promote) артефакт в другой репозиторий (например ЗР → ЗТ)."""
        ...

    @abstractmethod
    async def get_sbom_reference(
        self,
        name: str,
        digest: str,
    ) -> Optional[str]:
        """Получить ссылку на SBOM-документ для артефакта."""
        ...

    @abstractmethod
    async def list_tags(
        self,
        name: str,
        limit: int = 50,
    ) -> List[str]:
        """Список тегов для артефакта."""
        ...

    # ── Хелперы ───────────────────────────────────────────────────────

    def _qualified_image(self, name: str, tag: str = "") -> str:
        """Полное имя образа: repository/namespace/name:tag."""
        parts = [self.config.repository, self.config.namespace, name]
        ref = "/".join(p for p in parts if p)
        if tag:
            ref += f":{tag}"
        return ref

    def _compute_digest(self, data: bytes) -> str:
        return "sha256:" + hashlib.sha256(data).hexdigest()

    def _oci_manifest_url(self, name: str, ref: str) -> str:
        """OCI Distribution Spec: /v2/{name}/manifests/{reference}."""
        return f"{self.config.endpoint.rstrip('/')}/v2/{self._qualified_image(name)}/manifests/{ref}"

    def _oci_blob_url(self, name: str, digest: str) -> str:
        """OCI Distribution Spec: /v2/{name}/blobs/{digest}."""
        return f"{self.config.endpoint.rstrip('/')}/v2/{self._qualified_image(name)}/blobs/{digest}"

    def _oci_tags_url(self, name: str) -> str:
        """OCI Distribution Spec: /v2/{name}/tags/list."""
        return f"{self.config.endpoint.rstrip('/')}/v2/{self._qualified_image(name)}/tags/list"


# ── Provider Factory ─────────────────────────────────────────────────────

_registry_providers: Dict[RegistryProvider, type] = {}


def register_provider(provider: RegistryProvider, cls: type) -> None:
    """Зарегистрировать реализацию провайдера."""
    _registry_providers[provider] = cls


def create_registry(config: RegistryConfig) -> ArtifactRegistry:
    """Создать экземпляр registry-адаптера по конфигурации (BRG-001)."""
    provider_cls = _registry_providers.get(config.provider)
    if provider_cls is None:
        raise ValueError(
            f"Unknown registry provider: {config.provider.value}. "
            f"Available: {[p.value for p in _registry_providers.keys()]}"
        )
    return provider_cls(config)


def get_available_providers() -> List[str]:
    """Список доступных провайдеров."""
    return [p.value for p in _registry_providers.keys()]