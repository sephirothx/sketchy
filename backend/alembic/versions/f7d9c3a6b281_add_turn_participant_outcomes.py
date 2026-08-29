"""add complete per-turn participant outcomes

Revision ID: f7d9c3a6b281
Revises: e5c8a2b4d076
Create Date: 2026-08-23 00:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "f7d9c3a6b281"
down_revision: str | Sequence[str] | None = "e5c8a2b4d076"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "turn_participant_outcomes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("turn_id", sa.Uuid(), nullable=False),
        sa.Column("participant_id", sa.Uuid(), nullable=False),
        sa.Column("eligible", sa.Boolean(), nullable=False),
        sa.Column("eligibility_reason", sa.String(length=24), nullable=False),
        sa.Column("outcome", sa.String(length=16), nullable=False),
        sa.Column("terminal_state", sa.String(length=24), nullable=False),
        sa.Column("correct_guess_time_seconds", sa.Float(), nullable=True),
        sa.Column(
            "wrong_guess_count", sa.Integer(), server_default="0", nullable=False
        ),
        sa.Column("near_miss_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("hints_used", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "points_spent_on_hints", sa.Integer(), server_default="0", nullable=False
        ),
        # Nullable only for migration-created legacy rows. All future writes
        # receive the database clock.
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=True,
        ),
        sa.CheckConstraint(
            "eligibility_reason IN ('eligible', 'afk', 'disconnected', 'joined_late')",
            name="ck_turn_participant_outcomes_eligibility_reason",
        ),
        sa.CheckConstraint(
            "outcome IN ('correct', 'incorrect', 'no_attempt', 'ineligible')",
            name="ck_turn_participant_outcomes_outcome",
        ),
        sa.CheckConstraint(
            "terminal_state IN "
            "('active', 'afk', 'disconnected', 'left', 'legacy_unknown')",
            name="ck_turn_participant_outcomes_terminal_state",
        ),
        sa.CheckConstraint(
            "(eligible AND eligibility_reason = 'eligible' "
            "AND outcome != 'ineligible') OR "
            "(NOT eligible AND eligibility_reason != 'eligible' "
            "AND outcome = 'ineligible')",
            name="ck_turn_participant_outcomes_eligibility",
        ),
        sa.CheckConstraint(
            "(outcome = 'correct' AND correct_guess_time_seconds IS NOT NULL) OR "
            "(outcome != 'correct' AND correct_guess_time_seconds IS NULL)",
            name="ck_turn_participant_outcomes_correct_time",
        ),
        sa.CheckConstraint(
            "wrong_guess_count >= 0 AND near_miss_count >= 0 "
            "AND hints_used >= 0 AND points_spent_on_hints >= 0",
            name="ck_turn_participant_outcomes_nonnegative",
        ),
        sa.ForeignKeyConstraint(
            ["turn_id"], ["turn_records.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["participant_id"], ["game_participants.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "turn_id",
            "participant_id",
            name="uq_turn_participant_outcomes_turn_participant",
        ),
    )
    op.create_index(
        "ix_turn_participant_outcomes_turn_id",
        "turn_participant_outcomes",
        ["turn_id"],
    )
    op.create_index(
        "ix_turn_participant_outcomes_participant_id",
        "turn_participant_outcomes",
        ["participant_id"],
    )

    sqlite = op.get_bind().dialect.name == "sqlite"
    if sqlite:
        op.execute(
            "ALTER TABLE turn_guesses ADD COLUMN outcome_id CHAR(32) "
            "REFERENCES turn_participant_outcomes(id) ON DELETE CASCADE"
        )
    else:
        op.add_column(
            "turn_guesses", sa.Column("outcome_id", sa.Uuid(), nullable=True)
        )
        op.create_foreign_key(
            "fk_turn_guesses_outcome_id_turn_participant_outcomes",
            "turn_guesses",
            "turn_participant_outcomes",
            ["outcome_id"],
            ["id"],
            ondelete="CASCADE",
        )
    op.create_index(
        "uq_turn_guesses_outcome",
        "turn_guesses",
        ["outcome_id"],
        unique=True,
    )

    # A successful legacy guess proves eligibility and a correct outcome. It
    # does not prove how any non-guesser participated or the guesser's terminal
    # connection state, so no speculative rows are added for those facts.
    eligible_literal = "1" if sqlite else "TRUE"
    op.execute(
        sa.text(
            "INSERT INTO turn_participant_outcomes ("
            "id, turn_id, participant_id, eligible, eligibility_reason, outcome, "
            "terminal_state, correct_guess_time_seconds, wrong_guess_count, "
            "near_miss_count, hints_used, points_spent_on_hints, created_at"
            ") SELECT id, turn_id, participant_id, "
            f"{eligible_literal}, 'eligible', 'correct', 'legacy_unknown', "
            "guess_time_seconds, wrong_guesses_before, 0, hints_used, "
            "points_spent_on_hints, NULL FROM turn_guesses "
            "WHERE participant_id IS NOT NULL"
        )
    )
    op.execute(
        sa.text(
            "UPDATE turn_guesses SET outcome_id = id "
            "WHERE participant_id IS NOT NULL"
        )
    )


def downgrade() -> None:
    op.drop_index("uq_turn_guesses_outcome", table_name="turn_guesses")
    if op.get_bind().dialect.name != "sqlite":
        op.drop_constraint(
            "fk_turn_guesses_outcome_id_turn_participant_outcomes",
            "turn_guesses",
            type_="foreignkey",
        )
        op.drop_column("turn_guesses", "outcome_id")
    else:
        # Originally an inline REFERENCES that left with the column; a later
        # batch rebuild of turn_guesses re-emits it as a table-level FOREIGN
        # KEY clause, which a plain DROP COLUMN leaves dangling. A batch drop
        # rebuilds the table without the column and without any constraint
        # that named it.
        with op.batch_alter_table("turn_guesses") as batch_op:
            batch_op.drop_column("outcome_id")
    op.drop_index(
        "ix_turn_participant_outcomes_participant_id",
        table_name="turn_participant_outcomes",
    )
    op.drop_index(
        "ix_turn_participant_outcomes_turn_id",
        table_name="turn_participant_outcomes",
    )
    op.drop_table("turn_participant_outcomes")
