"""page a player's history off one index

Revision ID: d4e5f6a7b8c0
Revises: c0d1e2f3a4b6
Create Date: 2026-09-30 12:00:00.000000

A profile's game list is newest first, and `finished_at` lived only on the
game: every page, a cursor's included, gathered all of the player's seats,
joined their games and sorted them before it could take twenty (#477). Each
seat now carries its game's finish, and `(user_id, finished_at, game_id)`
lets the page walk down one player's seats from where the last page stopped
and stop after a page. The new index leads with `user_id`, so it replaces
`ix_game_participants_user_id` rather than sitting beside it.

The copy is tied to the game by a composite foreign key onto
`game_records (id, finished_at)`, which needs that pair to be unique - it is
trivially, the id being the key, and the constraint exists to be referenced.
A seat whose copy disagreed with its game would sort into the wrong place in
a history and nothing else would notice.

The shape is the one `tests/test_online_ddl.py` asks for where the runner
can honour it. The index builds cannot be `CONCURRENTLY`: the runner applies
every revision in one transaction, where PostgreSQL refuses it (#969), and
nothing is deployed yet. Going back drops the copy and restores the old index.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "d4e5f6a7b8c0"
down_revision: str | Sequence[str] | None = "c0d1e2f3a4b6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# The retention sweeps' batch: one bounded UPDATE at a time, each short.
_BATCH = 5000
_FK = "fk_game_participants_game_finished_at"
_TARGET = "uq_game_records_id_finished_at"
_NOT_NULL = "ck_game_participants_finished_at_not_null"
_INDEX = "ix_game_participants_user_history"
_OLD_INDEX = "ix_game_participants_user_id"


def _backfill() -> None:
    statement = sa.text(
        "UPDATE game_participants SET finished_at = ("
        "SELECT game_records.finished_at FROM game_records "
        "WHERE game_records.id = game_participants.game_id) "
        "WHERE id IN (SELECT id FROM game_participants "
        f"WHERE finished_at IS NULL LIMIT {_BATCH})"
    )
    bind = op.get_bind()
    while True:
        # online-ddl: bounded per statement; commits with the revision, which is safe only while nothing is deployed (see the docstring)
        if bind.execute(statement).rowcount == 0:
            return


def upgrade() -> None:
    op.add_column(
        "game_participants",
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    _backfill()
    if op.get_context().dialect.name == "postgresql":
        op.create_unique_constraint(_TARGET, "game_records", ["id", "finished_at"])
        op.create_check_constraint(
            _NOT_NULL, "game_participants", "finished_at IS NOT NULL", postgresql_not_valid=True
        )
        op.execute(f"ALTER TABLE game_participants VALIDATE CONSTRAINT {_NOT_NULL}")
        # online-ddl: the validated CHECK just above lets PostgreSQL set NOT NULL without a scan
        op.alter_column("game_participants", "finished_at", nullable=False)
        op.drop_constraint(_NOT_NULL, "game_participants", type_="check")
        op.create_foreign_key(
            _FK,
            "game_participants",
            "game_records",
            ["game_id", "finished_at"],
            ["id", "finished_at"],
            ondelete="CASCADE",
            postgresql_not_valid=True,
        )
        op.execute(f"ALTER TABLE game_participants VALIDATE CONSTRAINT {_FK}")
        op.drop_index(_OLD_INDEX, table_name="game_participants")
        # online-ddl: CONCURRENTLY cannot run in the runner's single transaction (#969); nothing is deployed
        op.create_index(_INDEX, "game_participants", ["user_id", "finished_at", "game_id"])
    else:
        with op.batch_alter_table("game_records") as batch:
            batch.create_unique_constraint(_TARGET, ["id", "finished_at"])
        with op.batch_alter_table("game_participants") as batch:
            # online-ddl: SQLite rebuilds the table in batch mode; it has no NOT VALID and holds no live deployment
            batch.alter_column("finished_at", nullable=False)
            # online-ddl: SQLite rebuilds the table in batch mode; it has no NOT VALID and holds no live deployment
            batch.create_foreign_key(
                _FK,
                "game_records",
                ["game_id", "finished_at"],
                ["id", "finished_at"],
                ondelete="CASCADE",
            )
            batch.drop_index(_OLD_INDEX)
            # online-ddl: SQLite rebuilds the table in batch mode and holds no live deployment
            batch.create_index(_INDEX, ["user_id", "finished_at", "game_id"])


def downgrade() -> None:
    if op.get_context().dialect.name == "postgresql":
        op.drop_index(_INDEX, table_name="game_participants")
        op.create_index(_OLD_INDEX, "game_participants", ["user_id"])
        op.drop_constraint(_FK, "game_participants", type_="foreignkey")
        op.drop_column("game_participants", "finished_at")
        op.drop_constraint(_TARGET, "game_records", type_="unique")
    else:
        with op.batch_alter_table("game_participants") as batch:
            batch.drop_index(_INDEX)
            batch.create_index(_OLD_INDEX, ["user_id"])
            batch.drop_constraint(_FK, type_="foreignkey")
            batch.drop_column("finished_at")
        with op.batch_alter_table("game_records") as batch:
            batch.drop_constraint(_TARGET, type_="unique")
