"""
COS-124: 16 Kinds Domain Schemas & ApplicationMetadata (Pydantic v2).

Определяет 16 типов приложений / космических кораблей космической верфи Cosmoport:
  1. Battleship          (Линкор — тяжелая высоконагруженная монолитная система КИТС)
  2. Cruiser             (Крейсер — микросервисный кластер бэкенда)
  3. SpaceStation        (Космостанция — центральный хаб / контрол-плейн)
  4. Module              (Модуль — подключаемый плагин / микросервис)
  5. Tugboat             (Буксир — вспомогательный сервис очередей / воркеров)
  6. Frigate             (Фрегат — API Gateway / reverse proxy)
  7. Interceptor         (Перехватчик — WAF / Security Sensor / IDS)
  8. Corvette            (Корвет — легковесный edge-сервис)
  9. Dreadnought         (Дредноут — ядро банковского клиринга и транзакций)
  10. Carrier            (Авианосец — CI/CD воркерная ферма)
  11. Shuttle            (Шаттл — ETL / шлюз передачи данных между зонами)
  12. Probe              (Зонд — telemetry daemon / health monitoring)
  13. MiningBarge        (Добывающая баржа — DWH / хранилище аналитики)
  14. OrbitalPlatform    (Орбитальная платформа — Kubernetes runtime)
  15. CommunicationRelay (Реле связи — Message Broker / Event Bus)
  16. Vault              (Хранилище — HSM / Secret Manager / ГОСТ ЭЦП)
"""
from __future__ import annotations

from enum import Enum
from typing import Annotated, Any, Dict, List, Literal, Optional, Union
from pydantic import BaseModel, ConfigDict, Field, field_validator

StrictConfig = ConfigDict(extra="ignore")


class ApplicationKind(str, Enum):
    BATTLESHIP = "battleship"
    CRUISER = "cruiser"
    SPACE_STATION = "space_station"
    MODULE = "module"
    TUGBOAT = "tugboat"
    FRIGATE = "frigate"
    INTERCEPTOR = "interceptor"
    CORVETTE = "corvette"
    DREADNOUGHT = "dreadnought"
    CARRIER = "carrier"
    SHUTTLE = "shuttle"
    PROBE = "probe"
    MINING_BARGE = "mining_barge"
    ORBITAL_PLATFORM = "orbital_platform"
    COMMUNICATION_RELAY = "communication_relay"
    VAULT = "vault"


class CriticalityCategory(str, Enum):
    CATEGORY_1 = "category_1"  # КИИ / КИТС 1 категории (наивысшая)
    CATEGORY_2 = "category_2"  # 2 категория
    CATEGORY_3 = "category_3"  # 3 категория


class SLATier(str, Enum):
    PLATINUM = "platinum"  # 99.999%
    GOLD = "gold"          # 99.99%
    SILVER = "silver"      # 99.9%
    BRONZE = "bronze"      # 99.0%


# ── 16 Kind Specific Configuration Schemas ───────────────────────────────────

class BattleshipConfig(BaseModel):
    """Линкор — тяжелая высоконагруженная монолитная система КИТС."""
    model_config = StrictConfig
    kind: Literal[ApplicationKind.BATTLESHIP] = ApplicationKind.BATTLESHIP
    monolith_engine: str = Field(default="enterprise_core")
    memory_limit_gb: int = Field(default=64, ge=8)
    cpu_cores: int = Field(default=32, ge=4)
    gost_mandatory: bool = Field(default=True)
    max_downtime_minutes: int = Field(default=5, le=15)


class CruiserConfig(BaseModel):
    """Крейсер — микросервисный кластер бэкенда."""
    model_config = StrictConfig
    kind: Literal[ApplicationKind.CRUISER] = ApplicationKind.CRUISER
    service_mesh: str = Field(default="istio")
    replica_count: int = Field(default=3, ge=2)
    autoscaling_enabled: bool = Field(default=True)
    ingress_protocol: str = Field(default="https_grpc")


class SpaceStationConfig(BaseModel):
    """Космостанция — центральный хаб / контрол-плейн."""
    model_config = StrictConfig
    kind: Literal[ApplicationKind.SPACE_STATION] = ApplicationKind.SPACE_STATION
    control_plane_version: str = Field(default="2.0")
    multi_region: bool = Field(default=True)
    cluster_nodes: int = Field(default=5, ge=3)
    dr_backup_interval_min: int = Field(default=15, ge=1)


class ModuleConfig(BaseModel):
    """Модуль — подключаемый плагин / микросервис."""
    model_config = StrictConfig
    kind: Literal[ApplicationKind.MODULE] = ApplicationKind.MODULE
    plugin_entrypoint: str = Field(default="main.plugin")
    sandboxed: bool = Field(default=True)
    hot_reload: bool = Field(default=False)
    api_version: str = Field(default="v1")


