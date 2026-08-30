# -*- coding: utf-8 -*-
"""COS-121: Multi-Zone Execution Context (ЗР → ЗТ → ЗПЭ).

Зональная изоляция рантайма. Валидация сетевых конвертов между контурами.
"""
from __future__ import annotations

from typing import Any, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field

ZoneName = Literal["zr", "zt", "zpe"]
ZONE_ORDER = ["zr", "zt", "zpe"]

ZONE_LABELS = {"zr": "ЗР — Зона Разработки", "zt": "ЗТ — Зона Тестирования", "zpe": "ЗПЭ — Зона Промышленной Эксплуатации"}

ZONE_NETWORKS: dict[str, list[str]] = {
    "zr": ["10.0.1.0/24", "10.0.2.0/24"],
    "zt": ["10.0.3.0/24", "10.0.4.0/24"],
    "zpe": ["10.0.10.0/24", "10.0.11.0/24"],
}

ZONE_ALLOWED_INTERACTIONS: dict[str, list[str]] = {
    "zr": ["zr", "zt"],   # Разработка может обращаться к Тестированию
    "zt": ["zt", "zpe"],   # Тестирование может обращаться к Промышленной
    "zpe": ["zpe"],        # Промышленная изолирована
}


class ZoneEnvelope(BaseModel):
    """Сетевой конверт для межзонного взаимодействия."""
    model_config = ConfigDict(extra="ignore")
    from_zone: ZoneName
    to_zone: ZoneName
    source_ip: str
    target_ip: str
    payload_type: str = "application/json"


class ZoneContext(BaseModel):
    """Контекст исполнения в конкретной зоне."""
    model_config = ConfigDict(extra="ignore")
    zone: ZoneName
    label: str = ""
    networks: list[str] = Field(default_factory=list)
    upstream_zones: list[ZoneName] = Field(default_factory=list)
    isolation_level: Literal["full", "partial", "none"] = "full"


class ZoneResolver:
    """Resolver для мультизонного контекста."""

    @staticmethod
    def context_for(zone: ZoneName) -> ZoneContext:
        upstream = [z for z in ZONE_ORDER[:ZONE_ORDER.index(zone)]]
        iso = "full" if zone == "zpe" else ("partial" if zone == "zt" else "none")
        return ZoneContext(
            zone=zone,
            label=ZONE_LABELS.get(zone, zone),
            networks=ZONE_NETWORKS.get(zone, []),
            upstream_zones=upstream,
            isolation_level=iso,
        )

    @staticmethod
    def validate_envelope(envelope: ZoneEnvelope) -> bool:
        allowed = ZONE_ALLOWED_INTERACTIONS.get(envelope.from_zone, [])
        return envelope.to_zone in allowed

    @staticmethod
    def can_promote(from_zone: ZoneName, to_zone: ZoneName) -> bool:
        """Можно ли промоутить релиз из from_zone в to_zone."""
        try:
            from_idx = ZONE_ORDER.index(from_zone)
            to_idx = ZONE_ORDER.index(to_zone)
            return to_idx == from_idx + 1  # can only promote to next zone
        except ValueError:
            return False