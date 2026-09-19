# -*- coding: utf-8 -*-
"""COS-152: cross-process durable-read probe.

Запускает GET-запрос к API в СВЕЖЕМ python-процессе (новый engine, новый
ASGI-инстанс приложения) против той же тестовой БД. Это честное
доказательство durable read-path: процесс-предшественник «умер», а ответ
всё равно приходит из ``evidence_ledger`` — in-memory состояния не требуется.

Используется restart-survival тестами COS-142 / COS-147 / COS-148.
Модуль начинается с ``_`` — pytest его не собирает.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]

_PROBE = r'''
import asyncio
import json
import os
import sys

sys.path.insert(0, os.environ["ORCH_ROOT"])

from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from orchestrator.cosmo.api.deps import get_current_principal, get_db
from orchestrator.cosmo.api.main import app
from orchestrator.cosmo.domain.rbac import PrincipalContext, Role


async def main():
    engine = create_async_engine(os.environ["COSMO_DATABASE_URL"])
    session_maker = async_sessionmaker(engine, expire_on_commit=False)

    async def _db():
        async with session_maker() as session:
            yield session

    async def _admin():
        return PrincipalContext(
            user_id="durable-probe",
            roles=[Role.ADMIN_SEC],
            domain_id="test",
            zone="zr",
            is_system_admin=True,
        )

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_current_principal] = _admin
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://probe") as ac:
        res = await ac.get(os.environ["PROBE_URL"])
        sys.stdout.write(
            json.dumps({"status": res.status_code, "body": res.text})
        )
    await engine.dispose()


asyncio.run(main())
'''


def get_in_fresh_process(
    url: str, pg_url: str, timeout: int = 180,
) -> tuple[int, dict]:
    """GET ``url`` в свежем процессе; возвращает ``(status_code, body_json)``.

    Raises:
        AssertionError: процесс-проба упал (с stdout/stderr для диагностики).
    """
    env = dict(os.environ)
    env["ORCH_ROOT"] = str(_REPO_ROOT)
    env["COSMO_DATABASE_URL"] = pg_url
    env["PROBE_URL"] = url
    env.setdefault("COSMO_ENV", "test")
    proc = subprocess.run(
        [sys.executable, "-c", _PROBE],
        cwd=str(_REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if proc.returncode != 0:
        raise AssertionError(
            "durable probe process failed:\n"
            f"stdout={proc.stdout}\nstderr={proc.stderr}"
        )
    payload = json.loads(proc.stdout.strip().splitlines()[-1])
    return payload["status"], json.loads(payload["body"])
