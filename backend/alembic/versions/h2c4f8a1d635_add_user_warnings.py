"""add user warnings

Revision ID: h2c4f8a1d635
Revises: f7a2d4b83e06
Create Date: 2026-08-26 00:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "h2c4f8a1d635"
down_revision: str | Sequence[str] | None = "f7a2d4b83e06"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_warnings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("issued_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("reason", sa.String(length=255), nullable=False),
        sa.Column("source_report_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["issued_by_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["source_report_id"], ["player_reports.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_user_warnings_user_id", "user_warnings", ["user_id"])
    op.create_index(
        "ix_user_warnings_source_report_id", "user_warnings", ["source_report_id"]
    )
    op.create_index(
        "ix_user_warnings_user_pending",
        "user_warnings",
        ["user_id", "acknowledged_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_user_warnings_user_pending", table_name="user_warnings")
    op.drop_index("ix_user_warnings_source_report_id", table_name="user_warnings")
    op.drop_index("ix_user_warnings_user_id", table_name="user_warnings")
    op.drop_table("user_warnings")
