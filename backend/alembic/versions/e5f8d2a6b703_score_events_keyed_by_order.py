"""key score_events by (game_id, event_order)

Revision ID: e5f8d2a6b703
Revises: d4e7c1f5a692
Create Date: 2026-09-06 12:00:00.000000

The ledger's natural identity is a game and the entry's place in it (#552):
the writer proves that order consecutive and every reader sorts by it. The
surrogate UUID beside it cost a primary key index and a (game_id, id)
unique index; the correction reference now names the earlier entry's order
under a same-game foreign key, and `scoring_version` /
`rule_snapshot_version`, copies of the game's columns, go with the UUID.
The append-only trigger survives the rebuild on both dialects.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "e5f8d2a6b703"
down_revision: str | Sequence[str] | None = "d4e7c1f5a692"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UTC = sa.DateTime(timezone=True)
_UUID = sa.Uuid(as_uuid=True, native_uuid=True)

_SHARED_CHECKS = (
    sa.CheckConstraint(
        "event_type IN ('guess_award', 'hint_charge', 'drawer_bonus', 'correction')",
        name="ck_score_events_event_type",
    ),
    sa.CheckConstraint("event_order > 0", name="ck_score_events_order_positive"),
    sa.CheckConstraint("points_delta != 0", name="ck_score_events_delta_nonzero"),
    sa.CheckConstraint(
        "(event_type IN ('guess_award', 'drawer_bonus') AND points_delta > 0) "
        "OR (event_type = 'hint_charge' AND points_delta < 0) "
        "OR event_type = 'correction'",
        name="ck_score_events_delta_direction",
    ),
    sa.CheckConstraint(
        "event_type = 'correction' OR turn_id IS NOT NULL",
        name="ck_score_events_turn_required",
    ),
)


def _same_game_keys() -> list:
    return [
        sa.ForeignKeyConstraint(["game_id"], ["game_records.id"], ondelete="CASCADE"),
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
        sa.Index("ix_score_events_participant_id", "participant_id"),
        sa.Index("ix_score_events_turn_id", "turn_id"),
    ]


def _order_keyed_table(metadata: sa.MetaData) -> sa.Table:
    """The shape this revision leaves behind."""
    return sa.Table(
        "score_events",
        metadata,
        sa.Column("game_id", _UUID, primary_key=True),
        sa.Column("event_order", sa.Integer(), primary_key=True),
        sa.Column("participant_id", _UUID, nullable=False),
        sa.Column("turn_id", _UUID, nullable=True),
        sa.Column("event_type", sa.String(24), nullable=False),
        sa.Column("points_delta", sa.Integer(), nullable=False),
        sa.Column("corrects_event_order", sa.Integer(), nullable=True),
        sa.Column("created_at", _UTC, server_default=sa.func.now(), nullable=False),
        *_same_game_keys(),
        sa.ForeignKeyConstraint(
            ["game_id", "corrects_event_order"],
            ["score_events.game_id", "score_events.event_order"],
            name="fk_score_events_correction_same_game",
            ondelete="RESTRICT",
        ),
        sa.Index(
            "ix_score_events_correction",
            "game_id",
            "corrects_event_order",
            sqlite_where=sa.text("corrects_event_order IS NOT NULL"),
        ),
        *_SHARED_CHECKS,
        sa.CheckConstraint(
            "(event_type = 'correction' AND corrects_event_order IS NOT NULL) OR "
            "(event_type != 'correction' AND corrects_event_order IS NULL)",
            name="ck_score_events_correction_target",
        ),
        sa.CheckConstraint(
            "corrects_event_order IS NULL OR corrects_event_order < event_order",
            name="ck_score_events_corrects_earlier",
        ),
    )


def _uuid_keyed_table(metadata: sa.MetaData) -> sa.Table:
    """The shape d4e7c1f5a692 left behind, for the downgrade."""
    return sa.Table(
        "score_events",
        metadata,
        sa.Column("id", _UUID, primary_key=True),
        sa.Column("game_id", _UUID, nullable=False),
        sa.Column("participant_id", _UUID, nullable=False),
        sa.Column("turn_id", _UUID, nullable=True),
        sa.Column("event_order", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(24), nullable=False),
        sa.Column("points_delta", sa.Integer(), nullable=False),
        sa.Column("scoring_version", sa.Integer(), nullable=False),
        sa.Column("rule_snapshot_version", sa.Integer(), nullable=False),
        sa.Column("corrects_event_id", _UUID, nullable=True),
        sa.Column("created_at", _UTC, server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("game_id", "event_order", name="uq_score_events_game_order"),
        sa.UniqueConstraint("game_id", "id", name="uq_score_events_game_id_id"),
        *_same_game_keys(),
        sa.ForeignKeyConstraint(
            ["game_id", "corrects_event_id"],
            ["score_events.game_id", "score_events.id"],
            name="fk_score_events_correction_same_game",
            ondelete="RESTRICT",
        ),
        *_SHARED_CHECKS,
        sa.CheckConstraint(
            "scoring_version >= 0 AND rule_snapshot_version >= 0",
            name="ck_score_events_versions_nonnegative",
        ),
        sa.CheckConstraint(
            "(event_type = 'correction' AND corrects_event_id IS NOT NULL) OR "
            "(event_type != 'correction' AND corrects_event_id IS NULL)",
            name="ck_score_events_correction_target",
        ),
        sa.CheckConstraint(
            "corrects_event_id IS NULL OR id != corrects_event_id",
            name="ck_score_events_not_self_correction",
        ),
    )


def _rebuild_sqlite(builder) -> None:
    """Rebuild score_events to the builder's shape, keeping its trigger.

    A batch rebuild is DROP TABLE + rename underneath, and DROP TABLE takes
    the table's triggers with it (see r1e5c8f3a469). Columns the target has
    and the source lacks must already exist and be filled: the copy is an
    INSERT ... SELECT of the target's column names from the old table.
    """
    trigger_ddl = [
        row[0]
        for row in op.get_bind().exec_driver_sql(
            "SELECT sql FROM sqlite_master WHERE type='trigger' AND tbl_name='score_events'"
        )
        if row[0]
    ]
    with op.batch_alter_table(
        "score_events", copy_from=builder(sa.MetaData()), recreate="always"
    ):
        pass
    for ddl in trigger_ddl:
        op.get_bind().exec_driver_sql(ddl)


def _drop_constraint_by_columns(columns: list[str], kind: str) -> None:
    """PostgreSQL named the original primary key and game FK itself."""
    inspector = sa.inspect(op.get_bind())
    if kind == "primary":
        name = inspector.get_pk_constraint("score_events")["name"]
        op.drop_constraint(name, "score_events", type_="primary")
        return
    for fk in inspector.get_foreign_keys("score_events"):
        if fk["constrained_columns"] == columns:
            op.drop_constraint(fk["name"], "score_events", type_="foreignkey")
            return
    raise RuntimeError(f"no foreign key on score_events{columns} to drop")


def upgrade() -> None:
    sqlite = op.get_bind().dialect.name == "sqlite"
    with op.batch_alter_table("score_events") as batch:
        batch.add_column(sa.Column("corrects_event_order", sa.Integer(), nullable=True))
    op.execute(
        "UPDATE score_events SET corrects_event_order = ("
        "SELECT corrected.event_order FROM score_events AS corrected "
        "WHERE corrected.game_id = score_events.game_id "
        "AND corrected.id = score_events.corrects_event_id) "
        "WHERE corrects_event_id IS NOT NULL"
    )
    if sqlite:
        _rebuild_sqlite(_order_keyed_table)
        return
    op.drop_constraint("fk_score_events_correction_same_game", "score_events", type_="foreignkey")
    op.drop_constraint("uq_score_events_game_id_id", "score_events", type_="unique")
    op.drop_constraint("uq_score_events_game_order", "score_events", type_="unique")
    for name in (
        "ck_score_events_not_self_correction",
        "ck_score_events_versions_nonnegative",
        "ck_score_events_correction_target",
    ):
        op.drop_constraint(name, "score_events", type_="check")
    _drop_constraint_by_columns(["id"], "primary")
    for column in ("id", "corrects_event_id", "scoring_version", "rule_snapshot_version"):
        op.drop_column("score_events", column)
    op.create_primary_key("pk_score_events", "score_events", ["game_id", "event_order"])
    op.create_foreign_key(
        "fk_score_events_correction_same_game",
        "score_events",
        "score_events",
        ["game_id", "corrects_event_order"],
        ["game_id", "event_order"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_score_events_correction",
        "score_events",
        ["game_id", "corrects_event_order"],
        postgresql_where=sa.text("corrects_event_order IS NOT NULL"),
    )
    op.create_check_constraint(
        "ck_score_events_correction_target",
        "score_events",
        "(event_type = 'correction' AND corrects_event_order IS NOT NULL) OR "
        "(event_type != 'correction' AND corrects_event_order IS NULL)",
    )
    op.create_check_constraint(
        "ck_score_events_corrects_earlier",
        "score_events",
        "corrects_event_order IS NULL OR corrects_event_order < event_order",
    )


def downgrade() -> None:
    sqlite = op.get_bind().dialect.name == "sqlite"
    with op.batch_alter_table("score_events") as batch:
        batch.add_column(sa.Column("id", _UUID, nullable=True))
        batch.add_column(sa.Column("corrects_event_id", _UUID, nullable=True))
        batch.add_column(sa.Column("scoring_version", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("rule_snapshot_version", sa.Integer(), nullable=True))
    # Fresh surrogates: the old ids were never referenced from outside the
    # ledger, and nothing that was exported under them can be matched back.
    op.execute(
        "UPDATE score_events SET id = lower(hex(randomblob(16)))"
        if sqlite
        else "UPDATE score_events SET id = gen_random_uuid()"
    )
    op.execute(
        "UPDATE score_events SET corrects_event_id = ("
        "SELECT corrected.id FROM score_events AS corrected "
        "WHERE corrected.game_id = score_events.game_id "
        "AND corrected.event_order = score_events.corrects_event_order) "
        "WHERE corrects_event_order IS NOT NULL"
    )
    op.execute(
        "UPDATE score_events SET scoring_version = ("
        "SELECT scoring_version FROM game_records WHERE game_records.id = score_events.game_id), "
        "rule_snapshot_version = ("
        "SELECT rule_snapshot_version FROM game_records WHERE game_records.id = score_events.game_id)"
    )
    if sqlite:
        _rebuild_sqlite(_uuid_keyed_table)
        return
    op.drop_index("ix_score_events_correction", table_name="score_events")
    op.drop_constraint("fk_score_events_correction_same_game", "score_events", type_="foreignkey")
    for name in ("ck_score_events_corrects_earlier", "ck_score_events_correction_target"):
        op.drop_constraint(name, "score_events", type_="check")
    op.drop_constraint("pk_score_events", "score_events", type_="primary")
    op.drop_column("score_events", "corrects_event_order")
    for column in ("id", "scoring_version", "rule_snapshot_version"):
        op.alter_column("score_events", column, nullable=False)
    op.create_primary_key("score_events_pkey", "score_events", ["id"])
    op.create_unique_constraint("uq_score_events_game_order", "score_events", ["game_id", "event_order"])
    op.create_unique_constraint("uq_score_events_game_id_id", "score_events", ["game_id", "id"])
    op.create_foreign_key(
        "fk_score_events_correction_same_game",
        "score_events",
        "score_events",
        ["game_id", "corrects_event_id"],
        ["game_id", "id"],
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        "ck_score_events_versions_nonnegative",
        "score_events",
        "scoring_version >= 0 AND rule_snapshot_version >= 0",
    )
    op.create_check_constraint(
        "ck_score_events_correction_target",
        "score_events",
        "(event_type = 'correction' AND corrects_event_id IS NOT NULL) OR "
        "(event_type != 'correction' AND corrects_event_id IS NULL)",
    )
    op.create_check_constraint(
        "ck_score_events_not_self_correction",
        "score_events",
        "corrects_event_id IS NULL OR id != corrects_event_id",
    )
