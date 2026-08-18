"""Make last_login_at required and backfill existing rows.

Revision ID: 7c9e2f1a4b80
Revises: 70c3292066f3
Create Date: 2026-08-18 16:45:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "7c9e2f1a4b80"
down_revision: Union[str, Sequence[str], None] = "70c3292066f3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _users_table(*, last_login_nullable: bool) -> sa.Table:
    """Users schema for SQLite batch copies.

    Passing copy_from avoids reflecting ix_users_username_lower, which SQLite
    cannot round-trip as an expression-based index.
    """
    metadata = sa.MetaData()
    users = sa.Table(
        "users",
        metadata,
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("username", sa.String(length=32), nullable=True),
        sa.Column("password_hash", sa.String(length=255), nullable=True),
        sa.Column("display_name", sa.String(length=32), nullable=False),
        sa.Column("name_color", sa.String(length=16), nullable=True),
        sa.Column("avatar_url", sa.String(length=512), nullable=True),
        sa.Column("is_anonymous", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "last_login_at",
            sa.DateTime(timezone=True),
            nullable=last_login_nullable,
            server_default=None if last_login_nullable else sa.func.now(),
        ),
    )
    sa.Index(
        "ix_users_username_lower",
        sa.func.lower(users.c.username),
        unique=True,
        sqlite_where=sa.text("username IS NOT NULL"),
        postgresql_where=sa.text("username IS NOT NULL"),
    )
    return users


def upgrade() -> None:
    op.execute(sa.text("UPDATE users SET last_login_at = created_at WHERE last_login_at IS NULL"))

    with op.batch_alter_table("users", copy_from=_users_table(last_login_nullable=True)) as batch_op:
        batch_op.alter_column(
            "last_login_at",
            existing_type=sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        )


def downgrade() -> None:
    with op.batch_alter_table("users", copy_from=_users_table(last_login_nullable=False)) as batch_op:
        batch_op.drop_column("last_login_at")
