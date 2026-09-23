# -*- coding: utf-8 -*-
"""COS-165: Docker runtime — реальный deploy образа по digest в контур ЗР.

Никакого выдуманного k8s: pull по immutable digest → ``docker run`` в
существующий compose-контур (сеть ``cosmo-net``) → healthcheck контейнера.
Статус ``deployed`` ставится ТОЛЬКО после фактического ``healthy``; иначе —
честная ``DockerDeployError`` (вызывающий переводит в failed/rollback).

``runner`` — ``subprocess.run``-совместимый callable (инъекция в тестах, тот
же приём, что ``transfer/sbom.py``). Docker CLI должен быть доступен на хосте,
где крутится API (в dev — host Docker; прод — агент с mounted docker.sock).
"""
from __future__ import annotations

import subprocess
import time
from typing import Any, Callable, Optional

Runner = Callable[..., Any]  # subprocess.run-совместимый (инъекция в тестах)

#: Дефолтная сеть контура ЗР (compose: `name: cosmo-net`).
DEFAULT_NETWORK = "cosmo-net"

#: Дефолтный таймаут ожидания healthcheck (сек).
DEFAULT_HEALTH_TIMEOUT = 60.0

#: Интервал опроса ``docker inspect`` (сек).
HEALTH_POLL_INTERVAL = 2.0


class DockerDeployError(RuntimeError):
    """Реальный deploy не доведён до healthy-состояния (честная ошибка)."""


class DeployRuntime:
    """Материализует образ в контур ЗР: pull → run → healthy-check."""

    def __init__(
        self,
        runner: Runner | None = None,
        *,
        network: str = DEFAULT_NETWORK,
        health_timeout: float = DEFAULT_HEALTH_TIMEOUT,
    ) -> None:
        self._runner: Runner = runner or subprocess.run
        self._network = network
        self._health_timeout = health_timeout

    def _run(self, argv: list[str], *, timeout: int) -> Any:
        return self._runner(argv, capture_output=True, text=True, timeout=timeout)

    def pull(self, image_ref: str) -> None:
        """``docker pull`` образа по immutable digest-ссылке."""
        proc = self._run(["docker", "pull", image_ref], timeout=300)
        if proc.returncode != 0:
            stderr = (getattr(proc, "stderr", "") or "").strip()
            raise DockerDeployError(f"docker pull failed for {image_ref}: {stderr}")

    def run_container(
        self,
        image_ref: str,
        container_name: str,
        *,
        labels: Optional[dict[str, str]] = None,
    ) -> None:
        """``docker run -d`` в контур (сеть cosmo-net) — detached, с метками."""
        argv = ["docker", "run", "-d", "--name", container_name]
        argv += ["--network", self._network]
        for key, value in (labels or {}).items():
            argv += ["--label", f"{key}={value}"]
        argv.append(image_ref)
        proc = self._run(argv, timeout=120)
        if proc.returncode != 0:
            stderr = (getattr(proc, "stderr", "") or "").strip()
            raise DockerDeployError(
                f"docker run failed for {image_ref}: {stderr}"
            )

    def inspect_health(self, container_name: str) -> str:
        """Health-статус контейнера из ``docker inspect`` ('' если нет health)."""
        proc = self._run(
            [
                "docker", "inspect", "--format",
                "{{.State.Health.Status}}", container_name,
            ],
            timeout=30,
        )
        if proc.returncode != 0:
            return "unhealthy"
        return (getattr(proc, "stdout", "") or "").strip()

    def wait_healthy(self, container_name: str) -> bool:
        """Опрашивать healthcheck до ``healthy`` или таймаута."""
        deadline = time.monotonic() + self._health_timeout
        while time.monotonic() < deadline:
            status = self.inspect_health(container_name)
            if status == "healthy":
                return True
            if status in ("unhealthy",):
                return False
            time.sleep(HEALTH_POLL_INTERVAL)
        return False

    def remove(self, container_name: str) -> None:
        """Снести контейнер (best-effort; сбой — WARN, не исключение)."""
        try:
            self._run(["docker", "rm", "-f", container_name], timeout=60)
        except Exception:  # noqa: BLE001 — cleanup не должен маскировать причину
            pass

    def deploy(
        self,
        image_ref: str,
        container_name: str,
        *,
        labels: Optional[dict[str, str]] = None,
    ) -> bool:
        """Полный цикл materialize: pull → run → healthy.

        Возвращает ``True`` только при фактическом ``healthy``. При любой
        ошибке сносит контейнер и поднимает ``DockerDeployError``.
        """
        try:
            self.pull(image_ref)
            self.run_container(image_ref, container_name, labels=labels)
            healthy = self.wait_healthy(container_name)
            if not healthy:
                raise DockerDeployError(
                    f"container '{container_name}' did not become healthy "
                    f"within {self._health_timeout}s"
                )
            return True
        except Exception:
            self.remove(container_name)
            raise


__all__ = [
    "DockerDeployError",
    "DeployRuntime",
    "DEFAULT_NETWORK",
    "DEFAULT_HEALTH_TIMEOUT",
]
