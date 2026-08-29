"""COS-089: Migration verifier."""
import os, sys
from pathlib import Path

_pg_ok = None

def is_pg_available():
    global _pg_ok
    if _pg_ok is not None:
        return _pg_ok
    try:
        from sqlalchemy import create_engine, text
        url = os.getenv("COSMO_DATABASE_URL", "postgresql+psycopg2://prettyk:prettyk@localhost:5432/cosmo")
        url = url.replace("+asyncpg", "+psycopg2")
        e = create_engine(url, connect_args={"connect_timeout": 3})
        with e.connect() as c:
            c.execute(text("SELECT 1"))
        e.dispose()
        _pg_ok = True
    except Exception:
        _pg_ok = False
    return _pg_ok


def _ensure_path():
    repo = Path(__file__).resolve().parents[2]
    orch = repo / "orchestrator"
    if str(orch) not in sys.path:
        sys.path.insert(0, str(orch))


def _alembic_cfg():
    from alembic.config import Config
    from orchestrator.cosmo.db.session import get_sync_url
    repo = Path(__file__).resolve().parents[2]
    cfg = Config(str(repo / "alembic.ini"))
    url = os.getenv("COSMO_DATABASE_URL", get_sync_url())
    cfg.set_main_option("sqlalchemy.url", url.replace("+asyncpg", "+psycopg2"))
    return cfg


def _sync_session():
    from orchestrator.cosmo.db.session import get_sync_session
    return get_sync_session()


def alembic_cycle():
    _ensure_path()
    from alembic import command
    cfg = _alembic_cfg()
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    return True


ALL_ENUMS = {
    "brick_type": {"sast","sca","build","deploy","dast","autotest","gate"},
    "batch_status": {"pending","running","passed","failed","blocked"},
    "batch_type": {"build","static_scan","deploy","dynamic_test"},
    "run_trigger": {"scheduled","pre_release","emergency","manual"},
    "run_status": {"draft","pending","queued","running","succeeded","failed","blocked","cancelled"},
    "gate_type": {"automatic","manual"},
    "gate_decision": {"pass","block","manual_required"},
    "evidence_type": {"screenshot","raw_request","raw_response","log","alert","finding","decision"},
}

EXPECTED_GIN = [
    ("pipeline_bricks","ix_pipeline_bricks_definition_json"),
    ("pipeline_bricks","ix_pipeline_bricks_depends_on"),
    ("pipeline_bricks","ix_pipeline_bricks_gates"),
    ("batches","ix_batches_bricks_refs"),
    ("batches","ix_batches_artifacts"),
    ("batches","ix_batches_evidence_refs"),
    ("gates","ix_gates_policy_json"),
    ("runs","ix_runs_findings_refs"),
    ("domains","ix_domains_rbac_config"),
    ("evidence_ledger","ix_evidence_ledger_provenance_json"),
]


def verify_enums():
    s = _sync_session()
    try:
        rows = s.execute(
            s.bind if hasattr(s, 'bind') else None,
        )
        from sqlalchemy import text
        rows = s.execute(text(
            "SELECT t.typname, string_agg(e.enumlabel, ',' order by e.enumsortorder) "
            "FROM pg_type t JOIN pg_enum e ON t.oid = e.enumtypid "
            "WHERE t.typtype = 'e' GROUP BY t.typname ORDER BY t.typname"
        )).all()
        current = {r[0]: set(r[1].split(",")) for r in rows}
        missing = set(ALL_ENUMS) - set(current)
        bad = {}
        for name, expected in ALL_ENUMS.items():
            actual = current.get(name)
            if actual and actual != expected:
                bad[name] = {"missing": expected - actual, "extra": actual - expected}
        return {"ok": not missing and not bad, "missing": sorted(missing), "mismatches": bad}
    finally:
        s.close()


def verify_gin():
    s = _sync_session()
    try:
        from sqlalchemy import text
        rows = s.execute(text(
            "SELECT tablename, indexname FROM pg_indexes WHERE indexdef ILIKE '%USING gin%'"
        )).all()
        existing = {(r[0], r[1]) for r in rows}
        missing = sorted(set(EXPECTED_GIN) - existing)
        return {"ok": not missing, "missing": missing, "total": len(existing), "expected": len(EXPECTED_GIN)}
    finally:
        s.close()


def verify_schema():
    from sqlalchemy import inspect
    from orchestrator.cosmo.db.session import get_sync_engine
    import orchestrator.cosmo.db.models
    from orchestrator.cosmo.db.session import Base
    engine = get_sync_engine()
    insp = inspect(engine)
    expected = set(Base.metadata.tables.keys())
    actual = set(insp.get_table_names()) - {"alembic_version"}
    missing = sorted(expected - actual)
    return {"ok": not missing, "expected_count": len(expected), "actual_count": len(actual), "missing_tables": missing}


def test_non_destructive():
    s = _sync_session()
    try:
        from sqlalchemy import text
        s.execute(text("DROP TABLE IF EXISTS _test_nd"))
        s.execute(text("CREATE TABLE _test_nd (id SERIAL PRIMARY KEY, name TEXT)"))
        s.execute(text("INSERT INTO _test_nd (name) VALUES ('t1'), ('t2')"))
        s.commit()
        s.execute(text("ALTER TABLE _test_nd ADD COLUMN IF NOT EXISTS nc TEXT DEFAULT 'dv'"))
        s.commit()
        old = [r[0] for r in s.execute(text("SELECT name FROM _test_nd ORDER BY id")).all()]
        new = [r[0] for r in s.execute(text("SELECT nc FROM _test_nd")).all()]
        ok = old == ["t1","t2"] and all(v == "dv" for v in new)
        s.execute(text("DROP TABLE IF EXISTS _test_nd"))
        s.commit()
        return {"ok": ok, "old_data": old, "new_defaults": new}
    except Exception as exc:
        s.rollback()
        try:
            s.execute(text("DROP TABLE IF EXISTS _test_nd"))
            s.commit()
        except Exception:
            s.rollback()
        return {"ok": False, "error": str(exc)}
    finally:
        s.close()