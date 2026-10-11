"""
COS-L3: Pydantic модель Pipeline Brick (Космопорт).

Brick — атомарный шаг пайплайна (SAST, SCA, Build, Deploy, DAST, Autotest, Gate).
BrickOverride — переопределение параметров для конкретного Domain.
"""
from __future__ import annotations

from typing import Literal, Optional
from pydantic import BaseModel, ConfigDict, Field

StrictModel = ConfigDict(extra="ignore")

BrickType = Literal["sast", "sca", "build", "deploy", "dast", "autotest", "gate"]


class BrickDefinition(BaseModel):
    """Рантайм-определение Brick: executor, образ, таймауты, inputs/outputs."""
    model_config = StrictModel

    executor: Literal["woodpecker", "jenkins", "github-actions"] = Field(
        default="woodpecker",
        description="CI-исполнитель",
    )
    image: str = Field(
        default="",
        description="Docker-образ (например sonarsource/sonar-scanner-cli:latest); "
                    "docker_build-специализация несёт образ шага сама (docker:24-cli)",
    )
    timeout_s: int = Field(
        default=3600,
        ge=1,
        description="Таймаут шага в секундах",
    )
    inputs: dict = Field(
        default_factory=dict,
        description="Входные параметры (env vars, volumes, secrets)",
    )
    outputs: dict = Field(
        default_factory=dict,
        description="Выходные артефакты (пути, форматы)",
    )

    # COS-196: docker_build-специализация кирпича (канон COS-162) — раньше
    # API-схема её не несла (extras игнорировались), и каталог наполнялся
    # только прямым upsert'ом. Теперь дефиниция проходит API-путь целиком.
    type: Optional[str] = Field(
        default=None,
        description="Специализация шага (docker_build — build + push по канону COS-162)",
    )
    image_name: Optional[str] = Field(
        default=None, description="Имя образа docker_build-шага (slug)")
    version: Optional[str] = Field(
        default=None, description="Версия образа docker_build-шага (строгий semver)")
    dockerfile: Optional[str] = Field(
        default=None, description="Путь к Dockerfile (docker_build)")
    context: Optional[str] = Field(
        default=None, description="Build-контекст (docker_build)")
    registry: Optional[str] = Field(
        default=None, description="Endpoint registry зоны, host:port (docker_build)")
    repository: Optional[str] = Field(
        default=None, description="Repository в registry (docker_build)")
    namespace: Optional[str] = Field(
        default=None, description="Namespace/зона registry (docker_build)")
    target: Optional[str] = Field(
        default=None, description="Build stage (docker_build)")
    platform: Optional[str] = Field(
        default=None, description="Платформа сборки (docker_build)")


class PipelineBrick(BaseModel):
    """Атомарный шаг pipeline-плана."""
    model_config = StrictModel

    id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    type: BrickType = Field(..., description="Тип шага")
    source: str = Field(
        ...,
        min_length=1,
        description="Источник: repo_path или internal",
    )
    definition: BrickDefinition = Field(
        ...,
        description="Рантайм-определение",
    )
    depends_on: list[str] = Field(
        default_factory=list,
        description="ID кирпичей, от которых зависит этот",
    )
    gates: list[str] = Field(
        default_factory=list,
        description="ID gate'ов, связанных с этим кирпичом",
    )


class BrickOverride(BaseModel):
    """Переопределение Brick для конкретного Domain."""
    model_config = StrictModel

    brick_id: str = Field(
        ...,
        min_length=1,
        description="ID переопределяемого кирпича",
    )
    domain_id: str = Field(
        ...,
        min_length=1,
        description="ID домена, для которого переопределение",
    )
    overrides_json: dict = Field(
        default_factory=dict,
        description="JSON-переопределения полей BrickDefinition",
    )