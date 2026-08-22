"""add persistent user blocks

Revision ID: e6c0a3b8d254
Revises: d5b9f2a7c143
Create Date: 2026-08-22 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "e6c0a3b8d254"
down_revision: Union[str, Sequence[str], None] = "d5b9f2a7c143"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "user_blocks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("blocker_user_id", sa.Uuid(), nullable=False),
        sa.Column("blocked_user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "blocker_user_id != blocked_user_id", name="chk_no_self_block"
        ),
        sa.ForeignKeyConstraint(
            ["blocked_user_id"], ["users.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["blocker_user_id"], ["users.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "blocker_user_id", "blocked_user_id", name="uq_user_block"
        ),
    )
    op.create_index(
        "ix_user_blocks_blocked_user_id",
        "user_blocks",
        ["blocked_user_id"],
    )
    op.create_index(
        op.f("ix_user_blocks_blocker_user_id"),
        "user_blocks",
        ["blocker_user_id"],
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_user_blocks_blocker_user_id"), table_name="user_blocks"
    )
    op.drop_index("ix_user_blocks_blocked_user_id", table_name="user_blocks")
    op.drop_table("user_blocks")
