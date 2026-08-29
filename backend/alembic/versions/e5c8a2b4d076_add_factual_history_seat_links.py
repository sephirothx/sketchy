"""add factual history seat links for drawers and guessers

Revision ID: e5c8a2b4d076
Revises: d4b7f1a3c965
Create Date: 2026-08-23 00:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "e5c8a2b4d076"
down_revision: str | Sequence[str] | None = "d4b7f1a3c965"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    sqlite = op.get_bind().dialect.name == "sqlite"
    if sqlite:
        # See d4b7f1a3c965: inline additive references avoid both SQLite's
        # unsupported constraint ALTER and a destructive parent-table rebuild.
        op.execute(
            "ALTER TABLE turn_records ADD COLUMN drawer_participant_id CHAR(32) "
            "REFERENCES game_participants(id) ON DELETE SET NULL"
        )
    else:
        op.add_column(
            "turn_records",
            sa.Column("drawer_participant_id", sa.Uuid(), nullable=True),
        )
        op.create_foreign_key(
            "fk_turn_records_drawer_participant_id_game_participants",
            "turn_records",
            "game_participants",
            ["drawer_participant_id"],
            ["id"],
            ondelete="SET NULL",
        )
    op.create_index(
        "ix_turn_records_drawer_participant_id",
        "turn_records",
        ["drawer_participant_id"],
    )

    if op.get_bind().dialect.name == "sqlite":
        op.execute(
            "ALTER TABLE turn_guesses ADD COLUMN participant_id CHAR(32) "
            "REFERENCES game_participants(id) ON DELETE SET NULL"
        )
    else:
        op.add_column(
            "turn_guesses",
            sa.Column("participant_id", sa.Uuid(), nullable=True),
        )
        op.create_foreign_key(
            "fk_turn_guesses_participant_id_game_participants",
            "turn_guesses",
            "game_participants",
            ["participant_id"],
            ["id"],
            ondelete="SET NULL",
        )
    op.create_index(
        "ix_turn_guesses_participant_id", "turn_guesses", ["participant_id"]
    )

    # Existing account-linked facts have an unambiguous game/user natural key.
    # Deleted/accountless legacy facts remain null rather than guessing a seat.
    op.execute(
        sa.text(
            "UPDATE turn_records SET drawer_participant_id = ("
            "SELECT game_participants.id FROM game_participants "
            "WHERE game_participants.game_id = turn_records.game_id "
            "AND game_participants.user_id = turn_records.drawer_user_id"
            ") WHERE drawer_user_id IS NOT NULL"
        )
    )
    op.drop_index("uq_turn_guesses_turn_user", table_name="turn_guesses")
    op.create_index(
        "uq_turn_guesses_turn_participant",
        "turn_guesses",
        ["turn_id", "participant_id"],
        unique=True,
    )
    op.execute(
        sa.text(
            "UPDATE turn_guesses SET participant_id = ("
            "SELECT game_participants.id FROM game_participants "
            "JOIN turn_records ON turn_records.game_id = game_participants.game_id "
            "WHERE turn_records.id = turn_guesses.turn_id "
            "AND game_participants.user_id = turn_guesses.user_id"
            ") WHERE user_id IS NOT NULL"
        )
    )


def downgrade() -> None:
    op.drop_index(
        "uq_turn_guesses_turn_participant", table_name="turn_guesses"
    )
    op.create_index(
        "uq_turn_guesses_turn_user",
        "turn_guesses",
        ["turn_id", "user_id"],
        unique=True,
    )
    op.drop_index("ix_turn_guesses_participant_id", table_name="turn_guesses")
    if op.get_bind().dialect.name != "sqlite":
        op.drop_constraint(
            "fk_turn_guesses_participant_id_game_participants",
            "turn_guesses",
            type_="foreignkey",
        )
    # Batch, not plain: the FK arrived inline with the column, but any later
    # batch rebuild of the table re-emits it as a table-level clause that a
    # plain DROP COLUMN leaves dangling on SQLite.
    with op.batch_alter_table("turn_guesses") as batch_op:
        batch_op.drop_column("participant_id")
    op.drop_index(
        "ix_turn_records_drawer_participant_id", table_name="turn_records"
    )
    if op.get_bind().dialect.name != "sqlite":
        op.drop_constraint(
            "fk_turn_records_drawer_participant_id_game_participants",
            "turn_records",
            type_="foreignkey",
        )
    # A batch rebuild is DROP TABLE + rename underneath, and DROP TABLE
    # takes the table's triggers with it - at this point in the chain the
    # prompt-identity triggers a later revision replaced with real checks
    # have been restored by that revision's downgrade, and the next
    # downgrade below expects to drop them. Save and re-create them.
    trigger_ddl = []
    if op.get_bind().dialect.name == "sqlite":
        trigger_ddl = [
            row[0]
            for row in op.get_bind().exec_driver_sql(
                "SELECT sql FROM sqlite_master "
                "WHERE type='trigger' AND tbl_name='turn_records'"
            )
            if row[0]
        ]
    with op.batch_alter_table("turn_records") as batch_op:
        batch_op.drop_column("drawer_participant_id")
    for ddl in trigger_ddl:
        op.get_bind().exec_driver_sql(ddl)
