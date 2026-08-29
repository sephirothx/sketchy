"""drop legacy row accommodations

There is no production deployment and no data predating any feature: every
"nullable only for legacy rows" column, every `legacy_unknown` sentinel, and
every default that existed to describe rows written before some capability
shipped now describes data that cannot exist. This tightens the schema to
what current writers actually produce, before a first deployment freezes the
accommodations in place for ever.

Revision ID: p8c3a6d9e147
Revises: n7e2f5b8c934
Create Date: 2026-08-29 00:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "p8c3a6d9e147"
down_revision: str | Sequence[str] | None = "n7e2f5b8c934"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


PROMPT_SOURCE_KINDS = "'curated', 'custom', 'builtin_fallback'"
PROMPT_SOURCE_KINDS_LEGACY = f"'legacy_unknown', {PROMPT_SOURCE_KINDS}"
GAME_PROMPT_SOURCE_MODES = "'curated', 'custom', 'mixed', 'builtin_fallback'"
GAME_PROMPT_SOURCE_MODES_LEGACY = f"'legacy_unknown', {GAME_PROMPT_SOURCE_MODES}"
TURN_PARTICIPANT_STATES = "'active', 'afk', 'disconnected', 'left'"
TURN_PARTICIPANT_STATES_LEGACY = f"{TURN_PARTICIPANT_STATES}, 'legacy_unknown'"

_UTC = sa.DateTime(timezone=True)
_UUID = sa.Uuid(as_uuid=True, native_uuid=True)


def _turn_records_desired(metadata: sa.MetaData) -> sa.Table:
    """The full post-migration shape of turn_records.

    Spelled out rather than reflected because two of its foreign keys were
    added with inline ``ALTER TABLE ... ADD COLUMN ... REFERENCES``, whose
    ``ON DELETE`` SQLite reflection loses - a plain batch rebuild would
    silently strip them. ``copy_from`` bypasses reflection entirely.
    """
    return sa.Table(
        "turn_records",
        metadata,
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
        sa.Column(
            "drawer_participant_id",
            _UUID,
            sa.ForeignKey(
                "game_participants.id",
                ondelete="CASCADE",
                name="fk_turn_records_drawer_participant_id_game_participants",
            ),
            nullable=False,
        ),
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
            "guesser_count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
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
        sa.Column(
            "created_at", _UTC, server_default=sa.func.now(), nullable=False
        ),
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
    )


def _turn_guesses_desired(metadata: sa.MetaData) -> sa.Table:
    """The full post-migration shape of turn_guesses (see _turn_records_desired)."""
    return sa.Table(
        "turn_guesses",
        metadata,
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
        sa.Column(
            "outcome_id",
            _UUID,
            sa.ForeignKey(
                "turn_participant_outcomes.id",
                ondelete="CASCADE",
                name="fk_turn_guesses_outcome_id_turn_participant_outcomes",
            ),
            nullable=False,
        ),
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
        sa.Column(
            "created_at", _UTC, server_default=sa.func.now(), nullable=False
        ),
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
    )


_LEGACY_ROW_PROBES: tuple[tuple[str, str], ...] = (
    ("app_config", "created_at IS NULL OR updated_at IS NULL"),
    (
        "game_records",
        "persisted_at IS NULL OR prompt_source_mode = 'legacy_unknown'",
    ),
    ("game_participants", "created_at IS NULL"),
    (
        "turn_records",
        "created_at IS NULL OR drawer_participant_id IS NULL "
        "OR prompt_source_kind = 'legacy_unknown'",
    ),
    (
        "turn_participant_outcomes",
        "created_at IS NULL OR terminal_state = 'legacy_unknown'",
    ),
    ("turn_guesses", "created_at IS NULL OR outcome_id IS NULL"),
    (
        "prompts",
        "created_at IS NULL OR concept_id IS NULL OR prompt_version_id IS NULL",
    ),
    (
        "prompt_usage_facts",
        "occurred_at IS NULL OR scoring_mode IS NULL OR hint_mode IS NULL",
    ),
)


def _refuse_legacy_rows() -> None:
    """Refuse, rather than convert, rows the tightened schema cannot hold.

    Filling a null write time or renaming a `legacy_unknown` would fabricate
    exactly the metadata the sentinels existed to avoid fabricating, and
    deleting the rows would be this migration deciding what history is worth.
    This revision assumes a pre-production database; one that actually holds
    such rows predates the v1 baseline and should be rebuilt (see
    docs/database.md, "Pre-v1 note") rather than upgraded through this.
    """
    bind = op.get_bind()
    found = []
    for table, condition in _LEGACY_ROW_PROBES:
        count = bind.execute(
            sa.text(f"SELECT COUNT(*) FROM {table} WHERE {condition}")
        ).scalar()
        if count:
            found.append(f"{table}: {count} rows where {condition}")
    if found:
        raise RuntimeError(
            "cannot tighten the schema over pre-feature rows; rebuild this "
            "pre-production database instead of upgrading it (docs/database.md, "
            "Pre-v1 note). Offending rows - " + "; ".join(found)
        )


def upgrade() -> None:
    sqlite = op.get_bind().dialect.name == "sqlite"
    _refuse_legacy_rows()

    with op.batch_alter_table("app_config") as batch_op:
        batch_op.alter_column("created_at", existing_type=_UTC, nullable=False)
        batch_op.alter_column("updated_at", existing_type=_UTC, nullable=False)

    with op.batch_alter_table("game_records") as batch_op:
        batch_op.alter_column("persisted_at", existing_type=_UTC, nullable=False)
        batch_op.alter_column(
            "prompt_source_mode",
            existing_type=sa.String(24),
            server_default=None,
            existing_server_default=sa.text("'legacy_unknown'"),
        )
        batch_op.drop_constraint("ck_game_records_prompt_source_mode", type_="check")
        batch_op.create_check_constraint(
            "ck_game_records_prompt_source_mode",
            f"prompt_source_mode IN ({GAME_PROMPT_SOURCE_MODES})",
        )

    with op.batch_alter_table("game_participants") as batch_op:
        batch_op.alter_column("created_at", existing_type=_UTC, nullable=False)

    with op.batch_alter_table("turn_participant_outcomes") as batch_op:
        batch_op.alter_column("created_at", existing_type=_UTC, nullable=False)
        batch_op.drop_constraint(
            "ck_turn_participant_outcomes_terminal_state", type_="check"
        )
        batch_op.create_check_constraint(
            "ck_turn_participant_outcomes_terminal_state",
            f"terminal_state IN ({TURN_PARTICIPANT_STATES})",
        )

    with op.batch_alter_table("prompts") as batch_op:
        batch_op.alter_column("concept_id", existing_type=_UUID, nullable=False)
        batch_op.alter_column(
            "prompt_version_id", existing_type=_UUID, nullable=False
        )
        batch_op.alter_column("created_at", existing_type=_UTC, nullable=False)

    with op.batch_alter_table("prompt_usage_facts") as batch_op:
        batch_op.alter_column("occurred_at", existing_type=_UTC, nullable=False)
        batch_op.alter_column(
            "scoring_mode", existing_type=sa.String(16), nullable=False
        )
        batch_op.alter_column(
            "hint_mode", existing_type=sa.String(16), nullable=False
        )

    if sqlite:
        with op.batch_alter_table(
            "turn_records",
            copy_from=_turn_records_desired(sa.MetaData()),
            recreate="always",
        ):
            pass
        # The rebuild gives SQLite the real ck_turn_records_prompt_identity
        # the models have always declared (PostgreSQL had it from the start;
        # SQLite enforced it with these triggers because adding a table check
        # then meant a rebuild). The rebuild's DROP TABLE removed them with
        # the old table; say so explicitly rather than relying on that.
        op.execute(
            "DROP TRIGGER IF EXISTS trg_turn_records_prompt_identity_insert"
        )
        op.execute(
            "DROP TRIGGER IF EXISTS trg_turn_records_prompt_identity_update"
        )
        with op.batch_alter_table(
            "turn_guesses",
            copy_from=_turn_guesses_desired(sa.MetaData()),
            recreate="always",
        ):
            pass
    else:
        op.alter_column(
            "turn_records", "created_at", existing_type=_UTC, nullable=False
        )
        op.alter_column(
            "turn_records",
            "drawer_participant_id",
            existing_type=_UUID,
            nullable=False,
        )
        op.alter_column(
            "turn_records",
            "prompt_source_kind",
            existing_type=sa.String(24),
            server_default=None,
            existing_server_default=sa.text("'legacy_unknown'"),
        )
        op.drop_constraint(
            "fk_turn_records_drawer_participant_id_game_participants",
            "turn_records",
            type_="foreignkey",
        )
        op.create_foreign_key(
            "fk_turn_records_drawer_participant_id_game_participants",
            "turn_records",
            "game_participants",
            ["drawer_participant_id"],
            ["id"],
            ondelete="CASCADE",
        )
        op.drop_constraint(
            "ck_turn_records_prompt_source_kind", "turn_records", type_="check"
        )
        op.create_check_constraint(
            "ck_turn_records_prompt_source_kind",
            "turn_records",
            f"prompt_source_kind IN ({PROMPT_SOURCE_KINDS})",
        )
        op.alter_column(
            "turn_guesses", "created_at", existing_type=_UTC, nullable=False
        )
        op.alter_column(
            "turn_guesses", "outcome_id", existing_type=_UUID, nullable=False
        )


def downgrade() -> None:
    sqlite = op.get_bind().dialect.name == "sqlite"

    if sqlite:
        # Restore the exact pre-tightening SQLite shape: nullable legacy
        # columns, the legacy source-kind value set, no table-level identity
        # check, and the two triggers that enforced identity in its place -
        # so every older downgrade below this one still sees the schema it
        # was written against.
        loosened_turns = _turn_records_desired(sa.MetaData())
        loosened_turns.columns["created_at"].nullable = True
        loosened_turns.columns["drawer_participant_id"].nullable = True
        loosened_turns.columns["prompt_source_kind"].server_default = sa.DefaultClause(
            "legacy_unknown"
        )
        for constraint in list(loosened_turns.constraints):
            if constraint.name in (
                "ck_turn_records_prompt_identity",
                "ck_turn_records_prompt_source_kind",
            ):
                loosened_turns.constraints.discard(constraint)
        sa.CheckConstraint(
            f"prompt_source_kind IN ({PROMPT_SOURCE_KINDS_LEGACY})",
            name="ck_turn_records_prompt_source_kind",
            table=loosened_turns,
        )
        with op.batch_alter_table(
            "turn_records", copy_from=loosened_turns, recreate="always"
        ):
            pass
        identity_check = (
            "(NEW.prompt_source_kind = 'curated' "
            "AND NEW.prompt_version_id IS NOT NULL) "
            "OR (NEW.prompt_source_kind != 'curated' "
            "AND NEW.prompt_version_id IS NULL)"
        )
        op.execute(
            "CREATE TRIGGER trg_turn_records_prompt_identity_insert "
            "BEFORE INSERT ON turn_records FOR EACH ROW WHEN NOT ("
            f"{identity_check}) "
            "BEGIN SELECT RAISE(ABORT, 'ck_turn_records_prompt_identity'); END"
        )
        op.execute(
            "CREATE TRIGGER trg_turn_records_prompt_identity_update "
            "BEFORE UPDATE OF prompt_source_kind, prompt_version_id "
            "ON turn_records FOR EACH ROW WHEN NOT ("
            f"{identity_check}) "
            "BEGIN SELECT RAISE(ABORT, 'ck_turn_records_prompt_identity'); END"
        )
        loosened_guesses = _turn_guesses_desired(sa.MetaData())
        loosened_guesses.columns["created_at"].nullable = True
        loosened_guesses.columns["outcome_id"].nullable = True
        with op.batch_alter_table(
            "turn_guesses", copy_from=loosened_guesses, recreate="always"
        ):
            pass
    else:
        op.alter_column(
            "turn_guesses", "outcome_id", existing_type=_UUID, nullable=True
        )
        op.alter_column(
            "turn_guesses", "created_at", existing_type=_UTC, nullable=True
        )
        op.drop_constraint(
            "ck_turn_records_prompt_source_kind", "turn_records", type_="check"
        )
        op.create_check_constraint(
            "ck_turn_records_prompt_source_kind",
            "turn_records",
            f"prompt_source_kind IN ({PROMPT_SOURCE_KINDS_LEGACY})",
        )
        op.drop_constraint(
            "fk_turn_records_drawer_participant_id_game_participants",
            "turn_records",
            type_="foreignkey",
        )
        op.create_foreign_key(
            "fk_turn_records_drawer_participant_id_game_participants",
            "turn_records",
            "game_participants",
            ["drawer_participant_id"],
            ["id"],
            ondelete="SET NULL",
        )
        op.alter_column(
            "turn_records",
            "prompt_source_kind",
            existing_type=sa.String(24),
            server_default=sa.text("'legacy_unknown'"),
        )
        op.alter_column(
            "turn_records",
            "drawer_participant_id",
            existing_type=_UUID,
            nullable=True,
        )
        op.alter_column(
            "turn_records", "created_at", existing_type=_UTC, nullable=True
        )

    with op.batch_alter_table("prompt_usage_facts") as batch_op:
        batch_op.alter_column("hint_mode", existing_type=sa.String(16), nullable=True)
        batch_op.alter_column(
            "scoring_mode", existing_type=sa.String(16), nullable=True
        )
        batch_op.alter_column("occurred_at", existing_type=_UTC, nullable=True)

    with op.batch_alter_table("prompts") as batch_op:
        batch_op.alter_column("created_at", existing_type=_UTC, nullable=True)
        batch_op.alter_column(
            "prompt_version_id", existing_type=_UUID, nullable=True
        )
        batch_op.alter_column("concept_id", existing_type=_UUID, nullable=True)

    with op.batch_alter_table("turn_participant_outcomes") as batch_op:
        batch_op.drop_constraint(
            "ck_turn_participant_outcomes_terminal_state", type_="check"
        )
        batch_op.create_check_constraint(
            "ck_turn_participant_outcomes_terminal_state",
            f"terminal_state IN ({TURN_PARTICIPANT_STATES_LEGACY})",
        )
        batch_op.alter_column("created_at", existing_type=_UTC, nullable=True)

    with op.batch_alter_table("game_participants") as batch_op:
        batch_op.alter_column("created_at", existing_type=_UTC, nullable=True)

    with op.batch_alter_table("game_records") as batch_op:
        batch_op.drop_constraint("ck_game_records_prompt_source_mode", type_="check")
        batch_op.create_check_constraint(
            "ck_game_records_prompt_source_mode",
            f"prompt_source_mode IN ({GAME_PROMPT_SOURCE_MODES_LEGACY})",
        )
        batch_op.alter_column(
            "prompt_source_mode",
            existing_type=sa.String(24),
            server_default=sa.text("'legacy_unknown'"),
        )
        batch_op.alter_column("persisted_at", existing_type=_UTC, nullable=True)

    with op.batch_alter_table("app_config") as batch_op:
        batch_op.alter_column("updated_at", existing_type=_UTC, nullable=True)
        batch_op.alter_column("created_at", existing_type=_UTC, nullable=True)
