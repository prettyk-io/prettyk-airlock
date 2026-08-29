"""Alembic env — Cosmoport 2.0 PostgreSQL migrations."""
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
    fileConfig(config.config_file_name)

# ── Target metadata: all 11 Cosmo ORM tables ──
from orchestrator.cosmo.db.session import Base, get_sync_url
# Import all models to ensure they're registered on Base.metadata
import orchestrator.cosmo.db.models  # noqa: F401 — side-effect: registers all tables

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = get_sync_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    url = get_sync_url()
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