"""remember when an account was last connected

Revision ID: d5e6f7a8b9c0
Revises: c4d5e6f7a8b9
Create Date: 2026-09-07 12:00:00.000000

A profile says whether the player is online and, if not, how long ago they
went (#469). `users.last_seen_at` is stamped when the account's last socket
closes and when its first one opens; null until the account has ever
connected. `last_login_at` (a page load) and `last_active_at` (retention)
both mean something else on purpose and are left alone.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "d5e6f7a8b9c0"
down_revision: str | Sequence[str] | None = "c4d5e6f7a8b9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.add_column(
            sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.drop_column("last_seen_at")
