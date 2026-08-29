"""natural keys where the surrogate bought nothing, one record per fact

user_blocks is keyed by its pair, identity_aliases by the merged guest,
prompt_usage_facts by the idempotency triple that was already unique, and
runtime_events - the highest-churn, thirty-day table nothing references -
by a plain integer that on SQLite is the rowid itself. turn_guesses drops
its three compatibility copies of the parent outcome's attempt/hint facts:
two records of one fact were two chances to disagree.

Revision ID: s2f6d9a4b571
Revises: r1e5c8f3a469
Create Date: 2026-08-29 00:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "s2f6d9a4b571"
down_revision: str | Sequence[str] | None = "r1e5c8f3a469"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_UTC = sa.DateTime(timezone=True)
_UUID = sa.Uuid(as_uuid=True, native_uuid=True)

RUNTIME_EVENT_TYPES = (
    "'room.created', 'room.closed', 'player.joined', 'player.left', "
    "'player.disconnected', 'player.reconnected', 'player.evicted', "
    "'game.started', 'game.finished', 'game.abandoned', 'turn.ended', "
    "'timer.overran', 'canvas.payload_observed', 'drawing.stored', "
    "'recap.budget_dropped', 'command.throttled'"
)


def _user_blocks_table(metadata: sa.MetaData, *, natural: bool) -> sa.Table:
    args = []
    if not natural:
        args.append(sa.Column("id", _UUID, primary_key=True))
    args += [
        sa.Column(
            "blocker_user_id",
            _UUID,
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=natural,
            nullable=False,
        ),
        sa.Column(
            "blocked_user_id",
            _UUID,
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=natural,
            nullable=False,
        ),
        sa.Column("created_at", _UTC, server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "blocker_user_id != blocked_user_id", name="chk_no_self_block"
        ),
        sa.Index("ix_user_blocks_blocked_user_id", "blocked_user_id"),
    ]
    if not natural:
        args += [
            sa.UniqueConstraint(
                "blocker_user_id", "blocked_user_id", name="uq_user_block"
            ),
            sa.Index("ix_user_blocks_blocker_user_id", "blocker_user_id"),
        ]
    return sa.Table("user_blocks", metadata, *args)


def _identity_aliases_table(metadata: sa.MetaData, *, natural: bool) -> sa.Table:
    args = []
    if not natural:
        args.append(sa.Column("id", _UUID, primary_key=True))
    args += [
        sa.Column(
            "source_user_id",
            _UUID,
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            primary_key=natural,
            nullable=False,
            unique=not natural,
        ),
        sa.Column(
            "target_user_id",
            _UUID,
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("created_at", _UTC, server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "source_user_id != target_user_id", name="ck_identity_alias_distinct"
        ),
        sa.Index("ix_identity_aliases_target_user_id", "target_user_id"),
    ]
    return sa.Table("identity_aliases", metadata, *args)


def _usage_facts_table(metadata: sa.MetaData, *, natural: bool) -> sa.Table:
    args = []
    if not natural:
        args.append(sa.Column("id", _UUID, primary_key=True))
    args += [
        sa.Column("batch_id", _UUID, primary_key=natural, nullable=False),
        sa.Column(
            "prompt_list_revision_id",
            _UUID,
            sa.ForeignKey("prompt_list_revisions.id", ondelete="CASCADE"),
            primary_key=natural,
            nullable=False,
        ),
        sa.Column(
            "prompt_version_id",
            _UUID,
            sa.ForeignKey("prompt_versions.id", ondelete="RESTRICT"),
            primary_key=natural,
            nullable=False,
        ),
        sa.Column("occurred_at", _UTC, nullable=False),
        sa.Column("scoring_mode", sa.String(16), nullable=False),
        sa.Column("hint_mode", sa.String(16), nullable=False),
        sa.Column(
            "offer_count", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column(
            "pick_count", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column(
            "correct_guess_count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "total_guesser_count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("created_at", _UTC, server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("offer_count >= 0", name="ck_prompt_usage_facts_offers"),
        sa.CheckConstraint("pick_count >= 0", name="ck_prompt_usage_facts_picks"),
        sa.CheckConstraint(
            "correct_guess_count >= 0", name="ck_prompt_usage_facts_correct_guesses"
        ),
        sa.CheckConstraint(
            "total_guesser_count >= 0", name="ck_prompt_usage_facts_total_guessers"
        ),
        sa.CheckConstraint(
            "scoring_mode IN ('default', 'pressure', 'no_scoring')",
            name="ck_prompt_usage_facts_scoring_mode",
        ),
        sa.CheckConstraint(
            "hint_mode IN ('none', 'checkpoints', 'purchase')",
            name="ck_prompt_usage_facts_hint_mode",
        ),
        sa.Index(
            "ix_prompt_usage_facts_revision_occurred_at",
            "prompt_list_revision_id",
            "occurred_at",
        ),
        sa.Index(
            "ix_prompt_usage_facts_version_occurred_at",
            "prompt_version_id",
            "occurred_at",
        ),
    ]
    if not natural:
        args += [
            sa.UniqueConstraint(
                "batch_id",
                "prompt_list_revision_id",
                "prompt_version_id",
                name="uq_prompt_usage_fact_batch_revision_version",
            ),
            sa.Index("ix_prompt_usage_facts_batch_id", "batch_id"),
        ]
    return sa.Table("prompt_usage_facts", metadata, *args)


def _runtime_events_table(metadata: sa.MetaData, *, natural: bool) -> sa.Table:
    if natural:
        id_column = sa.Column(
            "id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            primary_key=True,
            autoincrement=True,
        )
    else:
        id_column = sa.Column("id", _UUID, primary_key=True)
    return sa.Table(
        "runtime_events",
        metadata,
        id_column,
        sa.Column("event_type", sa.String(32), nullable=False),
        sa.Column(
            "occurred_at", _UTC, server_default=sa.func.now(), nullable=False
        ),
        sa.Column("room_id", sa.String(64), nullable=True),
        sa.Column(
            "user_id",
            _UUID,
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("value", sa.Integer(), nullable=True),
        sa.Column("details", sa.JSON(), nullable=natural),
        sa.CheckConstraint(
            f"event_type IN ({RUNTIME_EVENT_TYPES})",
            name="ck_runtime_events_type",
        ),
        sa.Index("ix_runtime_events_occurred_at", "occurred_at"),
        sa.Index("ix_runtime_events_type_occurred", "event_type", "occurred_at"),
        sa.Index("ix_runtime_events_user_id", "user_id"),
    )


def _turn_guesses_table(metadata: sa.MetaData, *, deduped: bool) -> sa.Table:
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
        sa.Column("outcome_id", _UUID, nullable=False),
        sa.Column("display_name_snapshot", sa.String(32), nullable=False),
        sa.Column("name_color_snapshot", sa.String(16), nullable=True),
        sa.Column("is_anonymous_snapshot", sa.Boolean(), nullable=False),
        sa.Column("points_awarded", sa.Integer(), nullable=False),
        sa.Column("guess_time_seconds", sa.Float(), nullable=False),
    ]
    if not deduped:
        args += [
            sa.Column(
                "hints_used",
                sa.Integer(),
                server_default=sa.text("0"),
                nullable=False,
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
        ]
    args += [
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
        sa.ForeignKeyConstraint(
            ["turn_id", "outcome_id"],
            ["turn_participant_outcomes.turn_id", "turn_participant_outcomes.id"],
            name="fk_turn_guesses_outcome_same_turn",
            ondelete="CASCADE",
        ),
    ]
    return sa.Table("turn_guesses", metadata, *args)


def _rebuild(table_name: str, table: sa.Table) -> None:
    with op.batch_alter_table(
        table_name, copy_from=table, recreate="always"
    ):
        pass


def _drop_pk(table: str) -> None:
    inspector = sa.inspect(op.get_bind())
    name = inspector.get_pk_constraint(table)["name"]
    op.drop_constraint(name, table, type_="primary")


def _drop_unique_on(table: str, columns: list[str]) -> None:
    inspector = sa.inspect(op.get_bind())
    for constraint in inspector.get_unique_constraints(table):
        if constraint["column_names"] == columns:
            op.drop_constraint(constraint["name"], table, type_="unique")
            return
    raise RuntimeError(f"no unique constraint on {table}{columns} to drop")


def upgrade() -> None:
    op.execute("UPDATE runtime_events SET details = NULL WHERE details = '{}'")
    if op.get_bind().dialect.name == "sqlite":
        _rebuild("user_blocks", _user_blocks_table(sa.MetaData(), natural=True))
        _rebuild(
            "identity_aliases", _identity_aliases_table(sa.MetaData(), natural=True)
        )
        _rebuild(
            "prompt_usage_facts", _usage_facts_table(sa.MetaData(), natural=True)
        )
        _rebuild(
            "runtime_events", _runtime_events_table(sa.MetaData(), natural=True)
        )
        _rebuild("turn_guesses", _turn_guesses_table(sa.MetaData(), deduped=True))
    else:
        _drop_unique_on("user_blocks", ["blocker_user_id", "blocked_user_id"])
        _drop_pk("user_blocks")
        op.drop_column("user_blocks", "id")
        op.create_primary_key(
            "pk_user_blocks", "user_blocks", ["blocker_user_id", "blocked_user_id"]
        )
        op.drop_index("ix_user_blocks_blocker_user_id", table_name="user_blocks")

        _drop_unique_on("identity_aliases", ["source_user_id"])
        _drop_pk("identity_aliases")
        op.drop_column("identity_aliases", "id")
        op.create_primary_key(
            "pk_identity_aliases", "identity_aliases", ["source_user_id"]
        )

        _drop_unique_on(
            "prompt_usage_facts",
            ["batch_id", "prompt_list_revision_id", "prompt_version_id"],
        )
        _drop_pk("prompt_usage_facts")
        op.drop_column("prompt_usage_facts", "id")
        op.create_primary_key(
            "pk_prompt_usage_facts",
            "prompt_usage_facts",
            ["batch_id", "prompt_list_revision_id", "prompt_version_id"],
        )
        op.drop_index(
            "ix_prompt_usage_facts_batch_id", table_name="prompt_usage_facts"
        )

        _drop_pk("runtime_events")
        op.drop_column("runtime_events", "id")
        op.add_column(
            "runtime_events",
            sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        )
        op.create_primary_key("pk_runtime_events", "runtime_events", ["id"])
        op.alter_column(
            "runtime_events", "details", existing_type=sa.JSON(), nullable=True
        )

        op.drop_column("turn_guesses", "hints_used")
        op.drop_column("turn_guesses", "points_spent_on_hints")
        op.drop_column("turn_guesses", "wrong_guesses_before")


def downgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        # copy_from's INSERT..SELECT reads the old table, so every restored
        # column is staged (and filled) before the shape-restoring rebuild.
        with op.batch_alter_table("turn_guesses") as batch_op:
            for name in (
                "hints_used",
                "points_spent_on_hints",
                "wrong_guesses_before",
            ):
                batch_op.add_column(
                    sa.Column(
                        name,
                        sa.Integer(),
                        server_default=sa.text("0"),
                        nullable=False,
                    )
                )
        op.execute(
            "UPDATE turn_guesses SET "
            "hints_used = (SELECT o.hints_used FROM turn_participant_outcomes "
            "AS o WHERE o.id = turn_guesses.outcome_id), "
            "points_spent_on_hints = (SELECT o.points_spent_on_hints "
            "FROM turn_participant_outcomes AS o "
            "WHERE o.id = turn_guesses.outcome_id), "
            "wrong_guesses_before = (SELECT o.wrong_guess_count "
            "FROM turn_participant_outcomes AS o "
            "WHERE o.id = turn_guesses.outcome_id)"
        )
        _rebuild("turn_guesses", _turn_guesses_table(sa.MetaData(), deduped=False))

        # runtime_events swaps its integer id for a UUID: retype loosely (no
        # primary key yet), mint fresh values - the old ids carried no meaning
        # and nothing references them - then rebuild to the keyed shape.
        loose_events = _runtime_events_table(sa.MetaData(), natural=False)
        loose = sa.Table(
            "runtime_events",
            sa.MetaData(),
            *[
                sa.Column("id", _UUID, nullable=True)
                if column.name == "id"
                else column._copy()
                for column in loose_events.columns
            ],
        )
        with op.batch_alter_table(
            "runtime_events", copy_from=loose, recreate="always"
        ):
            pass
        op.execute("UPDATE runtime_events SET id = lower(hex(randomblob(16)))")
        _rebuild(
            "runtime_events", _runtime_events_table(sa.MetaData(), natural=False)
        )

        for table_name, builder in (
            ("prompt_usage_facts", _usage_facts_table),
            ("identity_aliases", _identity_aliases_table),
            ("user_blocks", _user_blocks_table),
        ):
            with op.batch_alter_table(table_name) as batch_op:
                batch_op.add_column(sa.Column("id", _UUID, nullable=True))
            op.execute(
                f"UPDATE {table_name} SET id = lower(hex(randomblob(16)))"
            )
            _rebuild(table_name, builder(sa.MetaData(), natural=False))
    else:
        op.add_column(
            "turn_guesses",
            sa.Column(
                "hints_used",
                sa.Integer(),
                server_default=sa.text("0"),
                nullable=False,
            ),
        )
        op.add_column(
            "turn_guesses",
            sa.Column(
                "points_spent_on_hints",
                sa.Integer(),
                server_default=sa.text("0"),
                nullable=False,
            ),
        )
        op.add_column(
            "turn_guesses",
            sa.Column(
                "wrong_guesses_before",
                sa.Integer(),
                server_default=sa.text("0"),
                nullable=False,
            ),
        )
        op.execute(
            "UPDATE turn_guesses SET hints_used = o.hints_used, "
            "points_spent_on_hints = o.points_spent_on_hints, "
            "wrong_guesses_before = o.wrong_guess_count "
            "FROM turn_participant_outcomes AS o "
            "WHERE turn_guesses.outcome_id = o.id"
        )

        _drop_pk("runtime_events")
        op.drop_column("runtime_events", "id")
        op.add_column(
            "runtime_events",
            sa.Column("id", _UUID, nullable=True),
        )
        op.execute("UPDATE runtime_events SET id = gen_random_uuid()")
        op.alter_column(
            "runtime_events", "id", existing_type=_UUID, nullable=False
        )
        op.create_primary_key("pk_runtime_events", "runtime_events", ["id"])
        op.alter_column(
            "runtime_events", "details", existing_type=sa.JSON(), nullable=False
        )

        _drop_pk("prompt_usage_facts")
        op.add_column(
            "prompt_usage_facts", sa.Column("id", _UUID, nullable=True)
        )
        op.execute("UPDATE prompt_usage_facts SET id = gen_random_uuid()")
        op.alter_column(
            "prompt_usage_facts", "id", existing_type=_UUID, nullable=False
        )
        op.create_primary_key("pk_prompt_usage_facts", "prompt_usage_facts", ["id"])
        op.create_unique_constraint(
            "uq_prompt_usage_fact_batch_revision_version",
            "prompt_usage_facts",
            ["batch_id", "prompt_list_revision_id", "prompt_version_id"],
        )
        op.create_index(
            "ix_prompt_usage_facts_batch_id", "prompt_usage_facts", ["batch_id"]
        )

        _drop_pk("identity_aliases")
        op.add_column("identity_aliases", sa.Column("id", _UUID, nullable=True))
        op.execute("UPDATE identity_aliases SET id = gen_random_uuid()")
        op.alter_column(
            "identity_aliases", "id", existing_type=_UUID, nullable=False
        )
        op.create_primary_key("pk_identity_aliases", "identity_aliases", ["id"])
        op.create_unique_constraint(
            "identity_aliases_source_user_id_key",
            "identity_aliases",
            ["source_user_id"],
        )

        _drop_pk("user_blocks")
        op.add_column("user_blocks", sa.Column("id", _UUID, nullable=True))
        op.execute("UPDATE user_blocks SET id = gen_random_uuid()")
        op.alter_column("user_blocks", "id", existing_type=_UUID, nullable=False)
        op.create_primary_key("pk_user_blocks", "user_blocks", ["id"])
        op.create_unique_constraint(
            "uq_user_block", "user_blocks", ["blocker_user_id", "blocked_user_id"]
        )
        op.create_index(
            "ix_user_blocks_blocker_user_id", "user_blocks", ["blocker_user_id"]
        )

    op.execute("UPDATE runtime_events SET details = '{}' WHERE details IS NULL")
