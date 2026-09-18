"""COS-133: cosmo_workspace_runs.original_run_id (rerun link)

Revision ID: f5a6b7c8d9e0
Revises: e4f5a6b7c8d9
Create Date: 2026-09-18 12:00:00

Adds the rerun backlink to the workspace run tracker: a rerun creates a
new WorkspaceRunRow whose ``original_run_id`` points at the run it was
restarted from.

Guarded DDL: ``cosmo_workspace_runs`` lives on ExecutionBase and is
created by idempotent ``create_all`` at API startup (outside the frozen
alembic chain). A pure-alembic scratch database therefore has no such
table, and a create_all-era database already carries the column once the
model is updated — in both cases this revision is a safe no-op. It only
performs the ALTER on databases that have the table but not the column.
"""
import sys
from pathlib import Path
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'f5a6b7c8d9e0'
down_revision: Union[str, Sequence[str], None] = 'e4f5a6b7c8d9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

_TABLE = "cosmo_workspace_runs"
_COLUMN = "original_run_id"


def _has_table() -> bool:
    bind = op.get_bind()
    return _TABLE in set(sa.inspect(bind).get_table_names())


def _has_column() -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    return _COLUMN in {c["name"] for c in insp.get_columns(_TABLE)}


def upgrade() -> None:
    if not _has_table():
        return  # scratch/alembic-only DB: table is create_all-managed
    if not _has_column():
        op.add_column(
            _TABLE,
            sa.Column(_COLUMN, sa.String(64), nullable=True),
        )


def downgrade() -> None:
    if not _has_table():
        return
    if _has_column():
        op.drop_column(_TABLE, _COLUMN)
