"""remember whether a pen's pressure shapes the brush

Revision ID: e3f4a5b6c7d8
Revises: d2e3f4a5b6c7
Create Date: 2026-09-17 00:00:00.000000

A pressure-sensitive pen draws a thinner brush stroke under a lighter hand
(#828), and a player can turn that off: a tablet with a harsh pressure curve,
or a hand that simply wants one width. Stored with the account so the choice
follows the player to the device the pen is actually attached to, which is
often not the one they changed it on.

On by default. The client acts on it only for a pen that has shown a working
sensor, so for everybody else the column is inert whatever it holds.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "e3f4a5b6c7d8"
down_revision: str | Sequence[str] | None = "d2e3f4a5b6c7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "user_settings",
        sa.Column("pen_pressure", sa.Boolean(), nullable=False, server_default=sa.true()),
    )


def downgrade() -> None:
    op.drop_column("user_settings", "pen_pressure")
