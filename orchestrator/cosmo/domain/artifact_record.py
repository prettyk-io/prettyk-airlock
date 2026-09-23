# -*- coding: utf-8 -*-
"""COS-163: durable-метаданные артефакта (digest + manifest + SBOM).

Полная durable-схема «build → registry»: после канонического push образ
фиксируется одной записью, охватывающей:

  - ``digest`` — immutable ``sha256:...`` (identity образа);
  - ``manifest`` — OCI image manifest, считанный с registry;
  - ``sbom_ref`` — ссылка на SBOM-документ (если доступен).

Контракт имени/версии/digest наследуется из COS-142
(``CanonicalArtifactTag``) — плавающий ``latest`` запрещён, digest строго
sha256. Связка с canonical_ref из COS-162 — ``canonical_ref()`` даёт ту же
строку, что ``DockerBuildResult.canonical_ref()``.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from orchestrator.cosmo.domain.artifact_manifest import (
    DIGEST_RE,
    FORBIDDEN_TAG,
    NAME_RE,
    SEMVER_RE,
    ArtifactManifestError,
    CanonicalArtifactTag,
)


class ArtifactRecord(BaseModel):
    """Durable-запись артефакта в registry зоны (digest + manifest + SBOM)."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, max_length=255)
    version: str = Field(..., min_length=1, max_length=128)
    digest: str = Field(..., min_length=71, max_length=71)
    registry: str = Field(..., min_length=1, max_length=512)
    repository: str = Field(default="cosmoport", min_length=1, max_length=255)
    namespace: str = Field(default="zr", min_length=1, max_length=128)
    manifest: Optional[dict[str, Any]] = Field(default=None)
    sbom_ref: Optional[str] = Field(default=None, max_length=512)
    run_id: Optional[str] = Field(default=None, max_length=64)
    batch_id: Optional[str] = Field(default=None, max_length=64)

    @field_validator("name")
    @classmethod
    def _name_is_slug(cls, value: str) -> str:
        if not NAME_RE.match(value):
            raise ValueError(
                "artifact name must be a lowercase slug "
                "('^[a-z0-9][a-z0-9._-]*$'), no path or uppercase"
            )
        return value

    @field_validator("version")
    @classmethod
    def _version_is_pinned_semver(cls, value: str) -> str:
        if FORBIDDEN_TAG in value.lower():
            raise ValueError(
                "floating tag 'latest' is forbidden — pin a semver version"
            )
        if not SEMVER_RE.match(value):
            raise ValueError(
                f"version '{value}' is not a strict semver (major.minor.patch)"
            )
        return value

    @field_validator("digest")
    @classmethod
    def _digest_is_sha256(cls, value: str) -> str:
        if not DIGEST_RE.match(value):
            raise ValueError(
                "digest must match '^sha256:[a-f0-9]{64}$' (lowercase hex)"
            )
        return value

    def canonical_ref(self) -> str:
        """Каноническая строка ``<name>:<version>@sha256:<digest>`` (COS-142)."""
        tag = CanonicalArtifactTag(
            name=self.name, version=self.version, digest=self.digest
        )
        return tag.canonical_ref()

    def qualified_image(self) -> str:
        """Полное имя образа в registry: ``host/repository/namespace/name``."""
        parts = [self.registry, self.repository, self.namespace, self.name]
        return "/".join(part for part in parts if part)


def artifact_record_content_hash(record: ArtifactRecord) -> str:
    """SHA-256 канонического представления записи (тампер-якорь).

    sort_keys + compact — тот же приём, что ``manifest_content_hash``
    (COS-142) и ``sbom_content_hash`` (COS-138): подпись замороженного
    представления, сверка которой при чтении детектирует подмену.
    """
    payload = json.dumps(
        {
            "name": record.name,
            "version": record.version,
            "digest": record.digest,
            "registry": record.registry,
            "repository": record.repository,
            "namespace": record.namespace,
            "manifest": record.manifest or {},
            "sbom_ref": record.sbom_ref,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def validate_record_against_ref(record: ArtifactRecord) -> None:
    """Defence-in-depth: canonical_ref обязан быть консистентен (COS-142)."""
    try:
        CanonicalArtifactTag(
            name=record.name, version=record.version, digest=record.digest
        )
    except Exception as exc:  # noqa: BLE001 — контракт, арифметика не важна
        raise ArtifactManifestError(
            f"artifact record violates canonical tag contract: {exc}"
        ) from exc