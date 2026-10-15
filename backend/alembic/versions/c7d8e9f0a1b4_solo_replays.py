"""solo replays: a finished past Daily played again from the archive

Revision ID: c7d8e9f0a1b4
Revises: b6c7d8e9f0a3
Create Date: 2026-10-15 00:00:00.000000

The Daily archive (#1470) lets a player play a past Daily again once they
have finished it. That run records nothing, so it is a Daily run with
`replay` set, beside the date's own run rather than instead of it: the
one-Daily-per-date index leaves replays out, and a second index keeps one
replay going per player. The partial indexes are dropped around the batch
so SQLite's table copy does not have to carry their predicates.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "c7d8e9f0a1b4"
down_revision: str | Sequence[str] | None = "b6c7d8e9f0a3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ONE_FREE = "state = 'active' AND mode = 'free'"


def _partial(name: str, columns: list[str], where: str) -> None:
    op.create_index(
        name, "solo_runs", columns, unique=True,
        postgresql_where=sa.text(where), sqlite_where=sa.text(where),
    )


def upgrade() -> None:
    op.drop_index("uq_solo_runs_one_daily", table_name="solo_runs")
    op.drop_index("uq_solo_runs_one_active_free", table_name="solo_runs")
    with op.batch_alter_table("solo_runs") as batch:
        batch.add_column(
            sa.Column("replay", sa.Boolean(), nullable=False, server_default=sa.false())
        )
        batch.create_check_constraint("ck_solo_runs_replay", "NOT replay OR mode = 'daily'")
    _partial("uq_solo_runs_one_active_free", ["user_id"], _ONE_FREE)
    _partial("uq_solo_runs_one_daily", ["user_id", "daily_date"], "mode = 'daily' AND NOT replay")
    _partial("uq_solo_runs_one_active_replay", ["user_id"], "state = 'active' AND replay")


def downgrade() -> None:
    op.execute("DELETE FROM solo_runs WHERE replay")
    op.drop_index("uq_solo_runs_one_active_replay", table_name="solo_runs")
    op.drop_index("uq_solo_runs_one_daily", table_name="solo_runs")
    op.drop_index("uq_solo_runs_one_active_free", table_name="solo_runs")
    with op.batch_alter_table("solo_runs") as batch:
        batch.drop_constraint("ck_solo_runs_replay", type_="check")
        batch.drop_column("replay")
    _partial("uq_solo_runs_one_active_free", ["user_id"], _ONE_FREE)
    _partial("uq_solo_runs_one_daily", ["user_id", "daily_date"], "mode = 'daily'")
