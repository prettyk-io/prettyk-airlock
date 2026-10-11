# -*- coding: utf-8 -*-
"""COS-162: build first-class — канонический docker build шаг и tag-контракт.

Закрывает «build не first-class»: ``generate_pipeline_yaml`` умеет только
generic container-шаги. Здесь — спецификация ``docker_build`` шага и
построение канонического tag из COS-142 (``<name>:<version>@sha256:<digest>``,
no-``latest``).

Инварианты (наследуем COS-142, не дублируем):
  - имя образа — строгий slug (``CanonicalArtifactTag``);
  - версия — строгий semver, без ``latest``;
  - digest — ``sha256:<64 lowercase hex>``;
  - пушить только immutable digest-тагом; плавающий ``latest`` запрещён.

Каноническая строка строится через ``CanonicalArtifactTag.canonical_ref()``
(источник истины — COS-142), а не отдельной форматной строкой.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from orchestrator.cosmo.domain.artifact_manifest import (
    CanonicalArtifactTag,
    DIGEST_RE,
    NAME_RE,
    SEMVER_RE,
)


class DockerBuildError(ValueError):
    """Нарушение контракта docker_build-шага."""


#: Поля, которые docker_build-спека несёт в ``definition`` кирпича.
_DOCKER_BUILD_FIELDS = frozenset({
    "type", "image_name", "version", "dockerfile", "context",
    "registry", "repository", "namespace", "target", "platform",
})


class DockerBuildSpec(BaseModel):
    """Спецификация первого-классного docker build шага.

    Живёт в ``definition`` кирпича (``definition.type == "docker_build"``):
    генератор пайплайна разворачивает её в ``docker build`` + ``docker push``
    с каноническим digest-тагом.
    """

    model_config = ConfigDict(extra="forbid")

    type: str = Field(default="docker_build", description="тип шага")
    image_name: str = Field(..., min_length=1, max_length=255)
    version: str = Field(..., min_length=1, max_length=128)
    dockerfile: str = Field(default="Dockerfile", min_length=1)
    context: str = Field(default=".", min_length=1)
    registry: str = Field(
        ...,
        min_length=1,
        description="endpoint registry зоны (host:port), без scheme",
    )
    repository: str = Field(default="cosmoport", min_length=1)
    namespace: str = Field(default="zr", min_length=1)
    target: str = Field(default="runtime", min_length=1, description="build stage")
    platform: str = Field(default="linux/amd64", min_length=1)

    @field_validator("image_name")
    @classmethod
    def _name_is_slug(cls, value: str) -> str:
        if not NAME_RE.match(value):
            raise ValueError(
                "image_name must be a lowercase slug (no path/uppercase)"
            )
        return value

    @field_validator("version")
    @classmethod
    def _version_is_pinned_semver(cls, value: str) -> str:
        if "latest" in value.lower():
            raise ValueError("floating tag 'latest' is forbidden")
        if not SEMVER_RE.match(value):
            raise ValueError("version must be a strict semver")
        return value

    @classmethod
    def from_definition(cls, definition: dict) -> "DockerBuildSpec":
        """COS-196: спека из ``definition`` кирпича каталога.

        API-путь каталога несёт в definition и generic-поля (executor/image/
        timeout_s/inputs/outputs) — здесь берутся строго docker_build-поля;
        ``extra=forbid`` остаётся контрактом спеки (неизвестные ключи не
        проходят), фильтрация — на границе definition → spec.
        """
        return cls(**{
            key: value for key, value in (definition or {}).items()
            if key in _DOCKER_BUILD_FIELDS
        })


@dataclass
class DockerBuildResult:
    """Результат сборки: ссылка + канонический digest-таг + Evidence-поля.

    ``digest`` — immutable ``sha256:...`` (identity образа, не плавающий тег).
    ``canonical_ref`` — полная каноническая строка COS-142.
    """

    image_name: str
    version: str
    digest: str
    registry: str
    repository: str = "cosmoport"
    namespace: str = "zr"
    metadata: dict[str, Any] = field(default_factory=dict)

    def canonical_ref(self) -> str:
        """``<name>:<version>@sha256:<digest>`` — канон COS-142."""
        tag = CanonicalArtifactTag(
            name=self.image_name, version=self.version, digest=self.digest
        )
        return tag.canonical_ref()

    def qualified_image(self) -> str:
        """Полное имя образа в registry: ``host/repository/namespace/name``."""
        parts = [self.registry, self.repository, self.namespace, self.image_name]
        return "/".join(part for part in parts if part)


def canonical_image_ref(
    image_name: str,
    version: str,
    digest: str,
    *,
    registry: str,
    repository: str = "cosmoport",
    namespace: str = "zr",
) -> str:
    """Полная каноническая ссылка образа: ``<registry>/<repo>/<ns>/<name>:<ver>@sha256:<digest>``.

    Валидация строгая: имя/версия/digest проходят COS-142 контракт; любой
    отступ (``latest``, не-semver, не-sha256) → ``DockerBuildError``, а не
    молчаливый неканоничный тег.
    """
    tag = CanonicalArtifactTag(name=image_name, version=version, digest=digest)
    base = "/".join(p for p in [registry, repository, namespace] if p)
    return f"{base}/{tag.canonical_ref()}"


def is_canonical_digest(digest: str) -> bool:
    """``sha256:<64 lowercase hex>`` — identity, которую принимаем как docker push."""
    return DIGEST_RE.match(digest) is not None


def render_docker_build_commands(spec: DockerBuildSpec, digest_output: str) -> list[str]:
    """Команды woodpecker-шага: build → push по тегу → manifest-digest.

    Возвращает list shell-команд, которые:
      1. собирают образ сразу под qualified-тегом
         ``<registry>/<repo>/<ns>/<name>:<version>``;
      2. пушат его в registry по этому тегу (no-``latest``);
      3. извлекают manifest-digest из вывода ``docker push`` (последняя
         строка ``digest: sha256:...``) в файл ``digest_output`` — это
         identity записи, которую примет registry и по которой потом идёт
         ``docker pull`` из deploy-контура.

    Digest не выдумывается: это manifest-digest, которым registry ответил на
    push (``sha256:...`` из ``digest: ...`` строки), а НЕ config-digest из
    ``docker build --iidfile`` (image id ``64f724…`` ≠ manifest digest
    ``59903d…`` — расхождение, ловившееся только на live-progоне COS-166).
    ``docker push <qualified>@$DIGEST`` неработоспособен («cannot push a
    digest reference») — push всегда по тегу; digest снимается с ответа.
    """
    qualified = "/".join(
        p for p in [spec.registry, spec.repository, spec.namespace, spec.image_name] if p
    )
    tag = f"{spec.image_name}:{spec.version}"
    qualified_tag = f"{qualified}:{spec.version}"
    return [
        "set -eu",
        f"docker build -f {spec.dockerfile} -t {qualified_tag} {spec.context}",
        (
            f"docker push {qualified_tag} 2>&1 "
            f"| grep -oE 'digest: sha256:[0-9a-f]{{64}}' "
            f"| head -n 1 | sed 's/^digest: //' > {digest_output}"
        ),
        "DIGEST=$(cat " + digest_output + ")",
        f"test -n \"$DIGEST\"",
        f"echo {tag}@$DIGEST",
    ]


# ── COS-164: runtime-hook — канонический digest-маркер из вывода шага ─────────

#: Строка, которую ``docker_build``-шаг печатает после push:
#: ``echo <name>:<version>@$DIGEST`` → ``cosmo-testapp:0.1.0@sha256:ab..``.
#: Ищем строго по контракту COS-142 (slug : semver @ sha256 lowercase-hex) и
#: с границами, чтобы не зацепить случайный фрагмент лога.
DOCKER_BUILD_MARKER_RE = re.compile(
    r"(?<![a-z0-9])"
    r"(?P<name>[a-z0-9][a-z0-9._-]*):"
    r"(?P<version>[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z.-]+)?"
    r"(?:\+[0-9A-Za-z.-]+)?)"
    r"@(?P<digest>sha256:[a-f0-9]{64})"
    r"(?![a-f0-9])"
)


def parse_docker_build_marker(line: str) -> Optional[tuple[str, str, str]]:
    """Извлечь ``(name, version, digest)`` из строки лога, если она канонична.

    Возвращает ``None`` для любой строки без строгого digest-маркера COS-142 —
    пустой/битый вывод не выдаётся за артефакт (honest, no fake).
    """
    if not line:
        return None
    m = DOCKER_BUILD_MARKER_RE.search(line)
    if m is None:
        return None
    return m.group("name"), m.group("version"), m.group("digest")


def find_docker_build_digest(
    logs: dict[str, list[str]],
    image_name: str,
    version: str,
) -> Optional[str]:
    """Digest конкретного ``(image_name, version)`` из собранных логов шагов.

    Логи имеют вид ``{step_name: [lines]}`` (результат
    ``WoodpeckerAdapter.collect_all_logs``). Сверка имени/версии не даёт
    перепутать digest одного образа с другим в мульти-образном пайплайне.
    """
    for lines in logs.values():
        for line in lines:
            marker = parse_docker_build_marker(line)
            if marker and marker[0] == image_name and marker[1] == version:
                return marker[2]
    return None


def iter_docker_build_markers(
    logs: dict[str, list[str]],
) -> Iterable[tuple[str, str, str]]:
    """Все канонические digest-маркеры ``(name, version, digest)`` из логов."""
    for lines in logs.values():
        for line in lines:
            marker = parse_docker_build_marker(line)
            if marker is not None:
                yield marker