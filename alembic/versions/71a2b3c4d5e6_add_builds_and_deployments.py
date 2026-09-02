"""add_builds_and_deployments

Revision ID: 71a2b3c4d5e6
Revises: c1d2e3f4a5b6
Create Date: 2026-08-30 14:00:00

SAN-012 + SAN-013: Add cosmo_builds and cosmo_deployments tables.
COS-062: down_revision moved to c1d2e3f4a5b6 (releases table is created
before this revision because the deployment FK references releases.id);
JSON columns aligned to ORM JSONB (models.py declares JSONB for
builds.artifacts / builds.meta / deployments.env_vars).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '71a2b3c4d5e6'
down_revision: Union[str, Sequence[str], None] = 'c1d2e3f4a5b6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── Stage 1: cosmo_builds (FK → apps, domains) ──
    op.create_table(
        'cosmo_builds',
        sa.Column('id', sa.String(64), nullable=False),
        sa.Column('app_id', sa.String(64), nullable=False),
        sa.Column('domain_id', sa.String(64), nullable=False),
        sa.Column('title', sa.String(255), nullable=False),
        sa.Column('commit_sha', sa.String(64), nullable=False),
        sa.Column('branch', sa.String(128), server_default='main', nullable=False),
        sa.Column('status', sa.String(32), server_default='pending', nullable=False),
        sa.Column('artifacts', postgresql.JSONB(astext_type=sa.Text()), server_default='[]', nullable=False),
        sa.Column('initiator_user_id', sa.String(128), server_default='system', nullable=False),
        sa.Column('build_logs', sa.Text(), nullable=True),
        sa.Column('meta', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
        sa.Column('started_at', sa.DateTime(), nullable=True),
        sa.Column('finished_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['app_id'], ['apps.id']),
        sa.ForeignKeyConstraint(['domain_id'], ['domains.id']),
        sa.PrimaryKeyConstraint('id'),
        comment='Сборки приложений с фиксацией commit SHA и артефактов',
    )
    op.create_index('ix_builds_app_id', 'cosmo_builds', ['app_id'], unique=False)
    op.create_index('ix_builds_domain_id', 'cosmo_builds', ['domain_id'], unique=False)
    op.create_index('ix_builds_status', 'cosmo_builds', ['status'], unique=False)
    op.create_index('ix_builds_created_at', 'cosmo_builds', ['created_at'], unique=False)
    op.create_index('ix_builds_artifacts', 'cosmo_builds', ['artifacts'], unique=False, postgresql_using='gin')

    # ── Stage 2: cosmo_deployments (FK → builds, apps, domains, releases) ──
    op.create_table(
        'cosmo_deployments',
        sa.Column('id', sa.String(64), nullable=False),
        sa.Column('build_id', sa.String(64), nullable=False),
        sa.Column('app_id', sa.String(64), nullable=False),
        sa.Column('domain_id', sa.String(64), nullable=False),
        sa.Column('release_id', sa.String(64), nullable=True),
        sa.Column('segment', sa.String(32), server_default='bare', nullable=False),
        sa.Column('target_zone', sa.String(8), server_default='zr', nullable=False),
        sa.Column('runtime_name', sa.String(128), server_default='docker', nullable=False),
        sa.Column('status', sa.String(32), server_default='pending', nullable=False),
        sa.Column('custom_url', sa.String(512), nullable=True),
        sa.Column('operator_id', sa.String(128), server_default='system', nullable=False),
        sa.Column('env_vars', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
        sa.Column('rollback_from_id', sa.String(64), nullable=True),
        sa.Column('started_at', sa.DateTime(), nullable=True),
        sa.Column('finished_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['build_id'], ['cosmo_builds.id']),
        sa.ForeignKeyConstraint(['app_id'], ['apps.id']),
        sa.ForeignKeyConstraint(['domain_id'], ['domains.id']),
        sa.ForeignKeyConstraint(['release_id'], ['releases.id']),
        sa.PrimaryKeyConstraint('id'),
        comment='Развертывания сборок и релизов в зонах ЗР / ЗТ / ЗПЭ',
    )
    op.create_index('ix_deploys_app_id', 'cosmo_deployments', ['app_id'], unique=False)
    op.create_index('ix_deploys_build_id', 'cosmo_deployments', ['build_id'], unique=False)
    op.create_index('ix_deploys_domain_id', 'cosmo_deployments', ['domain_id'], unique=False)
    op.create_index('ix_deploys_status', 'cosmo_deployments', ['status'], unique=False)
    op.create_index('ix_deploys_created_at', 'cosmo_deployments', ['created_at'], unique=False)
    op.create_index('ix_deploys_target_zone', 'cosmo_deployments', ['target_zone'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_deploys_target_zone', table_name='cosmo_deployments')
    op.drop_index('ix_deploys_created_at', table_name='cosmo_deployments')
    op.drop_index('ix_deploys_status', table_name='cosmo_deployments')
    op.drop_index('ix_deploys_domain_id', table_name='cosmo_deployments')
    op.drop_index('ix_deploys_build_id', table_name='cosmo_deployments')
    op.drop_index('ix_deploys_app_id', table_name='cosmo_deployments')
    op.drop_table('cosmo_deployments')
    op.drop_index('ix_builds_artifacts', table_name='cosmo_builds', postgresql_using='gin')
    op.drop_index('ix_builds_created_at', table_name='cosmo_builds')
    op.drop_index('ix_builds_status', table_name='cosmo_builds')
    op.drop_index('ix_builds_domain_id', table_name='cosmo_builds')
    op.drop_index('ix_builds_app_id', table_name='cosmo_builds')
    op.drop_table('cosmo_builds')
