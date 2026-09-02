"""COS-089: Migration verifier.

Scratch-DB hygiene (durable transfer registry package): `alembic_cycle()`
прогоняет upgrade→downgrade→upgrade на ИЗОЛИРОВАННОЙ scratch-БД и никогда
не трогает shared dev-БД — downgrade на dev запрещён guard'ом.

COS-078:
  - URL-резолв единый через session.get_sync_url() (env override loud-logged
    там) — локальные os.getenv-дубли убраны.
  - In-process cycle указывает scratch через cfg + attributes
    ["cosmo_url_explicit"]=True — env.py не консультирует env (замена
    pop-env хака архитектурным маркером).
  - Scratch-имена уникальны per-run (pg_type_typname_nsp_index catalog-race
    mitigation при параллельных pytest на стенде).
  - verify_schema(url=...) умеет верифицировать произвольную БД —
    migration-тесты больше не зависят от состояния dev-БД.
"""
import os, sys
from pathlib import Path
import uuid

SCRATCH_DB = "cosmo_scratch_cycle"  # legacy fixed name (compat reference)
_SCRATCH_PREFIX = "cosmo_scratch"


def scratch_name(kind: str = "cycle") -> str:
    """COS-078: уникальное scratch-имя per-run (guard-префикс сохранён)."""
    return f"cosmo_scratch_{kind}_{uuid.uuid4().hex[:8]}"


_pg_ok = None


def _ensure_path():
    repo = Path(__file__).resolve().parents[3]
    orch = repo / "orchestrator"
    if str(orch) not in sys.path:
        sys.path.insert(0, str(orch))


def _deterministic_host(url: str) -> str:
    """localhost резолвится в ::1, который перехватывает wslrelay (чужой PG
    в WSL) — на 127.0.0.1 всегда com.docker.backend → контейнер cosmo-postgres."""
    return url.replace("@localhost:", "@127.0.0.1:")


def is_pg_available():
    global _pg_ok
    if _pg_ok is not None:
        return _pg_ok
    try:
        _ensure_path()
        from sqlalchemy import create_engine, text
        # COS-078: единый резолв через session (env override loud-logged там).
        from orchestrator.cosmo.db.session import get_sync_url
        url = _deterministic_host(get_sync_url())
        e = create_engine(url, connect_args={"connect_timeout": 3})
        with e.connect() as c:
            c.execute(text("SELECT 1"))
        e.dispose()
        _pg_ok = True
    except Exception:
        _pg_ok = False
    return _pg_ok


def _alembic_cfg(url: str | None = None, explicit: bool = False):
    from alembic.config import Config
    # COS-078: единый резолв через session; env дублирование убрано.
    from orchestrator.cosmo.db.session import get_sync_url
    repo = Path(__file__).resolve().parents[3]
    cfg = Config(str(repo / "alembic.ini"))
    if url is None:
        url = get_sync_url()
    cfg.set_main_option("sqlalchemy.url", url.replace("+asyncpg", "+psycopg2"))
    # COS-076: verifier всегда in-process — env.py не должен вызывать
    # fileConfig() (сносит handlers на root вместе с caplog-хэндлером
    # pytest и глушит логгеры вне ini).
    cfg.attributes["cosmo_in_process"] = True
    if explicit:
        # env.py НЕ консультирует env при явном программном таргете.
        cfg.attributes["cosmo_url_explicit"] = True
    return cfg


def _sync_session():
    from orchestrator.cosmo.db.session import get_sync_session
    return get_sync_session()


def _assert_scratch_target(url: str) -> None:
    """Guard: downgrade-цикл допустим ТОЛЬКО на scratch-БД, никогда на dev."""
    from sqlalchemy.engine import make_url

    dbname = (make_url(url).database or "").lower()
    if not dbname.startswith(_SCRATCH_PREFIX):
        raise RuntimeError(
            f"alembic_cycle refuses to run upgrade/downgrade cycle against "
            f"non-scratch database '{dbname}'. Only '{_SCRATCH_PREFIX}*' "
            "databases are allowed (downgrade on the shared dev DB is forbidden)."
        )


