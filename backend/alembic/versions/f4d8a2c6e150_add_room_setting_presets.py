"""add room setting presets

Revision ID: f4d8a2c6e150
Revises: e2c6f0a4b538
Create Date: 2026-08-23 00:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "f4d8a2c6e150"
down_revision: str | Sequence[str] | None = "e2c6f0a4b538"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "room_presets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_user_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("name_key", sa.String(length=64), nullable=False),
        sa.Column("room_name", sa.String(length=40), nullable=False),
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
        sa.CheckConstraint(
            "scoring_mode IN ('default', 'pressure', 'none')",
            name="ck_room_presets_scoring_mode",
        ),
        sa.CheckConstraint(
            "hint_mode IN ('none', 'checkpoints', 'purchase', 'wheel')",
            name="ck_room_presets_hint_mode",
        ),
        sa.CheckConstraint(
            "color_mode IN ('all', 'palette', 'colorblind_safe', 'black_and_white')",
            name="ck_room_presets_color_mode",
        ),
        sa.CheckConstraint(
            "max_players >= 2 AND max_players <= 16",
            name="ck_room_presets_max_players",
        ),
        sa.CheckConstraint(
            "rounds >= 1 AND rounds <= 10", name="ck_room_presets_rounds"
        ),
        sa.CheckConstraint(
            "drawing_seconds IN (15, 30, 60, 90, 120, 180, 240, 300)",
            name="ck_room_presets_drawing_seconds",
        ),
        sa.CheckConstraint("version >= 1", name="ck_room_presets_version"),
        sa.ForeignKeyConstraint(
            ["owner_user_id"], ["users.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "owner_user_id", "name_key", name="uq_room_presets_owner_name"
        ),
    )
    op.create_index(
        "ix_room_presets_owner_user_id", "room_presets", ["owner_user_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_room_presets_owner_user_id", table_name="room_presets")
    op.drop_table("room_presets")
