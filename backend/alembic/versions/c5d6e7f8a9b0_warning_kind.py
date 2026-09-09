"""say which kind of notice a warning row is

Revision ID: c5d6e7f8a9b0
Revises: b4c5d6e7f8a9
Create Date: 2026-09-09 22:00:00.000000

A picture's removal is delivered through the warning machinery (#620,
R-AVA-08), which is what a player already meets: shown once, acknowledged,
pushed to a live socket. What it is not is a formal warning, and the notice
those render says "nothing is restricted" - which of a removal is false, and
grows more false with each one, since the wait before another picture may go
up grows too.

So the row says which it is. `warning` for the formal kind, unchanged and the
default; `avatar_removal` for a removal, which restricts something and whose
notice says what and until when.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "c5d6e7f8a9b0"
down_revision: str | Sequence[str] | None = "b4c5d6e7f8a9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("user_warnings") as batch:
        batch.add_column(
            sa.Column(
                "kind",
                sa.String(length=24),
                nullable=False,
                server_default="warning",
            )
        )
        batch.create_check_constraint(
            "ck_user_warnings_kind", "kind IN ('warning', 'avatar_removal')"
        )


def downgrade() -> None:
    with op.batch_alter_table("user_warnings") as batch:
        batch.drop_constraint("ck_user_warnings_kind", type_="check")
        batch.drop_column("kind")
