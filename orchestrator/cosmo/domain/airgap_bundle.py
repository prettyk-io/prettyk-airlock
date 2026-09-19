# -*- coding: utf-8 -*-
"""COS-148: airgap-бандл — манифест целостности и офлайн-верификация.

Изолированный контур не ходит в сеть: целостность поставки проверяется
локально по манифесту. Манифест фиксирует список файлов пакета с их
SHA256/размером и ``package_digest_pin`` — SHA256 от отсортированных
чексумм файлов (порядок файлов на pin не влияет).

Офлайн-проверка (``ledger/airgap_verifier.py``) сравнивает манифест с
фактически наблюдаемыми чексуммами архива и выявляет:

  - ``missing_files`` — файлы манифеста, которых нет в архиве;
  - ``corrupted_files`` — файлы есть в обоих, но SHA256/размер разошлись;
  - ``unregistered_files`` — файлы архива, которых нет в манифесте
    (недоверенная/лишняя поставка).

Инварианты:
  - ``filename`` — безопасный относительный путь: без ``..``-сегментов,
    абсолютных путей, обратных слэшей и NUL (архив — недоверенный вход);
  - ``sha256`` — 64 hex, необязательный ``sha256:``-префикс;
  - ``size_bytes`` — неотрицательный.

Никаких сетевых вызовов: вся проверка — чистая логика над двумя списками.
"""
from __future__ import annotations

import re
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

#: sha256 hex с необязательным ``sha256:``-префиксом (регистр любой).
_SHA256_RE = re.compile(r"^(sha256:)?[0-9a-fA-F]{64}$")

#: Безопасный id пакета (уходит в content_ref и URL-путь).
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


def normalize_sha256(value: str) -> str:
    """SHA256 без ``sha256:``-префикса, lowercase (для сравнения)."""
    return value.split(":", 1)[1].lower() if ":" in value else value.lower()


class AirgapContractError(ValueError):
    """Нарушение контракта airgap-манифеста."""


def _validate_filename(value: str) -> str:
    if not value or not value.strip():
        raise ValueError("filename must not be empty")
    if len(value) > 512:
        raise ValueError("filename must be at most 512 chars")
    if "\x00" in value:
        raise ValueError("filename must not contain NUL")
    if "\\" in value:
        raise ValueError("filename must use '/' separators, not backslash")
    if value.startswith("/"):
        raise ValueError("filename must be a relative path")
    if re.match(r"^[A-Za-z]:", value):
        raise ValueError("filename must not be an absolute Windows path")
    segments = value.split("/")
    if any(seg in ("", ".", "..") for seg in segments):
        raise ValueError(
            "filename must not contain empty, '.' or '..' path segments"
        )
    return value


class _AirgapDTO(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class AirgapFileChecksum(_AirgapDTO):
    """Чексумма одного файла пакета (имя + sha256 + размер)."""

    filename: str = Field(..., min_length=1, max_length=512)
    sha256: str = Field(..., min_length=64, max_length=71)
    size_bytes: int = Field(..., ge=0)

    @field_validator("filename")
    @classmethod
    def _filename_is_safe(cls, value: str) -> str:
        return _validate_filename(value)

    @field_validator("sha256")
    @classmethod
    def _sha256_is_canonical(cls, value: str) -> str:
        if not _SHA256_RE.match(value):
            raise ValueError(
                "sha256 must be 64 hex chars (optional 'sha256:' prefix)"
            )
        return value

    def normalized_sha256(self) -> str:
        """SHA256 в канонической форме: lowercase bare hex."""
        return normalize_sha256(self.sha256)


class AirgapPackageManifest(_AirgapDTO):
    """Манифест airgap-пакета: состав + digest-pin."""

    package_id: str = Field(..., min_length=1, max_length=128)
    release_id: str = Field(..., min_length=1, max_length=64)
    created_at: str = Field(..., min_length=1, max_length=64)
    files: list[AirgapFileChecksum] = Field(default_factory=list)
    package_digest_pin: str = Field(..., min_length=64, max_length=71)

    @field_validator("package_id")
    @classmethod
    def _package_id_is_safe(cls, value: str) -> str:
        if not _SAFE_ID_RE.match(value):
            raise ValueError(
                "package_id must match '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'"
            )
        return value

    @field_validator("package_digest_pin")
    @classmethod
    def _pin_is_canonical(cls, value: str) -> str:
        if not _SHA256_RE.match(value):
            raise ValueError(
                "package_digest_pin must be 64 hex chars "
                "(optional 'sha256:' prefix)"
            )
        return value


class AirgapVerifyRequest(_AirgapDTO):
    """Запрос офлайн-верификации: манифест + фактически наблюдаемые чексуммы."""

    manifest: AirgapPackageManifest
    archive_files: list[AirgapFileChecksum] = Field(default_factory=list)


class AirgapVerifyResponse(_AirgapDTO):
    """Вердикт офлайн-проверки airgap-пакета."""

    verified: bool
    package_id: str
    missing_files: list[str] = Field(default_factory=list)
    corrupted_files: list[str] = Field(default_factory=list)
    unregistered_files: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
