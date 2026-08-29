"""record how the server behaves, including the games that go wrong

Revision ID: c4d1a8e35b72
Revises: b2e9f60c8a45
Create Date: 2026-08-24 15:05:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "c4d1a8e35b72"
down_revision: str | Sequence[str] | None = "b2e9f60c8a45"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


EVENT_TYPES = (
    "'room.created', 'room.closed', 'player.joined', 'player.left', "
    "'player.disconnected', 'player.reconnected', 'player.evicted', "
    "'game.started', 'game.finished', 'game.abandoned', 'turn.ended', "
    "'timer.overran', 'canvas.payload_observed', 'drawing.stored', "
    "'recap.budget_dropped'"
)


OUTCOMES = "'finished', 'abandoned', 'shutdown'"


def upgrade() -> None:
    # Added to the table, never through a rebuild. Batch mode would rebuild
    # game_records by copy, drop, rename, and that is destructive twice over:
    # DROP TABLE fires ON DELETE CASCADE and empties every child table, and the
    # rebuilt table carries SQLite's inline column CHECKs as table-level ones,
    # which makes a later DROP COLUMN of a checked column fail. Both measured.
    #
    # SQLite does allow a CHECK on ADD COLUMN, so the constraint arrives with
    # the column and sits exactly where `prompt_source_mode`'s does.
    #
    # Every game recorded until now reached its end, because a game that did
    # not never reached the writer at all. Defaulting them to 'finished' states
    # what was already true rather than guessing.
    if op.get_bind().dialect.name == "sqlite":
        op.execute(
            sa.text(
                "ALTER TABLE game_records ADD COLUMN outcome VARCHAR(16) "
                "NOT NULL DEFAULT 'finished' "
                f"CONSTRAINT ck_game_records_outcome CHECK (outcome IN ({OUTCOMES}))"
            )
        )
    else:
        op.add_column(
            "game_records",
            sa.Column(
                "outcome",
                sa.String(length=16),
                nullable=False,
                server_default=sa.text("'finished'"),
            ),
        )
        op.create_check_constraint(
            "ck_game_records_outcome", "game_records", f"outcome IN ({OUTCOMES})"
        )
    op.create_index(
        "ix_game_records_outcome_finished_at",
        "game_records",
        ["outcome", "finished_at"],
    )

    op.create_table(
        "runtime_events",
        sa.Column("id", sa.Uuid(as_uuid=True, native_uuid=True), primary_key=True),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("room_id", sa.String(length=64), nullable=True),
        sa.Column(
            "user_id",
            sa.Uuid(as_uuid=True, native_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("value", sa.Integer(), nullable=True),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.CheckConstraint(
            f"event_type IN ({EVENT_TYPES})", name="ck_runtime_events_type"
        ),
    )
    op.create_index("ix_runtime_events_user_id", "runtime_events", ["user_id"])
    op.create_index(
        "ix_runtime_events_occurred_at", "runtime_events", ["occurred_at"]
    )
    op.create_index(
        "ix_runtime_events_type_occurred",
        "runtime_events",
        ["event_type", "occurred_at"],
    )

    op.create_table(
        "runtime_stats_daily",
        sa.Column("stat_date", sa.Date(), primary_key=True),
        sa.Column("metric", sa.String(length=32), primary_key=True),
        sa.Column(
            "occurrences", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column(
            "value_sum", sa.BigInteger(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column("value_max", sa.Integer(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "occurrences >= 0 AND value_sum >= 0",
            name="ck_runtime_stats_nonnegative",
        ),
    )
    op.create_index(
        "ix_runtime_stats_daily_stat_date", "runtime_stats_daily", ["stat_date"]
    )


def downgrade() -> None:
    op.drop_index(
        "ix_runtime_stats_daily_stat_date", table_name="runtime_stats_daily"
    )
    op.drop_table("runtime_stats_daily")
    op.drop_index("ix_runtime_events_type_occurred", table_name="runtime_events")
    op.drop_index("ix_runtime_events_occurred_at", table_name="runtime_events")
    op.drop_index("ix_runtime_events_user_id", table_name="runtime_events")
    op.drop_table("runtime_events")
    op.drop_index(
        "ix_game_records_outcome_finished_at", table_name="game_records"
    )
    if op.get_bind().dialect.name != "sqlite":
        op.drop_constraint(
            "ck_game_records_outcome", "game_records", type_="check"
        )
    else:
        # As written above, the constraint rides on the column and leaves with
        # it. But any later batch rebuild of game_records re-emits it as a
        # table-level constraint, and SQLite then refuses to drop a column a
        # surviving CHECK still names - so drop it explicitly when reflection
        # can see it, whichever shape it is in by the time we downgrade.
        inspector = sa.inspect(op.get_bind())
        if any(
            constraint.get("name") == "ck_game_records_outcome"
            for constraint in inspector.get_check_constraints("game_records")
        ):
            with op.batch_alter_table("game_records") as batch_op:
                batch_op.drop_constraint("ck_game_records_outcome", type_="check")
    op.drop_column("game_records", "outcome")
