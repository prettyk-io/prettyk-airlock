"""
COS-071: SonarQube Community Worker Pool — жизненный цикл эфемерных контейнеров.

Пул эфемерных контейнеров SonarQube CE с PostgreSQL-аллокатором портов,
защитой от зомби-контейнеров и идемпотентным teardown'ом.

Инварианты:
  - Порты аллоцируются через PortLeaseTracker (PG), НЕ random.randint
  - Контейнеры имеют детерминированные метки (com.prettyk.*)
  - Готовность SonarQube CE проверяется по ceTaskId из report-task.txt
  - reconcile_orphans() находит зависшие контейнеры по Docker-лейблам
  - teardown идемпотентен: повторный вызов не падает
  - Два run не могут получить один порт одновременно
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from cosmo.domain.worker_lease import WorkerLease, WorkerState, FailureReason

logger = logging.getLogger("cosmoport.sonar_pool")


# ── Port Lease Tracker ──────────────────────────────────────────────────────

@dataclass
class PortAllocation:
    """Выделенный порт для SonarQube CE worker'а."""
    port: int
    run_id: str
    worker_id: str
    allocated_at: float = field(default_factory=time.time)
    lease_expires_at: float = field(default_factory=lambda: time.time() + 3600.0)


class PortLeaseTracker:
    """COS-071: трекер портов — гарантирует уникальность портов между run'ами.

    In-memory (dev) — production должен быть на PostgreSQL с SELECT FOR UPDATE.
    """

    _DEFAULT_PORT_RANGE = range(9000, 9050)  # 50 портов для SonarQube CE workers

    def __init__(self, port_range: range | None = None):
        self._port_range = port_range or self._DEFAULT_PORT_RANGE
        self._allocations: dict[int, PortAllocation] = {}  # port → allocation
        self._by_run: dict[str, PortAllocation] = {}        # run_id → allocation
        self._lock = threading.Lock()

    def acquire(self, run_id: str, worker_id: str) -> int | None:
        """Аллоцировать порт для run. Идемпотентно: повторный вызов возвращает тот же порт."""
        with self._lock:
            # Идемпотентность
            existing = self._by_run.get(run_id)
            if existing is not None:
                existing.lease_expires_at = time.time() + 3600.0  # продлить лиз
                return existing.port

            # Найти свободный порт
            for port in self._port_range:
                if port not in self._allocations:
                    alloc = PortAllocation(
                        port=port, run_id=run_id, worker_id=worker_id,
                    )
                    self._allocations[port] = alloc
                    self._by_run[run_id] = alloc
                    return port

            return None  # все порты заняты

    def release(self, run_id: str) -> int | None:
        """Освободить порт. Возвращает номер порта или None."""
        with self._lock:
            alloc = self._by_run.pop(run_id, None)
            if alloc is None:
                return None
            self._allocations.pop(alloc.port, None)
            return alloc.port

    def is_allocated(self, run_id: str) -> bool:
        with self._lock:
            return run_id in self._by_run

    def allocated_port(self, run_id: str) -> int | None:
        with self._lock:
            alloc = self._by_run.get(run_id)
            return alloc.port if alloc else None

    def recover_expired(self) -> list[PortAllocation]:
        """Освободить порты с истёкшим лизом (зомби-воркеры)."""
        now = time.time()
        expired: list[PortAllocation] = []
        with self._lock:
            for port, alloc in list(self._allocations.items()):
                if alloc.lease_expires_at < now:
                    del self._allocations[port]
                    self._by_run.pop(alloc.run_id, None)
                    expired.append(alloc)
        return expired

    @property
    def free_count(self) -> int:
        with self._lock:
            used = len(self._allocations)
            return max(0, len(self._port_range) - used)

    @property
    def used_count(self) -> int:
        with self._lock:
            return len(self._allocations)

    @property
    def snapshot(self) -> dict:
        with self._lock:
            used = len(self._allocations)
            total = len(self._port_range)
            return {
                "used_ports": sorted(self._allocations.keys()),
                "free_count": max(0, total - used),
                "total_ports": total,
                "allocations": {
                    run_id: {"port": a.port, "worker_id": a.worker_id}
                    for run_id, a in self._by_run.items()
                },
            }


# ── Docker Backend (ABC) ────────────────────────────────────────────────────

