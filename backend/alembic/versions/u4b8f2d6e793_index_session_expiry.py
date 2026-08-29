"""index auth_sessions.expires_at

Both the new retention sweep and every session-resolution path filter on
this column; until now none of them had an index for it.

Revision ID: u4b8f2d6e793
Revises: t3a7e1c5d682
Create Date: 2026-08-29 00:00:00.000000

"""
from collections.abc import Sequence

from alembic import op


revision: str = "u4b8f2d6e793"
down_revision: str | Sequence[str] | None = "t3a7e1c5d682"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_auth_sessions_expires_at", "auth_sessions", ["expires_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_auth_sessions_expires_at", table_name="auth_sessions")
