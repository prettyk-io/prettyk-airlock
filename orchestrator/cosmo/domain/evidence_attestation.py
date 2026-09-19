# -*- coding: utf-8 -*-
"""COS-147: PK-C-003.4 — attestation bundle релиза (provenance-конверт).

Формат ``cosmo-attestation@1``: субъект (артефакт) + предикат (собранные
крипто-свидетельства релиза) + детерминированный root-хэш бандла.

  - **subject** — что именно аттестуется: имя артефакта и его digest;
  - **predicate** — какие свидетельства собраны: манифест бандла (COS-142),
    аттестация SBOM (COS-138), клиренс Quality Gate (COS-141) и их digest'ы;
  - **provenance_bundle_hash** — SHA256 канонического представления
    (sort_keys, compact) субъекта и предиката: один и тот же набор фактов
    даёт один и тот же root, любое изменение — другой.

Формат digest'ов в этом контракте: ``sha256:<64 lowercase hex>``. Поля,
которые являются passthrough существующих контрактов (``sbom_digest`` —
content-hash SBOM из COS-138), сохраняют исходную форму источника.

``verified`` выставляет упаковщик (``ledger/attestation_packager.py``):
истинно, когда цепочка свидетельств непрерывна (digest артефакта совпадает
во всех собранных свидетельствах) и есть хотя бы одно digest-bearing
свидетельство.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

#: Версия формата attestation bundle.
ATTESTATION_FORMAT = "cosmo-attestation@1"

#: sha256 hex с необязательным ``sha256:``-префиксом (digest-поля конверта).
_DIGEST_RE = re.compile(r"^(sha256:)?[0-9a-f]{64}$")


def bare_hex(value: str) -> str:
    """Digest без ``sha256:``-префикса, lowercase (для сравнения)."""
    return value.split(":", 1)[1].lower() if ":" in value else value.lower()


class AttestationContractError(ValueError):
    """Нарушение контракта attestation bundle."""


class _AttestationDTO(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class EvidenceAttestationSubject(_AttestationDTO):
    """Субъект аттестации: артефакт, о котором собран конверт."""

    name: str = Field(..., min_length=1, max_length=255)
    digest: str = Field(..., min_length=1, max_length=71)

    @field_validator("digest")
    @classmethod
    def _digest_is_sha256(cls, value: str) -> str:
        if not _DIGEST_RE.match(value):
            raise ValueError(
                "subject digest must be a sha256 hex "
                "(64 lowercase hex, optional 'sha256:' prefix)"
            )
        return value

    def normalized_digest(self) -> str:
        """Digest в канонической форме ``sha256:<64 lowercase hex>``."""
        return f"sha256:{bare_hex(self.digest)}"


class EvidenceAttestationPredicate(_AttestationDTO):
    """Предикат аттестации: собранные свидетельства релиза и их digest'ы."""

    release_id: str = Field(..., min_length=1, max_length=64)
    bundle_id: Optional[str] = None
    profile: str = Field(..., min_length=1, max_length=64)
    manifest_digest_pin: Optional[str] = None
    sbom_digest: Optional[str] = None
    hub_clearance_status: Optional[str] = None
    hub_evaluation_id: Optional[str] = None
    timestamp: str = Field(..., min_length=1, max_length=64)

    @field_validator("manifest_digest_pin")
    @classmethod
    def _pin_is_sha256(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        if not _DIGEST_RE.match(value):
            raise ValueError(
                "manifest_digest_pin must be a sha256 hex "
                "(64 lowercase hex, optional 'sha256:' prefix)"
            )
        return value


class EvidenceAttestationBundle(_AttestationDTO):
    """Полный attestation bundle релиза (формат ``cosmo-attestation@1``)."""

    format: Literal["cosmo-attestation@1"] = "cosmo-attestation@1"
    subject: EvidenceAttestationSubject
    predicate: EvidenceAttestationPredicate
    provenance_bundle_hash: str
    verified: bool

    @field_validator("provenance_bundle_hash")
    @classmethod
    def _root_is_sha256(cls, value: str) -> str:
        if not _DIGEST_RE.match(value):
            raise ValueError(
                "provenance_bundle_hash must be a sha256 hex "
                "(64 lowercase hex, optional 'sha256:' prefix)"
            )
        return value


def compute_provenance_bundle_hash(
    subject: EvidenceAttestationSubject,
    predicate: EvidenceAttestationPredicate,
) -> str:
    """Детерминированный root-хэш бандла: SHA256(субъект + предикат).

    Канонизация — ``sort_keys`` + compact separators: один и тот же набор
    фактов даёт один и тот же root независимо от порядка полей; изменение
    любого поля меняет root. Возвращает ``sha256:<64 lowercase hex>``.
    """
    payload = {
        "subject": subject.model_dump(mode="json"),
        "predicate": predicate.model_dump(mode="json"),
    }
    blob = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    )
    return "sha256:" + hashlib.sha256(blob.encode("utf-8")).hexdigest()
