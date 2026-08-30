"""POST-LUNA-001: Add project_applications M:N table + Domain transitional compatibility.

Revision ID: 93d4e5f6a7b8
Revises: 82c3d4e5f6a7
Create Date: 2026-08-30 18:00:00

POST-LUNA-001:
  - project_applications M:N join table (replaces projects.application_ids JSON array)
  - Domain transitional compatibility view (domain_project_mapping)
  - NO backfill of old domain_id into new Project — new entities are Domain-free
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '93d4e5f6a7b8'
down_revision: Union[str, Sequence[str], None] = '82c3d4e5f6a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── project_applications M:N join table ──
    op.create_table(
        'project_applications',
        sa.Column('id', sa.String(64), nullable=False),
        sa.Column('project_id', sa.String(64), nullable=False),
        sa.Column('app_id', sa.String(64), nullable=False),
        sa.Column('role', sa.String(32), server_default='owner', nullable=False),
        sa.Column('backfill_source', sa.String(32), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['app_id'], ['apps.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('project_id', 'app_id', name='uq_project_app'),
        comment='Проект-Приложение M:N связь (POST-LUNA-001)',
    )
    op.create_index('ix_project_apps_project', 'project_applications', ['project_id'], unique=False)
    op.create_index('ix_project_apps_app', 'project_applications', ['app_id'], unique=False)

    # ── Backfill existing projects.application_ids into project_applications ──
    op.execute("""
        INSERT INTO project_applications (id, project_id, app_id, role, backfill_source, created_at)
        SELECT
            gen_random_uuid()::text AS id,
            p.id AS project_id,
            jsonb_array_elements_text(p.application_ids) AS app_id,
            'owner' AS role,
            'projects_json' AS backfill_source,
            p.created_at
        FROM projects p
        WHERE p.application_ids IS NOT NULL
          AND jsonb_array_length(p.application_ids) > 0
        ON CONFLICT (project_id, app_id) DO NOTHING;
    """)

    # ── Domain transitional compatibility view (read-only mapping) ──
    op.execute("""
        CREATE VIEW domain_project_mapping AS
        SELECT
            d.id AS domain_id,
            d.label AS domain_label,
            p.id AS project_id,
            p.name AS project_name
        FROM domains d
        LEFT JOIN apps a ON a.domain_id = d.id
        LEFT JOIN project_applications pa ON pa.app_id = a.id
        LEFT JOIN projects p ON p.id = pa.project_id
        GROUP BY d.id, d.label, p.id, p.name;
    """)
    op.execute("COMMENT ON VIEW domain_project_mapping IS 'POST-LUNA-001: Read-only переходная маппинг Domain → Project (НЕ production contract)'")


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS domain_project_mapping")
    op.drop_table('project_applications')