def alembic_cycle(keep_scratch: bool = False):
    """Upgrade→downgrade→upgrade на изолированной scratch-БД.

    Никогда не трогает shared dev-БД: scratch создаётся под уникальным
    именем ``cosmo_scratch_<kind>_<hex>`` (COS-078: per-run имена —
    mitigation каталожной гонки pg_type_typname_nsp_index при параллельных
    pytest), после цикла дропается вместе с соединениями.

    COS-078: env COSMO_DATABASE_URL НЕ снимается — env.py видит
    cfg.attributes["cosmo_url_explicit"] и не консультирует env
    (архитектурная замена pop-env хака COS-073).

    Returns: scratch_url при keep_scratch=True (для последующей
    verify_schema(url=...)), иначе True.
    """
    _ensure_path()
    import psycopg2
    from alembic import command
    from sqlalchemy.engine import make_url
    from orchestrator.cosmo.db.session import get_sync_url

    base_url = _deterministic_host(get_sync_url())
    u = make_url(base_url)
    # str(URL) маскирует пароль как "***" (SQLAlchemy 2.0) — рендерим с ним.
    scratch_db = scratch_name("cycle")
    scratch_url = u.set(database=scratch_db).render_as_string(hide_password=False)
    _assert_scratch_target(scratch_url)

    admin_kwargs = dict(
        host=u.host or "localhost",
        port=u.port or 5432,
        user=u.username,
        password=u.password,
        dbname="postgres",
        connect_timeout=3,
    )

    def _admin():
        return psycopg2.connect(**admin_kwargs)

    def _drop_scratch():
        conn = _admin()
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname = %s AND pid <> pg_backend_pid()",
            (scratch_db,),
        )
        cur.execute(f"DROP DATABASE IF EXISTS {scratch_db}")
        conn.close()

    _drop_scratch()
    conn = _admin()
    conn.autocommit = True
    conn.cursor().execute(f"CREATE DATABASE {scratch_db}")
    conn.close()

    try:
        # explicit=True: env.py не консультирует env — scratch-URL каноничен
        # даже при conftest-set COSMO_DATABASE_URL.
        cfg = _alembic_cfg(url=scratch_url, explicit=True)
        command.upgrade(cfg, "head")
        command.downgrade(cfg, "base")
        command.upgrade(cfg, "head")
        if keep_scratch:
            return scratch_url
        return True
    finally:
        if not keep_scratch:
            _drop_scratch()


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
    ("evidence_ledger","ix_evidence_provenance_json"),
]


def drop_scratch_db(scratch_url: str) -> None:
    """COS-078: дропнуть scratch-БД (terminate + DROP IF EXISTS).

    Guard: отказывается работать с non-scratch именами.
    """
    import psycopg2
    from sqlalchemy.engine import make_url

    u = make_url(scratch_url)
    _assert_scratch_target(scratch_url)
    conn = psycopg2.connect(
        host=u.host or "localhost",
        port=u.port or 5432,
        user=u.username,
        password=u.password,
        dbname="postgres",
        connect_timeout=3,
    )
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute(
        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
        "WHERE datname = %s AND pid <> pg_backend_pid()",
        (u.database,),
    )
    cur.execute(f"DROP DATABASE IF EXISTS {u.database}")
    conn.close()


def _sql_engine_session(url: str | None = None):
    """COS-078: session для verify-функций — явный url (scratch) или сессионная БД."""
    if url is not None:
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        engine = create_engine(url.replace("+asyncpg", "+psycopg2"), future=True)
        return engine, sessionmaker(bind=engine, autoflush=False, autocommit=False)()
    return None, _sync_session()


def verify_enums(url: str | None = None):
    from sqlalchemy import text

    engine, s = _sql_engine_session(url)
    try:
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
        if engine is not None:
            engine.dispose()


def verify_gin(url: str | None = None):
    from sqlalchemy import text

    engine, s = _sql_engine_session(url)
    try:
        rows = s.execute(text(
            "SELECT tablename, indexname FROM pg_indexes WHERE indexdef ILIKE '%USING gin%'"
        )).all()
        existing = {(r[0], r[1]) for r in rows}
        missing = sorted(set(EXPECTED_GIN) - existing)
        return {"ok": not missing, "missing": missing, "total": len(existing), "expected": len(EXPECTED_GIN)}
    finally:
        s.close()
        if engine is not None:
            engine.dispose()


def verify_schema(url: str | None = None):
    """COS-078: schema verification против произвольной БД.

    url=None → get_sync_engine() (legacy: dev/сессионная БД). Явный url —
    изолированная scratch-БД: migration-тесты не зависят от состояния dev.
    """
    from sqlalchemy import inspect, create_engine
    import orchestrator.cosmo.db.models
    import orchestrator.cosmo.db.models_transfer
    from orchestrator.cosmo.db.session import Base
    from orchestrator.cosmo.db.models_transfer import TransferRegistryBase
    if url is not None:
        engine = create_engine(url.replace("+asyncpg", "+psycopg2"), future=True)
    else:
        engine = get_sync_engine()
    try:
        insp = inspect(engine)
        expected = set(Base.metadata.tables.keys()) | set(TransferRegistryBase.metadata.tables.keys())
        actual = set(insp.get_table_names()) - {"alembic_version"}
        missing = sorted(expected - actual)
        return {"ok": not missing, "expected_count": len(expected), "actual_count": len(actual), "missing_tables": missing}
    finally:
        if url is not None:
            engine.dispose()


def test_non_destructive(url: str | None = None):
    engine, s = _sql_engine_session(url)
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
        if engine is not None:
            engine.dispose()