class TugboatConfig(BaseModel):
    """Буксир — вспомогательный сервис очередей и воркеров."""
    model_config = StrictConfig
    kind: Literal[ApplicationKind.TUGBOAT] = ApplicationKind.TUGBOAT
    queue_backend: str = Field(default="valkey")
    worker_concurrency: int = Field(default=16, ge=1)
    dead_letter_queue: bool = Field(default=True)
    max_retry_count: int = Field(default=5, ge=0)


class FrigateConfig(BaseModel):
    """Фрегат — API Gateway / reverse proxy."""
    model_config = StrictConfig
    kind: Literal[ApplicationKind.FRIGATE] = ApplicationKind.FRIGATE
    rate_limit_rps: int = Field(default=5000, ge=100)
    tls_termination: bool = Field(default=True)
    cors_strict: bool = Field(default=True)
    upstream_timeout_ms: int = Field(default=3000, ge=100)


class InterceptorConfig(BaseModel):
    """Перехватчик — WAF / Security Sensor / Anomaly detector."""
    model_config = StrictConfig
    kind: Literal[ApplicationKind.INTERCEPTOR] = ApplicationKind.INTERCEPTOR
    waf_mode: Literal["blocking", "monitoring"] = "blocking"
    ddos_protection: bool = Field(default=True)
    signature_engine_version: str = Field(default="coraza_v3")
    inspection_depth_bytes: int = Field(default=1048576)


class CorvetteConfig(BaseModel):
    """Корвет — легковесный edge-сервис."""
    model_config = StrictConfig
    kind: Literal[ApplicationKind.CORVETTE] = ApplicationKind.CORVETTE
    edge_location: str = Field(default="local_pop")
    static_caching: bool = Field(default=True)
    memory_limit_mb: int = Field(default=512, ge=128)


class DreadnoughtConfig(BaseModel):
    """Дредноут — ядро банковского клиринга и транзакций."""
    model_config = StrictConfig
    kind: Literal[ApplicationKind.DREADNOUGHT] = ApplicationKind.DREADNOUGHT
    pci_dss_level: int = Field(default=1, ge=1, le=4)
    hsm_slot_id: str = Field(default="slot_hsm_primary")
    zero_data_loss_sync: bool = Field(default=True)
    audit_chaining: bool = Field(default=True)


class CarrierConfig(BaseModel):
    """Авианосец — CI/CD воркерная ферма."""
    model_config = StrictConfig
    kind: Literal[ApplicationKind.CARRIER] = ApplicationKind.CARRIER
    runner_pool_size: int = Field(default=32, ge=2)
    container_engine: str = Field(default="docker_dind")
    isolated_network: bool = Field(default=True)
    cache_volume_gb: int = Field(default=200, ge=10)


class ShuttleConfig(BaseModel):
    """Шаттл — межзонный шлюз передачи данных (Airgap / ETL)."""
    model_config = StrictConfig
    kind: Literal[ApplicationKind.SHUTTLE] = ApplicationKind.SHUTTLE
    airgap_mode: bool = Field(default=True)
    cross_zone_protocol: str = Field(default="envelope_sftp")
    verify_envelope_on_ingest: bool = Field(default=True)
    batch_size: int = Field(default=50, ge=1)


class ProbeConfig(BaseModel):
    """Зонд — telemetry daemon / health monitoring."""
    model_config = StrictConfig
    kind: Literal[ApplicationKind.PROBE] = ApplicationKind.PROBE
    scrape_interval_sec: int = Field(default=15, ge=1)
    metrics_exporter: str = Field(default="prometheus")
    synthetic_checks: bool = Field(default=True)


class MiningBargeConfig(BaseModel):
    """Добывающая баржа — DWH / хранилище аналитики."""
    model_config = StrictConfig
    kind: Literal[ApplicationKind.MINING_BARGE] = ApplicationKind.MINING_BARGE
    dwh_engine: str = Field(default="clickhouse")
    retention_days: int = Field(default=365, ge=30)
    compression_algorithm: str = Field(default="zstd")


class OrbitalPlatformConfig(BaseModel):
    """Орбитальная платформа — Kubernetes runtime."""
    model_config = StrictConfig
    kind: Literal[ApplicationKind.ORBITAL_PLATFORM] = ApplicationKind.ORBITAL_PLATFORM
    k8s_distribution: str = Field(default="k3s_hardened")
    network_policy_enforced: bool = Field(default=True)
    node_count: int = Field(default=7, ge=3)