class DockerBackend(ABC):
    """Абстракция над Docker для тестируемости."""

    @abstractmethod
    def run_container(self, image: str, name: str, port: int, labels: dict[str, str],
                      env: dict[str, str] | None = None) -> str:
        """Запустить контейнер, вернуть container_id."""
        raise NotImplementedError

    @abstractmethod
    def stop_container(self, container_id: str, timeout: int = 10) -> bool:
        """Остановить контейнер. Возвращает успех."""
        raise NotImplementedError

    @abstractmethod
    def remove_container(self, container_id: str, force: bool = False) -> bool:
        """Удалить контейнер."""
        raise NotImplementedError

    @abstractmethod
    def inspect_container(self, container_id: str) -> dict | None:
        """Инспектировать контейнер (состояние, exit_code). Возвращает None если не найден."""
        raise NotImplementedError

    @abstractmethod
    def list_containers(self, label_filters: list[str]) -> list[str]:
        """Список container_id по label-фильтрам."""
        raise NotImplementedError

    @abstractmethod
    def is_running(self, container_id: str) -> bool:
        """Жив ли контейнер."""
        raise NotImplementedError


# ── In-Memory Mock Docker Backend ───────────────────────────────────────────

class MockDockerBackend(DockerBackend):
    """In-memory Docker backend для тестов и dev-режима."""

    def __init__(self):
        self._containers: dict[str, dict] = {}  # container_id → {name, image, port, labels, running}
        self._counter = 0

    def run_container(self, image: str, name: str, port: int, labels: dict[str, str],
                      env: dict[str, str] | None = None) -> str:
        self._counter += 1
        cid = f"mock-{uuid.uuid4().hex[:12]}"
        self._containers[cid] = {
            "image": image, "name": name, "port": port,
            "labels": dict(labels), "running": True,
            "env": env or {},
        }
        return cid

    def stop_container(self, container_id: str, timeout: int = 10) -> bool:
        if container_id not in self._containers:
            return True  # идемпотентность: уже нет → успех
        self._containers[container_id]["running"] = False
        return True

    def remove_container(self, container_id: str, force: bool = False) -> bool:
        if container_id not in self._containers:
            return True  # идемпотентность
        if not force and self._containers[container_id]["running"]:
            return False
        del self._containers[container_id]
        return True

    def inspect_container(self, container_id: str) -> dict | None:
        return self._containers.get(container_id)

    def list_containers(self, label_filters: list[str]) -> list[str]:
        result = []
        for cid, info in self._containers.items():
            labels = info.get("labels", {})
            match = True
            for filt in label_filters:
                if "=" in filt:
                    k, v = filt.split("=", 1)
                    if labels.get(k) != v:
                        match = False
                        break
            if match:
                result.append(cid)
        return result

    def is_running(self, container_id: str) -> bool:
        c = self._containers.get(container_id)
        return c["running"] if c else False


# ── SonarQube Worker Pool ───────────────────────────────────────────────────

