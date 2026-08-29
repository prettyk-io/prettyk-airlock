# -*- coding: utf-8 -*-
"""COS-092: Distributed Lock & Concurrency Guard.

Valkey SETNX-based distributed lock with PostgreSQL pg_try_advisory_lock fallback.
Protects against race conditions: simultaneous run launches, parallel gate evaluation,
concurrent app deploys.

ConcurrencyGuard:
  - acquire_run_lock(run_id, ttl) / release_run_lock(run_id)
  - acquire_app_lock(app_id)
  - SETNX + TTL в Valkey, fallback → pg_try_advisory_lock
"""
from __future__ import annotations

import hashlib
import logging
import os
import threading
import time
from typing import Any, Callable, Optional

logger = logging.getLogger("cosmoport.lock")

# ── Valkey client (lazy singleton, same pattern as events.py) ──

_valkey: Any = None
_valkey_check: bool | None = None


def _get_valkey() -> Any | None:
    global _valkey, _valkey_check
    if _valkey_check is False:
        return None
    if _valkey is not None:
        return _valkey
    url = os.getenv("COSMO_VALKEY_URL", "").strip()
    if not url:
        _valkey_check = False
        return None
    try:
        import valkey as vk
        _valkey = vk.Valkey.from_url(url)
        _valkey.ping()
        _valkey_check = True
        return _valkey
    except Exception as exc:
        _valkey_check = False
        _valkey = None
        logger.debug("Valkey unavailable for locks: %s", exc)
        return None


# ── Distributed Lock ──

class DistributedLock:
    """Одна распределённая блокировка на ключ.

    Valkey: SET lock_key <owner> NX EX ttl
    PG:    pg_try_advisory_lock(hashed_key)
    """

    def __init__(self, key: str, ttl: float = 30.0, owner: str = "") -> None:
        self._key = f"cosmo:lock:{key}"
        self._ttl = max(int(ttl), 1)
        self._owner = owner or f"{os.getpid()}-{threading.get_ident()}"
        self._acquired = False

    def acquire(self) -> bool:
        """Захватить блокировку. True = успех, False = уже занята."""
        v = _get_valkey()
        if v is not None:
            return self._acquire_valkey(v)
        return self._acquire_pg()

    def release(self) -> bool:
        """Освободить блокировку."""
        if not self._acquired:
            return False
        if _get_valkey() is not None:
            return self._release_valkey()
        return self._release_pg()

    def _acquire_valkey(self, v: Any) -> bool:
        try:
            # SET key value NX EX ttl → returns True if set, None if already exists
            result = v.set(self._key, self._owner, nx=True, ex=self._ttl)
            self._acquired = result is not None and result is True
            return self._acquired
        except Exception as exc:
            logger.warning("Valkey SETNX failed for %s: %s", self._key, exc)
            return False

    def _release_valkey(self) -> bool:
        try:
            v = _get_valkey()
            if v is not None:
                # Lua script: release only if owner matches
                script = """
                if redis.call("GET", KEYS[1]) == ARGV[1] then
                    return redis.call("DEL", KEYS[1])
                else
                    return 0
                end
                """
                result = v.eval(script, 1, self._key, self._owner)
                self._acquired = False
                return bool(result)
        except Exception as exc:
            logger.warning("Valkey DEL failed for %s: %s", self._key, exc)
        return False

    def _acquire_pg(self) -> bool:
        try:
            from orchestrator.cosmo.db.session import get_sync_session
            s = get_sync_session()
            try:
                from sqlalchemy import text
                lock_id = self._pg_lock_id()
                row = s.execute(text("SELECT pg_try_advisory_lock(:id)"), {"id": lock_id}).scalar()
                s.commit()
                self._acquired = bool(row)
                return self._acquired
            finally:
                s.close()
        except Exception as exc:
            logger.warning("PG advisory lock failed for %s: %s", self._key, exc)
            return False

    def _release_pg(self) -> bool:
        try:
            from orchestrator.cosmo.db.session import get_sync_session
            s = get_sync_session()
            try:
                from sqlalchemy import text
                lock_id = self._pg_lock_id()
                s.execute(text("SELECT pg_advisory_unlock(:id)"), {"id": lock_id})
                s.commit()
                self._acquired = False
                return True
            finally:
                s.close()
        except Exception:
            return False

    def _pg_lock_id(self) -> int:
        h = hashlib.md5(self._key.encode()).hexdigest()[:16]
        return int(h, 16) % (2**31 - 1)

    def __enter__(self) -> DistributedLock:
        self.acquire()
        return self

    def __exit__(self, *args: Any) -> None:
        self.release()

    @property
    def is_acquired(self) -> bool:
        return self._acquired


# ── Concurrency Guard ──

class ConcurrencyGuard:
    """Высокоуровневый API для блокировок run/app/gate.

    Интегрируется в RunControlPlane._assign() и GatePolicyEngine.evaluate_gate().
    """

    def __init__(self, clock: Callable[[], float] = time.time) -> None:
        self._clock = clock

    def acquire_run_lock(self, run_id: str, ttl_seconds: int = 30) -> DistributedLock:
        lock = DistributedLock(f"run:{run_id}", ttl=ttl_seconds)
        lock.acquire()
        return lock

    def release_run_lock(self, run_id: str) -> bool:
        lock = DistributedLock(f"run:{run_id}")
        lock._acquired = True  # для вызова release
        return lock.release()

    def acquire_app_lock(self, app_id: str) -> DistributedLock:
        lock = DistributedLock(f"app:{app_id}", ttl=120)  # long TTL for deploys
        lock.acquire()
        return lock

    def acquire_gate_lock(self, gate_id: str, ttl_seconds: int = 15) -> DistributedLock:
        lock = DistributedLock(f"gate:{gate_id}", ttl=ttl_seconds)
        lock.acquire()
        return lock

    def try_acquire_run(self, run_id: str, ttl_seconds: int = 30) -> bool:
        """Non-blocking try: возвращает True/False."""
        lock = DistributedLock(f"run:{run_id}", ttl=ttl_seconds)
        return lock.acquire()

    def try_acquire_gate(self, gate_id: str, ttl_seconds: int = 15) -> bool:
        lock = DistributedLock(f"gate:{gate_id}", ttl=ttl_seconds)
        return lock.acquire()