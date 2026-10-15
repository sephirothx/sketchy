"""solo runs: what Solo keeps of a run, and each drawing it served

Revision ID: f4a5b6c7d8e1
Revises: e3f4a5b6c7d0
Create Date: 2026-10-15 00:00:00.000000

Solo (#1434) is played in the browser; the server keeps the run. `solo_runs`
is one player's free run or Daily - at most one free run active per player,
by a partial unique index - and `solo_serves` each drawing it served, under
an id of its own: the only id the client sees, since a turn id would open the
drawing's Gallery entry and name its drawer.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "f4a5b6c7d8e1"
down_revision: str | Sequence[str] | None = "e3f4a5b6c7d0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UUID = sa.Uuid(as_uuid=True, native_uuid=True)
_ACTIVE_FREE = "state = 'active' AND mode = 'free'"


def upgrade() -> None:
    op.create_table(
        "solo_runs",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column("user_id", _UUID, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("mode", sa.String(length=8), nullable=False),
        sa.Column("length", sa.SmallInteger(), nullable=True),
        sa.Column("daily_date", sa.Date(), nullable=True),
        sa.Column("state", sa.String(length=12), nullable=False),
        sa.Column("end_reason", sa.String(length=12), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("solved", sa.Integer(), nullable=False),
        sa.Column("points", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("mode IN ('free', 'daily')", name="ck_solo_runs_mode"),
        sa.CheckConstraint("state IN ('active', 'ended', 'abandoned')", name="ck_solo_runs_state"),
        sa.CheckConstraint(
            "end_reason IS NULL OR end_reason IN ('completed', 'missed', 'abandoned')",
            name="ck_solo_runs_end_reason",
        ),
        sa.CheckConstraint("length IS NULL OR length IN (5, 10)", name="ck_solo_runs_length"),
        sa.CheckConstraint(
            "(mode = 'daily') = (daily_date IS NOT NULL) AND (mode <> 'daily' OR length = 5)",
            name="ck_solo_runs_daily",
        ),
        sa.CheckConstraint(
            "(state = 'active') = (ended_at IS NULL) AND (state = 'active') = (end_reason IS NULL)",
            name="ck_solo_runs_ended",
        ),
        sa.CheckConstraint(
            "position >= 0 AND solved >= 0 AND solved <= position AND points >= 0",
            name="ck_solo_runs_counts",
        ),
    )
    op.create_index(
        "uq_solo_runs_one_active_free",
        "solo_runs",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text(_ACTIVE_FREE),
        sqlite_where=sa.text(_ACTIVE_FREE),
    )
    op.create_index("ix_solo_runs_user_mode", "solo_runs", ["user_id", "mode", "length"])
    op.create_table(
        "solo_serves",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column(
            "run_id", _UUID, sa.ForeignKey("solo_runs.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("user_id", _UUID, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "turn_id", _UUID, sa.ForeignKey("turn_records.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("position", sa.SmallInteger(), nullable=False),
        sa.Column("prompt", sa.String(length=64), nullable=False),
        sa.Column("prompt_language", sa.String(length=8), nullable=False),
        sa.Column("forms", sa.Text(), nullable=False),
        sa.Column("served_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("settled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("outcome", sa.String(length=12), nullable=True),
        sa.Column("solve_seconds", sa.Float(), nullable=True),
        sa.Column("points", sa.Integer(), nullable=True),
        sa.UniqueConstraint("run_id", "position", name="uq_solo_serves_run_position"),
        sa.CheckConstraint(
            "outcome IS NULL OR outcome IN ('solved', 'given_up', 'timed_out')",
            name="ck_solo_serves_outcome",
        ),
        sa.CheckConstraint(
            "(outcome IS NULL) = (settled_at IS NULL)", name="ck_solo_serves_settled"
        ),
        sa.CheckConstraint(
            "(outcome = 'solved') = (points IS NOT NULL) "
            "AND (outcome IS NULL OR solve_seconds IS NOT NULL) "
            "AND (points IS NULL OR (points >= 100 AND points <= 300))",
            name="ck_solo_serves_points",
        ),
        sa.CheckConstraint("position >= 1", name="ck_solo_serves_position"),
    )
    op.create_index("ix_solo_serves_user_turn", "solo_serves", ["user_id", "turn_id"])
    op.create_index("ix_solo_serves_turn_id", "solo_serves", ["turn_id"])


def downgrade() -> None:
    op.drop_index("ix_solo_serves_turn_id", table_name="solo_serves")
    op.drop_index("ix_solo_serves_user_turn", table_name="solo_serves")
    op.drop_table("solo_serves")
    op.drop_index("ix_solo_runs_user_mode", table_name="solo_runs")
    op.drop_index("uq_solo_runs_one_active_free", table_name="solo_runs")
    op.drop_table("solo_runs")
