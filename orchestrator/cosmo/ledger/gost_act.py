"""
COS-005: ГОСТ-Акт модели (Pydantic).

GOSTAct — структура акта приёмочного тестирования по ГОСТ:
  заголовок → объект испытаний → таблица находок → подписи.
"""
from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

StrictModel = ConfigDict(extra="ignore")


class GOSTSignature(BaseModel):
    """Подпись должностного лица под актом."""
    model_config = StrictModel

    role: str = Field(..., min_length=1, description="Должность")
    name: str = Field(..., min_length=1, description="ФИО")
    date: str = Field(..., min_length=1, description="Дата подписи")
    status: Literal["signed", "unsigned"] = Field(
        default="signed",
        description="Статус подписи",
    )


class GOSTFinding(BaseModel):
    """Одна находка в таблице результатов тестирования."""
    model_config = StrictModel

    severity: Literal["Critical", "High", "Medium", "Low", "Info"] = Field(
        ...,
        description="Уровень критичности",
    )
    title: str = Field(..., min_length=1, description="Название находки")
    description: str = Field(default="", description="Описание")
    cwe: str = Field(default="", description="CWE-идентификатор")
    evidence_refs: list[str] = Field(
        default_factory=list,
        description="Ссылки на evidence-артефакты",
    )
    recommendation: str = Field(default="", description="Рекомендация по устранению")


class GOSTActHeader(BaseModel):
    """Заголовок акта: проект, организация, номер."""
    model_config = StrictModel

    project_name: str = Field(..., min_length=1, description="Название проекта")
    act_number: str = Field(default="", description="Номер акта")
    organization: str = Field(
        default="Центральный Банк РФ",
        description="Организация-заказчик",
    )


class GOSTActObject(BaseModel):
    """Объект испытаний: наименование, URL, домен."""
    model_config = StrictModel

    name: str = Field(..., min_length=1, description="Наименование объекта")
    url: str = Field(default="", description="URL объекта")
    domain: str = Field(default="", description="Домен")


class GOSTAct(BaseModel):
    """Акт приёмочного тестирования."""
    model_config = StrictModel

    header: GOSTActHeader = Field(..., description="Заголовок акта")
    object: GOSTActObject = Field(..., description="Объект испытаний")
    findings_table: list[GOSTFinding] = Field(
        default_factory=list,
        description="Таблица находок",
    )
    signatures: list[GOSTSignature] = Field(
        default_factory=list,
        description="Подписи",
    )