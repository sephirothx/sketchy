"""add short-lived audience-aware room messages and report evidence

Revision ID: b9f3e5d7a201
Revises: a8e2d4c6f190
Create Date: 2026-08-23 00:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "b9f3e5d7a201"
down_revision: str | Sequence[str] | None = "a8e2d4c6f190"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "room_messages",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("room_instance_id", sa.Uuid(), nullable=False),
        sa.Column("game_id", sa.Uuid(), nullable=True),
        sa.Column("turn_id", sa.Uuid(), nullable=True),
        sa.Column("sender_user_id", sa.Uuid(), nullable=True),
        sa.Column("sender_player_id", sa.Uuid(), nullable=False),
        sa.Column("sender_seat_id", sa.Uuid(), nullable=True),
        sa.Column("sender_display_name_snapshot", sa.String(length=32), nullable=False),
        sa.Column("sender_name_color_snapshot", sa.String(length=16), nullable=True),
        sa.Column("sender_is_anonymous_snapshot", sa.Boolean(), nullable=False),
        sa.Column(
            "is_spectator", sa.Boolean(), server_default=sa.false(), nullable=False
        ),
        sa.Column("message_kind", sa.String(length=24), nullable=False),
        sa.Column("audience", sa.String(length=24), nullable=False),
        sa.Column("audience_user_ids", sa.JSON(), nullable=False),
        sa.Column("near_miss_kind", sa.String(length=16), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "message_kind IN ('chat', 'wrong_guess', 'correct_guess')",
            name="ck_room_messages_kind",
        ),
        sa.CheckConstraint(
            "audience IN ('room', 'prompt_aware')",
            name="ck_room_messages_audience",
        ),
        sa.CheckConstraint(
            "near_miss_kind IN ('close', 'partial')",
            name="ck_room_messages_near_miss_kind",
        ),
        sa.CheckConstraint(
            "message_kind = 'wrong_guess' OR near_miss_kind IS NULL",
            name="ck_room_messages_near_miss_only_for_wrong_guess",
        ),
        sa.CheckConstraint(
            "turn_id IS NULL OR game_id IS NOT NULL",
            name="ck_room_messages_turn_has_game",
        ),
        sa.CheckConstraint(
            "message_kind = 'chat' OR (game_id IS NOT NULL AND turn_id IS NOT NULL)",
            name="ck_room_messages_guesses_have_turn",
        ),
        sa.CheckConstraint(
            "expires_at > created_at",
            name="ck_room_messages_expiry_after_creation",
        ),
        sa.ForeignKeyConstraint(
            ["sender_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_room_messages_room_instance_id", "room_messages", ["room_instance_id"]
    )
    op.create_index(
        "ix_room_messages_expires_at", "room_messages", ["expires_at"]
    )
    op.create_index(
        "ix_room_messages_game_turn_created",
        "room_messages",
        ["game_id", "turn_id", "created_at"],
    )
    op.create_index(
        "ix_room_messages_sender_created",
        "room_messages",
        ["sender_user_id", "created_at"],
    )

    op.create_table(
        "player_report_message_evidence",
        sa.Column("report_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("source_message_id", sa.Uuid(), nullable=True),
        sa.Column("source_message_snapshot_id", sa.Uuid(), nullable=False),
        sa.Column("game_id_snapshot", sa.Uuid(), nullable=True),
        sa.Column("turn_id_snapshot", sa.Uuid(), nullable=True),
        sa.Column("sender_user_id", sa.Uuid(), nullable=True),
        sa.Column("sender_display_name_snapshot", sa.String(length=32), nullable=False),
        sa.Column("sender_name_color_snapshot", sa.String(length=16), nullable=True),
        sa.Column("sender_is_anonymous_snapshot", sa.Boolean(), nullable=False),
        sa.Column("message_kind", sa.String(length=24), nullable=False),
        sa.Column("audience", sa.String(length=24), nullable=False),
        sa.Column("near_miss_kind", sa.String(length=16), nullable=True),
        sa.Column("text_snapshot", sa.Text(), nullable=False),
        sa.Column("message_created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "copied_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "message_kind IN ('chat', 'wrong_guess', 'correct_guess')",
            name="ck_report_message_evidence_kind",
        ),
        sa.CheckConstraint(
            "audience IN ('room', 'prompt_aware')",
            name="ck_report_message_evidence_audience",
        ),
        sa.CheckConstraint(
            "near_miss_kind IN ('close', 'partial')",
            name="ck_report_message_evidence_near_miss_kind",
        ),
        sa.CheckConstraint(
            "message_kind = 'wrong_guess' OR near_miss_kind IS NULL",
            name="ck_report_message_evidence_near_miss_only_for_wrong_guess",
        ),
        sa.CheckConstraint(
            "position >= 0", name="ck_report_message_evidence_position"
        ),
        sa.ForeignKeyConstraint(
            ["report_id"], ["player_reports.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["source_message_id"], ["room_messages.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["sender_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("report_id", "position"),
        sa.UniqueConstraint(
            "report_id",
            "source_message_snapshot_id",
            name="uq_report_message_evidence_source",
        ),
    )
    op.create_index(
        "ix_player_report_message_evidence_source_message_id",
        "player_report_message_evidence",
        ["source_message_id"],
    )
    op.create_index(
        "ix_player_report_message_evidence_sender_user_id",
        "player_report_message_evidence",
        ["sender_user_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_player_report_message_evidence_sender_user_id",
        table_name="player_report_message_evidence",
    )
    op.drop_index(
        "ix_player_report_message_evidence_source_message_id",
        table_name="player_report_message_evidence",
    )
    op.drop_table("player_report_message_evidence")
    op.drop_index("ix_room_messages_sender_created", table_name="room_messages")
    op.drop_index("ix_room_messages_game_turn_created", table_name="room_messages")
    op.drop_index("ix_room_messages_expires_at", table_name="room_messages")
    op.drop_index("ix_room_messages_room_instance_id", table_name="room_messages")
    op.drop_table("room_messages")
