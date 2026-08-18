"""Add last_login_at to users.

Revision ID: 70c3292066f3
Revises: 264a248789d1
Create Date: 2026-08-18 16:16:10.843112

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "70c3292066f3"
down_revision: Union[str, Sequence[str], None] = "264a248789d1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "last_login_at")
