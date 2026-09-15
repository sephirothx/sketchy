"""reactions keyed by account

Revision ID: b0c1d2e3f4a5
Revises: a9b8c7d6e5f4
Create Date: 2026-09-15 18:00:00.000000

A reaction was keyed by the reactor's participant seat (#520). The Gallery
(#524) lets anyone signed in react to a public-game drawing, and most of
them never sat in that game, so the key becomes the account: `user_id`,
resolved to its canonical identity by the writer, unique with the turn. The
seat stays beside it, nullable now, for the rows whose reactor was in the
room - it is what names a reaction there and in history; a row with no seat
only counts (R-REACT-05).

Existing rows are backfilled from their seat's account. A seat without one
cannot hold a reaction (the finished-game write refuses guest seats), so the
backfill leaves nothing null; the guard delete is for a repaired row only.

Going back drops the account column and every row that had no seat to fall
back on: those are the reactions given from outside the room, which the
older schema cannot represent.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "b0c1d2e3f4a5"
down_revision: str | Sequence[str] | None = "a9b8c7d6e5f4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("turn_drawing_reactions") as batch:
        batch.add_column(
            sa.Column("user_id", sa.Uuid(as_uuid=True, native_uuid=True), nullable=True)
        )
    op.execute(
        "UPDATE turn_drawing_reactions SET user_id = ("
        "SELECT user_id FROM game_participants "
        "WHERE game_participants.id = turn_drawing_reactions.participant_id)"
    )
    op.execute("DELETE FROM turn_drawing_reactions WHERE user_id IS NULL")
    with op.batch_alter_table("turn_drawing_reactions") as batch:
        batch.alter_column(
            "user_id",
            existing_type=sa.Uuid(as_uuid=True, native_uuid=True),
            nullable=False,
        )
        batch.alter_column(
            "participant_id",
            existing_type=sa.Uuid(as_uuid=True, native_uuid=True),
            nullable=True,
        )
        batch.create_foreign_key(
            "fk_turn_drawing_reactions_user_id_users",
            "users",
            ["user_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch.create_unique_constraint(
            "uq_turn_drawing_reactions_turn_user", ["turn_id", "user_id"]
        )
        batch.create_index("ix_turn_drawing_reactions_user_id", ["user_id"])


def downgrade() -> None:
    op.execute("DELETE FROM turn_drawing_reactions WHERE participant_id IS NULL")
    with op.batch_alter_table("turn_drawing_reactions") as batch:
        batch.drop_index("ix_turn_drawing_reactions_user_id")
        batch.drop_constraint("uq_turn_drawing_reactions_turn_user", type_="unique")
        batch.drop_constraint("fk_turn_drawing_reactions_user_id_users", type_="foreignkey")
        batch.alter_column(
            "participant_id",
            existing_type=sa.Uuid(as_uuid=True, native_uuid=True),
            nullable=False,
        )
        batch.drop_column("user_id")
