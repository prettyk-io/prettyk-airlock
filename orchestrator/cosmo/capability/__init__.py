"""COS-004: CapabilityBroker — аллокатор портов и сессий по run_id.

Единый брокер, управляющий изолированными сессиями защитных инструментов:
  - привязка к run_id
  - аллокация портов (scanner, Playwright CDP, KDT Live)
  - health check: инструмент жив / готов / занят
  - освобождение при завершении run
  - таймаут сессии (зависший run)

Инвариант: два run не могут получить один порт одновременно.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from enum import Enum


class Capability(str, Enum):
    """Типы защитных инструментов, которыми управляет брокер."""
    SCANNER = "scanner"
    PLAYWRIGHT = "playwright"
    KDT_LIVE = "kdt_live"


class ResourceHealth(str, Enum):
    """Состояние инструмента."""
    HEALTHY = "healthy"      # жив и готов
    DEGRADED = "degraded"    # жив, но частично работает
    UNAVAILABLE = "unavailable"  # недоступен


@dataclass
class AllocatedPort:
    """Выделенный порт для инструмента, привязанный к run_id."""
    capability: Capability
    run_id: str
    port: int
    host: str = "127.0.0.1"
    allocated_at: float = field(default_factory=time.time)
    lease_expires_at: float = field(default_factory=lambda: time.time() + 3600.0)


class CapabilityBroker:
    """Алокатор изолированных сессий инструментов по run_id."""

    def __init__(self, base_ports: dict[Capability, int] | None = None, lease_seconds: float = 3600.0):
        self._base_ports = base_ports or {
            Capability.SCANNER: 8080,
            Capability.PLAYWRIGHT: 9222,
            Capability.KDT_LIVE: 8767,
        }
        self._lease_seconds = lease_seconds
        self._allocations: dict[Capability, dict[str, AllocatedPort]] = {
            c: {} for c in Capability
        }
        self._health: dict[Capability, ResourceHealth] = {
            c: ResourceHealth.HEALTHY for c in Capability
        }
        self._lock = threading.Lock()

    # ── Аллокация ──

    def acquire(self, run_id: str, capability: Capability) -> AllocatedPort | None:
        """Выделить порт для инструмента. Возвращает None если все заняты.

        Идемпотентно: повторный acquire с тем же run_id возвращает тот же порт.
        """
        with self._lock:
            existing = self._allocations[capability].get(run_id)
            if existing is not None:
                existing.lease_expires_at = time.time() + self._lease_seconds
                return existing

            base = self._base_ports[capability]
            used_ports = {a.port for a in self._allocations[capability].values()}
            port = base
            while port in used_ports:
                port += 1
                if port > base + 50:
                    return None

            alloc = AllocatedPort(
                capability=capability,
                run_id=run_id,
                port=port,
                lease_expires_at=time.time() + self._lease_seconds,
            )
            self._allocations[capability][run_id] = alloc
            return alloc

    def release(self, run_id: str, capability: Capability | None = None) -> int:
        count = 0
        with self._lock:
            caps = [capability] if capability else list(Capability)
            for c in caps:
                if run_id in self._allocations[c]:
                    del self._allocations[c][run_id]
                    count += 1
        return count

    def release_all(self) -> int:
        with self._lock:
            total = sum(len(m) for m in self._allocations.values())
            for c in Capability:
                self._allocations[c].clear()
            return total

    def set_health(self, capability: Capability, health: ResourceHealth) -> None:
        with self._lock:
            self._health[capability] = health

    def get_health(self, capability: Capability) -> ResourceHealth:
        with self._lock:
            return self._health[capability]

    def health_snapshot(self) -> dict[str, str]:
        with self._lock:
            return {c.value: h.value for c, h in self._health.items()}

    def is_leased(self, run_id: str, capability: Capability) -> bool:
        with self._lock:
            return run_id in self._allocations[capability]

    def recover_expired(self) -> list[AllocatedPort]:
        now = time.time()
        expired: list[AllocatedPort] = []
        with self._lock:
            for c in Capability:
                stale = [
                    a for a in self._allocations[c].values()
                    if a.lease_expires_at < now
                ]
                for a in stale:
                    del self._allocations[c][a.run_id]
                    expired.append(a)
        return expired

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "allocations": {
                    c.value: {
                        run_id: {"port": a.port, "host": a.host}
                        for run_id, a in allocs.items()
                    }
                    for c, allocs in self._allocations.items()
                },
                "health": self.health_snapshot(),
                "free_ports": {
                    c.value: self._count_free(c)
                    for c in Capability
                },
            }

    def _count_free(self, capability: Capability) -> int:
        return max(0, 50 - len(self._allocations[capability]))

    def free_port_count(self, capability: Capability) -> int:
        with self._lock:
            return self._count_free(capability)


_global_broker = CapabilityBroker()


def get_broker() -> CapabilityBroker:
    return _global_broker