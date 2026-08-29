"""same-game coherence for the history graph

Every cross-row reference in the finished-game graph becomes checkable:
score events cannot award to a seat, charge a turn, or correct an entry
belonging to another game; an outcome's turn and seat must share a game
(turn_participant_outcomes gains a denormalized game_id precisely so that
is expressible); and a guess's outcome must belong to the guess's turn.
The writer already proved all of this transactionally - these constraints
make a second writer, a repair script, or a partial restore unable to
disagree with it silently.

Revision ID: r1e5c8f3a469
Revises: q9d4b7e2f358
Create Date: 2026-08-29 00:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "r1e5c8f3a469"
down_revision: str | Sequence[str] | None = "q9d4b7e2f358"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_UTC = sa.DateTime(timezone=True)
_UUID = sa.Uuid(as_uuid=True, native_uuid=True)

PROMPT_SOURCE_KINDS = "'curated', 'custom', 'builtin_fallback'"


def _turn_records_table(metadata: sa.MetaData, *, coherent: bool) -> sa.Table:
    """turn_records, with (coherent=True) or without the same-game drawer FK.

    Spelled out because SQLite reflection loses the ON DELETE of inline-added
    foreign keys, so a plain batch rebuild would silently strip them;
    ``copy_from`` bypasses reflection (see p8c3a6d9e147 for the precedent).
    """
    args = [
        sa.Column("id", _UUID, primary_key=True),
        sa.Column(
            "game_id",
            _UUID,
            sa.ForeignKey("game_records.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("round_number", sa.Integer(), nullable=False),
        sa.Column("turn_number", sa.Integer(), nullable=False),
        sa.Column(
            "drawer_user_id",
            _UUID,
            sa.ForeignKey(
                "users.id",
                ondelete="SET NULL",
                name="fk_turn_records_drawer_user_id_users_set_null",
            ),
            nullable=True,
        ),
    ]
    if coherent:
        args.append(sa.Column("drawer_participant_id", _UUID, nullable=False))
    else:
        args.append(
            sa.Column(
                "drawer_participant_id",
                _UUID,
                sa.ForeignKey(
                    "game_participants.id",
                    ondelete="CASCADE",
                    name="fk_turn_records_drawer_participant_id_game_participants",
                ),
                nullable=False,
            )
        )
    args += [
        sa.Column("drawer_display_name_snapshot", sa.String(32), nullable=False),
        sa.Column("drawer_name_color_snapshot", sa.String(16), nullable=True),
        sa.Column("drawer_is_anonymous_snapshot", sa.Boolean(), nullable=False),
        sa.Column("prompt", sa.String(64), nullable=False),
        sa.Column(
            "prompt_version_id",
            _UUID,
            sa.ForeignKey(
                "prompt_versions.id",
                ondelete="RESTRICT",
                name="fk_turn_records_prompt_version_id_prompt_versions",
            ),
            nullable=True,
        ),
        sa.Column("prompt_source_kind", sa.String(24), nullable=False),
        sa.Column("duration_seconds", sa.Float(), nullable=False),
        sa.Column(
            "guesser_count", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column(
            "prompt_auto_picked",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
        sa.Column(
            "stroke_count", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column(
            "end_reason",
            sa.String(16),
            server_default=sa.text("'timeout'"),
            nullable=False,
        ),
        sa.Column(
            "wrong_guess_count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "near_miss_count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("created_at", _UTC, server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "end_reason IN ('all_guessed', 'timeout')",
            name="ck_turn_records_end_reason",
        ),
        sa.CheckConstraint(
            f"prompt_source_kind IN ({PROMPT_SOURCE_KINDS})",
            name="ck_turn_records_prompt_source_kind",
        ),
        sa.CheckConstraint(
            "(prompt_source_kind = 'curated' AND prompt_version_id IS NOT NULL) "
            "OR (prompt_source_kind != 'curated' AND prompt_version_id IS NULL)",
            name="ck_turn_records_prompt_identity",
        ),
        sa.CheckConstraint("duration_seconds > 0", name="ck_turn_records_duration"),
        sa.CheckConstraint(
            "round_number >= 1 AND turn_number >= 1 AND guesser_count >= 0 "
            "AND wrong_guess_count >= 0 AND near_miss_count >= 0 "
            "AND stroke_count >= 0",
            name="ck_turn_records_counts_nonnegative",
        ),
        sa.Index(
            "uq_turn_records_game_round_turn",
            "game_id",
            "round_number",
            "turn_number",
            unique=True,
        ),
        sa.Index("ix_turn_records_game_id", "game_id"),
        sa.Index("ix_turn_records_drawer_user_id", "drawer_user_id"),
        sa.Index("ix_turn_records_drawer_participant_id", "drawer_participant_id"),
        sa.Index("ix_turn_records_prompt_version_id", "prompt_version_id"),
    ]
    if coherent:
        args += [
            sa.UniqueConstraint("game_id", "id", name="uq_turn_records_game_id_id"),
            sa.ForeignKeyConstraint(
                ["game_id", "drawer_participant_id"],
                ["game_participants.game_id", "game_participants.id"],
                name="fk_turn_records_drawer_seat_same_game",
                ondelete="CASCADE",
            ),
        ]
    return sa.Table("turn_records", metadata, *args)


def _turn_guesses_table(metadata: sa.MetaData, *, coherent: bool) -> sa.Table:
    args = [
        sa.Column("id", _UUID, primary_key=True),
        sa.Column(
            "turn_id",
            _UUID,
            sa.ForeignKey("turn_records.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            _UUID,
            sa.ForeignKey(
                "users.id",
                ondelete="SET NULL",
                name="fk_turn_guesses_user_id_users_set_null",
            ),
            nullable=True,
        ),
        sa.Column(
            "participant_id",
            _UUID,
            sa.ForeignKey(
                "game_participants.id",
                ondelete="SET NULL",
                name="fk_turn_guesses_participant_id_game_participants",
            ),
            nullable=True,
        ),
    ]
    if coherent:
        args.append(sa.Column("outcome_id", _UUID, nullable=False))
    else:
        args.append(
            sa.Column(
                "outcome_id",
                _UUID,
                sa.ForeignKey(
                    "turn_participant_outcomes.id",
                    ondelete="CASCADE",
                    name="fk_turn_guesses_outcome_id_turn_participant_outcomes",
                ),
                nullable=False,
            )
        )
    args += [
        sa.Column("display_name_snapshot", sa.String(32), nullable=False),
        sa.Column("name_color_snapshot", sa.String(16), nullable=True),
        sa.Column("is_anonymous_snapshot", sa.Boolean(), nullable=False),
        sa.Column("points_awarded", sa.Integer(), nullable=False),
        sa.Column("guess_time_seconds", sa.Float(), nullable=False),
        sa.Column(
            "hints_used", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column(
            "points_spent_on_hints",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "wrong_guesses_before",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("created_at", _UTC, server_default=sa.func.now(), nullable=False),
        sa.Index(
            "uq_turn_guesses_turn_participant",
            "turn_id",
            "participant_id",
            unique=True,
        ),
        sa.Index("uq_turn_guesses_outcome", "outcome_id", unique=True),
        sa.Index("ix_turn_guesses_turn_id", "turn_id"),
        sa.Index("ix_turn_guesses_user_id", "user_id"),
        sa.Index("ix_turn_guesses_participant_id", "participant_id"),
    ]
    if coherent:
        args.append(
            sa.ForeignKeyConstraint(
                ["turn_id", "outcome_id"],
                [
                    "turn_participant_outcomes.turn_id",
                    "turn_participant_outcomes.id",
                ],
                name="fk_turn_guesses_outcome_same_turn",
                ondelete="CASCADE",
            )
        )
    return sa.Table("turn_guesses", metadata, *args)


def _outcomes_table(metadata: sa.MetaData, *, coherent: bool) -> sa.Table:
    args = [
        sa.Column("id", _UUID, primary_key=True),
    ]
    if coherent:
        args += [
            sa.Column("game_id", _UUID, nullable=False),
            sa.Column("turn_id", _UUID, nullable=False),
            sa.Column("participant_id", _UUID, nullable=False),
        ]
    else:
        args += [
            sa.Column(
                "turn_id",
                _UUID,
                sa.ForeignKey("turn_records.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "participant_id",
                _UUID,
                sa.ForeignKey("game_participants.id", ondelete="CASCADE"),
                nullable=False,
            ),
        ]
    args += [
        sa.Column("eligible", sa.Boolean(), nullable=False),
        sa.Column("eligibility_reason", sa.String(24), nullable=False),
        sa.Column("outcome", sa.String(16), nullable=False),
        sa.Column("terminal_state", sa.String(24), nullable=False),
        sa.Column("correct_guess_time_seconds", sa.Float(), nullable=True),
        sa.Column(
            "wrong_guess_count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "near_miss_count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "hints_used", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column(
            "points_spent_on_hints",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("created_at", _UTC, server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint(
            "turn_id",
            "participant_id",
            name="uq_turn_participant_outcomes_turn_participant",
        ),
        sa.CheckConstraint(
            "eligibility_reason IN "
            "('eligible', 'afk', 'disconnected', 'joined_late')",
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
        sa.Index("ix_turn_participant_outcomes_turn_id", "turn_id"),
        sa.Index("ix_turn_participant_outcomes_participant_id", "participant_id"),
    ]
    if coherent:
        args += [
            sa.UniqueConstraint(
                "turn_id", "id", name="uq_turn_participant_outcomes_turn_id_id"
            ),
            sa.ForeignKeyConstraint(
                ["game_id", "turn_id"],
                ["turn_records.game_id", "turn_records.id"],
                name="fk_turn_participant_outcomes_turn_same_game",
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["game_id", "participant_id"],
                ["game_participants.game_id", "game_participants.id"],
                name="fk_turn_participant_outcomes_seat_same_game",
                ondelete="CASCADE",
            ),
        ]
    return sa.Table("turn_participant_outcomes", metadata, *args)


def _score_events_table(metadata: sa.MetaData, *, coherent: bool) -> sa.Table:
    args = [
        sa.Column("id", _UUID, primary_key=True),
        sa.Column(
            "game_id",
            _UUID,
            sa.ForeignKey("game_records.id", ondelete="CASCADE"),
            nullable=False,
        ),
    ]
    if coherent:
        args += [
            sa.Column("participant_id", _UUID, nullable=False),
            sa.Column("turn_id", _UUID, nullable=True),
        ]
    else:
        args += [
            sa.Column(
                "participant_id",
                _UUID,
                sa.ForeignKey("game_participants.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "turn_id",
                _UUID,
                sa.ForeignKey("turn_records.id", ondelete="CASCADE"),
                nullable=True,
            ),
        ]
    args += [
        sa.Column("event_order", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(24), nullable=False),
        sa.Column("points_delta", sa.Integer(), nullable=False),
        sa.Column("scoring_version", sa.Integer(), nullable=False),
        sa.Column("rule_snapshot_version", sa.Integer(), nullable=False),
    ]
    if coherent:
        args.append(sa.Column("corrects_event_id", _UUID, nullable=True))
    else:
        args.append(
            sa.Column(
                "corrects_event_id",
                _UUID,
                sa.ForeignKey("score_events.id", ondelete="RESTRICT"),
                nullable=True,
            )
        )
    args += [
        sa.Column("created_at", _UTC, server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint(
            "game_id", "event_order", name="uq_score_events_game_order"
        ),
        sa.CheckConstraint(
            "event_type IN "
            "('guess_award', 'hint_charge', 'drawer_bonus', 'correction')",
            name="ck_score_events_event_type",
        ),
        sa.CheckConstraint("event_order > 0", name="ck_score_events_order_positive"),
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
        sa.Index("ix_score_events_game_id", "game_id"),
        sa.Index("ix_score_events_participant_id", "participant_id"),
        sa.Index("ix_score_events_turn_id", "turn_id"),
    ]
    if coherent:
        args += [
            sa.UniqueConstraint("game_id", "id", name="uq_score_events_game_id_id"),
            sa.ForeignKeyConstraint(
                ["game_id", "participant_id"],
                ["game_participants.game_id", "game_participants.id"],
                name="fk_score_events_seat_same_game",
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["game_id", "turn_id"],
                ["turn_records.game_id", "turn_records.id"],
                name="fk_score_events_turn_same_game",
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["game_id", "corrects_event_id"],
                ["score_events.game_id", "score_events.id"],
                name="fk_score_events_correction_same_game",
                ondelete="RESTRICT",
            ),
        ]
    return sa.Table("score_events", metadata, *args)


def _drop_fk_by_columns(table: str, columns: list[str]) -> None:
    """PostgreSQL: drop a foreign key by its constrained columns.

    The originals were created without explicit names, so the name is
    whatever the server generated; reflection is the honest way to find it.
    """
    inspector = sa.inspect(op.get_bind())
    for fk in inspector.get_foreign_keys(table):
        if fk["constrained_columns"] == columns:
            op.drop_constraint(fk["name"], table, type_="foreignkey")
            return
    raise RuntimeError(f"no foreign key on {table}{columns} to drop")


def _rebuild(table_name: str, builder, *, coherent: bool) -> None:
    """Rebuild one table to the builder's shape, keeping its triggers.

    A batch rebuild is DROP TABLE + rename underneath, and DROP TABLE takes
    the table's triggers with it - score_events' append-only trigger is part
    of the current schema and must survive both directions.
    """
    trigger_ddl = [
        row[0]
        for row in op.get_bind().exec_driver_sql(
            "SELECT sql FROM sqlite_master "
            "WHERE type='trigger' AND tbl_name=:t",
            {"t": table_name},
        )
        if row[0]
    ]
    with op.batch_alter_table(
        table_name,
        copy_from=builder(sa.MetaData(), coherent=coherent),
        recreate="always",
    ):
        pass
    for ddl in trigger_ddl:
        op.get_bind().exec_driver_sql(ddl)


def upgrade() -> None:
    with op.batch_alter_table("game_participants") as batch_op:
        batch_op.create_unique_constraint(
            "uq_game_participants_game_id_id", ["game_id", "id"]
        )

    if op.get_bind().dialect.name == "sqlite":
        # Two phases for outcomes: copy_from's INSERT..SELECT reads the old
        # table, so the new column must exist before the coherent rebuild.
        # Nullable here; the rebuild below makes it NOT NULL over the empty
        # table (pre-production premise, enforced by p8c3a6d9e147's guard).
        with op.batch_alter_table("turn_participant_outcomes") as batch_op:
            batch_op.add_column(sa.Column("game_id", _UUID, nullable=True))
        _rebuild("turn_records", _turn_records_table, coherent=True)
        _rebuild("score_events", _score_events_table, coherent=True)
        _rebuild("turn_participant_outcomes", _outcomes_table, coherent=True)
        _rebuild("turn_guesses", _turn_guesses_table, coherent=True)
    else:
        op.create_unique_constraint(
            "uq_turn_records_game_id_id", "turn_records", ["game_id", "id"]
        )
        op.drop_constraint(
            "fk_turn_records_drawer_participant_id_game_participants",
            "turn_records",
            type_="foreignkey",
        )
        op.create_foreign_key(
            "fk_turn_records_drawer_seat_same_game",
            "turn_records",
            "game_participants",
            ["game_id", "drawer_participant_id"],
            ["game_id", "id"],
            ondelete="CASCADE",
        )

        op.create_unique_constraint(
            "uq_score_events_game_id_id", "score_events", ["game_id", "id"]
        )
        _drop_fk_by_columns("score_events", ["participant_id"])
        _drop_fk_by_columns("score_events", ["turn_id"])
        _drop_fk_by_columns("score_events", ["corrects_event_id"])
        op.create_foreign_key(
            "fk_score_events_seat_same_game",
            "score_events",
            "game_participants",
            ["game_id", "participant_id"],
            ["game_id", "id"],
            ondelete="CASCADE",
        )
        op.create_foreign_key(
            "fk_score_events_turn_same_game",
            "score_events",
            "turn_records",
            ["game_id", "turn_id"],
            ["game_id", "id"],
            ondelete="CASCADE",
        )
        op.create_foreign_key(
            "fk_score_events_correction_same_game",
            "score_events",
            "score_events",
            ["game_id", "corrects_event_id"],
            ["game_id", "id"],
            ondelete="RESTRICT",
        )

        op.add_column(
            "turn_participant_outcomes",
            sa.Column("game_id", _UUID, nullable=False),
        )
        op.create_unique_constraint(
            "uq_turn_participant_outcomes_turn_id_id",
            "turn_participant_outcomes",
            ["turn_id", "id"],
        )
        _drop_fk_by_columns("turn_participant_outcomes", ["turn_id"])
        _drop_fk_by_columns("turn_participant_outcomes", ["participant_id"])
        op.create_foreign_key(
            "fk_turn_participant_outcomes_turn_same_game",
            "turn_participant_outcomes",
            "turn_records",
            ["game_id", "turn_id"],
            ["game_id", "id"],
            ondelete="CASCADE",
        )
        op.create_foreign_key(
            "fk_turn_participant_outcomes_seat_same_game",
            "turn_participant_outcomes",
            "game_participants",
            ["game_id", "participant_id"],
            ["game_id", "id"],
            ondelete="CASCADE",
        )

        op.drop_constraint(
            "fk_turn_guesses_outcome_id_turn_participant_outcomes",
            "turn_guesses",
            type_="foreignkey",
        )
        op.create_foreign_key(
            "fk_turn_guesses_outcome_same_turn",
            "turn_guesses",
            "turn_participant_outcomes",
            ["turn_id", "outcome_id"],
            ["turn_id", "id"],
            ondelete="CASCADE",
        )


def downgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        _rebuild("turn_guesses", _turn_guesses_table, coherent=False)
        _rebuild("turn_participant_outcomes", _outcomes_table, coherent=False)
        _rebuild("score_events", _score_events_table, coherent=False)
        _rebuild("turn_records", _turn_records_table, coherent=False)
    else:
        op.drop_constraint(
            "fk_turn_guesses_outcome_same_turn", "turn_guesses", type_="foreignkey"
        )
        op.create_foreign_key(
            "fk_turn_guesses_outcome_id_turn_participant_outcomes",
            "turn_guesses",
            "turn_participant_outcomes",
            ["outcome_id"],
            ["id"],
            ondelete="CASCADE",
        )

        op.drop_constraint(
            "fk_turn_participant_outcomes_seat_same_game",
            "turn_participant_outcomes",
            type_="foreignkey",
        )
        op.drop_constraint(
            "fk_turn_participant_outcomes_turn_same_game",
            "turn_participant_outcomes",
            type_="foreignkey",
        )
        op.drop_constraint(
            "uq_turn_participant_outcomes_turn_id_id",
            "turn_participant_outcomes",
            type_="unique",
        )
        op.create_foreign_key(
            "fk_turn_participant_outcomes_turn_id",
            "turn_participant_outcomes",
            "turn_records",
            ["turn_id"],
            ["id"],
            ondelete="CASCADE",
        )
        op.create_foreign_key(
            "fk_turn_participant_outcomes_participant_id",
            "turn_participant_outcomes",
            "game_participants",
            ["participant_id"],
            ["id"],
            ondelete="CASCADE",
        )
        op.drop_column("turn_participant_outcomes", "game_id")

        op.drop_constraint(
            "fk_score_events_correction_same_game", "score_events", type_="foreignkey"
        )
        op.drop_constraint(
            "fk_score_events_turn_same_game", "score_events", type_="foreignkey"
        )
        op.drop_constraint(
            "fk_score_events_seat_same_game", "score_events", type_="foreignkey"
        )
        op.drop_constraint(
            "uq_score_events_game_id_id", "score_events", type_="unique"
        )
        op.create_foreign_key(
            "fk_score_events_participant_id",
            "score_events",
            "game_participants",
            ["participant_id"],
            ["id"],
            ondelete="CASCADE",
        )
        op.create_foreign_key(
            "fk_score_events_turn_id",
            "score_events",
            "turn_records",
            ["turn_id"],
            ["id"],
            ondelete="CASCADE",
        )
        op.create_foreign_key(
            "fk_score_events_corrects_event_id",
            "score_events",
            "score_events",
            ["corrects_event_id"],
            ["id"],
            ondelete="RESTRICT",
        )

        op.drop_constraint(
            "fk_turn_records_drawer_seat_same_game", "turn_records", type_="foreignkey"
        )
        op.drop_constraint(
            "uq_turn_records_game_id_id", "turn_records", type_="unique"
        )
        op.create_foreign_key(
            "fk_turn_records_drawer_participant_id_game_participants",
            "turn_records",
            "game_participants",
            ["drawer_participant_id"],
            ["id"],
            ondelete="CASCADE",
        )

    with op.batch_alter_table("game_participants") as batch_op:
        batch_op.drop_constraint("uq_game_participants_game_id_id", type_="unique")
