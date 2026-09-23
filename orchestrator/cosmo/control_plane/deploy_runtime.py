# -*- coding: utf-8 -*-
"""COS-165: singleton-доступ к Docker runtime контура ЗР (инъектируемо).

``get_deploy_runtime()`` — единственная точка создания ``DeployRuntime``;
``set_deploy_runtime()`` — тестовый шов (подмена на fake runner без Docker).
Сеть читается из ``COSMO_DEPLOY_NETWORK`` (default: ``cosmo-net``).
"""
from __future__ import annotations

import os
from typing import Optional

from orchestrator.cosmo.adapters.runtime_docker import (
    DEFAULT_NETWORK,
    DeployRuntime,
)

_runtime: Optional[DeployRuntime] = None


def get_deploy_runtime() -> DeployRuntime:
    global _runtime
    if _runtime is None:
        _runtime = DeployRuntime(
            network=os.getenv("COSMO_DEPLOY_NETWORK", DEFAULT_NETWORK),
        )
    return _runtime


def set_deploy_runtime(runtime: DeployRuntime) -> None:
    global _runtime
    _runtime = runtime


__all__ = ["get_deploy_runtime", "set_deploy_runtime"]
