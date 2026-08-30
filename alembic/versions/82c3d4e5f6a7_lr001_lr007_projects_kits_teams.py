"""LR-001..LR-007: Add Project, KITS Tags, Teams, Release Types, ReleaseBatch, Artifact Registry, Instance Config

Revision ID: 82c3d4e5f6a7
Revises: 71a2b3c4d5e6
Create Date: 2026-08-30 15:00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '82c3d4e5f6a7'
down_revision: Union[str, Sequence[str], None] = '71a2b3c4d5e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # LR-001: Projects
    op.create_table(
        'projects',
        sa.Column('id', sa.String(64), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('owner_team', sa.String(128), server_default='core_platform', nullable=False),
        sa.Column('criticality', sa.String(32), server_default='category_2', nullable=False),
        sa.Column('sla_tier', sa.String(32), server_default='gold', nullable=False),
        sa.Column('deployment_model', sa.String(32), server_default='microservices', nullable=False),
        sa.Column('git_repo_root', sa.String(512), nullable=True),
        sa.Column('custom_metadata', sa.JSON(), server_default='{}', nullable=False),
        sa.Column('application_ids', sa.JSON(), server_default='[]', nullable=False),
        sa.Column('graph_edges', sa.JSON(), server_default='[]', nullable=False),
        sa.Column('kits_tag_ids', sa.JSON(), server_default='[]', nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        comment='Проекты КИТС — структурные единицы',
    )
    op.create_index('ix_projects_owner_team', 'projects', ['owner_team'], unique=False)
    op.create_index('ix_projects_created_at', 'projects', ['created_at'], unique=False)

    # LR-002: KITS Tags
    op.create_table(
        'kits_tags',
        sa.Column('id', sa.String(64), nullable=False),
        sa.Column('label', sa.String(128), nullable=False),
        sa.Column('color', sa.String(16), server_default='#1E88E5', nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        comment='Теги КИТС — семантические метки приложений',
    )
    op.create_index('ix_kits_tags_label', 'kits_tags', ['label'], unique=False)

    op.create_table(
        'application_kits_tags',
        sa.Column('id', sa.String(64), nullable=False),
        sa.Column('app_id', sa.String(64), nullable=False),
        sa.Column('tag_id', sa.String(64), nullable=False),
        sa.ForeignKeyConstraint(['app_id'], ['apps.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['tag_id'], ['kits_tags.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('app_id', 'tag_id', name='uq_app_kits_tag'),
        comment='Many-to-Many связь приложений с тегами КИТС',
    )
    op.create_index('ix_app_kits_tag_app_id', 'application_kits_tags', ['app_id'], unique=False)
    op.create_index('ix_app_kits_tag_tag_id', 'application_kits_tags', ['tag_id'], unique=False)

    # LR-003: Teams
    op.create_table(
        'project_teams',
        sa.Column('id', sa.String(64), nullable=False),
        sa.Column('project_id', sa.String(64), nullable=False),
        sa.Column('inherited_members', sa.JSON(), server_default='[]', nullable=False),
        sa.Column('local_additions', sa.JSON(), server_default='[]', nullable=False),
        sa.Column('local_exclusions', sa.JSON(), server_default='[]', nullable=False),
        sa.Column('role_overrides', sa.JSON(), server_default='[]', nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        comment='Командная структура проектов с наследованием',
    )
    op.create_index('ix_project_teams_project_id', 'project_teams', ['project_id'], unique=False)

    op.create_table(
        'application_teams',
        sa.Column('id', sa.String(64), nullable=False),
        sa.Column('app_id', sa.String(64), nullable=False),
        sa.Column('project_id', sa.String(64), nullable=False),
        sa.Column('inherited_from_project', sa.JSON(), server_default='[]', nullable=False),
        sa.Column('local_members', sa.JSON(), server_default='[]', nullable=False),
        sa.Column('local_exclusions', sa.JSON(), server_default='[]', nullable=False),
        sa.Column('role_overrides', sa.JSON(), server_default='[]', nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['app_id'], ['apps.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        comment='Командная структура приложений с наследованием от проекта',
    )
    op.create_index('ix_app_teams_app_id', 'application_teams', ['app_id'], unique=False)
    op.create_index('ix_app_teams_project_id', 'application_teams', ['project_id'], unique=False)

    # LR-006: Release Types & ReleaseBatch
    op.create_table(
        'release_types',
        sa.Column('id', sa.String(64), nullable=False),
        sa.Column('name', sa.String(128), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('version', sa.String(32), server_default='1.0.0', nullable=False),
        sa.Column('steps_json', sa.JSON(), server_default='[]', nullable=False),
        sa.Column('required_approvals', sa.Integer(), server_default='2', nullable=False),
        sa.Column('allowed_zones', sa.JSON(), server_default='[]', nullable=False),
        sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        comment='Версионируемые профили типов релизов (patch, minor, emergency)',
    )
    op.create_index('ix_release_types_is_active', 'release_types', ['is_active'], unique=False)

    op.create_table(
        'release_batches',
        sa.Column('id', sa.String(64), nullable=False),
        sa.Column('project_id', sa.String(64), nullable=False),
        sa.Column('release_type_id', sa.String(64), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('status', sa.String(32), server_default='draft', nullable=False),
        sa.Column('app_ids', sa.JSON(), server_default='[]', nullable=False),
        sa.Column('run_id', sa.String(64), nullable=True),
        sa.Column('started_at', sa.DateTime(), nullable=True),
        sa.Column('finished_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['release_type_id'], ['release_types.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        comment='Пакетные запуски релизного ЖЦ',
    )
    op.create_index('ix_release_batches_project_id', 'release_batches', ['project_id'], unique=False)
    op.create_index('ix_release_batches_status', 'release_batches', ['status'], unique=False)

    # LR-007: Artifact Registry
    op.create_table(
        'artifact_records',
        sa.Column('id', sa.String(64), nullable=False),
        sa.Column('registry_provider', sa.String(32), server_default='oci', nullable=False),
        sa.Column('registry_endpoint', sa.String(512), nullable=False),
        sa.Column('namespace', sa.String(128), server_default='cosmoport', nullable=False),
        sa.Column('repository', sa.String(255), nullable=False),
        sa.Column('artifact_name', sa.String(255), nullable=False),
        sa.Column('artifact_tag', sa.String(128), server_default='latest', nullable=False),
        sa.Column('digest_sha256', sa.String(64), nullable=False),
        sa.Column('sbom_ref', sa.String(512), nullable=True),
        sa.Column('scan_refs', sa.JSON(), server_default='[]', nullable=False),
        sa.Column('signature_attestation', sa.String(512), nullable=True),
        sa.Column('secret_ref', sa.String(512), nullable=True),
        sa.Column('app_id', sa.String(64), nullable=True),
        sa.Column('build_id', sa.String(64), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        comment='Метаданные артефактов — local-oci / Nexus / Т1-Сфера (Artifactory удалён)',
    )
    op.create_index('ix_artifact_records_app_id', 'artifact_records', ['app_id'], unique=False)
    op.create_index('ix_artifact_records_build_id', 'artifact_records', ['build_id'], unique=False)
    op.create_index('ix_artifact_records_digest', 'artifact_records', ['digest_sha256'], unique=False)

    # LR-004: Instance Configuration
    op.create_table(
        'instance_configuration',
        sa.Column('id', sa.String(64), server_default='cosmo-primary', nullable=False),
        sa.Column('instance_id', sa.String(128), server_default='cosmo-primary', nullable=False),
        sa.Column('network_id', sa.String(128), server_default='kits-core-net', nullable=False),
        sa.Column('platform_label', sa.String(255), server_default='KITS Central Platform', nullable=False),
        sa.Column('zone', sa.String(8), server_default='zr', nullable=False),
        sa.Column('forge_provider_type', sa.String(32), server_default='gitea', nullable=False),
        sa.Column('forge_endpoint_url', sa.String(512), nullable=False),
        sa.Column('forge_auth_ref', sa.String(512), server_default='vault:secret/cosmo/forge/credentials', nullable=False),
        sa.Column('prettyk_endpoint_url', sa.String(512), server_default='https://prettyk.io/api/v1', nullable=False),
        sa.Column('prettyk_auth_ref', sa.String(512), server_default='vault:secret/cosmo/prettyk/credentials', nullable=False),
        sa.Column('prettyk_check_timeout_seconds', sa.Integer(), server_default='30', nullable=False),
        sa.Column('registry_provider_type', sa.String(32), server_default='oci', nullable=False),
        sa.Column('registry_endpoint_url', sa.String(512), nullable=False),
        sa.Column('registry_namespace', sa.String(128), server_default='cosmoport', nullable=False),
        sa.Column('registry_auth_ref', sa.String(512), server_default='vault:secret/cosmo/registry/credentials', nullable=False),
        sa.Column('extra', sa.JSON(), server_default='{}', nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        comment='Глобальная конфигурация экземпляра Cosmoport',
    )


def downgrade() -> None:
    op.drop_table('instance_configuration')
    op.drop_table('artifact_records')
    op.drop_table('release_batches')
    op.drop_table('release_types')
    op.drop_table('application_teams')
    op.drop_table('project_teams')
    op.drop_table('application_kits_tags')
    op.drop_table('kits_tags')
    op.drop_table('projects')