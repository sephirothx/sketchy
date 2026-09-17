"""remember the brush size a player's turn starts at

Revision ID: f4a5b6c7d8e9
Revises: e3f4a5b6c7d8
Create Date: 2026-09-17 00:00:01.000000

Every turn resets the toolbar, so a player who always draws at another size
was reaching for the slider at the start of every turn, with the clock
running. The size is one of the slider's stops - a default the slider could
not show would be a size nobody can get back to - and the CHECK says so.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "f4a5b6c7d8e9"
down_revision: str | Sequence[str] | None = "e3f4a5b6c7d8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

BRUSH_SIZES = (2, 4, 6, 8, 12, 16, 24, 32)


def upgrade() -> None:
    op.add_column(
        "user_settings",
        sa.Column("default_brush_size", sa.SmallInteger(), nullable=False, server_default=sa.text("6")),
    )
    with op.batch_alter_table("user_settings") as batch:
        batch.create_check_constraint(
            "ck_user_settings_default_brush_size",
            sa.column("default_brush_size").in_(BRUSH_SIZES),
        )


def downgrade() -> None:
    with op.batch_alter_table("user_settings") as batch:
        batch.drop_constraint("ck_user_settings_default_brush_size", type_="check")
    op.drop_column("user_settings", "default_brush_size")
