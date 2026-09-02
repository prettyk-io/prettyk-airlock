"""cosmo_initial

Revision ID: 23b56529e15d
Revises:
Create Date: 2026-08-29 01:39:20

All 11 Cosmoport ORM tables + 8 ENUMs + GIN indexes + CheckConstraints.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '23b56529e15d'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# ── ENUM names for downgrade cleanup ──
_ENUM_NAMES = [
    "brick_type", "batch_status", "batch_type",
    "run_trigger", "run_status",
    "gate_type", "gate_decision", "evidence_type",
]


def upgrade() -> None:
    # ── Stage 1: domains (no FK deps) ──
    op.create_table(
        'domains',
        sa.Column('id', sa.String(64), nullable=False),
        sa.Column('label', sa.String(255), nullable=False),
        sa.Column('forge_type', sa.String(32), nullable=False),
        sa.Column('forge_url', sa.String(512), nullable=False),
        sa.Column('forge_token_ref', sa.String(128), nullable=False),
        sa.Column('rbac_config', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('quota_max_runs', sa.Integer(), nullable=False),
        sa.Column('quota_max_storage_gb', sa.Integer(), nullable=False),
        sa.Column('quota_max_cpu', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        comment='КИТС — бизнес-домены и команды разработки',
    )
    op.create_index('ix_domains_rbac_config', 'domains', ['rbac_config'], unique=False, postgresql_using='gin')
    op.create_index('ix_domains_created_at', 'domains', ['created_at'], unique=False)
    op.create_index('ix_domains_label', 'domains', ['label'], unique=False)

    # ── Stage 2: groups (FK → domains) ──
    op.create_table(
        'groups',
        sa.Column('id', sa.String(64), nullable=False),
        sa.Column('domain_id', sa.String(64), nullable=False),
        sa.Column('parent_group_id', sa.String(64), nullable=True),
        sa.Column('level', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.CheckConstraint('level >= 0 AND level <= 3', name='ck_groups_level'),
        sa.ForeignKeyConstraint(['domain_id'], ['domains.id']),
        sa.ForeignKeyConstraint(['parent_group_id'], ['groups.id']),
        sa.PrimaryKeyConstraint('id'),
        comment='Группы приложений с иерархией parent/child',
    )
    op.create_index('ix_groups_domain_id', 'groups', ['domain_id'], unique=False)
    op.create_index('ix_groups_parent_group_id', 'groups', ['parent_group_id'], unique=False)

    # ── Stage 3: pipeline_bricks (no FK deps) ──
    op.create_table(
        'pipeline_bricks',
        sa.Column('id', sa.String(64), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('type', postgresql.ENUM('sast','sca','build','deploy','dast','autotest','gate', name='brick_type'), nullable=False),
        sa.Column('source', sa.String(256), nullable=False),
        sa.Column('definition_json', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('depends_on', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('gates', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        comment='Каталог Pipeline Bricks — атомарные шаги пайплайнов',
    )
    op.create_index('ix_pipeline_bricks_definition_json', 'pipeline_bricks', ['definition_json'], unique=False, postgresql_using='gin')
    op.create_index('ix_pipeline_bricks_depends_on', 'pipeline_bricks', ['depends_on'], unique=False, postgresql_using='gin')
    op.create_index('ix_pipeline_bricks_gates', 'pipeline_bricks', ['gates'], unique=False, postgresql_using='gin')

    # ── Stage 4: apps WITHOUT pipeline_plan_id FK (circular dep with pipeline_plans) ──
    op.create_table(
        'apps',
        sa.Column('id', sa.String(64), nullable=False),
        sa.Column('domain_id', sa.String(64), nullable=False),
        sa.Column('level', sa.Integer(), nullable=False),
        sa.Column('group_id', sa.String(64), nullable=True),
        sa.Column('pipeline_plan_id', sa.String(64), nullable=True),
        sa.CheckConstraint('level >= 0 AND level <= 3', name='ck_apps_level'),
        sa.ForeignKeyConstraint(['domain_id'], ['domains.id']),
        sa.ForeignKeyConstraint(['group_id'], ['groups.id']),
        sa.PrimaryKeyConstraint('id'),
        comment='Приложения — Level 0 (библиотеки), Level 1 (сервисы), Level 2 (группы)',
    )
    op.create_index('ix_apps_domain_id', 'apps', ['domain_id'], unique=False)
    op.create_index('ix_apps_group_id', 'apps', ['group_id'], unique=False)
    op.create_index('ix_apps_level', 'apps', ['level'], unique=False)

    # ── Stage 5: pipeline_plans (FK → apps) ──
    op.create_table(
        'pipeline_plans',
        sa.Column('id', sa.String(64), nullable=False),
        sa.Column('app_id', sa.String(64), nullable=False),
        sa.Column('level', sa.String(32), nullable=False),
        sa.Column('scope_id', sa.String(64), nullable=False),
        sa.Column('compiled_at', sa.DateTime(), nullable=False),
        sa.Column('compiled_hash', sa.String(128), nullable=False),
        sa.ForeignKeyConstraint(['app_id'], ['apps.id']),
        sa.PrimaryKeyConstraint('id'),
        comment='Скомпилированные планы пайплайнов',
    )
    op.create_index('ix_pipeline_plans_app_id', 'pipeline_plans', ['app_id'], unique=False)
    op.create_index('ix_pipeline_plans_compiled_at', 'pipeline_plans', ['compiled_at'], unique=False)

    # ── Stage 5b: resolve circular FK — apps.pipeline_plan_id → pipeline_plans.id ──
    op.create_foreign_key(
        'fk_apps_pipeline_plan_id', 'apps', 'pipeline_plans',
        ['pipeline_plan_id'], ['id'],
    )

    # ── Stage 6: plan_bricks (M:N) ──
    op.create_table(
        'plan_bricks',
        sa.Column('id', sa.String(64), nullable=False),
        sa.Column('plan_id', sa.String(64), nullable=False),
        sa.Column('brick_id', sa.String(64), nullable=False),
        sa.Column('sort_order', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['brick_id'], ['pipeline_bricks.id']),
        sa.ForeignKeyConstraint(['plan_id'], ['pipeline_plans.id']),
        sa.PrimaryKeyConstraint('id'),
        comment='M:N связь кирпичей с планами (сортировка)',
    )
    op.create_index('ix_plan_bricks_plan_id', 'plan_bricks', ['plan_id'], unique=False)
    op.create_index('ix_plan_bricks_brick_id', 'plan_bricks', ['brick_id'], unique=False)

    # ── Stage 7: repo_bindings (FK → apps) ──
    op.create_table(
        'repo_bindings',
        sa.Column('id', sa.String(64), nullable=False),
        sa.Column('app_id', sa.String(64), nullable=False),
        sa.Column('forge_id', sa.String(64), nullable=False),
        sa.Column('repo_path', sa.String(256), nullable=False),
        sa.Column('default_branch', sa.String(128), nullable=False),
        sa.Column('webhook_id', sa.String(128), nullable=True),
        sa.ForeignKeyConstraint(['app_id'], ['apps.id']),
        sa.PrimaryKeyConstraint('id'),
        comment='Привязки приложений к Git-репозиториям (Gitea/GitLab)',
    )
    op.create_index('ix_repo_bindings_app_id', 'repo_bindings', ['app_id'], unique=False)

    # ── Stage 8: batches (FK → pipeline_plans) ──
    op.create_table(
        'batches',
        sa.Column('id', sa.String(64), nullable=False),
        sa.Column('plan_id', sa.String(64), nullable=False),
        sa.Column('type', postgresql.ENUM('build','static_scan','deploy','dynamic_test', name='batch_type'), nullable=False),
        sa.Column('status', postgresql.ENUM('pending','running','passed','failed','blocked', name='batch_status'), nullable=False),
        sa.Column('bricks_refs', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('artifacts', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('evidence_refs', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('started_at', sa.DateTime(), nullable=True),
        sa.Column('finished_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['plan_id'], ['pipeline_plans.id']),
        sa.PrimaryKeyConstraint('id'),
        comment='Пачки шагов: Build, Static Scan, Deploy, Dynamic Test',
    )
    op.create_index('ix_batch_plan_id', 'batches', ['plan_id'], unique=False)
    op.create_index('ix_batches_status', 'batches', ['status'], unique=False)
    op.create_index('ix_batches_artifacts', 'batches', ['artifacts'], unique=False, postgresql_using='gin')
    op.create_index('ix_batches_bricks_refs', 'batches', ['bricks_refs'], unique=False, postgresql_using='gin')
    op.create_index('ix_batches_evidence_refs', 'batches', ['evidence_refs'], unique=False, postgresql_using='gin')

    # ── Stage 9: gates (FK → pipeline_plans) ──
    op.create_table(
        'gates',
        sa.Column('id', sa.String(64), nullable=False),
        sa.Column('plan_id', sa.String(64), nullable=False),
        sa.Column('type', postgresql.ENUM('automatic','manual', name='gate_type'), nullable=False),
        sa.Column('position', sa.Integer(), nullable=False),
        sa.Column('policy_json', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('decision', postgresql.ENUM('pass','block','manual_required', name='gate_decision'), nullable=True),
        sa.Column('decided_by', sa.String(128), nullable=True),
        sa.Column('signature', sa.String(512), nullable=True),
        sa.Column('decided_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['plan_id'], ['pipeline_plans.id']),
        sa.PrimaryKeyConstraint('id'),
        comment='Security Gates с политиками и решениями',
    )
    op.create_index('ix_gates_plan_id', 'gates', ['plan_id'], unique=False)
    op.create_index('ix_gates_position', 'gates', ['position'], unique=False)
    op.create_index('ix_gates_policy_json', 'gates', ['policy_json'], unique=False, postgresql_using='gin')

    # ── Stage 10: runs (FK → pipeline_plans, domains, batches) ──
    op.create_table(
        'runs',
        sa.Column('id', sa.String(64), nullable=False),
        sa.Column('plan_id', sa.String(64), nullable=False),
        sa.Column('trigger', postgresql.ENUM('scheduled','pre_release','emergency','manual', name='run_trigger'), nullable=False),
        sa.Column('initiator_user_id', sa.String(128), nullable=False),
        sa.Column('initiator_role', sa.String(64), nullable=False),
        sa.Column('domain_id', sa.String(64), nullable=False),
        sa.Column('batch_id', sa.String(64), nullable=True),
        sa.Column('status', postgresql.ENUM('draft','pending','queued','running','succeeded','failed','blocked','cancelled', name='run_status'), nullable=False),
        sa.Column('findings_refs', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('started_at', sa.DateTime(), nullable=True),
        sa.Column('finished_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['batch_id'], ['batches.id']),
        sa.ForeignKeyConstraint(['domain_id'], ['domains.id']),
        sa.ForeignKeyConstraint(['plan_id'], ['pipeline_plans.id']),
        sa.PrimaryKeyConstraint('id'),
        comment='Прогоны — экземпляры выполнения пайплайнов',
    )
    op.create_index('ix_runs_status', 'runs', ['status'], unique=False)
    op.create_index('ix_runs_domain_id', 'runs', ['domain_id'], unique=False)
    op.create_index('ix_runs_created_at', 'runs', ['created_at'], unique=False)
    op.create_index('ix_runs_findings_refs', 'runs', ['findings_refs'], unique=False, postgresql_using='gin')

    # ── Stage 11: evidence_ledger (FK → runs, batches) ──
    op.create_table(
        'evidence_ledger',
        sa.Column('id', sa.String(64), nullable=False),
        sa.Column('run_id', sa.String(64), nullable=False),
        sa.Column('batch_id', sa.String(64), nullable=True),
        sa.Column('type', postgresql.ENUM('screenshot','raw_request','raw_response','log','alert','finding','decision', name='evidence_type'), nullable=False),
        sa.Column('content_ref', sa.String(512), nullable=True),
        sa.Column('content_hash', sa.String(128), nullable=True),
        sa.Column('provenance_json', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['batch_id'], ['batches.id']),
        sa.ForeignKeyConstraint(['run_id'], ['runs.id']),
        sa.PrimaryKeyConstraint('id'),
        comment='Неизменяемый журнал доказательств SHA-256',
    )
    op.create_index('ix_evidence_provenance_json', 'evidence_ledger', ['provenance_json'], unique=False, postgresql_using='gin')
    op.create_index('ix_evidence_run_id', 'evidence_ledger', ['run_id'], unique=False)
    op.create_index('ix_evidence_batch_id', 'evidence_ledger', ['batch_id'], unique=False)
    op.create_index('ix_evidence_created_at', 'evidence_ledger', ['created_at'], unique=False)


def downgrade() -> None:
    # Drop indexes + tables in reverse dependency order
    op.drop_index('ix_evidence_created_at', table_name='evidence_ledger')
    op.drop_index('ix_evidence_batch_id', table_name='evidence_ledger')
    op.drop_index('ix_evidence_run_id', table_name='evidence_ledger')
    op.drop_index('ix_evidence_provenance_json', table_name='evidence_ledger', postgresql_using='gin')
    op.drop_table('evidence_ledger')

    op.drop_index('ix_runs_findings_refs', table_name='runs', postgresql_using='gin')
    op.drop_index('ix_runs_created_at', table_name='runs')
    op.drop_index('ix_runs_domain_id', table_name='runs')
    op.drop_index('ix_runs_status', table_name='runs')
    op.drop_table('runs')

    op.drop_index('ix_gates_policy_json', table_name='gates', postgresql_using='gin')
    op.drop_index('ix_gates_position', table_name='gates')
    op.drop_index('ix_gates_plan_id', table_name='gates')
    op.drop_table('gates')

    op.drop_index('ix_batches_evidence_refs', table_name='batches', postgresql_using='gin')
    op.drop_index('ix_batches_bricks_refs', table_name='batches', postgresql_using='gin')
    op.drop_index('ix_batches_artifacts', table_name='batches', postgresql_using='gin')
    op.drop_index('ix_batches_status', table_name='batches')
    op.drop_index('ix_batch_plan_id', table_name='batches')
    op.drop_table('batches')

    op.drop_index('ix_repo_bindings_app_id', table_name='repo_bindings')
    op.drop_table('repo_bindings')

    op.drop_index('ix_plan_bricks_brick_id', table_name='plan_bricks')
    op.drop_index('ix_plan_bricks_plan_id', table_name='plan_bricks')
    op.drop_table('plan_bricks')

    # Drop the circular FK BEFORE dropping pipeline_plans
    op.drop_constraint('fk_apps_pipeline_plan_id', 'apps', type_='foreignkey')
    op.drop_index('ix_pipeline_plans_compiled_at', table_name='pipeline_plans')
    op.drop_index('ix_pipeline_plans_app_id', table_name='pipeline_plans')
    op.drop_table('pipeline_plans')

    op.drop_index('ix_apps_level', table_name='apps')
    op.drop_index('ix_apps_group_id', table_name='apps')
    op.drop_index('ix_apps_domain_id', table_name='apps')
    op.drop_table('apps')

    op.drop_index('ix_pipeline_bricks_gates', table_name='pipeline_bricks', postgresql_using='gin')
    op.drop_index('ix_pipeline_bricks_depends_on', table_name='pipeline_bricks', postgresql_using='gin')
    op.drop_index('ix_pipeline_bricks_definition_json', table_name='pipeline_bricks', postgresql_using='gin')
    op.drop_table('pipeline_bricks')

    op.drop_index('ix_groups_parent_group_id', table_name='groups')
    op.drop_index('ix_groups_domain_id', table_name='groups')
    op.drop_table('groups')
    op.drop_index('ix_domains_label', table_name='domains')
    op.drop_index('ix_domains_created_at', table_name='domains')
    op.drop_index('ix_domains_rbac_config', table_name='domains', postgresql_using='gin')
    op.drop_table('domains')

    # ── Drop all 8 ENUM types ──
    for enum_name in _ENUM_NAMES:
        op.execute(sa.text(f'DROP TYPE IF EXISTS {enum_name}'))