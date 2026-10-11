"""hidden lobby lines: a moderator hides a line, and can show it again

Revision ID: b0c1d2e3f4a7
Revises: a9b0c1d2e3f6
Create Date: 2026-10-10 00:00:00.000000

A moderator hides lobby lines a report cites (#1435): `room_messages.hidden_at`
says so, every lobby shows "This message was deleted" in the line's place,
and nobody is sent its text. A stamp rather than a deletion, because a hide
can be undone. Only a lobby line can carry it. The audit ledger gains the
target type the decision is recorded against, `lobby_message`.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "b0c1d2e3f4a7"
down_revision: str | Sequence[str] | None = "a9b0c1d2e3f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_HIDDEN = "hidden_at IS NULL OR audience = 'lobby'"
_TARGET_TYPES_BEFORE = (
    "target_type IS NULL OR target_type IN "
    "('user', 'prompt_list', 'prompt_version', 'room', 'app_config', "
    "'bug_report', 'drawing')"
)
_TARGET_TYPES_AFTER = (
    "target_type IS NULL OR target_type IN "
    "('user', 'prompt_list', 'prompt_version', 'room', 'app_config', "
    "'bug_report', 'drawing', 'lobby_message')"
)


def _replace_check(table: str, name: str, expression: str) -> None:
    """Swap one check for another without holding the table while its rows
    are read: NOT VALID, then validated, on PostgreSQL (database.md §13)."""
    if op.get_context().dialect.name == "postgresql":
        op.drop_constraint(name, table, type_="check")
        op.create_check_constraint(name, table, expression, postgresql_not_valid=True)
        op.execute(f"ALTER TABLE {table} VALIDATE CONSTRAINT {name}")
        return
    with op.batch_alter_table(table) as batch:
        batch.drop_constraint(name, type_="check")
        # online-ddl: SQLite rebuilds the table in batch mode; it has no NOT VALID and holds no live deployment
        batch.create_check_constraint(name, expression)


def upgrade() -> None:
    if op.get_context().dialect.name == "postgresql":
        op.add_column(
            "room_messages", sa.Column("hidden_at", sa.DateTime(timezone=True), nullable=True)
        )
        op.create_check_constraint(
            "ck_room_messages_hidden_lobby_only",
            "room_messages",
            _HIDDEN,
            postgresql_not_valid=True,
        )
        op.execute("ALTER TABLE room_messages VALIDATE CONSTRAINT ck_room_messages_hidden_lobby_only")
    else:
        with op.batch_alter_table("room_messages") as batch:
            batch.add_column(sa.Column("hidden_at", sa.DateTime(timezone=True), nullable=True))
            # online-ddl: SQLite rebuilds the table in batch mode; it has no NOT VALID and holds no live deployment
            batch.create_check_constraint("ck_room_messages_hidden_lobby_only", _HIDDEN)
    _replace_check("audit_events", "ck_audit_events_target_type", _TARGET_TYPES_AFTER)


def downgrade() -> None:
    op.execute("DELETE FROM audit_events WHERE target_type = 'lobby_message'")
    _replace_check("audit_events", "ck_audit_events_target_type", _TARGET_TYPES_BEFORE)
    if op.get_context().dialect.name == "postgresql":
        op.drop_constraint("ck_room_messages_hidden_lobby_only", "room_messages", type_="check")
        op.drop_column("room_messages", "hidden_at")
        return
    with op.batch_alter_table("room_messages") as batch:
        batch.drop_constraint("ck_room_messages_hidden_lobby_only", type_="check")
        batch.drop_column("hidden_at")
