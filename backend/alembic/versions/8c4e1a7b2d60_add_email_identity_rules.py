"""add email identity rules

Revision ID: 8c4e1a7b2d60
Revises: 6a2d9f4c1b80
Create Date: 2026-08-22 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "8c4e1a7b2d60"
down_revision: Union[str, Sequence[str], None] = "6a2d9f4c1b80"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _restore_username_index_on_sqlite() -> None:
    if op.get_bind().dialect.name == "sqlite":
        op.create_index(
            "ix_users_username_lower",
            "users",
            [sa.text("lower(username)")],
            unique=True,
            sqlite_where=sa.text("username IS NOT NULL"),
        )


def upgrade() -> None:
    """Normalize existing values and constrain future email identities."""
    op.execute("UPDATE users SET email = lower(trim(email)) WHERE email IS NOT NULL")
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(
            sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.create_check_constraint(
            "ck_users_email_normalized",
            "email IS NULL OR email = lower(trim(email))",
        )
        batch_op.create_check_constraint(
            "ck_users_verified_email_present",
            "email IS NOT NULL OR email_verified_at IS NULL",
        )

    _restore_username_index_on_sqlite()
    op.create_index(
        "ix_users_email_lower",
        "users",
        [sa.text("lower(email)")],
        unique=True,
        postgresql_where=sa.text("email IS NOT NULL"),
        sqlite_where=sa.text("email IS NOT NULL"),
    )


def downgrade() -> None:
    """Remove verification metadata and email identity constraints."""
    op.drop_index("ix_users_email_lower", table_name="users")
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_constraint("ck_users_verified_email_present", type_="check")
        batch_op.drop_constraint("ck_users_email_normalized", type_="check")
        batch_op.drop_column("email_verified_at")
    _restore_username_index_on_sqlite()
