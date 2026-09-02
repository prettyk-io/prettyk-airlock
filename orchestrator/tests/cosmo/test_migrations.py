"""COS-089: migration verifier tests. Skip when PostgreSQL unavailable.

COS-078: миграционные тесты полностью scratch-based — ни один тест не
зависит от состояния dev-БД. Test-PG env форсируется в шапке (как в
conftest) — при --noconftest прогоне цикл тоже идёт на изолированный
test PG (:5433), не на dev-stand.
"""
import os
import sys
import logging
from pathlib import Path
from urllib.parse import urlsplit

import pytest

_orch = Path(__file__).resolve().parents[1]
if str(_orch) not in sys.path:
    sys.path.insert(0, str(_orch))

import _testpg

# Forced, not setdefault — как в conftest: внешний COSMO_DATABASE_URL
# (например от gate-прогона на live stand) не должен утекать в тесты.
_testpg.refuse_dev_stand(_testpg.TEST_PG_URL)
os.environ["COSMO_DATABASE_URL"] = _testpg.TEST_PG_URL

from orchestrator.cosmo.db.migration_verifier import is_pg_available

skip_pg = pytest.mark.skipif(not is_pg_available(), reason="PostgreSQL not available")

# COS-076: реестр scratch-БД, созданных в этой pytest-сессии (каждый
# xdist-worker ведёт свой набор — имена уникальны per-run через
# _testpg.scratch_name). Session-teardown дропает всё, что пережило тесты.
_CREATED_SCRATCH: set[str] = set()


def _scratch_cycle():
    """COS-078/076: cycle с сохранённым scratch + гарантированный дроп в finally;
    имя регистрируется в _CREATED_SCRATCH для session-teardown guard'а."""
    from orchestrator.cosmo.db.migration_verifier import alembic_cycle, drop_scratch_db

    scratch_url = alembic_cycle(keep_scratch=True)
    _CREATED_SCRATCH.add(urlsplit(scratch_url).path.lstrip("/"))
    return scratch_url, lambda: drop_scratch_db(scratch_url)


@pytest.fixture(scope="session", autouse=True)
def _scratch_session_teardown():
    """COS-076: fixtured teardown scratch-БД — тестовый PG не копит мусор,
    даже если тест упал мимо try/finally (assert/краш в теле). xdist-безопасно:
    worker дропает только СВОИ зарегистрированные имена (уникальны per-run)."""
    yield
    if not _CREATED_SCRATCH or not _testpg.pg_available():
        _CREATED_SCRATCH.clear()
        return
    import psycopg2

    for dbname in list(_CREATED_SCRATCH):
        try:
            conn = psycopg2.connect(_testpg.admin_dsn())
            try:
                conn.autocommit = True
                cur = conn.cursor()
                cur.execute(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = %s AND pid <> pg_backend_pid()",
                    (dbname,),
                )
                cur.execute(f'DROP DATABASE IF EXISTS "{dbname}"')
            finally:
                conn.close()
        except Exception:
            pass  # teardown guard не маскирует результат тестов
        finally:
            _CREATED_SCRATCH.discard(dbname)


class TestVerifierStructure:
    """Структура модуля корректна даже без PostgreSQL."""

    def test_imports_all_functions(self):
        from orchestrator.cosmo.db.migration_verifier import (
            is_pg_available,
            alembic_cycle,
            verify_enums,
            verify_gin,
            verify_schema,
            test_non_destructive,
            ALL_ENUMS,
            EXPECTED_GIN,
        )
        assert callable(alembic_cycle)
        assert callable(verify_enums)
        assert callable(verify_gin)
        assert callable(verify_schema)
        assert callable(test_non_destructive)
        assert len(ALL_ENUMS) == 8
        assert len(EXPECTED_GIN) == 10

    def test_pg_available_does_not_crash(self):
        result = is_pg_available()
        assert isinstance(result, bool)

    def test_all_enum_names_correct(self):
        from orchestrator.cosmo.db.migration_verifier import ALL_ENUMS
        expected = {
            "brick_type", "batch_status", "batch_type", "run_trigger",
            "run_status", "gate_type", "gate_decision", "evidence_type",
        }
        assert set(ALL_ENUMS.keys()) == expected

    def test_brick_type_has_7_values(self):
        from orchestrator.cosmo.db.migration_verifier import ALL_ENUMS
        assert len(ALL_ENUMS["brick_type"]) == 7

    def test_gin_indexes_cover_all_tables(self):
        from orchestrator.cosmo.db.migration_verifier import EXPECTED_GIN
        tables = {t for t, _ in EXPECTED_GIN}
        assert "pipeline_bricks" in tables
        assert "batches" in tables
        assert "gates" in tables
        assert "runs" in tables
        assert "domains" in tables
        assert "evidence_ledger" in tables


