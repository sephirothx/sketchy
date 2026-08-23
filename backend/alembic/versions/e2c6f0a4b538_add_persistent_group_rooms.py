"""add persistent group rooms

Revision ID: e2c6f0a4b538
Revises: d1b5e9f3a427
Create Date: 2026-08-23 00:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "e2c6f0a4b538"
down_revision: str | Sequence[str] | None = "d1b5e9f3a427"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "persistent_rooms",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(length=6), nullable=False),
        sa.Column("owner_user_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=40), nullable=False),
        sa.Column("is_public", sa.Boolean(), nullable=False),
        sa.Column("max_players", sa.Integer(), nullable=False),
        sa.Column("rounds", sa.Integer(), nullable=False),
        sa.Column("drawing_seconds", sa.Integer(), nullable=False),
        sa.Column("hint_mode", sa.String(length=16), nullable=False),
        sa.Column("scoring_mode", sa.String(length=16), nullable=False),
        sa.Column("spectators_see_prompt", sa.Boolean(), nullable=False),
        sa.Column("hide_masked_prompt", sa.Boolean(), nullable=False),
        sa.Column("allowed_tools", sa.JSON(), nullable=False),
        sa.Column("color_mode", sa.String(length=24), nullable=False),
        sa.Column("prompt_list_ids", sa.JSON(), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
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
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "scoring_mode IN ('default', 'pressure', 'none')",
            name="ck_persistent_rooms_scoring_mode",
        ),
        sa.CheckConstraint(
            "hint_mode IN ('none', 'checkpoints', 'purchase', 'wheel')",
            name="ck_persistent_rooms_hint_mode",
        ),
        sa.CheckConstraint(
            "color_mode IN ('all', 'palette', 'colorblind_safe', 'black_and_white')",
            name="ck_persistent_rooms_color_mode",
        ),
        sa.CheckConstraint(
            "max_players >= 2 AND max_players <= 16",
            name="ck_persistent_rooms_max_players",
        ),
        sa.CheckConstraint(
            "rounds >= 1 AND rounds <= 10",
            name="ck_persistent_rooms_rounds",
        ),
        sa.CheckConstraint(
            "drawing_seconds IN (15, 30, 60, 90, 120, 180, 240, 300)",
            name="ck_persistent_rooms_drawing_seconds",
        ),
        sa.CheckConstraint("version >= 1", name="ck_persistent_rooms_version"),
        sa.ForeignKeyConstraint(
            ["code"], ["room_code_reservations.code"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["owner_user_id"], ["users.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code"),
    )
    op.create_index(
        "ix_persistent_rooms_owner_user_id",
        "persistent_rooms",
        ["owner_user_id"],
    )
    op.create_index(
        "ix_persistent_rooms_archived_at", "persistent_rooms", ["archived_at"]
    )
    op.create_index(
        "ix_persistent_rooms_owner_archived",
        "persistent_rooms",
        ["owner_user_id", "archived_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_persistent_rooms_owner_archived", table_name="persistent_rooms")
    op.drop_index("ix_persistent_rooms_archived_at", table_name="persistent_rooms")
    op.drop_index("ix_persistent_rooms_owner_user_id", table_name="persistent_rooms")
    op.drop_table("persistent_rooms")
