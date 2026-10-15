"""solo daily: the same five drawings for everybody, and what each player made of them

Revision ID: a5b6c7d8e9f2
Revises: f4a5b6c7d8e1
Create Date: 2026-10-15 00:00:00.000000

The Daily (#1434) is five drawings a day, the same for every player in every
language. `solo_daily_days` says whether a date has one - the row the first
two requests race for - and `solo_daily_sets` holds the five, kept forever
for the archive. `solo_daily_results` is a player's Daily for a date, written
as each drawing settles so half a Daily keeps its progress; `solo_bests` is a
player's best free run of each length. A partial index over the pool reads
only the Daily's candidates, and one more on `solo_runs` keeps a player to one
Daily per date.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "a5b6c7d8e9f2"
down_revision: str | Sequence[str] | None = "f4a5b6c7d8e1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UUID = sa.Uuid(as_uuid=True, native_uuid=True)
_JSON = sa.JSON(none_as_null=True).with_variant(
    postgresql.JSONB(none_as_null=True, astext_type=sa.Text()), "postgresql"
)
_CANDIDATE = "guesser_count >= 2 AND correct_count * 5 >= guesser_count"
_DAILY = "mode = 'daily'"


def upgrade() -> None:
    op.create_index(
        "ix_solo_pool_daily",
        "solo_pool",
        ["sample_key"],
        postgresql_where=sa.text(_CANDIDATE),
        sqlite_where=sa.text(_CANDIDATE),
    )
    op.create_index(
        "uq_solo_runs_one_daily",
        "solo_runs",
        ["user_id", "daily_date"],
        unique=True,
        postgresql_where=sa.text(_DAILY),
        sqlite_where=sa.text(_DAILY),
    )
    op.create_table(
        "solo_daily_days",
        sa.Column("daily_date", sa.Date(), primary_key=True),
        sa.Column("state", sa.String(length=8), nullable=False),
        sa.Column("picked_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("state IN ('set', 'skipped')", name="ck_solo_daily_days_state"),
    )
    op.create_table(
        "solo_daily_sets",
        sa.Column(
            "daily_date",
            sa.Date(),
            sa.ForeignKey("solo_daily_days.daily_date", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("position", sa.SmallInteger(), primary_key=True),
        sa.Column(
            "turn_id", _UUID, sa.ForeignKey("turn_records.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "concept_id",
            _UUID,
            sa.ForeignKey("prompt_concepts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("solve_rate", sa.Float(), nullable=False),
        sa.Column("replaced_turn_id", _UUID, nullable=True),
        sa.Column("replaced_concept_id", _UUID, nullable=True),
        sa.Column("replaced_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("daily_date", "concept_id", name="uq_solo_daily_sets_date_concept"),
        sa.CheckConstraint("position >= 1 AND position <= 5", name="ck_solo_daily_sets_position"),
    )
    op.create_index("ix_solo_daily_sets_turn_id", "solo_daily_sets", ["turn_id"])
    op.create_index(
        "ix_solo_daily_sets_concept_date", "solo_daily_sets", ["concept_id", "daily_date"]
    )
    op.create_table(
        "solo_daily_results",
        sa.Column(
            "user_id", _UUID, sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
        ),
        sa.Column("daily_date", sa.Date(), primary_key=True),
        sa.Column(
            "run_id", _UUID, sa.ForeignKey("solo_runs.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column("positions_played", sa.SmallInteger(), nullable=False),
        sa.Column("solved", sa.SmallInteger(), nullable=False),
        sa.Column("points", sa.Integer(), nullable=False),
        sa.Column("marks", _JSON, nullable=False),
        sa.Column("started_on_date", sa.Boolean(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "positions_played >= 0 AND positions_played <= 5 AND solved >= 0 "
            "AND solved <= positions_played AND points >= 0",
            name="ck_solo_daily_results_counts",
        ),
        sa.CheckConstraint(
            "(completed_at IS NOT NULL) = (positions_played = 5)",
            name="ck_solo_daily_results_completed",
        ),
    )
    op.create_index("ix_solo_daily_results_run_id", "solo_daily_results", ["run_id"])
    op.create_table(
        "solo_bests",
        sa.Column(
            "user_id", _UUID, sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
        ),
        sa.Column("length_key", sa.String(length=12), primary_key=True),
        sa.Column("best", sa.Integer(), nullable=False),
        sa.Column(
            "run_id", _UUID, sa.ForeignKey("solo_runs.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column("achieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "length_key IN ('5', '10', 'unlimited')", name="ck_solo_bests_length_key"
        ),
        sa.CheckConstraint("best >= 0", name="ck_solo_bests_best"),
    )
    op.create_index("ix_solo_bests_run_id", "solo_bests", ["run_id"])


def downgrade() -> None:
    op.drop_index("ix_solo_bests_run_id", table_name="solo_bests")
    op.drop_table("solo_bests")
    op.drop_index("ix_solo_daily_results_run_id", table_name="solo_daily_results")
    op.drop_table("solo_daily_results")
    op.drop_index("ix_solo_daily_sets_concept_date", table_name="solo_daily_sets")
    op.drop_index("ix_solo_daily_sets_turn_id", table_name="solo_daily_sets")
    op.drop_table("solo_daily_sets")
    op.drop_table("solo_daily_days")
    op.drop_index("uq_solo_runs_one_daily", table_name="solo_runs")
    op.drop_index("ix_solo_pool_daily", table_name="solo_pool")
