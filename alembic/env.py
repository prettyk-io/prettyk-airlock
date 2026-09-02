"""Alembic env — Cosmoport 2.0 PostgreSQL migrations."""
import os
import sys
from pathlib import Path

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# ── Ensure orchestrator/ is on sys.path ──
_here = Path(__file__).resolve().parents[0]
_repo = _here.parent
_orch = _repo / "orchestrator"
if str(_orch) not in sys.path:
    sys.path.insert(0, str(_orch))

# ── Alembic Config ──
config = context.config
if config.config_file_name is not None:
    if config.attributes.get("cosmo_in_process"):
        # COS-076: in-process цикл (migration_verifier). fileConfig() не только
        # глушит логгеры вне ini (disable_existing_loggers), но и СНОСИТ
        # handlers на root/sqlalchemy/alembic — вместе с caplog-хэндлером
        # pytest. В хост-процессе логирование уже настроено (pytest/приложение)
        # — не трогаем его вообще. CLI-прогоны (subprocess) конфигурируются
        # обычной веткой ниже.
        pass
    else:
        # COS-076: disable_existing_loggers=False — не глушим логгеры, не
        # упомянутые в ini (cosmoport.*). Дефолт fileConfig() ставил им
        # .disabled=True после каждого standalone-прогона alembic.
        fileConfig(config.config_file_name, disable_existing_loggers=False)

# ── Target metadata: shared Base + TransferRegistryBase (durable registry) ──
from orchestrator.cosmo.db.session import Base, env_override_url, get_sync_url
# Import all models to ensure they're registered on Base.metadata
import orchestrator.cosmo.db.models  # noqa: F401 — side-effect: registers all tables
import orchestrator.cosmo.db.models_notifications  # noqa: F401 — COS-055
import orchestrator.cosmo.db.models_transfer  # noqa: F401 — durable transfer registry

target_metadata = [Base.metadata, orchestrator.cosmo.db.models_transfer.TransferRegistryBase.metadata]


def _target_url() -> str:
    """COS-078 canonical DB-URL resolution (см. контракт в session.py):

    1. Explicit programmatic target: cfg.attributes["cosmo_url_explicit"]
       (in-process verifier передаёт scratch-URL). Env НЕ консультируется —
       conftest-set env не может увести цикл мимо scratch (замена
       COS-073 pop-env хака архитектурным маркером).
    2. COSMO_DATABASE_URL env — явный override, LOUD-logged (env_override_url).
    3. cfg sqlalchemy.url (ini placeholder, dev stand) → get_sync_url().
    """
    if config.attributes.get("cosmo_url_explicit"):
        url = config.get_main_option("sqlalchemy.url")
        context.config.print_stdout(
            "COS-078: explicit cfg URL target in effect — env override not consulted")
        return (url or get_sync_url()).replace("+asyncpg", "+psycopg2")
    env_url = env_override_url()
    if env_url:
        return env_url.replace("+asyncpg", "+psycopg2")
    cfg_url = config.get_main_option("sqlalchemy.url")
    return (cfg_url or get_sync_url()).replace("+asyncpg", "+psycopg2")


def run_migrations_offline() -> None:
    url = _target_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    url = _target_url()
    connectable = engine_from_config(
        {"sqlalchemy.url": url},
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()