"""remember that an accepted request still owes its asker the news

Revision ID: d6e7f8a9b0c1
Revises: c5d6e7f8a9b0
Create Date: 2026-09-09 22:30:00.000000

Being told a request was accepted was derived on the client, by watching the
lists move somebody from `outgoing` to `friends`. A client that never saw the
`outgoing` state cannot see that move: reload the page while the answer is in
flight and the first lists it ever reads already contain the friendship, so
there is nothing to notice and the asker is never told - on that visit or any
later one (#724).

A thing somebody must be told cannot be derived from a diff the reader might
not be present for. So the row carries it: accepted and not yet announced is
a state the server holds, and it survives reloads, other devices, and being
offline when the answer came.

Null for every existing accepted friendship, which would otherwise announce
the entire history of the service to everybody at once. Backfilled to the
moment of the migration: told already, as far as anyone is concerned.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "d6e7f8a9b0c1"
down_revision: str | Sequence[str] | None = "c5d6e7f8a9b0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("friendships") as batch:
        batch.add_column(
            sa.Column(
                "acceptance_announced_at", sa.DateTime(timezone=True), nullable=True
            )
        )
    # Everything already accepted counts as already told: the alternative is
    # announcing every friendship anybody ever made, at once, on their next
    # visit.
    op.execute(
        "UPDATE friendships SET acceptance_announced_at = responded_at "
        "WHERE status = 'accepted'"
    )
    # The asker's question on every read: "anything of mine accepted that I
    # have not been told about?" Over exactly the rows that can still answer
    # yes.
    op.create_index(
        "ix_friendships_acceptance_unannounced",
        "friendships",
        ["requested_by_id"],
        postgresql_where=sa.text(
            "status = 'accepted' AND acceptance_announced_at IS NULL"
        ),
        sqlite_where=sa.text(
            "status = 'accepted' AND acceptance_announced_at IS NULL"
        ),
    )


def downgrade() -> None:
    op.drop_index("ix_friendships_acceptance_unannounced", table_name="friendships")
    with op.batch_alter_table("friendships") as batch:
        batch.drop_column("acceptance_announced_at")
