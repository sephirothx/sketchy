"""add account data exports

Revision ID: b3f7d0e5a821
Revises: a2e6c9d4f710
Create Date: 2026-08-22 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "b3f7d0e5a821"
down_revision: Union[str, Sequence[str], None] = "a2e6c9d4f710"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "data_exports",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="pending", nullable=False),
        sa.Column("schema_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("artifact", sa.JSON(), nullable=True),
        sa.Column("failure_code", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('pending', 'processing', 'ready', 'failed')",
            name="ck_data_exports_status",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_data_exports_expires_at"),
        "data_exports",
        ["expires_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_data_exports_user_id"),
        "data_exports",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        "ix_data_exports_user_created_at",
        "data_exports",
        ["user_id", "created_at"],
        unique=False,
    )
    # One live export per account, enforced where two simultaneous requests
    # can only be told apart: at the insert.
    op.create_index(
        "uq_data_exports_one_live_per_user",
        "data_exports",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('pending', 'processing')"),
        sqlite_where=sa.text("status IN ('pending', 'processing')"),
    )


def downgrade() -> None:
    op.drop_index("uq_data_exports_one_live_per_user", table_name="data_exports")
    op.drop_index("ix_data_exports_user_created_at", table_name="data_exports")
    op.drop_index(op.f("ix_data_exports_user_id"), table_name="data_exports")
    op.drop_index(op.f("ix_data_exports_expires_at"), table_name="data_exports")
    op.drop_table("data_exports")
