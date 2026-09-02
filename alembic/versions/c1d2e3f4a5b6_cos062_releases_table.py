"""COS-062: releases table

Revision ID: c1d2e3f4a5b6
Revises: 23b56529e15d
Create Date: 2026-09-02 10:00:00

Adds the `releases` table exactly as declared in
orchestrator/cosmo/db/models.py::Release (ORM is the source of truth).

This migration closes blocker #1 of COS-059: `71a2b3c4d5e6` (builds and
deployments) declares FKs to `releases.id`, but no prior migration created
the table, so a fresh `alembic upgrade head` always failed with
UndefinedTable on this step.

Note for legacy databases bootstrapped via `create_all` (pre-alembic era):
they already contain `releases`. The supported path for such databases is
`alembic stamp b8c9d0e1f2a3` followed by `alembic upgrade head` — do NOT
run the full chain from base against them (they hit DuplicateTable at the
initial migration by design).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'c1d2e3f4a5b6'
down_revision: Union[str, Sequence[str], None] = '23b56529e15d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'releases',
        sa.Column('id', sa.String(64), nullable=False),
        sa.Column('domain_id', sa.String(64), nullable=False),
        sa.Column('plan_id', sa.String(64), nullable=False),
        sa.Column('status', sa.String(32), server_default='draft', nullable=False),
        sa.Column('current_zone', sa.String(8), server_default='zr', nullable=False),
        sa.Column('version', sa.String(64), server_default='1.0.0', nullable=False),
        sa.Column('run_ids', postgresql.JSONB(astext_type=sa.Text()), server_default='[]', nullable=False),
        sa.Column('approvals', postgresql.JSONB(astext_type=sa.Text()), server_default='[]', nullable=False),
        sa.Column('artifacts', postgresql.JSONB(astext_type=sa.Text()), server_default='[]', nullable=False),
        sa.Column('transfer_history', postgresql.JSONB(astext_type=sa.Text()), server_default='[]', nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['domain_id'], ['domains.id']),
        sa.ForeignKeyConstraint(['plan_id'], ['pipeline_plans.id']),
        sa.PrimaryKeyConstraint('id'),
        comment='Релизы и межзонный трансфер (ЗР -> ЗТ -> ЗПЭ)',
    )
    op.create_index('ix_releases_domain_id', 'releases', ['domain_id'], unique=False)
    op.create_index('ix_releases_status', 'releases', ['status'], unique=False)
    op.create_index('ix_releases_created_at', 'releases', ['created_at'], unique=False)
    op.create_index('ix_releases_run_ids', 'releases', ['run_ids'], unique=False, postgresql_using='gin')


def downgrade() -> None:
    op.drop_index('ix_releases_run_ids', table_name='releases', postgresql_using='gin')
    op.drop_index('ix_releases_created_at', table_name='releases')
    op.drop_index('ix_releases_status', table_name='releases')
    op.drop_index('ix_releases_domain_id', table_name='releases')
    op.drop_table('releases')
