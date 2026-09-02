"""cos055_notification_manager

Revision ID: b8c9d0e1f2a3
Revises: a4b5c6d7e8f9
Create Date: 2026-09-01 12:00:00

COS-055: Portal-local Notification Manager V1 — durable outbox/inbox tables.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'b8c9d0e1f2a3'
down_revision: Union[str, Sequence[str], None] = 'a4b5c6d7e8f9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── notification_events (outbox) ──
    op.create_table(
        'notification_events',
        sa.Column('event_id', sa.String(64), nullable=False),
        sa.Column('event_type', sa.String(64), nullable=False),
        sa.Column('aggregate_type', sa.String(32), server_default='system', nullable=False),
        sa.Column('aggregate_id', sa.String(64), server_default='', nullable=False),
        sa.Column('occurred_at', sa.DateTime(), nullable=False),
        sa.Column('payload', postgresql.JSONB(), server_default='{}', nullable=False),
        sa.Column('correlation_id', sa.String(128), nullable=True),
        sa.Column('domain_id', sa.String(64), nullable=True),
        sa.Column('project_id', sa.String(64), nullable=True),
        sa.Column('app_id', sa.String(64), nullable=True),
        sa.Column('recipient_count', sa.Integer(), server_default='0', nullable=False),
        sa.Column('processed', sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column('processed_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('event_id'),
        comment='COS-055: durable event/outbox journal уведомлений',
    )
    op.create_index('ix_notif_events_type', 'notification_events', ['event_type'])
    op.create_index('ix_notif_events_correlation', 'notification_events', ['correlation_id'])
    op.create_index('ix_notif_events_occurred', 'notification_events', ['occurred_at'])
    op.create_index('ix_notif_events_processed', 'notification_events', ['processed'])

    # ── notification_inbox (per-recipient journal) ──
    op.create_table(
        'notification_inbox',
        sa.Column('id', sa.String(64), nullable=False),
        sa.Column('event_id', sa.String(64), nullable=False),
        sa.Column('recipient_id', sa.String(128), nullable=False),
        sa.Column('channel', sa.String(16), nullable=False),
        sa.Column('notification_type', sa.String(64), nullable=False),
        sa.Column('severity', sa.String(16), server_default='info', nullable=False),
        sa.Column('title', sa.String(255), nullable=False),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('state', sa.String(32), server_default='created', nullable=False),
        sa.Column('attempts', sa.Integer(), server_default='0', nullable=False),
        sa.Column('max_attempts', sa.Integer(), server_default='5', nullable=False),
        sa.Column('last_error', sa.Text(), nullable=True),
        sa.Column('provider_message_id', sa.String(255), nullable=True),
        sa.Column('claimed_at', sa.DateTime(), nullable=True),
        sa.Column('next_retry_at', sa.DateTime(), nullable=True),
        sa.Column('read_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['event_id'], ['notification_events.event_id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('event_id', 'recipient_id', 'channel', name='uq_notif_dedup'),
        sa.CheckConstraint("channel IN ('in_app','email')", name='ck_notif_channel'),
        comment='COS-055: inbox journal уведомлений (in_app + email delivery)',
    )
    op.create_index('ix_notif_inbox_recipient', 'notification_inbox', ['recipient_id', 'channel', 'state'])
    op.create_index('ix_notif_inbox_state', 'notification_inbox', ['state'])
    op.create_index('ix_notif_inbox_next_retry', 'notification_inbox', ['next_retry_at'])
    op.create_index('ix_notif_inbox_created', 'notification_inbox', ['created_at'])

    # ── notification_subscriptions (V1 policy) ──
    op.create_table(
        'notification_subscriptions',
        sa.Column('user_id', sa.String(128), nullable=False),
        sa.Column('policy', sa.String(16), server_default='all', nullable=False),
        sa.Column('selected_event_types', postgresql.JSONB(), server_default='[]', nullable=False),
        sa.Column('blocked_event_types', postgresql.JSONB(), server_default='[]', nullable=False),
        sa.Column('domain_scope', sa.String(64), nullable=True),
        sa.Column('email_enabled', sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('user_id'),
        sa.CheckConstraint("policy IN ('all','selected')", name='ck_notif_sub_policy'),
        comment='COS-055: подписки пользователей (V1: all/selected + blocklist)',
    )

    # ── notification_channel_configs (durable provider configs) ──
    op.create_table(
        'notification_channel_configs',
        sa.Column('id', sa.String(64), nullable=False),
        sa.Column('domain_id', sa.String(64), nullable=True),
        sa.Column('channel', sa.String(32), server_default='webhook', nullable=False),
        sa.Column('endpoint', sa.String(512), nullable=True),
        sa.Column('channels', postgresql.JSONB(), server_default='[]', nullable=False),
        sa.Column('secret_ref', sa.String(512), nullable=True),
        sa.Column('enabled', sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        comment='COS-055: durable конфиги каналов доставки',
    )
    op.create_index('ix_notif_cfg_domain', 'notification_channel_configs', ['domain_id'])


def downgrade() -> None:
    op.drop_index('ix_notif_cfg_domain', table_name='notification_channel_configs')
    op.drop_table('notification_channel_configs')
    op.drop_table('notification_subscriptions')
    op.drop_index('ix_notif_inbox_created', table_name='notification_inbox')
    op.drop_index('ix_notif_inbox_next_retry', table_name='notification_inbox')
    op.drop_index('ix_notif_inbox_state', table_name='notification_inbox')
    op.drop_index('ix_notif_inbox_recipient', table_name='notification_inbox')
    op.drop_table('notification_inbox')
    op.drop_index('ix_notif_events_processed', table_name='notification_events')
    op.drop_index('ix_notif_events_occurred', table_name='notification_events')
    op.drop_index('ix_notif_events_correlation', table_name='notification_events')
    op.drop_index('ix_notif_events_type', table_name='notification_events')
    op.drop_table('notification_events')
