"""
COS-L2: Pydantic модель App Graph (Космопорт).

Application Graph — иерархия приложений внутри Domain:
  Level 0: библиотеки
  Level 1-3: приложения
  Group: папка/группа приложений
"""
from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

StrictModel = ConfigDict(extra="ignore")


class RepositoryBinding(BaseModel):
    """Привязка приложения к репозиторию в forge."""
    model_config = StrictModel

    forge_id: str = Field(
        ...,
        min_length=1,
        description="ID forge-инстанса (из Domain.ForgeBinding)",
    )
    repo_path: str = Field(
        ...,
        min_length=1,
        description="Путь к репозиторию (owner/repo)",
    )
    default_branch: str = Field(
        default="main",
        min_length=1,
        description="Ветка по умолчанию",
    )
    webhook_id: str | None = Field(
        default=None,
        description="ID webhook'а в forge (заполняется после регистрации)",
    )


class Group(BaseModel):
    """Группа приложений (папка) — может быть вложенной."""
    model_config = StrictModel

    id: str = Field(..., min_length=1)
    domain_id: str = Field(..., min_length=1)
    parent_group_id: str | None = Field(
        default=None,
        description="Родительская группа (None = корень домена)",
    )
    level: int = Field(
        default=0,
        ge=0,
        le=3,
        description="Уровень вложенности 0..3",
    )
    name: str = Field(..., min_length=1)


class Application(BaseModel):
    """Приложение внутри Domain — Level 0..3."""
    model_config = StrictModel

    id: str = Field(..., min_length=1)
    domain_id: str = Field(..., min_length=1)
    level: int = Field(
        ...,
        ge=0,
        le=3,
        description="Уровень: 0=библиотека, 1-3=приложение",
    )
    group_id: str | None = Field(
        default=None,
        description="Группа, которой принадлежит приложение",
    )
    repo_binding: RepositoryBinding = Field(
        ...,
        description="Привязка к репозиторию",
    )
    pipeline_plan_id: str | None = Field(
        default=None,
        description="ID скомпилированного pipeline-плана",
    )


class AppGraph(BaseModel):
    """Граф приложений домена: группы + приложения + библиотеки."""
    model_config = StrictModel

    domain: str = Field(
        ...,
        min_length=1,
        description="ID домена",
    )
    groups: list[Group] = Field(
        default_factory=list,
        description="Группы (папки) приложений",
    )
    apps: list[Application] = Field(
        default_factory=list,
        description="Приложения уровня 1-3",
    )
    libraries: list[Application] = Field(
        default_factory=list,
        description="Библиотеки уровня 0",
    )

    @model_validator(mode="after")
    def no_cycles_in_groups(self) -> "AppGraph":
        """Проверка: нет циклов в иерархии групп."""
        by_parent: dict[str | None, list[Group]] = {}
        for g in self.groups:
            pid = g.parent_group_id
            by_parent.setdefault(pid, []).append(g)

        visited: set[str] = set()
        stack: set[str] = set()

        def dfs(gid: str) -> bool:
            """True если цикл."""
            if gid in stack:
                return True
            if gid in visited:
                return False
            visited.add(gid)
            stack.add(gid)
            for child in by_parent.get(gid, []):
                if dfs(child.id):
                    return True
            stack.discard(gid)
            return False

        for g in self.groups:
            if g.id not in visited:
                if dfs(g.id):
                    raise ValueError("Обнаружен цикл в иерархии групп")
        return self

    @field_validator("apps", "libraries")
    @classmethod
    def validate_level(cls, v: list[Application], info) -> list[Application]:
        """Приложения в apps должны быть level 1-3, в libraries — level 0."""
        field_name = info.field_name
        for app in v:
            if field_name == "apps" and app.level < 1:
                raise ValueError(f"apps должен содержать level >= 1, получен {app.level}")
            if field_name == "libraries" and app.level != 0:
                raise ValueError(f"libraries должен содержать level 0, получен {app.level}")
        return v