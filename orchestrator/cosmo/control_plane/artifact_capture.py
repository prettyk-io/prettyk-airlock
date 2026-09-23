# -*- coding: utf-8 -*-
"""COS-164: runtime-hook — авто-захват digest docker_build в durable ArtifactRecord.

Закрывает разрыв «образ собран и запушен, но метаданные в никуда»: когда batch
с docker_build-шагом завершается успешно, его реальные логи прогона
(``collect_all_logs``) сканируются на канонический digest-маркер
``<name>:<version>@sha256:<digest>`` (его печатает ``docker_build``-шаг после
``docker push``), и по этому digest пишется durable ``ArtifactRecord``
(``record_artifact_record``) с привязкой ``run_id`` — без ручного вызова,
не in-memory.

Honesty:
  - docker_build-шага нет → no-op (скан/динамические batch'и не имеют образа);
  - шаг есть, но маркер пустой/битый → ``MissingDockerBuildDigestError``
    (вызывающий пишет честный alert-след, а не выдумывает digest);
  - digest берётся из реального вывода, а не из спецификации.
"""
from __future__ import annotations

from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.cosmo.domain.docker_build import (
    DockerBuildSpec,
    find_docker_build_digest,
)
from orchestrator.cosmo.domain.artifact_record import ArtifactRecord
from orchestrator.cosmo.ledger.artifact_record import record_artifact_record


class MissingDockerBuildDigestError(RuntimeError):
    """docker_build-шаг завершился без канонического digest-маркера в логах."""

    def __init__(self, image_name: str, version: str, batch_id: str) -> None:
        super().__init__(
            f"docker_build batch '{batch_id}' produced no canonical digest "
            f"marker for '{image_name}:{version}' — artifact record not written"
        )
        self.image_name = image_name
        self.version = version
        self.batch_id = batch_id


def docker_build_specs(bricks: list[dict[str, Any]]) -> list[DockerBuildSpec]:
    """Спецификации docker_build-шагов из ``batch.bricks_refs``.

    ``bricks_refs`` хранит список кирпичей ``{name, definition}``; берём только
    те, у которых ``definition.type == "docker_build"``.
    """
    specs: list[DockerBuildSpec] = []
    for brick in bricks or []:
        definition = brick.get("definition") or {}
        if definition.get("type") != "docker_build":
            continue
        specs.append(DockerBuildSpec(**definition))
    return specs


def _to_artifact_record(
    spec: DockerBuildSpec,
    digest: str,
    *,
    run_id: str,
    batch_id: str,
) -> ArtifactRecord:
    return ArtifactRecord(
        name=spec.image_name,
        version=spec.version,
        digest=digest,
        registry=spec.registry,
        repository=spec.repository,
        namespace=spec.namespace,
        run_id=run_id,
        batch_id=batch_id,
    )


async def capture_artifact_records(
    session: AsyncSession,
    *,
    run_id: str,
    batch_id: str,
    bricks: list[dict[str, Any]],
    logs: dict[str, list[str]],
) -> list[str]:
    """Захватить digest каждого docker_build-шага из логов → durable записи.

    Возвращает список entry id'ов записанных ``ArtifactRecord``. Пустой
    список — docker_build-шагов в batch'е нет (no-op). Если шаг есть, но
    digest-маркер не найден — ``MissingDockerBuildDigestError`` (честно, без
    выдуманного digest).
    """
    specs = docker_build_specs(bricks)
    if not specs:
        return []

    entry_ids: list[str] = []
    missing: Optional[DockerBuildSpec] = None
    for spec in specs:
        digest = find_docker_build_digest(logs, spec.image_name, spec.version)
        if digest is None:
            missing = spec
            break
        record = _to_artifact_record(
            spec, digest, run_id=run_id, batch_id=batch_id,
        )
        entry_ids.append(await record_artifact_record(session, record))

    if missing is not None:
        raise MissingDockerBuildDigestError(
            missing.image_name, missing.version, batch_id,
        )
    return entry_ids


__all__ = [
    "MissingDockerBuildDigestError",
    "docker_build_specs",
    "capture_artifact_records",
]
