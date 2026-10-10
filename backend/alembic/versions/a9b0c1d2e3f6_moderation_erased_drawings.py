"""moderation erasure: a drawing an administrator erased says so

Revision ID: a9b0c1d2e3f6
Revises: f8a9b0c1d2e5
Create Date: 2026-10-10 00:00:00.000000

An administrator can erase one drawing for illegal content (#1419). The bytes
go exactly as an account erasure takes them - `status` `deleted`, the payload
gone - and `turn_drawings.moderation_erased_at` records that it was a
moderation decision, so a history reads "removed by moderation" and the
report's evidence copy is held back from everybody but administrators.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "a9b0c1d2e3f6"
down_revision: str | Sequence[str] | None = "f8a9b0c1d2e5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CHECK = "moderation_erased_at IS NULL OR status = 'deleted'"


def upgrade() -> None:
    # A nullable column with no default is a catalogue change on PostgreSQL,
    # and the check is added NOT VALID and validated after, so neither holds
    # `turn_drawings` - every drawing kept - locked while its rows are read
    # (docs/database.md §13, `tests/test_online_ddl.py`).
    if op.get_context().dialect.name == "postgresql":
        op.add_column(
            "turn_drawings",
            sa.Column("moderation_erased_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.create_check_constraint(
            "ck_turn_drawings_moderation_erased",
            "turn_drawings",
            _CHECK,
            postgresql_not_valid=True,
        )
        op.execute("ALTER TABLE turn_drawings VALIDATE CONSTRAINT ck_turn_drawings_moderation_erased")
        return
    with op.batch_alter_table("turn_drawings") as batch:
        batch.add_column(
            sa.Column("moderation_erased_at", sa.DateTime(timezone=True), nullable=True)
        )
        # online-ddl: SQLite rebuilds the table in batch mode; it has no NOT VALID and holds no live deployment
        batch.create_check_constraint("ck_turn_drawings_moderation_erased", _CHECK)


def downgrade() -> None:
    if op.get_context().dialect.name == "postgresql":
        op.drop_constraint("ck_turn_drawings_moderation_erased", "turn_drawings", type_="check")
        op.drop_column("turn_drawings", "moderation_erased_at")
        return
    with op.batch_alter_table("turn_drawings") as batch:
        batch.drop_constraint("ck_turn_drawings_moderation_erased", type_="check")
        batch.drop_column("moderation_erased_at")
