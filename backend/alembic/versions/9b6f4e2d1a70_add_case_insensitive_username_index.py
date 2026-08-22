"""add case-insensitive username index

Revision ID: 9b6f4e2d1a70
Revises: e7c9d4bc813e
Create Date: 2026-08-22 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "9b6f4e2d1a70"
down_revision: Union[str, Sequence[str], None] = "e7c9d4bc813e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Enforce username uniqueness independently of letter case."""
    op.create_index(
        "ix_users_username_lower",
        "users",
        [sa.text("lower(username)")],
        unique=True,
        sqlite_where=sa.text("username IS NOT NULL"),
        postgresql_where=sa.text("username IS NOT NULL"),
    )


def downgrade() -> None:
    """Remove the case-insensitive username uniqueness rule."""
    op.drop_index("ix_users_username_lower", table_name="users")
