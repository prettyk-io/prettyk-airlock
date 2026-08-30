"""
BRG-004 / NX-BUDDY-01: Registry per zone configuration — canonical endpoints.

Canonical endpoints (один источник правды):
  - Хост (dev):    localhost:5100  (compose: 5100:5000)
  - Docker (cosmo): cosmo-registry-zr:5000  (docker-compose.registry.yml env override)
  - Caddy (Docker): cosmo-registry-zr:5000  (Caddyfile.cosmo)

Cosmoport ЗР  → Registry ЗР   (dev artifacts, push allowed)
Cosmoport ЗТ  → Registry ЗТ   (staging, pull-only from ЗТ)
Cosmoport ЗПЭ → Registry ЗПЭ  (production, airgap, read-only)

Текущий target: Cosmoport ЗР → Registry ЗР.
"""

import os
from typing import Dict, Optional

from orchestrator.cosmo.adapters.artifact_registry import (
    RegistryConfig,
    RegistryProvider,
    RegistryZone,
    create_registry,
    get_available_providers,
)

# ══════════════════════════════════════════════════════════════════════════════
# Canonical endpoint resolution (NX-BUDDY-01)
# ══════════════════════════════════════════════════════════════════════════════
#
# Правило: endpoint задаётся через переменную окружения.
# Если переменная не задана — используется хост-дефолт (localhost:PORT).
# Docker Compose задаёт переменные для Docker-internal адресации.

def _resolve_endpoint(env_var: str, host_default: str) -> str:
    """Разрешить эндпоинт: env override → host default."""
    return os.environ.get(env_var, host_default)

# Canonical: один endpoint на зону
_ZR_ENDPOINT = _resolve_endpoint("REGISTRY_ZR_ENDPOINT", "http://localhost:5100")
_ZT_ENDPOINT = _resolve_endpoint("REGISTRY_ZT_ENDPOINT", "http://localhost:5200")


def get_registry_config(zone: RegistryZone) -> RegistryConfig:
    """
    Получить конфигурацию registry для зоны (BRG-004 / NX-BUDDY-01).

    Все секреты — через vault secret references, не plaintext.
    Провайдер выбирается конфигурацией, не хардкодится.
    Эндпоинты — канонические (один источник правды).
    """
    configs: Dict[RegistryZone, RegistryConfig] = {
        # ЗР (Dev): Локальный OCI-compatible smoke registry (НЕ Nexus)
        RegistryZone.ZR: RegistryConfig(
            provider=RegistryProvider.LOCAL_OCI,
            zone=RegistryZone.ZR,
            endpoint=_ZR_ENDPOINT,
            repository="cosmoport",
            namespace="zr",
            robot_account="",
            secret_ref="",
            tls_verify=False,
            labels={
                "cosmoport.zone": "zr",
                "cosmoport.role": "artifact-registry",
                "cosmoport.provider": "local-oci",
            },
        ),
        # ЗТ (Staging): Nexus OCI V2 endpoint — dirty artifacts
        RegistryZone.ZT: RegistryConfig(
            provider=RegistryProvider.NEXUS,
            zone=RegistryZone.ZT,
            endpoint=_ZT_ENDPOINT,
            repository="cosmoport",
            namespace="zt",
            robot_account="cosmo-ci",
            secret_ref="vault:secret/cosmo/registry/zt/robot-account",
            tls_verify=False,
            labels={"cosmoport.zone": "zt"},
        ),
        RegistryZone.ZPE: RegistryConfig(
            provider=RegistryProvider.T1_SFERA,
            zone=RegistryZone.ZPE,
            endpoint=_resolve_endpoint("REGISTRY_ZPE_ENDPOINT", "https://sfera-zpe.kits.bank.corp"),
            repository="cosmoport",
            namespace="zpe",
            robot_account="cosmo-zpe-svc",
            secret_ref="vault:secret/cosmo/registry/zpe/robot-account",
            tls_verify=True,
            labels={"cosmoport.zone": "zpe", "cosmoport.role": "production-registry"},
        ),
    }
    return configs[zone]


def get_registry_for_zone(zone: RegistryZone):
    """Создать экземпляр ArtifactRegistry для указанной зоны."""
    config = get_registry_config(zone)
    return create_registry(config)


def get_zr_registry():
    """Текущий target: Cosmoport ЗР → Registry ЗР."""
    return get_registry_for_zone(RegistryZone.ZR)


# ──────────────────────────────────────────────────────────────────────────────

def validate_zone_configs() -> Dict[str, Optional[str]]:
    """Проверить корректность конфигураций всех зон."""
    errors: Dict[str, Optional[str]] = {}
    for zone in RegistryZone:
        try:
            config = get_registry_config(zone)
            assert config.endpoint, f"Missing endpoint for {zone.value}"
            assert config.repository, f"Missing repository for {zone.value}"
            assert config.provider in [RegistryProvider(p) for p in get_available_providers()], \
                f"Provider {config.provider.value} not available for {zone.value}"
            errors[zone.value] = None  # OK
        except Exception as e:
            errors[zone.value] = str(e)
    return errors