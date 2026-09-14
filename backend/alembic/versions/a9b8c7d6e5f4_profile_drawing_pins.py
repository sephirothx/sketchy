"""pinned drawings on a profile

Revision ID: a9b8c7d6e5f4
Revises: d8e9f0a1b2c3
Create Date: 2026-09-14 16:00:00.000000

A profile can show up to six drawings its owner chose (#440). The table is
the pinner's act, not a fact about the drawing, which is why it hangs off the
account where a reaction hangs off a seat: it lasts as long as the account
wants it there, and a deleted account has no profile left to show a shelf on.

The cap and the ordering are in the schema rather than only in the write
path: `position` is `0..5` and unique per account, so a seventh pin has no
slot to sit in whatever writes it. The turn is addressed through the same
`(game_id, turn_id)` edge the rest of the history graph uses (#512), so a
turn from another game cannot be named by mistake and a pin goes with its
game or its turn through the cascade. Erasure is a status on `turn_drawings`
and no cascade reaches it; the account-erasure path deletes those pins itself.

Going back drops the pins. They are curated social data, nothing pins them,
and no finished game reads one; what a rollback loses is which six an owner
had chosen.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "a9b8c7d6e5f4"
down_revision: str | Sequence[str] | None = "d8e9f0a1b2c3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "profile_drawing_pins",
        sa.Column(
            "user_id",
            sa.Uuid(as_uuid=True, native_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "turn_id", sa.Uuid(as_uuid=True, native_uuid=True), primary_key=True
        ),
        sa.Column("game_id", sa.Uuid(as_uuid=True, native_uuid=True), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "user_id", "position", name="uq_profile_drawing_pins_user_position"
        ),
        sa.ForeignKeyConstraint(
            ["game_id", "turn_id"],
            ["turn_records.game_id", "turn_records.id"],
            name="fk_profile_drawing_pins_turn_same_game",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "position >= 0 AND position < 6", name="ck_profile_drawing_pins_position"
        ),
    )
    op.create_index(
        "ix_profile_drawing_pins_turn_id", "profile_drawing_pins", ["turn_id"]
    )
    op.create_index(
        "ix_profile_drawing_pins_game_id", "profile_drawing_pins", ["game_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_profile_drawing_pins_game_id", table_name="profile_drawing_pins")
    op.drop_index("ix_profile_drawing_pins_turn_id", table_name="profile_drawing_pins")
    op.drop_table("profile_drawing_pins")