@skip_pg
class TestMigrationCycle:
    def test_alembic_cycle(self):
        from orchestrator.cosmo.db.migration_verifier import alembic_cycle
        assert alembic_cycle() is True

    def test_cycle_then_schema_matches(self):
        """COS-078: schema verification на СВЕЖЕЙ scratch-БД — dev-БД не участвует."""
        from orchestrator.cosmo.db.migration_verifier import verify_schema

        scratch_url, drop = _scratch_cycle()
        try:
            result = verify_schema(url=scratch_url)
        finally:
            drop()
        assert result["ok"], f"Tables missing: {result['missing_tables']}"
        assert result["missing_tables"] == []

    def test_cycle_scratch_names_unique(self):
        """COS-078: два цикла используют разные scratch-БД (catalog-race isolation)."""
        from orchestrator.cosmo.db.migration_verifier import alembic_cycle

        url1 = alembic_cycle(keep_scratch=True)
        try:
            url2 = alembic_cycle(keep_scratch=True)
            try:
                assert url1 != url2
            finally:
                from orchestrator.cosmo.db.migration_verifier import drop_scratch_db
                drop_scratch_db(url2)
        finally:
            from orchestrator.cosmo.db.migration_verifier import drop_scratch_db
            drop_scratch_db(url1)

    def test_verify_schema_does_not_touch_main_db(self, monkeypatch):
        """COS-076: verify_schema(url=scratch) не консультируется с основным
        резолвом — зелёный при битом/чужом COSMO_DATABASE_URL (cycle сам
        легитимно ставит scratch на инстанс из резолва ДО патча env)."""
        from orchestrator.cosmo.db.migration_verifier import verify_schema

        scratch_url, drop = _scratch_cycle()
        try:
            monkeypatch.setenv(
                "COSMO_DATABASE_URL",
                "postgresql+asyncpg://ghost:ghost@127.0.0.1:5999/void",
            )
            result = verify_schema(url=scratch_url)
        finally:
            drop()
        assert result["ok"], f"Tables missing: {result['missing_tables']}"


@skip_pg
class TestLogSurvival:
    """COS-076 regression: fileConfig() в alembic/env.py НЕ глушит логгеры."""

    def test_caplog_survives_inprocess_cycle(self, caplog):
        """caplog ловит запись ПОСЛЕ in-process alembic_cycle() — минa
        disable_existing_loggers снята на поверхности env.py."""
        from orchestrator.cosmo.db.migration_verifier import alembic_cycle

        assert alembic_cycle() is True

        probe = logging.getLogger("cosmoport.migration_probe")
        assert not probe.disabled, "fileConfig() disabled existing loggers"
        with caplog.at_level(logging.INFO, logger="cosmoport.migration_probe"):
            probe.info("COS-076 caplog probe after in-process cycle")
        assert any("caplog probe" in r.getMessage() for r in caplog.records), (
            "caplog captured nothing after in-process alembic_cycle"
        )

    def test_app_logger_not_disabled_after_cycle(self):
        """Прикладной логгер cosmoport.* остаётся живым после цикла."""
        from orchestrator.cosmo.db.migration_verifier import alembic_cycle

        assert alembic_cycle() is True
        assert not logging.getLogger("cosmoport.notifications").disabled
        assert not logging.getLogger("cosmoport.db.config").disabled


class TestScratchHygiene:
    """Downgrade-цикл допустим только на scratch-БД (никогда на dev)."""

    def test_downgrade_forbidden_on_dev(self):
        from orchestrator.cosmo.db.migration_verifier import _assert_scratch_target
        with pytest.raises(RuntimeError, match="non-scratch"):
            _assert_scratch_target(
                _testpg.psycopg2_url()
            )

    def test_scratch_target_accepted(self):
        from orchestrator.cosmo.db.migration_verifier import _assert_scratch_target
        _assert_scratch_target(
            _testpg.psycopg2_url("cosmo_scratch_cycle")
        )

    @skip_pg
    def test_cycle_preserves_main_db(self):
        """После scratch-цикла main (test) БД не тронута: версия и таблицы на месте."""
        import psycopg2
        from orchestrator.cosmo.db.migration_verifier import alembic_cycle

        conn = psycopg2.connect(
            _testpg.admin_dsn("cosmo_test")
        )
        cur = conn.cursor()
        cur.execute("SELECT version_num FROM alembic_version")
        version_before = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema='public'")
        tables_before = cur.fetchone()[0]
        conn.close()

        assert alembic_cycle() is True

        conn = psycopg2.connect(
            _testpg.admin_dsn("cosmo_test")
        )
        cur = conn.cursor()
        cur.execute("SELECT version_num FROM alembic_version")
        version_after = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema='public'")
        tables_after = cur.fetchone()[0]
        conn.close()

        assert version_after == version_before, (
            f"scratch cycle changed dev version: {version_before} → {version_after}"
        )
        assert tables_after == tables_before


@skip_pg
class TestEnums:
    def test_all_enums_after_cycle(self):
        """COS-078: enums верифицируются на свежей scratch (не на dev)."""
        from orchestrator.cosmo.db.migration_verifier import verify_enums

        scratch_url, drop = _scratch_cycle()
        try:
            result = verify_enums(url=scratch_url)
        finally:
            drop()
        assert result["ok"], f"Missing: {result['missing']}, bad: {result['mismatches']}"


@skip_pg
class TestGin:
    def test_gin_indexes_after_cycle(self):
        """COS-078: GIN-индексы верифицируются на свежей scratch (не на dev)."""
        from orchestrator.cosmo.db.migration_verifier import verify_gin

        scratch_url, drop = _scratch_cycle()
        try:
            result = verify_gin(url=scratch_url)
        finally:
            drop()
        assert result["ok"], f"Missing GIN: {result['missing']}"


@skip_pg
class TestNonDestructive:
    def test_add_column_preserves_data(self):
        """COS-078: non-destructive DDL проверяется на scratch (не на dev)."""
        from orchestrator.cosmo.db.migration_verifier import test_non_destructive

        scratch_url, drop = _scratch_cycle()
        try:
            result = test_non_destructive(url=scratch_url)
        finally:
            drop()
        assert result["ok"], f"Failed: {result}"
