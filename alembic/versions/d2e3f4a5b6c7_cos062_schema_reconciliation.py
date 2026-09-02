"""COS-062: schema reconciliation & drift verification

Revision ID: d2e3f4a5b6c7
Revises: b8c9d0e1f2a3
Create Date: 2026-09-02 11:00:00

Runs after every `alembic upgrade head`:

1. Guarded add of `ix_domains_created_at` / `ix_domains_label` — needed only
   by databases that were upgraded while the pre-COS-062 initial migration
   (without these indexes) was already stamped; fresh chains create them
   earlier, so the guarded check is a no-op there.
2. Drift verification: every table declared on the shared ORM Base
   (orchestrator/cosmo/db/models.py and the modules it registers) MUST exist
   in the database. Missing tables are a hard failure with the exact list —
   silent drift between Base.metadata and the migration chain is what broke
   COS-059 startup (releases never created while FK'd by deployments).

Legacy create_all-era databases: `alembic stamp b8c9d0e1f2a3` then
`alembic upgrade head` — this revision then only verifies.
"""
import sys
from pathlib import Path
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'd2e3f4a5b6c7'
down_revision: Union[str, Sequence[str], None] = 'b8c9d0e1f2a3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


def _add_index_if_missing(index_name: str, table: str, column: str) -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    existing = {i["name"] for i in insp.get_indexes(table)}
    if index_name not in existing:
        op.create_index(index_name, table, [column], unique=False)


def upgrade() -> None:
    # 1) Guarded repair for pre-COS-062 upgraded databases
    _add_index_if_missing('ix_domains_created_at', 'domains', 'created_at')
    _add_index_if_missing('ix_domains_label', 'domains', 'label')

    # 2) Drift verification: ORM Base.metadata vs actual database
    from orchestrator.cosmo.db.session import Base
    import orchestrator.cosmo.db.models  # noqa: F401 — registers all tables

    bind = op.get_bind()
    insp = sa.inspect(bind)
    actual = set(insp.get_table_names())
    expected = set(Base.metadata.tables.keys())
    missing = sorted(expected - actual)
    if missing:
        raise RuntimeError(
            "COS-062 schema reconciliation failed: tables declared in ORM "
            "Base.metadata but absent in the database: "
            f"{missing}. Add the corresponding alembic migration; do NOT "
            "silence this check."
        )


def downgrade() -> None:
    # Verification is forward-only: there is no state to undo. The guarded
    # index adds above are part of the ORM contract and stay.
    pass
