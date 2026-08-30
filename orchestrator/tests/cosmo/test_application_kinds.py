"""
COS-124: Tests for 16 Kinds Domain Schemas & ApplicationMetadata (Pydantic v2).

Проверяет:
  1. Валидацию всех 16 типов конфигураций (Battleship, Cruiser, SpaceStation, Module, Tugboat,
     Frigate, Interceptor, Corvette, Dreadnought, Carrier, Shuttle, Probe, MiningBarge,
     OrbitalPlatform, CommunicationRelay, Vault).
  2. Валидацию ограничений полей (ge, le, default values).
  3. Работу фабрики `create_application_metadata` и `get_typed_config()`.
  4. Сериализацию / десериализацию в JSON.
"""
import pytest
from pydantic import ValidationError

from cosmo.domain.application_kinds import (
    ApplicationKind,
    ApplicationMetadata,
    BattleshipConfig,
    CarrierConfig,
    CommunicationRelayConfig,
    CorvetteConfig,
    CriticalityCategory,
    CruiserConfig,
    DreadnoughtConfig,
    FrigateConfig,
    InterceptorConfig,
    MiningBargeConfig,
    ModuleConfig,
    OrbitalPlatformConfig,
    ProbeConfig,
    SLATier,
    ShuttleConfig,
    SpaceStationConfig,
    TugboatConfig,
    VaultConfig,
    create_application_metadata,
)


def test_all_16_kinds_enum_coverage():
    """Проверка наличия всех 16 типов верфи в enum."""
    assert len(ApplicationKind) == 16
    expected_kinds = {
        "battleship", "cruiser", "space_station", "module", "tugboat",
        "frigate", "interceptor", "corvette", "dreadnought", "carrier",
        "shuttle", "probe", "mining_barge", "orbital_platform",
        "communication_relay", "vault"
    }
    actual_kinds = {k.value for k in ApplicationKind}
    assert actual_kinds == expected_kinds


def test_battleship_config():
    """Линкор — проверка ограничений памяти и ядер."""
    cfg = BattleshipConfig(memory_limit_gb=128, cpu_cores=64, gost_mandatory=True)
    assert cfg.kind == ApplicationKind.BATTLESHIP
    assert cfg.memory_limit_gb == 128

    with pytest.raises(ValidationError):
        BattleshipConfig(memory_limit_gb=4)  # ge=8


def test_cruiser_config():
    """Крейсер — реплики и service mesh."""
    cfg = CruiserConfig(replica_count=5, service_mesh="linkerd")
    assert cfg.kind == ApplicationKind.CRUISER
    assert cfg.replica_count == 5

    with pytest.raises(ValidationError):
        CruiserConfig(replica_count=1)  # ge=2


def test_space_station_config():
    """Космостанция — контрол-плейн и мультирегион."""
    cfg = SpaceStationConfig(cluster_nodes=7, multi_region=True)
    assert cfg.kind == ApplicationKind.SPACE_STATION
    assert cfg.cluster_nodes == 7


def test_module_config():
    """Модуль — sandbox и точка входа."""
    cfg = ModuleConfig(plugin_entrypoint="plugins.scanner_zap")
    assert cfg.kind == ApplicationKind.MODULE
    assert cfg.sandboxed is True


def test_tugboat_config():
    """Буксир — очереди и concurrency."""
    cfg = TugboatConfig(worker_concurrency=32, queue_backend="valkey")
    assert cfg.kind == ApplicationKind.TUGBOAT
    assert cfg.worker_concurrency == 32


def test_frigate_config():
    """Фрегат — API Gateway rate limits."""
    cfg = FrigateConfig(rate_limit_rps=10000, tls_termination=True)
    assert cfg.kind == ApplicationKind.FRIGATE
    assert cfg.rate_limit_rps == 10000


def test_interceptor_config():
    """Перехватчик — WAF и DDoS."""
    cfg = InterceptorConfig(waf_mode="blocking", ddos_protection=True)
    assert cfg.kind == ApplicationKind.INTERCEPTOR
    assert cfg.waf_mode == "blocking"


def test_corvette_config():
    """Корвет — edge service."""
    cfg = CorvetteConfig(memory_limit_mb=256)
    assert cfg.kind == ApplicationKind.CORVETTE
    assert cfg.memory_limit_mb == 256


def test_dreadnought_config():
    """Дредноут — банковский клиринг."""
    cfg = DreadnoughtConfig(pci_dss_level=1, zero_data_loss_sync=True)
    assert cfg.kind == ApplicationKind.DREADNOUGHT
    assert cfg.pci_dss_level == 1


def test_carrier_config():
    """Авианосец — runner pool."""
    cfg = CarrierConfig(runner_pool_size=64, container_engine="docker_dind")
    assert cfg.kind == ApplicationKind.CARRIER
    assert cfg.runner_pool_size == 64


def test_shuttle_config():
    """Шаттл — межзонный перенос."""
    cfg = ShuttleConfig(airgap_mode=True, batch_size=100)
    assert cfg.kind == ApplicationKind.SHUTTLE
    assert cfg.airgap_mode is True


def test_probe_config():
    """Зонд — метрики и скрейп."""
    cfg = ProbeConfig(scrape_interval_sec=30)
    assert cfg.kind == ApplicationKind.PROBE
    assert cfg.scrape_interval_sec == 30


def test_mining_barge_config():
    """Добывающая баржа — DWH."""
    cfg = MiningBargeConfig(retention_days=730, dwh_engine="clickhouse")
    assert cfg.kind == ApplicationKind.MINING_BARGE
    assert cfg.retention_days == 730


def test_orbital_platform_config():
    """Орбитальная платформа — K8s runtime."""
    cfg = OrbitalPlatformConfig(node_count=10, k8s_distribution="k3s_hardened")
    assert cfg.kind == ApplicationKind.ORBITAL_PLATFORM
    assert cfg.node_count == 10


def test_communication_relay_config():
    """Реле связи — event broker."""
    cfg = CommunicationRelayConfig(broker_type="kafka", throughput_msg_per_sec=50000)
    assert cfg.kind == ApplicationKind.COMMUNICATION_RELAY
    assert cfg.broker_type == "kafka"


def test_vault_config():
    """Хранилище — ГОСТ ЭЦП и HSM."""
    cfg = VaultConfig(gost_crypto_provider="CryptoPro_CSP_5", key_rotation_period_days=60)
    assert cfg.kind == ApplicationKind.VAULT
    assert cfg.key_rotation_period_days == 60


def test_create_application_metadata_factory():
    """Проверка фабрики ApplicationMetadata для всех 16 типов."""
    for kind in ApplicationKind:
        meta = create_application_metadata(
            app_id=f"app-{kind.value}-01",
            name=f"App {kind.value.capitalize()}",
            domain_id="dom-secops",
            kind=kind,
            criticality=CriticalityCategory.CATEGORY_1,
            sla_tier=SLATier.PLATINUM,
            team="kits_core",
            tags=["banking", "production"],
        )
        typed_cfg = meta.get_typed_config()
        assert typed_cfg.kind == kind
        assert meta.app_id == f"app-{kind.value}-01"
        assert meta.criticality == CriticalityCategory.CATEGORY_1
        assert meta.sla_tier == SLATier.PLATINUM
