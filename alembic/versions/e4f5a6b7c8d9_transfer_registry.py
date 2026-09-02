"""Durable Transfer Registry: transfer_plans / transfer_items /
transfer_landing_states / transfer_received_revisions

Revision ID: e4f5a6b7c8d9
Revises: d2e3f4a5b6c7
Create Date: 2026-09-02 12:00:00

Durable persistence for the in-memory TransferRegistry (COS-058 follow-up).
Models live on a separate TransferRegistryBase (orchestrator/cosmo/db/
models_transfer.py) so the d2e3f4a5b6c7 drift check (shared Base only) is
unaffected.

Guarded creates: legacy create_all-era databases (stamp b8c9d0e1f2a3 →
upgrade head) already carry these tables, so every create is skipped when
the table exists.

Downgrade: drop all four tables (registry data is reconstructible from
transfer manifests; downgrade is only exercised on scratch databases).
"""
import sys
from pathlib import Path
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'e4f5a6b7c8d9'
down_revision: Union[str, Sequence[str], None] = 'd2e3f4a5b6c7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

_TRANSFER_TABLES = (
    "transfer_plans",
    "transfer_items",
    "transfer_landing_states",
    "transfer_received_revisions",
)


def _existing_tables() -> set[str]:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    return set(insp.get_table_names())


def _verify_transfer_schema() -> None:
    """Post-create drift check: TransferRegistryBase vs actual database.

    Strict symmetric diff over the transfer subset — a guarded legacy-stamp
    path must produce byte-identical schema to a fresh chain.
    """
    from orchestrator.cosmo.db.models_transfer import TransferRegistryBase

    bind = op.get_bind()
    insp = sa.inspect(bind)
    actual = set(insp.get_table_names())
    expected = set(TransferRegistryBase.metadata.tables.keys())
    missing = sorted(expected - actual)
    if missing:
        raise RuntimeError(
            "Durable Transfer Registry migration failed: tables declared on "
            f"TransferRegistryBase but absent in the database: {missing}"
        )
    extra = sorted(set(_TRANSFER_TABLES) - actual)
    if extra:
        raise RuntimeError(
            "Durable Transfer Registry migration failed: transfer tables "
            f"absent from TransferRegistryBase but present in DB: {extra}"
        )


def upgrade() -> None:
    existing = _existing_tables()

    if "transfer_plans" not in existing:
        op.create_table(
            'transfer_plans',
            sa.Column('plan_id', sa.String(64), nullable=False),
            sa.Column('release_id', sa.String(64), nullable=False),
            sa.Column('domain_id', sa.String(64), nullable=False),
            sa.Column('correlation_id', sa.String(128), nullable=False),
            sa.Column('source_zone', sa.String(8), nullable=False),
            sa.Column('target_zone', sa.String(8), nullable=False),
            sa.Column('status', sa.String(32), nullable=False),
            sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint('plan_id'),
            comment='Durable Transfer Registry: планы передачи (COS-050/058)',
        )
        op.create_index('ix_transfer_plans_release', 'transfer_plans', ['release_id'])
        op.create_index('ix_transfer_plans_domain', 'transfer_plans', ['domain_id'])
        op.create_index('ix_transfer_plans_status', 'transfer_plans', ['status'])

    if "transfer_items" not in existing:
        op.create_table(
            'transfer_items',
            sa.Column('item_id', sa.String(64), nullable=False),
            sa.Column('plan_id', sa.String(64), nullable=False),
            sa.Column('release_id', sa.String(64), nullable=False),
            sa.Column('correlation_id', sa.String(128), nullable=False),
            sa.Column('artifact_plane', sa.String(32), nullable=False),
            sa.Column('package_mode', sa.String(32), nullable=False),
            sa.Column('transport_profile', sa.String(64), nullable=False),
            sa.Column('status', sa.String(32), nullable=False),
            sa.Column('revision_key', sa.String(128), nullable=False),
            sa.Column('retry_count', sa.Integer(), nullable=False),
            sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.Column('updated_at', sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(['plan_id'], ['transfer_plans.plan_id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('item_id'),
            sa.UniqueConstraint('revision_key', 'item_id', name='uq_transfer_item_revision'),
            comment='Durable Transfer Registry: items передачи (COS-050/058)',
        )
        op.create_index('ix_transfer_items_plan', 'transfer_items', ['plan_id'])
        op.create_index('ix_transfer_items_release', 'transfer_items', ['release_id'])
        op.create_index('ix_transfer_items_status', 'transfer_items', ['status'])
        op.create_index('ix_transfer_items_revision_key', 'transfer_items', ['revision_key'])

    if "transfer_landing_states" not in existing:
        op.create_table(
            'transfer_landing_states',
            sa.Column('item_id', sa.String(64), nullable=False),
            sa.Column('state', sa.String(32), nullable=False),
            sa.Column('revision_key', sa.String(128), nullable=False),
            sa.Column('history', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
            sa.Column('updated_at', sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(
                ['item_id'], ['transfer_items.item_id'], ondelete='CASCADE'
            ),
            sa.PrimaryKeyConstraint('item_id'),
            comment='Durable Transfer Registry: landing state machines (COS-053)',
        )
        op.create_index('ix_transfer_landing_state', 'transfer_landing_states', ['state'])

    if "transfer_received_revisions" not in existing:
        op.create_table(
            'transfer_received_revisions',
            sa.Column('revision_key', sa.String(128), nullable=False),
            sa.Column('item_id', sa.String(64), nullable=False),
            sa.Column('received_at', sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint('revision_key'),
            comment='Durable Transfer Registry: received revision index (idempotency)',
        )
        op.create_index('ix_transfer_recv_rev_item', 'transfer_received_revisions', ['item_id'])

    _verify_transfer_schema()


def downgrade() -> None:
    existing = _existing_tables()
    if "transfer_received_revisions" in existing:
        op.drop_index('ix_transfer_recv_rev_item', table_name='transfer_received_revisions')
        op.drop_table('transfer_received_revisions')
    if "transfer_landing_states" in existing:
        op.drop_index('ix_transfer_landing_state', table_name='transfer_landing_states')
        op.drop_table('transfer_landing_states')
    if "transfer_items" in existing:
        op.drop_index('ix_transfer_items_revision_key', table_name='transfer_items')
        op.drop_index('ix_transfer_items_status', table_name='transfer_items')
        op.drop_index('ix_transfer_items_release', table_name='transfer_items')
        op.drop_index('ix_transfer_items_plan', table_name='transfer_items')
        op.drop_table('transfer_items')
    if "transfer_plans" in existing:
        op.drop_index('ix_transfer_plans_status', table_name='transfer_plans')
        op.drop_index('ix_transfer_plans_domain', table_name='transfer_plans')
        op.drop_index('ix_transfer_plans_release', table_name='transfer_plans')
        op.drop_table('transfer_plans')
