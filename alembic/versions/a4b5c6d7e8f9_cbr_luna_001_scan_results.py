"""CBR-LUNA-001/002: Add scan_results, scan_findings, scan_evidence tables.
CBR-LUNA-002 follow-up: FK constraints (apps, cosmo_builds, releases, runs), run_id, artifact_digest index.

Revision ID: a4b5c6d7e8f9
Revises: 93d4e5f6a7b8
Create Date: 2026-08-30 20:00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'a4b5c6d7e8f9'
down_revision: Union[str, Sequence[str], None] = '93d4e5f6a7b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── scan_results ──
    op.create_table(
        'scan_results',
        sa.Column('id', sa.String(64), nullable=False),
        sa.Column('scan_id', sa.String(64), nullable=False),
        sa.Column('tool', sa.String(32), nullable=False),
        sa.Column('tool_version', sa.String(64), nullable=False),
        sa.Column('rules_version', sa.String(64), server_default='latest', nullable=False),
        sa.Column('verdict', sa.String(16), nullable=False),
        sa.Column('findings_count', sa.Integer(), server_default='0', nullable=False),
        sa.Column('critical_count', sa.Integer(), server_default='0', nullable=False),
        sa.Column('high_count', sa.Integer(), server_default='0', nullable=False),
        sa.Column('artifact_digest_sha256', sa.String(64), nullable=True),
        sa.Column('artifact_name', sa.String(255), nullable=True),
        sa.Column('app_id', sa.String(64), nullable=True),
        sa.Column('build_id', sa.String(64), nullable=True),
        sa.Column('release_id', sa.String(64), nullable=True),
        sa.Column('run_id', sa.String(64), nullable=True),
        sa.Column('started_at', sa.DateTime(), nullable=True),
        sa.Column('finished_at', sa.DateTime(), nullable=True),
        sa.Column('duration_ms', sa.Integer(), nullable=True),
        sa.Column('evidence_ref', sa.String(512), nullable=True),
        sa.Column('sarif_ref', sa.String(512), nullable=True),
        sa.Column('provenance_hash', sa.String(32), nullable=True),
        sa.Column('idempotency_key', sa.String(16), nullable=True),
        sa.Column('meta', sa.JSON(), server_default='{}', nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['app_id'], ['apps.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['build_id'], ['cosmo_builds.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['release_id'], ['releases.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['run_id'], ['runs.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('scan_id'),
        comment='Результаты сканеров — FK + digest identity (CBR-LUNA-002)',
    )
    op.create_index('ix_scan_results_app', 'scan_results', ['app_id'], unique=False)
    op.create_index('ix_scan_results_build', 'scan_results', ['build_id'], unique=False)
    op.create_index('ix_scan_results_release', 'scan_results', ['release_id'], unique=False)
    op.create_index('ix_scan_results_run', 'scan_results', ['run_id'], unique=False)
    op.create_index('ix_scan_results_tool', 'scan_results', ['tool'], unique=False)
    op.create_index('ix_scan_results_verdict', 'scan_results', ['verdict'], unique=False)
    op.create_index('ix_scan_results_artifact_digest', 'scan_results', ['artifact_digest_sha256'], unique=False)

    # ── scan_findings ──
    op.create_table(
        'scan_findings',
        sa.Column('id', sa.String(64), nullable=False),
        sa.Column('scan_id', sa.String(64), nullable=False),
        sa.Column('rule_id', sa.String(128), nullable=False),
        sa.Column('severity', sa.String(16), server_default='medium', nullable=False),
        sa.Column('title', sa.String(512), nullable=False),
        sa.Column('description', sa.Text(), server_default='', nullable=False),
        sa.Column('file_path', sa.String(1024), server_default='', nullable=False),
        sa.Column('line_number', sa.Integer(), server_default='0', nullable=False),
        sa.Column('cwe_id', sa.String(16), nullable=True),
        sa.Column('remediation', sa.Text(), server_default='', nullable=False),
        sa.Column('raw_output_snippet', sa.Text(), server_default='', nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['scan_id'], ['scan_results.scan_id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        comment='Находки сканеров безопасности — STACK-LUNA-001',
    )
    op.create_index('ix_scan_findings_scan', 'scan_findings', ['scan_id'], unique=False)
    op.create_index('ix_scan_findings_severity', 'scan_findings', ['severity'], unique=False)
    op.create_index('ix_scan_findings_cwe', 'scan_findings', ['cwe_id'], unique=False)

    # ── scan_evidence ──
    op.create_table(
        'scan_evidence',
        sa.Column('id', sa.String(64), nullable=False),
        sa.Column('scan_id', sa.String(64), nullable=False),
        sa.Column('evidence_type', sa.String(64), server_default='scan_result', nullable=False),
        sa.Column('content_ref', sa.String(512), nullable=False),
        sa.Column('sha256_hash', sa.String(64), nullable=False),
        sa.Column('attestation_ref', sa.String(512), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['scan_id'], ['scan_results.scan_id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        comment='Evidence linkage (MinIO/S3, не Vault) — CBR-LUNA-002',
    )
    op.create_index('ix_scan_evidence_scan', 'scan_evidence', ['scan_id'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_scan_evidence_scan', table_name='scan_evidence')
    op.drop_table('scan_evidence')
    op.drop_index('ix_scan_findings_cwe', table_name='scan_findings')
    op.drop_index('ix_scan_findings_severity', table_name='scan_findings')
    op.drop_index('ix_scan_findings_scan', table_name='scan_findings')
    op.drop_table('scan_findings')
    op.drop_index('ix_scan_results_artifact_digest', table_name='scan_results')
    op.drop_index('ix_scan_results_verdict', table_name='scan_results')
    op.drop_index('ix_scan_results_tool', table_name='scan_results')
    op.drop_index('ix_scan_results_run', table_name='scan_results')
    op.drop_index('ix_scan_results_release', table_name='scan_results')
    op.drop_index('ix_scan_results_build', table_name='scan_results')
    op.drop_index('ix_scan_results_app', table_name='scan_results')
    op.drop_table('scan_results')