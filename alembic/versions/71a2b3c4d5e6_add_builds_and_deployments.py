"""add_builds_and_deployments

Revision ID: 71a2b3c4d5e6
Revises: 23b56529e15d
Create Date: 2026-08-30 14:00:00

SAN-012 + SAN-013: Add cosmo_builds and cosmo_deployments tables.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '71a2b3c4d5e6'
down_revision: Union[str, Sequence[str], None] = '23b56529e15d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── Stage 1: cosmo_builds (FK → apps, domains) ──
    op.create_table(
        'cosmo_builds',
        sa.Column('id', sa.String(64), nullable=False),
        sa.Column('app_id', sa.String(64), nullable=False),
        sa.Column('domain_id', sa.String(64), nullable=False),
        sa.Column('commit_sha', sa.String(64), nullable=False),
        sa.Column('branch', sa.String(128), server_default='main', nullable=False),
        sa.Column('status', sa.String(32), server_default='pending', nullable=False),
        sa.Column('artifacts', sa.JSON(), server_default='[]', nullable=False),
        sa.Column('initiator_user_id', sa.String(128), server_default='system', nullable=False),
        sa.Column('build_logs', sa.Text(), nullable=True),
        sa.Column('meta', sa.JSON(), server_default='{}', nullable=False),
        sa.Column('started_at', sa.DateTime(), nullable=True),
        sa.Column('finished_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['app_id'], ['apps.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['domain_id'], ['domains.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        comment='Сборки приложений с фиксацией commit SHA и артефактов',
    )
    op.create_index('ix_cosmo_builds_app_id', 'cosmo_builds', ['app_id'], unique=False)
    op.create_index('ix_cosmo_builds_domain_id', 'cosmo_builds', ['domain_id'], unique=False)
    op.create_index('ix_cosmo_builds_commit_sha', 'cosmo_builds', ['commit_sha'], unique=False)

    # ── Stage 2: cosmo_deployments (FK → builds, apps, domains, releases) ──
    op.create_table(
        'cosmo_deployments',
        sa.Column('id', sa.String(64), nullable=False),
        sa.Column('build_id', sa.String(64), nullable=False),
        sa.Column('app_id', sa.String(64), nullable=False),
        sa.Column('domain_id', sa.String(64), nullable=False),
        sa.Column('release_id', sa.String(64), nullable=True),
        sa.Column('segment', sa.String(32), server_default='bare', nullable=False),
        sa.Column('target_zone', sa.String(16), server_default='zr', nullable=False),
        sa.Column('status', sa.String(32), server_default='pending', nullable=False),
        sa.Column('custom_url', sa.String(512), nullable=True),
        sa.Column('operator_id', sa.String(128), server_default='system', nullable=False),
        sa.Column('env_vars', sa.JSON(), server_default='{}', nullable=False),
        sa.Column('rollback_from_id', sa.String(64), nullable=True),
        sa.Column('started_at', sa.DateTime(), nullable=True),
        sa.Column('finished_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['build_id'], ['cosmo_builds.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['app_id'], ['apps.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['domain_id'], ['domains.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['release_id'], ['releases.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        comment='Развертывания сборок и релизов в зонах ЗР / ЗТ / ЗПЭ',
    )
    op.create_index('ix_cosmo_deployments_app_id', 'cosmo_deployments', ['app_id'], unique=False)
    op.create_index('ix_cosmo_deployments_build_id', 'cosmo_deployments', ['build_id'], unique=False)
    op.create_index('ix_cosmo_deployments_domain_id', 'cosmo_deployments', ['domain_id'], unique=False)
    op.create_index('ix_cosmo_deployments_zone', 'cosmo_deployments', ['target_zone'], unique=False)


def downgrade() -> None:
    op.drop_table('cosmo_deployments')
    op.drop_table('cosmo_builds')
