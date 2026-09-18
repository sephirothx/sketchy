"""index the login lockouts by age, for the sweep that now removes them

Revision ID: b2d3e4f5a6c7
Revises: a1c2e3f4b5d6
Create Date: 2026-09-18 01:00:00.000000

`auth_login_lockouts` was documented as dropping rows untouched for a day,
but nothing ever did (#891): the method existed and had one caller, a test.
The retention sweep now walks the table oldest first, and this index is the
walk - without it, every hourly pass and its overdue probe would read the
whole table, which is the one an unauthenticated client can grow.
"""
from collections.abc import Sequence

from alembic import op


revision: str = "b2d3e4f5a6c7"
down_revision: str | Sequence[str] | None = "a1c2e3f4b5d6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_auth_login_lockouts_updated_at",
        "auth_login_lockouts",
        ["updated_at", "key_hash"],
    )


def downgrade() -> None:
    op.drop_index("ix_auth_login_lockouts_updated_at", table_name="auth_login_lockouts")
