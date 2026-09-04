"""add reports and user bans

Revision ID: d5b9f2a7c143
Revises: c4a8e1f6b932
Create Date: 2026-08-22 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "d5b9f2a7c143"
down_revision: Union[str, Sequence[str], None] = "c4a8e1f6b932"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "player_reports",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("reporter_user_id", sa.Uuid(), nullable=True),
        sa.Column("reported_user_id", sa.Uuid(), nullable=True),
        sa.Column("game_id", sa.Uuid(), nullable=True),
        sa.Column("turn_id", sa.Uuid(), nullable=True),
        sa.Column("reason", sa.String(length=32), nullable=False),
        sa.Column("details", sa.Text(), nullable=False),
        sa.Column(
            "context_snapshot",
            sa.JSON(),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.String(length=16),
            server_default="pending",
            nullable=False,
        ),
        sa.Column("reviewed_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("resolution_note", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "reporter_user_id IS NULL OR reported_user_id IS NULL "
            "OR reporter_user_id != reported_user_id",
            name="ck_player_reports_not_self",
        ),
        sa.CheckConstraint(
            "reason IN ('harassment', 'offensive_drawing', "
            "'inappropriate_name', 'cheating', 'spam', 'inappropriate_avatar')",
            name="ck_player_reports_reason",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'resolved', 'dismissed')",
            name="ck_player_reports_status",
        ),
        sa.ForeignKeyConstraint(
            ["game_id"], ["game_records.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["reported_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["reporter_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["reviewed_by_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["turn_id"], ["turn_records.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_player_reports_game_id"), "player_reports", ["game_id"]
    )
    op.create_index(
        op.f("ix_player_reports_reported_user_id"),
        "player_reports",
        ["reported_user_id"],
    )
    op.create_index(
        op.f("ix_player_reports_reporter_user_id"),
        "player_reports",
        ["reporter_user_id"],
    )
    op.create_index(
        op.f("ix_player_reports_reviewed_by_user_id"),
        "player_reports",
        ["reviewed_by_user_id"],
    )
    op.create_index(
        "ix_player_reports_status_created_at",
        "player_reports",
        ["status", "created_at"],
    )
    op.create_index(
        op.f("ix_player_reports_turn_id"), "player_reports", ["turn_id"]
    )

    op.create_table(
        "user_bans",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("banned_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("reason", sa.String(length=255), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "is_active", sa.Boolean(), server_default=sa.true(), nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("revoke_reason", sa.String(length=255), nullable=True),
        sa.CheckConstraint(
            "expires_at IS NULL OR expires_at > created_at",
            name="ck_user_bans_expiry_after_creation",
        ),
        sa.ForeignKeyConstraint(
            ["banned_by_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["revoked_by_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_user_bans_banned_by_user_id"),
        "user_bans",
        ["banned_by_user_id"],
    )
    op.create_index(op.f("ix_user_bans_user_id"), "user_bans", ["user_id"])
    op.create_index(
        "ix_user_bans_user_active_expires",
        "user_bans",
        ["user_id", "is_active", "expires_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_user_bans_user_active_expires", table_name="user_bans")
    op.drop_index(op.f("ix_user_bans_user_id"), table_name="user_bans")
    op.drop_index(op.f("ix_user_bans_banned_by_user_id"), table_name="user_bans")
    op.drop_table("user_bans")

    op.drop_index(op.f("ix_player_reports_turn_id"), table_name="player_reports")
    op.drop_index(
        "ix_player_reports_status_created_at", table_name="player_reports"
    )
    op.drop_index(
        op.f("ix_player_reports_reviewed_by_user_id"),
        table_name="player_reports",
    )
    op.drop_index(
        op.f("ix_player_reports_reporter_user_id"),
        table_name="player_reports",
    )
    op.drop_index(
        op.f("ix_player_reports_reported_user_id"),
        table_name="player_reports",
    )
    op.drop_index(op.f("ix_player_reports_game_id"), table_name="player_reports")
    op.drop_table("player_reports")
