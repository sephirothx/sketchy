"""add meaningful user activity

Revision ID: f1d5b8c3e690
Revises: e9c4a7b2d580
Create Date: 2026-08-22 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "f1d5b8c3e690"
down_revision: Union[str, Sequence[str], None] = "e9c4a7b2d580"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _restore_expression_indexes_on_sqlite() -> None:
    if op.get_bind().dialect.name != "sqlite":
        return
    op.create_index(
        "ix_users_username_lower",
        "users",
        [sa.text("lower(username)")],
        unique=True,
        sqlite_where=sa.text("username IS NOT NULL"),
    )
    op.create_index(
        "ix_users_email_lower",
        "users",
        [sa.text("lower(email)")],
        unique=True,
        sqlite_where=sa.text("email IS NOT NULL"),
    )


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("last_active_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute("UPDATE users SET last_active_at = created_at")
    with op.batch_alter_table("users") as batch_op:
        batch_op.alter_column(
            "last_active_at",
            existing_type=sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        )
    _restore_expression_indexes_on_sqlite()
    op.create_index(
        "ix_users_state_last_active_at",
        "users",
        ["state", "last_active_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_users_state_last_active_at", table_name="users")
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_column("last_active_at")
    _restore_expression_indexes_on_sqlite()
