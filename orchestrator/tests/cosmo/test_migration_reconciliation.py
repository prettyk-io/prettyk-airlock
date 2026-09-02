"""COS-062: migration chain verification tests.

Verifies that the alembic chain reproduces the ORM Base.metadata exactly and
survives fresh / repeat / legacy-stamp / partial-replay upgrades. Uses an
isolated scratch database (never the shared `cosmo` DB). Skips when PG is
unreachable.

COS-078: scratch-имя уникально per-run (pg_type_typname_nsp_index
catalog-race mitigation при параллельных pytest); availability-чек —
_testpg.pg_available (унификация дублей).
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

import _testpg

_repo = Path(__file__).resolve().parents[3]
_orch = Path(__file__).resolve().parents[2]
for p in (str(_repo), str(_orch)):
    if p not in sys.path:
        sys.path.insert(0, p)

SCRATCH_DB = _testpg.scratch_name("mig_recon")  # per-run unique (COS-078)
_POSTGRES_ADMIN_URL = _testpg.admin_dsn()
_MAIN_URL = os.getenv("COSMO_DATABASE_URL", _testpg.TEST_PG_URL)
_HEAD = "e4f5a6b7c8d9"
_NOTIF_TABLES = {
    "notification_events",
    "notification_inbox",
    "notification_subscriptions",
    "notification_channel_configs",
}


skip_pg = pytest.mark.skipif(
    not _testpg.pg_available(),
    reason="test PG (:5433) unreachable - docker compose -f services/docker-compose.test-pg.yml up -d",
)


def _scratch_url() -> str:
    return _testpg.psycopg2_url(SCRATCH_DB)


def _run_alembic(args: list[str], expect_success: bool = True) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["COSMO_DATABASE_URL"] = _scratch_url()
    env["PYTHONIOENCODING"] = "utf-8"
    proc = subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=str(_repo),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
    )
    if expect_success and proc.returncode != 0:
        pytest.fail(f"alembic {' '.join(args)} failed:\n{proc.stdout}\n{proc.stderr}")
    return proc


@pytest.fixture(scope="module")
def scratch_db():
    """Create an isolated scratch database for the whole module, drop after."""
    import psycopg2

    def _admin():
        return psycopg2.connect(_POSTGRES_ADMIN_URL)

    def _drop_scratch():
        conn = _admin()
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname = %s AND pid <> pg_backend_pid()",
            (SCRATCH_DB,),
        )
        cur.execute(f"DROP DATABASE IF EXISTS {SCRATCH_DB}")
        conn.close()

    _drop_scratch()
    conn = _admin()
    conn.autocommit = True
    conn.cursor().execute(f"CREATE DATABASE {SCRATCH_DB}")
    conn.close()
    yield _scratch_url()
    _drop_scratch()


# ════════════════════════════════════════════════════════════════════
# Offline chain-structure tests (no PG required)
# ════════════════════════════════════════════════════════════════════


class TestChainStructure:
    def test_exactly_one_head(self):
        from alembic.config import Config
        from alembic.script import ScriptDirectory

        cfg = Config(str(_repo / "alembic.ini"))
        script = ScriptDirectory.from_config(cfg)
        heads = script.get_heads()
        assert heads == [_HEAD], f"expected single head {_HEAD}, got {heads}"

    def test_chain_is_linear_no_branch_points(self):
        from alembic.config import Config
        from alembic.script import ScriptDirectory

        cfg = Config(str(_repo / "alembic.ini"))
        script = ScriptDirectory.from_config(cfg)
        revisions = script.walk_revisions("base", "heads")
        down_targets: dict[str, list[str]] = {}
        for rev in revisions:
            downs = rev.down_revision if isinstance(rev.down_revision, tuple) else (rev.down_revision,)
            for d in downs:
                down_targets.setdefault(d, []).append(rev.revision)
        branch_points = {k: v for k, v in down_targets.items() if len(v) > 1}
        assert not branch_points, f"branch points detected: {branch_points}"

    def test_releases_created_before_builds_deployments(self):
        from alembic.config import Config
        from alembic.script import ScriptDirectory

        cfg = Config(str(_repo / "alembic.ini"))
        script = ScriptDirectory.from_config(cfg)
        order = [rev.revision for rev in script.walk_revisions("base", "heads")]
        order.reverse()  # base → head
        assert "c1d2e3f4a5b6" in order and "71a2b3c4d5e6" in order
        assert order.index("c1d2e3f4a5b6") < order.index("71a2b3c4d5e6"), (
            "releases (c1d2e3f4a5b6) must be created before builds/deployments "
            "FK to it (71a2b3c4d5e6)"
        )


# ════════════════════════════════════════════════════════════════════
# Schema diff helpers (ORM Base.metadata vs live scratch DB)
# ════════════════════════════════════════════════════════════════════


def _norm_type(t: str) -> str:
    s = str(t).upper()
    if s.startswith("JSONB"):
        return "JSONB"
    if s.startswith("JSON"):
        return "JSON"
    if s.startswith("DATETIME") or s.startswith("TIMESTAMP"):
        return "TIMESTAMP"
    return s


def _fk_map(engine, table: str) -> set[tuple[str, str, str]]:
    """FKs via pg_get_constraintdef — the inspector misreads ondelete."""
    from sqlalchemy import text

    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                "WHERE contype='f' AND conrelid::regclass::text = :t"
            ),
            {"t": table},
        ).all()
    out = set()
    for (defn,) in rows:
        m = re.match(
            r"FOREIGN KEY \((.+?)\) REFERENCES (\w+)\((\w+)\)"
            r"(?: ON DELETE (CASCADE|SET NULL|RESTRICT))?",
            defn,
        )
        src, ref = m.group(1), f"{m.group(2)}.{m.group(3)}"
        ondel = (m.group(4) or "NO ACTION").upper()
        out.add((src, ref, ondel))
    return out


def _orm_fk_map(orm_table) -> set[tuple[str, str, str]]:
    out = set()
    for fk in orm_table.foreign_keys:
        src = ",".join(c.name for c in fk.constraint.columns)
        ref = f"{fk.constraint.referred_table}.{fk.column.name}"
        ondel = (fk.constraint.ondelete or "NO ACTION").upper()
        out.add((src, ref, ondel))
    return out


def _assert_schema_matches_orm(url: str) -> None:
    import orchestrator.cosmo.db.models  # noqa: F401 — registers all tables
    import orchestrator.cosmo.db.models_transfer  # noqa: F401 — durable registry
    from orchestrator.cosmo.db.models_transfer import TransferRegistryBase
    from orchestrator.cosmo.db.session import Base
    from sqlalchemy import create_engine, inspect

    engine = create_engine(url)
    insp = inspect(engine)
    db_tables = set(insp.get_table_names()) - {"alembic_version"}
    # Shared Base (models + notifications) ∪ TransferRegistryBase (durable
    # transfer registry, миграция e4f5a6b7c8d9 после d2e3f4a5b6c7).
    orm_tables = {
        **Base.metadata.tables,
        **TransferRegistryBase.metadata.tables,
    }
    expected = set(orm_tables.keys())

    missing_tables = sorted(expected - db_tables)
    extra_tables = sorted(db_tables - expected)
    assert not missing_tables, f"tables in ORM but not in DB: {missing_tables}"
    assert not extra_tables, f"tables in DB but not in ORM: {extra_tables}"

    col_problems: list[str] = []
    idx_problems: list[str] = []
    fk_problems: list[str] = []

    for tname in sorted(expected & db_tables):
        orm_t = orm_tables[tname]
        db_cols = {c["name"]: c for c in insp.get_columns(tname)}
        for cname, orm_c in orm_t.columns.items():
            if cname not in db_cols:
                col_problems.append(f"{tname}.{cname}: missing in DB")
                continue
            db_c = db_cols[cname]
            if bool(orm_c.nullable) != bool(db_c["nullable"]):
                col_problems.append(
                    f"{tname}.{cname}: nullable ORM={orm_c.nullable} DB={db_c['nullable']}"
                )
            if _norm_type(orm_c.type) != _norm_type(db_c["type"]):
                col_problems.append(
                    f"{tname}.{cname}: type ORM={orm_c.type} DB={db_c['type']}"
                )
        if set(orm_t.columns.keys()) - set(db_cols):
            continue  # already reported missing columns

        orm_idx = {ix.name for ix in orm_t.indexes}
        db_idx = {i["name"] for i in insp.get_indexes(tname)}
        # PG auto-creates backing indexes for PK / UNIQUE constraints; they
        # are not ORM Index() declarations, so exclude them from comparison.
        pk_name = (insp.get_pk_constraint(tname) or {}).get("name")
        db_uq_names = {u["name"] for u in insp.get_unique_constraints(tname) if u.get("name")}
        orm_uq_names = {
            u.name
            for u in orm_t.constraints
            if u.__class__.__name__ == "UniqueConstraint" and u.name
        }
        for name in sorted(orm_idx - db_idx):
            idx_problems.append(f"{tname}: index {name} missing in DB")
        for name in sorted(db_idx - orm_idx - db_uq_names - orm_uq_names - {pk_name}):
            idx_problems.append(f"{tname}: extra index {name} in DB (not in ORM)")

        orm_fks = _orm_fk_map(orm_t)
        db_fks = _fk_map(engine, tname)
        for fk in sorted(orm_fks - db_fks):
            fk_problems.append(f"{tname}: FK missing in DB: {fk}")
        for fk in sorted(db_fks - orm_fks):
            fk_problems.append(f"{tname}: extra FK in DB: {fk}")

    assert not col_problems, "column drift:\n" + "\n".join(col_problems)
    assert not idx_problems, "index drift:\n" + "\n".join(idx_problems)
    assert not fk_problems, "FK drift:\n" + "\n".join(fk_problems)


# ════════════════════════════════════════════════════════════════════
# PG upgrade-path tests (isolated scratch DB)
# ════════════════════════════════════════════════════════════════════


@skip_pg
class TestFreshUpgrade:
    def test_fresh_upgrade_matches_orm(self, scratch_db):
        _run_alembic(["upgrade", "head"])
        _assert_schema_matches_orm(scratch_db)

    def test_repeat_upgrade_is_noop(self, scratch_db):
        _run_alembic(["upgrade", "head"])
        proc = _run_alembic(["current"])
        assert _HEAD in proc.stdout, f"expected version {_HEAD}, got: {proc.stdout}"
        # A second upgrade must succeed and change nothing.
        proc2 = _run_alembic(["upgrade", "head"])
        assert "Running upgrade" not in proc2.stdout, (
            f"repeat upgrade re-ran migrations:\n{proc2.stdout}"
        )
        proc3 = _run_alembic(["current"])
        assert _HEAD in proc3.stdout

    def test_notification_tables_and_columns(self, scratch_db):
        from sqlalchemy import create_engine, inspect

        _run_alembic(["upgrade", "head"])
        engine = create_engine(scratch_db)
        insp = inspect(engine)
        tables = set(insp.get_table_names())
        assert _NOTIF_TABLES <= tables, f"missing notification tables: {_NOTIF_TABLES - tables}"
        cols = {c["name"]: c for c in insp.get_columns("notification_events")}
        assert _norm_type(cols["payload"]["type"]) == "JSONB"
        assert cols["payload"]["nullable"] is False

    def test_domains_indexes_present(self, scratch_db):
        from sqlalchemy import create_engine, inspect

        _run_alembic(["upgrade", "head"])
        engine = create_engine(scratch_db)
        insp = inspect(engine)
        idx = {i["name"] for i in insp.get_indexes("domains")}
        assert {"ix_domains_rbac_config", "ix_domains_created_at", "ix_domains_label"} <= idx

    def test_releases_exists_with_fk_target(self, scratch_db):
        from sqlalchemy import create_engine, inspect

        _run_alembic(["upgrade", "head"])
        engine = create_engine(scratch_db)
        insp = inspect(engine)
        assert "releases" in insp.get_table_names()
        dep_fks = _fk_map(engine, "cosmo_deployments")
        assert any(ref == "releases.id" for _, ref, _ in dep_fks), (
            f"deployments must FK to releases.id, got: {dep_fks}"
        )


@skip_pg
class TestLegacyAndReplay:
    def test_legacy_stamp_path(self, scratch_db):
        """create_all-era DB: all tables exist, no alembic_version.
        Supported path: stamp pre-head revision, then upgrade head
        (only the reconciliation migration runs and must pass)."""
        import psycopg2
        from sqlalchemy import create_engine

        # Build a create_all-equivalent schema (fresh chain, then forget version)
        _run_alembic(["upgrade", "head"])
        engine = create_engine(scratch_db)
        with engine.connect() as conn:
            from sqlalchemy import text

            conn.execute(text("DROP TABLE alembic_version"))
            conn.commit()
        engine.dispose()

        _run_alembic(["stamp", "b8c9d0e1f2a3"])
        _run_alembic(["upgrade", "head"])
        proc = _run_alembic(["current"])
        assert _HEAD in proc.stdout

    def test_replay_after_partial_downgrade(self, scratch_db):
        """Downgrade back into mid-chain state, then replay to head."""
        _run_alembic(["upgrade", "head"])
        _run_alembic(["downgrade", "82c3d4e5f6a7"])
        _run_alembic(["upgrade", "head"])
        proc = _run_alembic(["current"])
        assert _HEAD in proc.stdout
        _assert_schema_matches_orm(scratch_db)
