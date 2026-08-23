"""add global room code reservations

Revision ID: d1b5e9f3a427
Revises: c0a4e6f8b312
Create Date: 2026-08-23 00:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "d1b5e9f3a427"
down_revision: str | Sequence[str] | None = "c0a4e6f8b312"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "room_code_reservations",
        sa.Column("code", sa.String(length=6), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("retired_until", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "kind IN ('ephemeral', 'persistent')",
            name="ck_room_code_kind",
        ),
        sa.CheckConstraint(
            "(kind = 'persistent' AND retired_until IS NULL) OR kind = 'ephemeral'",
            name="ck_persistent_room_code_never_retires",
        ),
        sa.PrimaryKeyConstraint("code"),
    )
    op.create_index(
        "ix_room_code_reservations_retired_until",
        "room_code_reservations",
        ["retired_until"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_room_code_reservations_retired_until",
        table_name="room_code_reservations",
    )
    op.drop_table("room_code_reservations")
