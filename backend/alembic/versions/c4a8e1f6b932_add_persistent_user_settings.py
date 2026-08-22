"""add persistent user settings

Revision ID: c4a8e1f6b932
Revises: b3f7d0e5a821
Create Date: 2026-08-22 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "c4a8e1f6b932"
down_revision: Union[str, Sequence[str], None] = "b3f7d0e5a821"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "user_settings",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("theme", sa.String(length=16), server_default="system", nullable=False),
        sa.Column("sound_effects", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("confetti_effects", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("sound_effects_volume", sa.Float(), server_default="0.7", nullable=False),
        sa.Column("brush_cursor", sa.String(length=16), server_default="crosshair", nullable=False),
        sa.Column(
            "key_bindings",
            sa.JSON(),
            server_default=sa.text(
                "'{\"brush\":[\"p\",\"1\"],\"fill\":[\"f\",\"2\"],"
                "\"eraser\":[\"e\",\"3\"],\"rectangle\":[\"r\",\"4\"],"
                "\"triangle\":[\"t\",\"5\"],\"ellipse\":[\"c\",\"6\"],"
                "\"brushDecrease\":[\"[\"],\"brushIncrease\":[\"]\"],"
                "\"undo\":[\"z\"]}'"
            ),
            nullable=False,
        ),
        sa.Column("colorblind_safe_colors", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("auto_clear_chat_on_guess", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("custom_brush_presets", sa.JSON(), server_default=sa.text("'[]'"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "brush_cursor IN ('crosshair', 'circle')",
            name="ck_user_settings_brush_cursor",
        ),
        sa.CheckConstraint(
            "theme IN ('light', 'dark', 'system')",
            name="ck_user_settings_theme",
        ),
        sa.CheckConstraint(
            "sound_effects_volume >= 0.0 AND sound_effects_volume <= 1.0",
            name="ck_user_settings_volume",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id"),
    )


def downgrade() -> None:
    op.drop_table("user_settings")
