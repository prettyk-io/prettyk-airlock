"""COS-089: migration verifier tests. Skip when PostgreSQL unavailable."""
import sys
from pathlib import Path

import pytest

_orch = Path(__file__).resolve().parents[1]
if str(_orch) not in sys.path:
    sys.path.insert(0, str(_orch))

from orchestrator.cosmo.db.migration_verifier import is_pg_available

skip_pg = pytest.mark.skipif(not is_pg_available(), reason="PostgreSQL not available")


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
        from orchestrator.cosmo.db.migration_verifier import alembic_cycle, verify_schema
        alembic_cycle()
        result = verify_schema()
        assert result["ok"], f"Tables missing: {result['missing_tables']}"


@skip_pg
class TestEnums:
    def test_all_enums_after_cycle(self):
        from orchestrator.cosmo.db.migration_verifier import alembic_cycle, verify_enums
        alembic_cycle()
        result = verify_enums()
        assert result["ok"], f"Missing: {result['missing']}, bad: {result['mismatches']}"


@skip_pg
class TestGin:
    def test_gin_indexes_after_cycle(self):
        from orchestrator.cosmo.db.migration_verifier import alembic_cycle, verify_gin
        alembic_cycle()
        result = verify_gin()
        assert result["ok"], f"Missing GIN: {result['missing']}"


@skip_pg
class TestNonDestructive:
    def test_add_column_preserves_data(self):
        from orchestrator.cosmo.db.migration_verifier import test_non_destructive
        result = test_non_destructive()
        assert result["ok"], f"Failed: {result}"