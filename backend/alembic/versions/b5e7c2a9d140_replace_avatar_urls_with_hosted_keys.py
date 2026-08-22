"""replace avatar urls with hosted keys

Revision ID: b5e7c2a9d140
Revises: 8c4e1a7b2d60
Create Date: 2026-08-22 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "b5e7c2a9d140"
down_revision: Union[str, Sequence[str], None] = "8c4e1a7b2d60"
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
    """Invalidate external hotlinks and reserve future identity asset tables."""
    op.execute("UPDATE users SET avatar_url = NULL")
    with op.batch_alter_table("users") as batch_op:
        batch_op.alter_column(
            "avatar_url",
            new_column_name="avatar_key",
            existing_type=sa.String(length=512),
            type_=sa.String(length=32),
            existing_nullable=True,
        )
        batch_op.create_check_constraint(
            "ck_users_avatar_key",
            "avatar_key IN ('initial', 'pencil', 'palette', 'spark')",
        )
    _restore_expression_indexes_on_sqlite()

    op.create_table(
        "uploaded_avatar_assets",
        sa.Column("id", sa.Uuid(native_uuid=True), nullable=False),
        sa.Column("user_id", sa.Uuid(native_uuid=True), nullable=False),
        sa.Column("object_key", sa.String(length=512), nullable=False),
        sa.Column("content_type", sa.String(length=64), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column("checksum_sha256", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("object_key"),
        sa.UniqueConstraint("user_id"),
    )
    op.create_table(
        "external_identities",
        sa.Column("id", sa.Uuid(native_uuid=True), nullable=False),
        sa.Column("user_id", sa.Uuid(native_uuid=True), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("subject", sa.String(length=255), nullable=False),
        sa.Column("provider_email", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider", "subject", name="uq_external_identity"),
    )
    op.create_index(
        op.f("ix_external_identities_user_id"),
        "external_identities",
        ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    """Restore the legacy URL slot while leaving all old hotlinks discarded."""
    op.drop_index(
        op.f("ix_external_identities_user_id"), table_name="external_identities"
    )
    op.drop_table("external_identities")
    op.drop_table("uploaded_avatar_assets")
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_constraint("ck_users_avatar_key", type_="check")
        batch_op.alter_column(
            "avatar_key",
            new_column_name="avatar_url",
            existing_type=sa.String(length=32),
            type_=sa.String(length=512),
            existing_nullable=True,
        )
    _restore_expression_indexes_on_sqlite()
