# -*- coding: utf-8 -*-
"""COS-171/172: scan-registry network policy — точечный insecure-allow.

Registry ЗР — локальный HTTP smoke (``distribution:3.1.0``, без TLS). Сканеры
(trivy/syft) по умолчанию ходят в HTTPS; для HTTP-registry нужен явный insecure.
Глобальный downgrade запрещён: разрешаем строго для allowlist-хостов.

Канон хостов (BRG-004): хост-режим ``localhost:5100``, docker-режим
``cosmo-registry-zr:5000`` (см. ``adapters/registry_per_zone.py``).
"""
from __future__ import annotations

import os
from typing import Iterable, Optional

#: Env-переменная со списком insecure-хостов (через запятую/пробел).
INSECURE_REGISTRY_HOSTS_ENV = "INSECURE_REGISTRY_HOSTS"

#: Дефолтный allowlist — только локальный dev CSV registry ЗР (HTTP).
DEFAULT_INSECURE_REGISTRY_HOSTS: frozenset[str] = frozenset(
    {"cosmo-registry-zr:5000"}
)


def _host_of(ref: str) -> str:
    """Вытащить host[:port] из ref (scheme://host[:port]/path → host[:port])."""
    candidate = ref.strip()
    if "://" in candidate:
        candidate = candidate.split("://", 1)[1]
    candidate = candidate.split("/", 1)[0].split("@", 1)[-1]
    return candidate


def registry_host(image_ref: str) -> str:
    """Host (с портом) первого сегмента ref: ``<qualified>@digest``/scheme-форма."""
    return _host_of(image_ref)


def parse_allowlist(raw: Optional[str]) -> frozenset[str]:
    """Разобрать env-строку в frozenset хостов (через запятую/пробел)."""
    if not raw:
        return frozenset()
    hosts: set[str] = set()
    for token in raw.replace(",", " ").split():
        host = _host_of(token)
        if host:
            hosts.add(host)
    return frozenset(hosts)


def load_insecure_hosts(env: Optional[str] = None) -> frozenset[str]:
    """Текущий allowlist: env → дефолт (``cosmo-registry-zr:5000``)."""
    raw = os.environ.get(INSECURE_REGISTRY_HOSTS_ENV) if env is None else env
    if raw is None or raw.strip() == "":
        return DEFAULT_INSECURE_REGISTRY_HOSTS
    return parse_allowlist(raw)


def allows_insecure(image_ref: str, hosts: Iterable[str]) -> bool:
    """True, если host ref'а в allowlist (точечный insecure, глобального нет)."""
    return registry_host(image_ref) in set(hosts)


__all__ = [
    "INSECURE_REGISTRY_HOSTS_ENV",
    "DEFAULT_INSECURE_REGISTRY_HOSTS",
    "registry_host",
    "parse_allowlist",
    "load_insecure_hosts",
    "allows_insecure",
]