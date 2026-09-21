"""store only what the database is for; the daily roll-up goes to Prometheus

Revision ID: d7e8f9a0b1c2
Revises: c3e4f5a6b7d8
Create Date: 2026-09-21 12:00:00.000000

Every runtime event is counted on `/metrics` as `sketchy_events_total{event}`
(#965). Four were also written here as pure measures Prometheus already holds
in more detail - a drawing's wire and stored size (two rows every turn), a
recap drop, a throttle - and nothing in the app read their rows; three more
were declared and never written by anything. They leave the check, and their
rows go first, since the narrower check would refuse them. What stays is keyed
to an account or a room for the moderation activity view, or worth keeping
even if the metrics stack was down: a timer overrun, an abandoned history
write (R-OBS-10).

`runtime_stats_daily` goes with them. Everything in it was derivable from the
counter, and the one chart that read it now reads Grafana.

The shape is the one `tests/test_online_ddl.py` asks for - the delete in
batches, the check replaced `NOT VALID` and validated in a separate statement -
but **it buys nothing yet, and this revision does not rely on it.** Every
revision runs inside one transaction: `upgrade_database` holds a
transaction-scoped advisory lock so two deploys cannot migrate at once, and
applies the application role's grants in the same transaction (#896). Inside
it the batches do not commit between each other, and the exclusive lock the
check's replacement takes is held to the end, so `VALIDATE` scans under it. And
`autocommit_block()`, which would make the batches commit, cannot run under a
transaction the runner rather than Alembic opened. Resolving that is a decision
about the runner, not about this revision (#969).

This one is safe regardless, because nothing is deployed: it runs on an empty
production database, or a development one with nothing writing beside it. For
the same reason narrowing the check is safe here; after launch a check that
running code might still violate has to be narrowed in a later revision than
the one that stops writing it (`docs/database.md`, *Adding a table or
column*).

Going back restores the wider check and an empty roll-up table: the rows that
were deleted were thirty-day diagnostics, and the roll-up is rebuilt from the
events written after it exists again.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "d7e8f9a0b1c2"
down_revision: str | Sequence[str] | None = "c3e4f5a6b7d8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_BEFORE = (
    "room.created", "room.closed", "player.joined", "player.left",
    "player.disconnected", "player.reconnected", "player.evicted",
    "game.started", "game.finished", "game.abandoned", "turn.ended",
    "timer.overran", "canvas.payload_observed", "drawing.stored",
    "drawing.encoded", "recap.budget_dropped", "command.throttled",
    "history.write_abandoned",
)
# Counted on `/metrics` only from now on, or never written by anything.
_REMOVED = (
    "game.started", "turn.ended", "canvas.payload_observed",
    "drawing.stored", "drawing.encoded", "recap.budget_dropped",
    "command.throttled",
)
_AFTER = tuple(value for value in _BEFORE if value not in _REMOVED)

# The retention sweeps' batch: one bounded DELETE at a time, each short.
_BATCH = 5000


def _check(values: tuple[str, ...]) -> str:
    return "event_type IN (" + ", ".join(f"'{value}'" for value in values) + ")"


def _delete_removed_rows() -> None:
    listed = ", ".join(f"'{value}'" for value in _REMOVED)
    statement = sa.text(
        f"DELETE FROM runtime_events WHERE id IN ("
        f"SELECT id FROM runtime_events WHERE event_type IN ({listed}) LIMIT {_BATCH})"
    )
    bind = op.get_bind()
    while True:
        # online-ddl: bounded per statement; commits with the revision, which is safe only while nothing is deployed (see the docstring)
        if bind.execute(statement).rowcount == 0:
            return


def upgrade() -> None:
    _delete_removed_rows()
    if op.get_context().dialect.name == "postgresql":
        op.drop_constraint("ck_runtime_events_type", "runtime_events", type_="check")
        op.create_check_constraint(
            "ck_runtime_events_type",
            "runtime_events",
            _check(_AFTER),
            postgresql_not_valid=True,
        )
        op.execute("ALTER TABLE runtime_events VALIDATE CONSTRAINT ck_runtime_events_type")
    else:
        with op.batch_alter_table("runtime_events") as batch:
            batch.drop_constraint("ck_runtime_events_type", type_="check")
            # online-ddl: SQLite rebuilds the table in batch mode; it has no NOT VALID and holds no live deployment
            batch.create_check_constraint("ck_runtime_events_type", _check(_AFTER))
    op.drop_table("runtime_stats_daily")


def downgrade() -> None:
    op.create_table(
        "runtime_stats_daily",
        sa.Column("stat_date", sa.Date(), nullable=False),
        sa.Column("metric", sa.String(length=32), nullable=False),
        sa.Column("occurrences", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("value_sum", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("value_max", sa.Integer(), nullable=True),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "occurrences >= 0 AND value_sum >= 0", name="ck_runtime_stats_nonnegative"
        ),
        sa.PrimaryKeyConstraint("stat_date", "metric"),
    )
    if op.get_context().dialect.name == "postgresql":
        # As `a1c2e3f4b5d6` left it: updated in place on every flush.
        op.execute("ALTER TABLE runtime_stats_daily SET (fillfactor = 85)")
    with op.batch_alter_table("runtime_events") as batch:
        batch.drop_constraint("ck_runtime_events_type", type_="check")
        batch.create_check_constraint("ck_runtime_events_type", _check(_BEFORE))
