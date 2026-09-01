"""add the friendships table

One row per pair rather than one per direction, in a canonical order that a
CHECK enforces. Two directional rows can disagree - one accepted, one not -
and nothing in the schema could forbid it; the ordering also makes a crossing
request collide on the primary key instead of creating a second row, which is
what turns "A asked B while B was asking A" into one accepted friendship.

Revision ID: w6d0b4f8a925
Revises: v5c9a3e7f814
Create Date: 2026-09-02 00:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "w6d0b4f8a925"
down_revision: str | Sequence[str] | None = "v5c9a3e7f814"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "friendships",
        sa.Column("user_low_id", sa.Uuid(), nullable=False),
        sa.Column("user_high_id", sa.Uuid(), nullable=False),
        sa.Column("requested_by_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("responded_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_low_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_high_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["requested_by_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_low_id", "user_high_id"),
        # Named explicitly so SQLite's batch mode can drop and rebuild them.
        sa.CheckConstraint("user_low_id < user_high_id", name="ck_friendships_ordered"),
        sa.CheckConstraint(
            "requested_by_id = user_low_id OR requested_by_id = user_high_id",
            name="ck_friendships_requester_is_a_member",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'accepted', 'declined')",
            name="ck_friendships_status",
        ),
    )
    # The primary key already serves every lookup leading with `user_low_id`;
    # these two cover the other directions a read arrives from.
    op.create_index("ix_friendships_user_high_id", "friendships", ["user_high_id"])
    op.create_index("ix_friendships_requested_by_id", "friendships", ["requested_by_id"])


def downgrade() -> None:
    op.drop_index("ix_friendships_requested_by_id", table_name="friendships")
    op.drop_index("ix_friendships_user_high_id", table_name="friendships")
    op.drop_table("friendships")
