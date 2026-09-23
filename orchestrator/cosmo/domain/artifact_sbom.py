# -*- coding: utf-8 -*-
"""COS-167: PK-C-003.6 / DOCKER_AUDIT — SBOM поверх собранного образа (DTO).

Снимает SBOM (CycloneDX 1.5) поверх уже собранного и запушенного образа и
связывает его с durable ``ArtifactRecord`` (COS-163) через ``sbom_ref``.

Итоговый документ — ``SbomInventoryDocument`` (COS-155): единый контракт
CycloneDX 1.5 с честным маркером генератора (``syft`` | ``python-inventory``)
и сводкой уязвимостей. Дайджест-сверка держится на уровне ledger:
``artifact_digest`` SBOM обязан совпасть с ``ArtifactRecord.digest``.

Сепарация канона (не дублируем):
  - генерация SBOM       → ``ledger/sbom_inventory.generate_sbom_inventory``
                            (syft → python-inventory, COS-155);
  - durable якорь +      → ``ledger/artifact_sbom.py`` (COS-167).
    привязка sbom_ref
  - digest-контракт      → ``ArtifactRecord`` (COS-163) / ``DockerBuildResult``
                            (COS-162).
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from orchestrator.cosmo.domain.sbom_inventory import SbomInventoryDocument


class ArtifactSbomRequest(BaseModel):
    """Запрос на снятие SBOM с durable-образа (по ``name`` + ``version``).

    Образ резолвится по актуальному ``ArtifactRecord`` (latest wins, COS-163);
    digest берётся оттуда же — не передаётся клиентом и не выдумывается.
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, max_length=255)
    version: str = Field(..., min_length=1, max_length=128)


class ArtifactSbomResponse(BaseModel):
    """Результат: SBOM-документ + происхождение + привязка к артефакту."""

    model_config = ConfigDict(extra="forbid")

    name: str
    version: str
    artifact_digest: str
    canonical_ref: str
    sbom_ref: str
    generator: str
    tool_name: str = ""
    tool_version: str = ""
    content_hash: str
    document: SbomInventoryDocument