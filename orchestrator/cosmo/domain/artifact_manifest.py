# -*- coding: utf-8 -*-
"""COS-142: PK-C-003.4 — canonical artifact tags и digest-pin манифеста бандла.

Требование PK-C-003.4 «One bundle, canonical tags»: образ/артефакт собирается
один раз, регистрируется ровно одним каноническим tag-форматом
(``<name>:<version>@sha256:<digest>``, без плавающего ``latest``), а бандл
поставки описывается манифестом с digest-pin — расхождение версий ядро/стенд
становится невозможно by construction.

Инварианты:
  - ``name`` — строгий slug (нижний регистр, без пути и спецсимволов);
  - ``version`` — строгий semver ``major.minor.patch`` (+ prerelease/build);
  - ``digest`` — ровно ``sha256:`` + 64 lowercase-hex;
  - ``latest`` запрещён в любой позиции версии (плавающий тег = незакреплённая
    поставка);
  - ``artifacts`` манифеста непуст, ``profile`` — закрытый набор профилей
    поставки.

``digest_pin`` бандла считается сервисом ``ledger/manifest_verifier.py``;
здесь живёт канонический ``manifest_content_hash`` — крипто-якорь записи в
evidence ledger (по образцу ``sbom_content_hash`` из COS-138).
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

#: Канонический digest артефакта: только sha256 и только lowercase-hex.
DIGEST_RE = re.compile(r"^sha256:[a-f0-9]{64}$")

#: Имя артефакта — строгий slug (lowercase, без пути/спецсимволов).
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")

#: Строгий semver: major.minor.patch + необязательные prerelease/build.
SEMVER_RE = re.compile(
    r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$"
)

#: ``bundle_id`` уходит в content_ref и в URL-путь чтения — без слэшей/пробелов.
BUNDLE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")

#: Плавающий тег, запрещённый в любой позиции версии.
FORBIDDEN_TAG = "latest"

#: Закрытый набор профилей поставки.
BundleProfile = Literal["ordinary@1", "hardened@1", "airgap@1"]


class ArtifactManifestError(ValueError):
    """Нарушение контракта canonical tag / bundle manifest."""


def normalize_digest_pin(value: str) -> str:
    """Привести digest-pin к канонической форме ``sha256:<64 lowercase hex>``.

    Принимает pin с префиксом и без (``sha256:ab..`` / ``ab..``), возвращает
    канонический вид. Пустое значение/не-hex → ``ArtifactManifestError``.
    """
    raw = (value or "").strip()
    if not raw:
        raise ArtifactManifestError("digest_pin must not be empty")
    body = raw.split(":", 1)[1] if ":" in raw else raw
    body = body.lower()
    if not re.fullmatch(r"[a-f0-9]{64}", body):
        raise ArtifactManifestError(
            "digest_pin must be a sha256 hex (64 lowercase hex chars)"
        )
    return f"sha256:{body}"


class _ManifestDTO(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class CanonicalArtifactTag(_ManifestDTO):
    """Канонический tag артефакта: имя + закреплённая версия + digest."""

    name: str = Field(..., min_length=1, max_length=255)
    version: str = Field(..., min_length=1, max_length=128)
    digest: str = Field(..., min_length=71, max_length=71)

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
        """Каноническая строка ``<name>:<version>@sha256:<digest>``."""
        return f"{self.name}:{self.version}@{self.digest}"


class ArtifactBundleManifest(_ManifestDTO):
    """Манифест бандла поставки: профиль + артефакты + ожидаемый digest-pin."""

    bundle_id: str = Field(..., min_length=1, max_length=128)
    release_version: str = Field(..., min_length=1, max_length=128)
    profile: BundleProfile
    artifacts: list[CanonicalArtifactTag] = Field(..., min_length=1)
    expected_digest_pin: Optional[str] = None
    created_at: str = Field(..., min_length=1, max_length=64)
    # COS-142 (extension): якорь ledger-записи. ``run_id`` — NOT NULL FK на
    # runs.id, а у самого манифеста прогона нет; передаётся контекстом
    # верификации. Без него верификация остаётся валидной, но не якорится
    # (``ledger_entry_id=None``) — честная граница.
    run_id: Optional[str] = None

    @field_validator("bundle_id")
    @classmethod
    def _bundle_id_is_safe(cls, value: str) -> str:
        if not BUNDLE_ID_RE.match(value):
            raise ValueError(
                "bundle_id must match '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'"
            )
        return value

    @field_validator("release_version")
    @classmethod
    def _release_version_is_pinned(cls, value: str) -> str:
        if FORBIDDEN_TAG in value.lower():
            raise ValueError("release_version must not contain 'latest'")
        return value

    @field_validator("expected_digest_pin")
    @classmethod
    def _pin_is_canonical(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        return normalize_digest_pin(value)

    @field_validator("run_id")
    @classmethod
    def _run_id_is_safe(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        if not re.fullmatch(r"[A-Za-z0-9._:-]{1,64}", value):
            raise ValueError("run_id must be a plain id (letters/digits/._:-)")
        return value

    def canonical_refs(self) -> list[str]:
        """Отсортированные канонические ref'ы всех артефактов бандла."""
        return sorted(artifact.canonical_ref() for artifact in self.artifacts)


class ManifestVerificationResult(_ManifestDTO):
    """Вердикт верификации манифеста (не исключение: расчёт + фиксация)."""

    valid: bool
    bundle_id: str
    digest_pin: str
    artifacts_count: int
    errors: list[str] = Field(default_factory=list)
    ledger_entry_id: Optional[str] = None


def manifest_content_hash(manifest: ArtifactBundleManifest) -> str:
    """Канонический sha256 содержимого манифеста (sort_keys, compact).

    Крипто-якорь ledger-записи: тот же приём, что ``sbom_content_hash``
    (COS-138) — подпись замороженного представления, а не «доверие на слово».
    """
    payload = json.dumps(
        manifest.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
