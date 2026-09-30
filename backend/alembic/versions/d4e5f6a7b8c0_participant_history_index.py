"""page a player's history off one index

Revision ID: d4e5f6a7b8c0
Revises: c0d1e2f3a4b6
Create Date: 2026-09-30 12:00:00.000000

A profile's game list is newest first, and what it orders and filters on -
`finished_at`, `outcome`, `visibility` - lived only on the game: every page, a
cursor's included, gathered all of the player's seats, joined their games and
sorted them before it could take twenty (#477). Each seat now carries its
game's three, and `(user_id, outcome, visibility, finished_at, game_id)` lets
the page walk one player's finished public seats (say) from where the last
page stopped and stop after a page - with the filters in the index rather than
probed per row, so a stranger's page does not walk every private game to find
public ones. The new index leads with `user_id`, so it replaces
`ix_game_participants_user_id` rather than sitting beside it.

The copies are tied to the game by a composite foreign key onto
`game_records (id, finished_at, outcome, visibility)`, which needs those four
to be unique - they are trivially, the id being the key, and the constraint
exists to be referenced. A seat whose copy disagreed with its game would sort
into the wrong place in a history, or show a private game, and nothing else
would notice. Nothing updates any of the three once a game is written; if
something ever does, `ON UPDATE CASCADE` carries it to the copies.

The shape is the one `tests/test_online_ddl.py` asks for where the runner
can honour it. The index builds cannot be `CONCURRENTLY`: the runner applies
every revision in one transaction, where PostgreSQL refuses it (#969), and
nothing is deployed yet. Going back drops the copies and restores the old
index.
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
_FK = "fk_game_participants_game_history"
_TARGET = "uq_game_records_history_key"
_TARGET_COLUMNS = ["id", "finished_at", "outcome", "visibility"]
_COPIES = ["game_id", "finished_at", "outcome", "visibility"]
_NOT_NULL = "ck_game_participants_finished_at_not_null"
_INDEX = "ix_game_participants_user_history"
_INDEX_COLUMNS = ["user_id", "outcome", "visibility", "finished_at", "game_id"]
_OLD_INDEX = "ix_game_participants_user_id"


def _backfill() -> None:
    """Copy each seat's game values over, one primary-key range at a time.

    Ranges rather than `WHERE finished_at IS NULL LIMIT n`, which nothing
    indexes: each batch of that scanned past every row already filled, so the
    whole backfill was quadratic in the table.
    """
    bind = op.get_bind()
    copied = ", ".join(
        f"{column} = (SELECT g.{column} FROM game_records g WHERE g.id = game_participants.game_id)"
        for column in ("finished_at", "outcome", "visibility")
    )
    last = None
    while True:
        after = "" if last is None else "WHERE id > :last "
        # The batch's last key; `max()` is not defined over PostgreSQL's uuid.
        upper = bind.execute(
            sa.text(
                f"SELECT id FROM (SELECT id FROM game_participants {after}"
                f"ORDER BY id LIMIT {_BATCH}) AS batch ORDER BY id DESC LIMIT 1"
            ),
            {} if last is None else {"last": last},
        ).scalar()
        if upper is None:
            return
        bounds = "id <= :upper" if last is None else "id > :last AND id <= :upper"
        # online-ddl: bounded per statement by a primary-key range; commits with the revision, which is safe only while nothing is deployed (see the docstring)
        bind.execute(
            sa.text(f"UPDATE game_participants SET {copied} WHERE {bounds}"),
            {"upper": upper} if last is None else {"last": last, "upper": upper},
        )
        last = upper


def upgrade() -> None:
    op.add_column(
        "game_participants",
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    # The game's own defaults, so the copy needs no default of its own to be
    # wrong about: the backfill overwrites both for every existing seat.
    op.add_column(
        "game_participants",
        sa.Column("outcome", sa.String(16), nullable=False, server_default=sa.text("'finished'")),
    )
    op.add_column(
        "game_participants",
        sa.Column("visibility", sa.String(16), nullable=False, server_default=sa.text("'private'")),
    )
    _backfill()
    if op.get_context().dialect.name == "postgresql":
        # online-ddl: CONCURRENTLY cannot run in the runner's single transaction (#969); nothing is deployed. At launch: build this index concurrently, then ADD CONSTRAINT ... UNIQUE USING INDEX
        op.create_unique_constraint(_TARGET, "game_records", _TARGET_COLUMNS)
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
            _COPIES,
            _TARGET_COLUMNS,
            ondelete="CASCADE",
            onupdate="CASCADE",
            postgresql_not_valid=True,
        )
        op.execute(f"ALTER TABLE game_participants VALIDATE CONSTRAINT {_FK}")
        op.drop_index(_OLD_INDEX, table_name="game_participants")
        # online-ddl: CONCURRENTLY cannot run in the runner's single transaction (#969); nothing is deployed
        op.create_index(_INDEX, "game_participants", _INDEX_COLUMNS)
    else:
        with op.batch_alter_table("game_records") as batch:
            # online-ddl: SQLite rebuilds the table in batch mode and holds no live deployment
            batch.create_unique_constraint(_TARGET, _TARGET_COLUMNS)
        with op.batch_alter_table("game_participants") as batch:
            # online-ddl: SQLite rebuilds the table in batch mode; it has no NOT VALID and holds no live deployment
            batch.alter_column("finished_at", nullable=False)
            # online-ddl: SQLite rebuilds the table in batch mode; it has no NOT VALID and holds no live deployment
            batch.create_foreign_key(
                _FK,
                "game_records",
                _COPIES,
                _TARGET_COLUMNS,
                ondelete="CASCADE",
                onupdate="CASCADE",
            )
            batch.drop_index(_OLD_INDEX)
            # online-ddl: SQLite rebuilds the table in batch mode and holds no live deployment
            batch.create_index(_INDEX, _INDEX_COLUMNS)


def downgrade() -> None:
    if op.get_context().dialect.name == "postgresql":
        op.drop_index(_INDEX, table_name="game_participants")
        op.create_index(_OLD_INDEX, "game_participants", ["user_id"])
        op.drop_constraint(_FK, "game_participants", type_="foreignkey")
        for column in ("visibility", "outcome", "finished_at"):
            op.drop_column("game_participants", column)
        op.drop_constraint(_TARGET, "game_records", type_="unique")
    else:
        with op.batch_alter_table("game_participants") as batch:
            batch.drop_index(_INDEX)
            batch.create_index(_OLD_INDEX, ["user_id"])
            batch.drop_constraint(_FK, type_="foreignkey")
            for column in ("visibility", "outcome", "finished_at"):
                batch.drop_column(column)
        with op.batch_alter_table("game_records") as batch:
            batch.drop_constraint(_TARGET, type_="unique")