class CommunicationRelayConfig(BaseModel):
    """Реле связи — Message Broker / Event Bus."""
    model_config = StrictConfig
    kind: Literal[ApplicationKind.COMMUNICATION_RELAY] = ApplicationKind.COMMUNICATION_RELAY
    broker_type: Literal["valkey", "kafka", "sse_multiplex"] = "valkey"
    throughput_msg_per_sec: int = Field(default=25000, ge=1000)
    persistence_enabled: bool = Field(default=True)


class VaultConfig(BaseModel):
    """Хранилище — HSM / Secret Manager / ГОСТ ЭЦП."""
    model_config = StrictConfig
    kind: Literal[ApplicationKind.VAULT] = ApplicationKind.VAULT
    gost_crypto_provider: str = Field(default="CryptoPro_CSP_5")
    key_rotation_period_days: int = Field(default=90, ge=30)
    strict_hsm_mode: bool = Field(default=True)


# ── Discriminated Union of Kind Configs ──────────────────────────────────────

KindConfigUnion = Union[
    BattleshipConfig,
    CruiserConfig,
    SpaceStationConfig,
    ModuleConfig,
    TugboatConfig,
    FrigateConfig,
    InterceptorConfig,
    CorvetteConfig,
    DreadnoughtConfig,
    CarrierConfig,
    ShuttleConfig,
    ProbeConfig,
    MiningBargeConfig,
    OrbitalPlatformConfig,
    CommunicationRelayConfig,
    VaultConfig,
]


# ── Grand Application Metadata Model ─────────────────────────────────────────

class ApplicationMetadata(BaseModel):
    """COS-124: Pydantic v2 схема метаданных приложения / КИТС."""
    model_config = StrictConfig

    app_id: str = Field(..., min_length=1, description="Уникальный идентификатор приложения")
    name: str = Field(..., min_length=1, description="Человекочитаемое имя приложения")
    domain_id: str = Field(..., min_length=1, description="ID КИТС-домена")
    kind: ApplicationKind = Field(..., description="Тип приложения (1 из 16 видов верфи)")
    criticality: CriticalityCategory = Field(default=CriticalityCategory.CATEGORY_2)
    sla_tier: SLATier = Field(default=SLATier.GOLD)
    team: str = Field(default="core_dev")
    tags: List[str] = Field(default_factory=list)
    zones_permitted: List[str] = Field(default_factory=lambda: ["zr", "zt", "zpe"])
    config: Dict[str, Any] = Field(default_factory=dict)

    def get_typed_config(self) -> KindConfigUnion:
        """Получить строго типизированную конфигурацию согласно kind."""
        config_map = {
            ApplicationKind.BATTLESHIP: BattleshipConfig,
            ApplicationKind.CRUISER: CruiserConfig,
            ApplicationKind.SPACE_STATION: SpaceStationConfig,
            ApplicationKind.MODULE: ModuleConfig,
            ApplicationKind.TUGBOAT: TugboatConfig,
            ApplicationKind.FRIGATE: FrigateConfig,
            ApplicationKind.INTERCEPTOR: InterceptorConfig,
            ApplicationKind.CORVETTE: CorvetteConfig,
            ApplicationKind.DREADNOUGHT: DreadnoughtConfig,
            ApplicationKind.CARRIER: CarrierConfig,
            ApplicationKind.SHUTTLE: ShuttleConfig,
            ApplicationKind.PROBE: ProbeConfig,
            ApplicationKind.MINING_BARGE: MiningBargeConfig,
            ApplicationKind.ORBITAL_PLATFORM: OrbitalPlatformConfig,
            ApplicationKind.COMMUNICATION_RELAY: CommunicationRelayConfig,
            ApplicationKind.VAULT: VaultConfig,
        }
        cls_target = config_map[self.kind]
        data = dict(self.config)
        data["kind"] = self.kind
        return cls_target.model_validate(data)


def create_application_metadata(
    app_id: str,
    name: str,
    domain_id: str,
    kind: ApplicationKind | str,
    criticality: CriticalityCategory | str = CriticalityCategory.CATEGORY_2,
    sla_tier: SLATier | str = SLATier.GOLD,
    team: str = "core_dev",
    tags: Optional[List[str]] = None,
    config: Optional[Dict[str, Any]] = None,
) -> ApplicationMetadata:
    """Фабрика для создания проверенных метаданных приложения."""
    k_enum = ApplicationKind(kind) if isinstance(kind, str) else kind
    c_enum = CriticalityCategory(criticality) if isinstance(criticality, str) else criticality
    s_enum = SLATier(sla_tier) if isinstance(sla_tier, str) else sla_tier

    meta = ApplicationMetadata(
        app_id=app_id,
        name=name,
        domain_id=domain_id,
        kind=k_enum,
        criticality=c_enum,
        sla_tier=s_enum,
        team=team,
        tags=tags or [],
        config=config or {},
    )
    # Validate kind config
    _ = meta.get_typed_config()
    return meta
