"""
LR-004: Instance Configuration model.

Глобальная конфигурация инстанса Cosmoport — не зашита в код,
загружается из БД или конфигурационного файла.
"""
from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field

StrictModel = ConfigDict(extra="ignore")


class RegistryProvider(BaseModel):
    """Провайдер артефактного реестра (local-oci, nexus, t1_sfera, harbor)."""
    model_config = StrictModel

    provider_type: Literal["local-oci", "nexus", "t1_sfera", "harbor"] = Field(
        default="local-oci", description="Тип реестра"
    )
    endpoint_url: str = Field(
        default="https://registry.corp.internal", min_length=1, description="URL эндпоинта реестра"
    )
    namespace: str = Field(
        default="cosmoport", description="Пространство имён / организация в реестре"
    )
    auth_ref: str = Field(
        default="vault:secret/cosmo/registry/credentials",
        description="Ссылка на креды в Vault (vault:secret/...)",
    )


class ForgeProvider(BaseModel):
    """Провайдер Git-форджа."""
    model_config = StrictModel

    provider_type: Literal["gitea", "gitlab", "github"] = Field(
        default="gitea", description="Тип форджа"
    )
    endpoint_url: str = Field(
        default="https://gitea.corp.internal", min_length=1, description="URL форджа"
    )
    auth_ref: str = Field(
        default="vault:secret/cosmo/forge/credentials",
        description="Ссылка на креды в Vault",
    )


class PrettyKProvider(BaseModel):
    """Провайдер PrettyK (SecOps endpoint)."""
    model_config = StrictModel

    endpoint_url: str = Field(
        default="https://prettyk.io/api/v1",
        description="URL внешнего PrettyK эндпоинта",
    )
    auth_ref: str = Field(
        default="vault:secret/cosmo/prettyk/credentials",
        description="Ссылка на креды в Vault",
    )
    check_timeout_seconds: int = Field(
        default=30, ge=5, description="Таймаут запроса к PrettyK"
    )


class InstanceConfiguration(BaseModel):
    """Глобальная конфигурация экземпляра Cosmoport (LR-004)."""
    model_config = StrictModel

    instance_id: str = Field(
        default="cosmo-primary", description="Уникальный идентификатор инстанса"
    )
    network_id: str = Field(
        default="kits-core-net", description="Сетевой идентификатор"
    )
    platform_label: str = Field(
        default="KITS Central Platform", description="Метка платформы"
    )
    zone: Literal["zr", "zt", "zpe"] = Field(
        default="zr", description="Зона размещения инстанса"
    )
    forge: ForgeProvider = Field(
        default_factory=ForgeProvider, description="Провайдер Git-форджа"
    )
    prettyk: PrettyKProvider = Field(
        default_factory=PrettyKProvider, description="Провайдер PrettyK"
    )
    registry: RegistryProvider = Field(
        default_factory=RegistryProvider, description="Провайдер артефактного реестра"
    )
    extra: Dict[str, Any] = Field(
        default_factory=dict, description="Расширяемые настройки"
    )