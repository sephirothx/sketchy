"""add immutable score event ledger

Revision ID: a8e2d4c6f190
Revises: f7d9c3a6b281
Create Date: 2026-08-23 00:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "a8e2d4c6f190"
down_revision: str | Sequence[str] | None = "f7d9c3a6b281"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    sqlite = op.get_bind().dialect.name == "sqlite"
    if sqlite:
        # SQLite cannot add a named table CHECK without rebuilding this parent
        # table, which would cascade-delete history children. An inline column
        # check is equivalent and preserves every existing game.
        op.execute(
            "ALTER TABLE game_records ADD COLUMN score_ledger_version INTEGER "
            "NOT NULL DEFAULT 0 CHECK (score_ledger_version >= 0)"
        )
    else:
        op.add_column(
            "game_records",
            sa.Column(
                "score_ledger_version",
                sa.Integer(),
                server_default="0",
                nullable=False,
            ),
        )
        op.create_check_constraint(
            "ck_game_records_score_ledger_version",
            "game_records",
            "score_ledger_version >= 0",
        )
    op.create_table(
        "score_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("game_id", sa.Uuid(), nullable=False),
        sa.Column("participant_id", sa.Uuid(), nullable=False),
        sa.Column("turn_id", sa.Uuid(), nullable=True),
        sa.Column("event_order", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=24), nullable=False),
        sa.Column("points_delta", sa.Integer(), nullable=False),
        sa.Column("scoring_version", sa.Integer(), nullable=False),
        sa.Column("rule_snapshot_version", sa.Integer(), nullable=False),
        sa.Column("corrects_event_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "event_type IN ('guess_award', 'hint_charge', 'drawer_bonus', 'correction')",
            name="ck_score_events_event_type",
        ),
        sa.CheckConstraint(
            "event_order > 0", name="ck_score_events_order_positive"
        ),
        sa.CheckConstraint(
            "points_delta != 0", name="ck_score_events_delta_nonzero"
        ),
        sa.CheckConstraint(
            "scoring_version >= 0 AND rule_snapshot_version >= 0",
            name="ck_score_events_versions_nonnegative",
        ),
        sa.CheckConstraint(
            "(event_type IN ('guess_award', 'drawer_bonus') AND points_delta > 0) "
            "OR (event_type = 'hint_charge' AND points_delta < 0) "
            "OR event_type = 'correction'",
            name="ck_score_events_delta_direction",
        ),
        sa.CheckConstraint(
            "(event_type = 'correction' AND corrects_event_id IS NOT NULL) OR "
            "(event_type != 'correction' AND corrects_event_id IS NULL)",
            name="ck_score_events_correction_target",
        ),
        sa.CheckConstraint(
            "event_type = 'correction' OR turn_id IS NOT NULL",
            name="ck_score_events_turn_required",
        ),
        sa.CheckConstraint(
            "corrects_event_id IS NULL OR id != corrects_event_id",
            name="ck_score_events_not_self_correction",
        ),
        sa.ForeignKeyConstraint(
            ["game_id"], ["game_records.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["participant_id"], ["game_participants.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["turn_id"], ["turn_records.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["corrects_event_id"], ["score_events.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "game_id", "event_order", name="uq_score_events_game_order"
        ),
    )
    op.create_index("ix_score_events_game_id", "score_events", ["game_id"])
    op.create_index(
        "ix_score_events_participant_id", "score_events", ["participant_id"]
    )
    op.create_index("ix_score_events_turn_id", "score_events", ["turn_id"])

    # Events are corrected by appending a correction event. Once inserted, an
    # event's reason, amount, order and rule context cannot be rewritten.
    if sqlite:
        op.execute(
            "CREATE TRIGGER trg_score_events_immutable_update "
            "BEFORE UPDATE ON score_events BEGIN "
            "SELECT RAISE(ABORT, 'score events are immutable'); END"
        )
    else:
        op.execute(
            "CREATE FUNCTION reject_score_event_update() RETURNS trigger "
            "LANGUAGE plpgsql AS $$ BEGIN "
            "RAISE EXCEPTION 'score events are immutable'; END; $$"
        )
        op.execute(
            "CREATE TRIGGER trg_score_events_immutable_update "
            "BEFORE UPDATE ON score_events FOR EACH ROW "
            "EXECUTE FUNCTION reject_score_event_update()"
        )


def downgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        op.execute("DROP TRIGGER trg_score_events_immutable_update")
    else:
        op.execute("DROP TRIGGER trg_score_events_immutable_update ON score_events")
        op.execute("DROP FUNCTION reject_score_event_update()")
    op.drop_index("ix_score_events_turn_id", table_name="score_events")
    op.drop_index("ix_score_events_participant_id", table_name="score_events")
    op.drop_index("ix_score_events_game_id", table_name="score_events")
    op.drop_table("score_events")
    if op.get_bind().dialect.name != "sqlite":
        op.drop_constraint(
            "ck_game_records_score_ledger_version",
            "game_records",
            type_="check",
        )
    op.drop_column("game_records", "score_ledger_version")