class SonarWorkerPool:
    """COS-071: пул эфемерных воркеров SonarQube CE.

    Управляет жизненным циклом контейнеров: запуск, мониторинг,
    сбор результатов, teardown, очистка зомби.
    """

    _DEFAULT_IMAGE = "sonarsource/sonar-scanner-cli:latest"
    _DEFAULT_SONAR_HOST = "http://sonarqube:9000"
    _PROVISION_TIMEOUT = 60.0       # макс время ожидания контейнера
    _SCAN_TIMEOUT = 600.0           # макс время сканирования (10 мин)
    _COLLECT_TIMEOUT = 120.0        # макс время сбора результатов

    def __init__(
        self,
        docker: DockerBackend,
        port_tracker: PortLeaseTracker | None = None,
        sonar_host: str = _DEFAULT_SONAR_HOST,
        scanner_image: str = _DEFAULT_IMAGE,
    ):
        self._docker = docker
        self._ports = port_tracker or PortLeaseTracker()
        self._sonar_host = sonar_host.rstrip("/")
        self._scanner_image = scanner_image
        self._workers: dict[str, WorkerLease] = {}  # worker_id → lease
        self._lock = threading.Lock()

    # ── Worker lifecycle ────────────────────────────────────────────────────

    def request_worker(self, run_id: str, sonar_project_key: str = "",
                       sonar_token: str = "") -> WorkerLease:
        """Запросить воркер для run. Создаёт WorkerLease в состоянии REQUESTED."""
        with self._lock:
            # Идемпотентность: тот же run_id → тот же worker
            for w in self._workers.values():
                if w.run_id == run_id and not w.is_terminal:
                    return w

            # Аллоцировать порт
            worker_id = f"sonar-{uuid.uuid4().hex[:12]}"
            port = self._ports.acquire(run_id, worker_id)

            lease = WorkerLease(
                worker_id=worker_id,
                run_id=run_id,
                sonar_project_key=sonar_project_key,
                allocated_port=port or 0,
                state=WorkerState.REQUESTED,
            )
            self._workers[worker_id] = lease
            return lease

    def provision(self, lease: WorkerLease) -> WorkerLease:
        """COS-071: запустить Docker-контейнер для воркера. REQUESTED → PROVISIONING → READY."""
        if lease.state not in (WorkerState.REQUESTED, WorkerState.PROVISIONING):
            raise ValueError(f"Cannot provision worker in state {lease.state.value}")

        lease = self._try_transition(lease, WorkerState.PROVISIONING)
        if lease.state == WorkerState.FAILED:
            return lease

        try:
            labels = lease.default_labels()
            container_id = self._docker.run_container(
                image=self._scanner_image,
                name=f"sonar-ce-{lease.run_id}",
                port=lease.allocated_port,
                labels=labels,
                env={
                    "SONAR_HOST_URL": self._sonar_host,
                    "SONAR_PROJECT_KEY": lease.sonar_project_key,
                },
            )
            # Обновить lease с container_id
            lease_data = lease.model_dump()
            lease_data["container_id"] = container_id
            lease_data["state"] = WorkerState.PROVISIONING
            lease = WorkerLease.model_validate(lease_data)
        except Exception as exc:
            return self._fail_with_teardown(lease, FailureReason.INFRA_FAILED, str(exc))

        # Опрос готовности: контейнер запущен → READY
        try:
            if not self._docker.is_running(container_id):
                return self._fail_with_teardown(lease, FailureReason.INFRA_FAILED, "container not running after start")
        except Exception as exc:
            return self._fail_with_teardown(lease, FailureReason.INFRA_FAILED, str(exc))

        lease = self._try_transition(lease, WorkerState.READY)
        self._update_worker(lease)
        return lease

    def start_scan(self, lease: WorkerLease) -> WorkerLease:
        """Запустить сканирование. READY → RUNNING."""
        if lease.state != WorkerState.READY:
            raise ValueError(f"Cannot start scan in state {lease.state.value}")
        lease = self._try_transition(lease, WorkerState.RUNNING)
        self._update_worker(lease)
        return lease

    def register_sonar_task(self, lease: WorkerLease, ce_task_id: str) -> WorkerLease:
        """COS-071: зарегистрировать ceTaskId из report-task.txt."""
        if lease.state not in (WorkerState.RUNNING, WorkerState.COLLECTING):
            raise ValueError(f"Cannot register task in state {lease.state.value}")
        lease_data = lease.model_dump()
        lease_data["sonar_task_id"] = ce_task_id
        lease_data["updated_at"] = time.time()
        return WorkerLease.model_validate(lease_data)

    def collect_results(self, lease: WorkerLease) -> WorkerLease:
        """Завершить сканирование, собрать результаты. RUNNING → COLLECTING → PUBLISHING."""
        if lease.state not in (WorkerState.RUNNING, WorkerState.COLLECTING):
            raise ValueError(f"Cannot collect results in state {lease.state.value}")
        lease = self._try_transition(lease, WorkerState.COLLECTING)
        lease = self._try_transition(lease, WorkerState.PUBLISHING)
        self._update_worker(lease)
        return lease

    def teardown_worker(self, lease: WorkerLease) -> WorkerLease:
        """COS-071: идемпотентный teardown — остановка контейнера + освобождение порта.

        Может вызываться многократно без ошибок.
        """
        if lease.state in (WorkerState.RELEASED,):
            return lease  # уже освобождён

        # Остановить контейнер (если есть) — идемпотентно
        if lease.container_id:
            try:
                self._docker.stop_container(lease.container_id, timeout=10)
            except Exception as exc:
                logger.warning("stop_container failed for %s: %s", lease.worker_id, exc)

            try:
                self._docker.remove_container(lease.container_id, force=True)
            except Exception as exc:
                logger.warning("remove_container failed for %s: %s", lease.worker_id, exc)

        # Освободить порт — идемпотентно
        if lease.allocated_port > 0:
            self._ports.release(lease.run_id)

        # Переходы: TEARDOWN → RELEASED. Если не в TEARDOWN — FAULT.
        try:
            if lease.state != WorkerState.TEARDOWN:
                lease = lease.fail(
                    FailureReason.INFRA_FAILED,
                    f"force teardown from {lease.state.value}",
                )
            # FAILED → TEARDOWN → RELEASED
            if lease.state == WorkerState.FAILED:
                lease = lease.transition(WorkerState.TEARDOWN)
            lease = lease.transition(WorkerState.RELEASED)
        except ValueError:
            # Если уже в RELEASED или переход невозможен — вернуть как есть
            # (идемпотентность: уже всё сделано)
            pass

        # Сохранить в реестр
        self._update_worker(lease)

        # Всегда возвращаем lease в RELEASED
        if lease.state != WorkerState.RELEASED:
            lease_data = lease.model_dump()
            lease_data["state"] = WorkerState.RELEASED
            lease = WorkerLease.model_validate(lease_data)

        return lease

    # ── Orphan reconciliation ───────────────────────────────────────────────

    def reconcile_orphans(self) -> list[WorkerLease]:
        """COS-071: найти и очистить зомби-контейнеры.

        При рестарте оркестратора находит контейнеры без активного worker'а
        в пуле и корректно их удаляет.
        """
        orphan_leases: list[WorkerLease] = []

        # Найти все контейнеры по лейблам
        container_ids = self._docker.list_containers(
            WorkerLease.label_filters()
        )

        known_container_ids = {
            w.container_id for w in self._workers.values()
            if w.container_id
        }

        for cid in container_ids:
            if cid not in known_container_ids:
                # Зомби — создаём синтетический lease для teardown
                info = self._docker.inspect_container(cid)
                run_id = ""
                if info:
                    labels = info.get("labels", {})
                    run_id = labels.get("com.prettyk.run_id", "")

                orphan = WorkerLease(
                    worker_id=f"orphan-{cid[:8]}",
                    run_id=run_id,
                    container_id=cid,
                    state=WorkerState.FAILED,
                    failure_reason=FailureReason.CONTAINER_STALE,
                )
                self.teardown_worker(orphan)
                orphan_leases.append(orphan)

        # Освободить истёкшие порты
        expired_ports = self._ports.recover_expired()
        for alloc in expired_ports:
            logger.info("Released expired port %d for run %s", alloc.port, alloc.run_id)

        return orphan_leases

    # ── Query ───────────────────────────────────────────────────────────────

    def get_worker(self, worker_id: str) -> WorkerLease | None:
        with self._lock:
            return self._workers.get(worker_id)

    def get_worker_by_run(self, run_id: str) -> WorkerLease | None:
        with self._lock:
            for w in self._workers.values():
                if w.run_id == run_id:
                    return w
        return None

    def list_workers(self) -> list[WorkerLease]:
        with self._lock:
            return list(self._workers.values())

    def active_workers(self) -> list[WorkerLease]:
        with self._lock:
            return [w for w in self._workers.values() if w.is_active]

    def port_snapshot(self) -> dict:
        return self._ports.snapshot

    # ── Internal ────────────────────────────────────────────────────────────

    def _try_transition(self, lease: WorkerLease, target: WorkerState) -> WorkerLease:
        try:
            return lease.transition(target)
        except ValueError as exc:
            return lease.fail(FailureReason.INFRA_FAILED, str(exc))

    def _fail_with_teardown(self, lease: WorkerLease, reason: FailureReason,
                            detail: str = "") -> WorkerLease:
        """Перевести в FAILED и сразу запустить teardown (идемпотентно)."""
        if lease.state != WorkerState.FAILED:
            try:
                lease = lease.fail(reason, detail)
            except ValueError:
                pass  # уже failed или в невалидном состоянии
        self._update_worker(lease)
        return self.teardown_worker(lease)

    def _update_worker(self, lease: WorkerLease) -> None:
        with self._lock:
            self._workers[lease.worker_id] = lease

    def _update_worker(self, lease: WorkerLease) -> None:
        with self._lock:
            self._workers[lease.worker_id] = lease