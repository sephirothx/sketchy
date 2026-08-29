"""add role change notices

Revision ID: n7e2f5b8c934
Revises: m6d1e7a4b829
Create Date: 2026-08-29 00:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "n7e2f5b8c934"
down_revision: str | Sequence[str] | None = "m6d1e7a4b829"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "role_change_notices",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "role IN ('user', 'moderator')",
            name="ck_role_change_notices_role",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_role_change_notices_user_id", "role_change_notices", ["user_id"]
    )
    op.create_index(
        "ix_role_change_notices_user_pending",
        "role_change_notices",
        ["user_id", "acknowledged_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_role_change_notices_user_pending", table_name="role_change_notices"
    )
    op.drop_index("ix_role_change_notices_user_id", table_name="role_change_notices")
    op.drop_table("role_change_notices")
