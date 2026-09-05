"""right-size the indexes behind the admin and moderation reads

Revision ID: c3d6b0e4f581
Revises: b2c5a9d3e470
Create Date: 2026-09-06 02:00:00.000000

Chosen from EXPLAIN (ANALYZE, BUFFERS) on a skewed representative
population (benchmarks/index_plans.py, #554): the lobby restore sorted every
retained message, the active-ban queue sorted every ban, the outbox's sent
branch scanned the outbox, and a rare audit event type walked the time index
past every other type. Each gets the smallest index that turns that into a
bounded walk; the standalone event_type index is replaced by the composite
that leads with it.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "c3d6b0e4f581"
down_revision: str | Sequence[str] | None = "b2c5a9d3e470"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_room_messages_lobby_newest",
        "room_messages",
        ["created_at", "id"],
        unique=False,
        postgresql_where=sa.text("audience = 'lobby'"),
        sqlite_where=sa.text("audience = 'lobby'"),
    )
    op.create_index(
        "ix_user_bans_active_newest",
        "user_bans",
        ["created_at"],
        unique=False,
        postgresql_where=sa.text("is_active IS TRUE"),
        sqlite_where=sa.text("is_active IS TRUE"),
    )
    op.create_index(
        "ix_email_outbox_sent_at_sent",
        "email_outbox",
        ["sent_at", "id"],
        unique=False,
        postgresql_where=sa.text("state = 'sent'"),
        sqlite_where=sa.text("state = 'sent'"),
    )
    op.create_index(
        "ix_audit_events_type_created_at",
        "audit_events",
        ["event_type", "created_at"],
        unique=False,
    )
    op.drop_index("ix_audit_events_event_type", table_name="audit_events")


def downgrade() -> None:
    op.create_index("ix_audit_events_event_type", "audit_events", ["event_type"], unique=False)
    op.drop_index("ix_audit_events_type_created_at", table_name="audit_events")
    op.drop_index("ix_email_outbox_sent_at_sent", table_name="email_outbox")
    op.drop_index("ix_user_bans_active_newest", table_name="user_bans")
    op.drop_index("ix_room_messages_lobby_newest", table_name="room_messages")
