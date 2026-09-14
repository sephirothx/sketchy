"""a copy remembers that it was one

Revision ID: c7d8e9f0a1b2
Revises: f8a9b0c1d2e3
Create Date: 2026-09-14 14:00:00.000000

A copy credits the list it was copied from (R-LIST-21), and the credit needs
one fact the schema did not keep.

`prompt_list_revisions.forked_from_revision_id` already says where a copy came
from, and it is deliberately **forgotten** when the original's author deletes
it: the reclaim sweep deletes the original's unpinned revisions and the
foreign key's `SET NULL` clears the pointer (R-LIST-17). The copy keeps every
prompt it took and forgets only where they came from, because the person they
came from asked for the list to go. That rule stays.

What it left behind was a copy indistinguishable from a list nobody copied, so
"copied from a list that was deleted" could only be said for the day between
the deletion and the sweep. `is_copy` is the fact that survives: that a list
was copied, and nothing about what from. It is a boolean on purpose - a name,
an author or an id would be exactly what the deleted list's author asked to
take away.

Existing copies are backfilled from the pointer they still hold. One whose
original was already reclaimed cannot be recovered, and is left as it was.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "c7d8e9f0a1b2"
down_revision: str | Sequence[str] | None = "f8a9b0c1d2e3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "prompt_lists",
        sa.Column("is_copy", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.execute(
        "UPDATE prompt_lists SET is_copy = true WHERE id IN ("
        "SELECT prompt_list_id FROM prompt_list_revisions "
        "WHERE version = 1 AND forked_from_revision_id IS NOT NULL)"
    )
    # A copy is a player's list: the official catalogue is seeded, never copied.
    with op.batch_alter_table("prompt_lists") as batch:
        batch.create_check_constraint(
            "ck_prompt_lists_copy_is_player_owned",
            "is_copy = false OR is_bundled = false",
        )


def downgrade() -> None:
    with op.batch_alter_table("prompt_lists") as batch:
        batch.drop_constraint("ck_prompt_lists_copy_is_player_owned", type_="check")
        batch.drop_column("is_copy")
