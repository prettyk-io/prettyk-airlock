"""COS-080: Steel Thread integration fixtures — isolated test PG (:5433).

API-level harness поверх РЕАЛЬНОГО app без дублирования движков: все запросы
идут через ленивый синглтон db.session.get_engine() (canonical path, как в
проде). Родительский conftest (COS-073) уже форсит COSMO_DATABASE_URL на
тестовый PG до импорта app. Auto-skip, если тестовый PG недоступен.

restart() эмулирует рестарт процесса: dispose app-движка (все соединения
убиты), сброс sync-синглонов, новый клиент; данные в PG не трогаются —
стейт восстанавливается из БД на следующем запросе.
"""
import os

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

import _testpg
from _testpg import TEST_PG_URL
from _wipe_order import CIRCULAR_NULLIFY, DELETE_ORDER

from orchestrator.cosmo.api.deps import get_current_principal
from orchestrator.cosmo.api.main import app
from orchestrator.cosmo.db import session as _db_session_mod
from orchestrator.cosmo.db.models import Base as CosmoBase
from orchestrator.cosmo.domain.rbac import PrincipalContext, Role

# COS-081 WIP: gate decision trail живёт на ОТДЕЛЬНОМ Base (frozen chain);
# общий CosmoBase.metadata.create_all его не создаёт, а роут gates пишет в
# него на каждом решении. Создаём/чистим сами, пока единый create_all не
# собран; ImportError-safe — интеграция не зависит от trail.
try:
    from orchestrator.cosmo.db.models_gate_trail import GateTrailBase as _GateTrailBase
except ImportError:
    _GateTrailBase = None

# COS-087: сериализация create_all/wipe между ПАРАЛЛЕЛЬНЫМИ pytest-процессами
# на общем тестовом PG. pg_advisory_xact_lock держится до конца транзакции —
# create_all (один tx) и wipe (один tx) идут под одним ключом, каталожкие
# гонки (pg_type_typname_nsp_index) на параллельных прогонах исключены.
_ADVISORY_LOCK_KEY = 0x434F534D  # 'COSM'

# COS-087: внешний якорь головы evidence-цепочки (append-only JSONL).
# Каждый тест получает СВОЙ sink (tmp_path) — publish/verify замкнуты
# в рамках теста, стейты не текут между тестами и процессами.
_ANCHOR_ENV = "COSMO_EVIDENCE_ANCHOR_FILE"

PG_UP = _testpg.pg_available()

_SKIP_REASON = (
    "test PG (:5433) unreachable - "
    "docker compose -f services/docker-compose.test-pg.yml up -d"
)

# COS-151: единый топологический порядок очистки (см. _wipe_order) — тот же,
# что в родительском conftest.py. integration создаёт только CosmoBase +
# (опц.) GateTrailBase, поэтому в wipe() таблицы Transfer*/Execution*,
# отсутствующие на чистой БД, пропускаются по to_regclass.


def _admin_principal() -> PrincipalContext:
    return PrincipalContext(
        user_id="integration-admin",
        roles=[Role.ADMIN_SEC],
        domain_id="it-integration",
        zone="zr",
        is_system_admin=True,
    )


class SteelThreadHarness:
    """API-level harness: real app, app-own engine, admin principal, restart()."""

    def __init__(self) -> None:
        self.client: AsyncClient | None = None
        self.restarts = 0

    async def start(self) -> None:
        async def _principal() -> PrincipalContext:
            return _admin_principal()

        app.dependency_overrides[get_current_principal] = _principal
        self.client = AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        )

    async def aclose(self) -> None:
        if self.client is not None:
            await self.client.aclose()
            self.client = None
        app.dependency_overrides.pop(get_current_principal, None)

    async def restart(self) -> None:
        """Рестарт процесса: убить соединения, сбросить синглтоны, новый клиент."""
        self.restarts += 1
        await self.client.aclose()
        await _db_session_mod.dispose_engine()
        _db_session_mod._sync_engine = None
        _db_session_mod._SyncSessionLocal = None
        self.client = AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        )

    async def wipe(self) -> None:
        """Полная очистка доменных таблиц под advisory lock (COS-087).

        Весь wipe — одна транзакция: pg_advisory_xact_lock берётся первым
        statement'ом и держится до commit, параллельный pytest-процесс
        дождётся конца wipe перед своим create_all/wipe.
        """
        sm = _db_session_mod.get_sessionmaker()
        async with sm() as s:
            await s.execute(
                text("SELECT pg_advisory_xact_lock(:k)"), {"k": _ADVISORY_LOCK_KEY},
            )
            # circular FK: nullify до DELETE
            for stmt in CIRCULAR_NULLIFY:
                await s.execute(text(stmt))
            # Наличие таблиц: integration Base = Cosmo + GateTrail; таблицы
            # Transfer/Execution могут отсутствовать на чистой БД.
            present = set(
                (await s.execute(text(
                    "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
                ))).scalars()
            )
            for tbl in DELETE_ORDER:
                if tbl in present:
                    await s.execute(text(f'DELETE FROM "{tbl}"'))
            await s.commit()

    async def sync_exec(self, sql: str, **params) -> None:
        """Сырой SQL (tamper-тесты) через тот же app-движок."""
        sm = _db_session_mod.get_sessionmaker()
        async with sm() as s:
            await s.execute(text(sql), params or {})
            await s.commit()


@pytest_asyncio.fixture
async def steel_thread(tmp_path):
    if not PG_UP:
        pytest.skip(_SKIP_REASON)
    # COS-075 loop-safety: синглтон-движок привязан к loop'у, который его
    # создал; каждый pytest-asyncio тест получает свежий loop — сбрасываем
    # синглтон ДО первого использования, чтобы он пере-биндился к живому.
    await _db_session_mod.dispose_engine()
    # Схема: create_all через app-движок (идемпотентно), под advisory lock
    engine = _db_session_mod.get_engine()
    async with engine.begin() as conn:
        await conn.execute(
            text("SELECT pg_advisory_xact_lock(:k)"), {"k": _ADVISORY_LOCK_KEY},
        )
        await conn.run_sync(CosmoBase.metadata.create_all)
        if _GateTrailBase is not None:
            await conn.run_sync(_GateTrailBase.metadata.create_all)

    # COS-087: внешний якорь головы — у каждого теста свой append-only sink
    anchor_file = tmp_path / "evidence_anchor.jsonl"
    prev_anchor_env = os.environ.get(_ANCHOR_ENV)
    os.environ[_ANCHOR_ENV] = str(anchor_file)

    harness = SteelThreadHarness()
    await harness.start()
    await harness.wipe()
    yield harness
    await harness.wipe()
    await harness.aclose()
    if prev_anchor_env is None:
        os.environ.pop(_ANCHOR_ENV, None)
    else:
        os.environ[_ANCHOR_ENV] = prev_anchor_env
    # Движок умирает вместе с loop'ом теста — не оставлять его синглтону.
    await _db_session_mod.dispose_engine()
