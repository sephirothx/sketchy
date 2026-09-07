"""record who may find a game on a profile

Revision ID: c4d5e6f7a8b9
Revises: b3c4d5e6f7a8
Create Date: 2026-09-07 10:00:00.000000

A finished game was the same to everyone who held a player's id: room name,
times, and every participant, whether the room had been listed in the lobby
or opened by invitation only (#469). `game_records.visibility` freezes the
room's public flag at save time, because the room is gone by the time anyone
asks. Rows written before the column existed read as private - nothing that
was not disclosed on purpose becomes public by migrating.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "c4d5e6f7a8b9"
down_revision: str | Sequence[str] | None = "b3c4d5e6f7a8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Batch mode so SQLite can carry the CHECK; on PostgreSQL it is two
    # plain ALTERs. Table-level, because autogenerate renders those and
    # silently drops column-level ones (#557).
    with op.batch_alter_table("game_records") as batch:
        batch.add_column(
            sa.Column(
                "visibility",
                sa.String(length=16),
                server_default=sa.text("'private'"),
                nullable=False,
            )
        )
        batch.create_check_constraint(
            "ck_game_records_visibility", "visibility IN ('public', 'private')"
        )


def downgrade() -> None:
    with op.batch_alter_table("game_records") as batch:
        batch.drop_constraint("ck_game_records_visibility", type_="check")
        batch.drop_column("visibility")
