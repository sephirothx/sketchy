"""fold the correct guess into its outcome

Revision ID: a2b3c4d5e6f7
Revises: f0a1b2c3d4e5
Create Date: 2026-09-06 14:00:00.000000

A correct guess was a row of its own beside the outcome it scored, with a
surrogate key, five index structures, a link to the outcome, and a copy of
the guesser's presentation that game_participants already carries (#548).
The outcome now carries the net award (`points_awarded`, NULL on every
outcome but `correct`, held by a CHECK), and is keyed by the pair that
identified it all along, (turn_id, participant_id); turn_guesses goes. The
guess's time was already the outcome's `correct_guess_time_seconds`.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "a2b3c4d5e6f7"
down_revision: str | Sequence[str] | None = "f0a1b2c3d4e5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UTC = sa.DateTime(timezone=True)
_UUID = sa.Uuid(as_uuid=True, native_uuid=True)

_SHARED_CHECKS = (
    sa.CheckConstraint(
        "(eligible AND eligibility_reason = 'eligible' AND outcome != 'ineligible') OR "
        "(NOT eligible AND eligibility_reason != 'eligible' AND outcome = 'ineligible')",
        name="ck_turn_participant_outcomes_eligibility",
    ),
    sa.CheckConstraint(
        "(outcome = 'correct' AND correct_guess_time_seconds IS NOT NULL) OR "
        "(outcome != 'correct' AND correct_guess_time_seconds IS NULL)",
        name="ck_turn_participant_outcomes_correct_time",
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
        "terminal_state IN ('active', 'afk', 'disconnected', 'left')",
        name="ck_turn_participant_outcomes_terminal_state",
    ),
    sa.CheckConstraint(
        "wrong_guess_count >= 0 AND near_miss_count >= 0 AND hints_used >= 0 "
        "AND points_spent_on_hints >= 0",
        name="ck_turn_participant_outcomes_nonnegative",
    ),
)
_POINTS_CHECK = (
    "((outcome = 'correct') = (points_awarded IS NOT NULL)) "
    "AND (points_awarded IS NULL OR points_awarded >= 0)"
)


def _shared_columns() -> list:
    return [
        sa.Column("game_id", _UUID, nullable=False),
        sa.Column("eligible", sa.Boolean(), nullable=False),
        sa.Column("eligibility_reason", sa.String(24), nullable=False),
        sa.Column("outcome", sa.String(16), nullable=False),
        sa.Column("terminal_state", sa.String(24), nullable=False),
        sa.Column("correct_guess_time_seconds", sa.Float(), nullable=True),
        sa.Column("wrong_guess_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("near_miss_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("hints_used", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("points_spent_on_hints", sa.Integer(), server_default=sa.text("0"), nullable=False),
    ]


def _same_game_keys() -> list:
    return [
        sa.ForeignKeyConstraint(
            ["game_id", "participant_id"],
            ["game_participants.game_id", "game_participants.id"],
            name="fk_turn_participant_outcomes_seat_same_game",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["game_id", "turn_id"],
            ["turn_records.game_id", "turn_records.id"],
            name="fk_turn_participant_outcomes_turn_same_game",
            ondelete="CASCADE",
        ),
        sa.Index("ix_turn_participant_outcomes_participant_id", "participant_id"),
    ]


def _pair_keyed_table(metadata: sa.MetaData) -> sa.Table:
    """The shape this revision leaves behind."""
    return sa.Table(
        "turn_participant_outcomes",
        metadata,
        sa.Column("turn_id", _UUID, primary_key=True),
        sa.Column("participant_id", _UUID, primary_key=True),
        *_shared_columns(),
        sa.Column("points_awarded", sa.Integer(), nullable=True),
        sa.Column("created_at", _UTC, server_default=sa.func.now(), nullable=False),
        *_same_game_keys(),
        *_SHARED_CHECKS,
        sa.CheckConstraint(_POINTS_CHECK, name="ck_turn_participant_outcomes_points"),
    )


def _uuid_keyed_table(metadata: sa.MetaData) -> sa.Table:
    """The shape the baseline created, for the downgrade."""
    return sa.Table(
        "turn_participant_outcomes",
        metadata,
        sa.Column("id", _UUID, primary_key=True),
        sa.Column("turn_id", _UUID, nullable=False),
        sa.Column("participant_id", _UUID, nullable=False),
        *_shared_columns(),
        sa.Column("created_at", _UTC, server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("turn_id", "id", name="uq_turn_participant_outcomes_turn_id_id"),
        sa.UniqueConstraint(
            "turn_id", "participant_id", name="uq_turn_participant_outcomes_turn_participant"
        ),
        *_same_game_keys(),
        *_SHARED_CHECKS,
    )


def _create_turn_guesses() -> None:
    """The table the baseline created, for the downgrade."""
    op.create_table(
        "turn_guesses",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column("turn_id", _UUID, nullable=False),
        sa.Column("user_id", _UUID, nullable=True),
        sa.Column("participant_id", _UUID, nullable=True),
        sa.Column("outcome_id", _UUID, nullable=False),
        sa.Column("display_name_snapshot", sa.String(32), nullable=False),
        sa.Column("name_color_snapshot", sa.String(16), nullable=True),
        sa.Column("is_anonymous_snapshot", sa.Boolean(), nullable=False),
        sa.Column("points_awarded", sa.Integer(), nullable=False),
        sa.Column("guess_time_seconds", sa.Float(), nullable=False),
        sa.Column("created_at", _UTC, server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["participant_id"], ["game_participants.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["turn_id"], ["turn_records.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["turn_id", "outcome_id"],
            ["turn_participant_outcomes.turn_id", "turn_participant_outcomes.id"],
            name="fk_turn_guesses_outcome_same_turn",
            ondelete="CASCADE",
        ),
    )
    op.create_index("ix_turn_guesses_participant_id", "turn_guesses", ["participant_id"])
    op.create_index("ix_turn_guesses_user_id", "turn_guesses", ["user_id"])
    op.create_index("uq_turn_guesses_outcome", "turn_guesses", ["outcome_id"], unique=True)
    op.create_index(
        "uq_turn_guesses_turn_participant", "turn_guesses", ["turn_id", "participant_id"], unique=True
    )


def _rebuild_sqlite(builder) -> None:
    """A key change is a table rebuild on SQLite; the copy takes the target's
    columns from the old table, so a new column is added and filled first."""
    with op.batch_alter_table(
        "turn_participant_outcomes", copy_from=builder(sa.MetaData()), recreate="always"
    ):
        pass


def _drop_primary_key() -> None:
    name = sa.inspect(op.get_bind()).get_pk_constraint("turn_participant_outcomes")["name"]
    op.drop_constraint(name, "turn_participant_outcomes", type_="primary")


def upgrade() -> None:
    sqlite = op.get_bind().dialect.name == "sqlite"
    with op.batch_alter_table("turn_participant_outcomes") as batch:
        batch.add_column(sa.Column("points_awarded", sa.Integer(), nullable=True))
    op.execute(
        "UPDATE turn_participant_outcomes SET points_awarded = ("
        "SELECT points_awarded FROM turn_guesses "
        "WHERE turn_guesses.outcome_id = turn_participant_outcomes.id) "
        "WHERE outcome = 'correct'"
    )
    # A correct outcome that had no guess row cannot have happened under the
    # writer, which proved the two sets equal; a repaired row gets nothing.
    op.execute(
        "UPDATE turn_participant_outcomes SET points_awarded = 0 "
        "WHERE outcome = 'correct' AND points_awarded IS NULL"
    )
    op.drop_table("turn_guesses")
    if sqlite:
        _rebuild_sqlite(_pair_keyed_table)
        return
    op.drop_constraint(
        "uq_turn_participant_outcomes_turn_id_id", "turn_participant_outcomes", type_="unique"
    )
    op.drop_constraint(
        "uq_turn_participant_outcomes_turn_participant",
        "turn_participant_outcomes",
        type_="unique",
    )
    _drop_primary_key()
    op.drop_column("turn_participant_outcomes", "id")
    op.create_primary_key(
        "pk_turn_participant_outcomes", "turn_participant_outcomes", ["turn_id", "participant_id"]
    )
    op.create_check_constraint(
        "ck_turn_participant_outcomes_points", "turn_participant_outcomes", _POINTS_CHECK
    )


def downgrade() -> None:
    sqlite = op.get_bind().dialect.name == "sqlite"
    with op.batch_alter_table("turn_participant_outcomes") as batch:
        batch.add_column(sa.Column("id", _UUID, nullable=True))
    op.execute(
        "UPDATE turn_participant_outcomes SET id = lower(hex(randomblob(16)))"
        if sqlite
        else "UPDATE turn_participant_outcomes SET id = gen_random_uuid()"
    )
    if not sqlite:
        op.drop_constraint(
            "ck_turn_participant_outcomes_points", "turn_participant_outcomes", type_="check"
        )
        _drop_primary_key()
        op.alter_column("turn_participant_outcomes", "id", nullable=False)
        op.create_primary_key("turn_participant_outcomes_pkey", "turn_participant_outcomes", ["id"])
        op.create_unique_constraint(
            "uq_turn_participant_outcomes_turn_id_id", "turn_participant_outcomes", ["turn_id", "id"]
        )
        op.create_unique_constraint(
            "uq_turn_participant_outcomes_turn_participant",
            "turn_participant_outcomes",
            ["turn_id", "participant_id"],
        )
    # The guess rows are copied out before the award column goes. Fresh
    # surrogates and the seat's own presentation: the guess row never held
    # anything the outcome and the seat do not.
    _create_turn_guesses()
    op.execute(
        "INSERT INTO turn_guesses (id, turn_id, user_id, participant_id, outcome_id, "
        "display_name_snapshot, name_color_snapshot, is_anonymous_snapshot, "
        "points_awarded, guess_time_seconds, created_at) "
        "SELECT " + ("lower(hex(randomblob(16)))" if sqlite else "gen_random_uuid()") + ", "
        "o.turn_id, p.user_id, o.participant_id, o.id, p.display_name_snapshot, "
        "p.name_color_snapshot, p.is_anonymous_snapshot, o.points_awarded, "
        "o.correct_guess_time_seconds, o.created_at "
        "FROM turn_participant_outcomes o JOIN game_participants p ON p.id = o.participant_id "
        "WHERE o.outcome = 'correct'"
    )
    if sqlite:
        # Foreign keys are off for the run (see env.py), so the child could
        # be filled before its parent regained the key it points at.
        _rebuild_sqlite(_uuid_keyed_table)
    else:
        op.drop_column("turn_participant_outcomes", "points_awarded")
