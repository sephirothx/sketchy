"""add missing row write timestamps

Revision ID: a1e4c7d9b632
Revises: f6d1a8c3e520
Create Date: 2026-08-23 00:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "a1e4c7d9b632"
down_revision: str | Sequence[str] | None = "f6d1a8c3e520"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_CREATED_AT_TABLES = (
    "game_participants",
    "turn_records",
    "turn_guesses",
    "prompts",
)


def _add_unknown_legacy_timestamp(table_name: str, column_name: str) -> None:
    # Add without a default first so existing rows remain honestly unknown.
    # A second table operation installs the server default for future writes;
    # the split also preserves nulls during SQLite batch-table recreation.
    with op.batch_alter_table(table_name) as batch_op:
        batch_op.add_column(
            sa.Column(column_name, sa.DateTime(timezone=True), nullable=True)
        )
    with op.batch_alter_table(table_name) as batch_op:
        batch_op.alter_column(
            column_name,
            existing_type=sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            existing_nullable=True,
        )


def upgrade() -> None:
    _add_unknown_legacy_timestamp("app_config", "created_at")
    _add_unknown_legacy_timestamp("app_config", "updated_at")
    _add_unknown_legacy_timestamp("game_records", "persisted_at")
    for table_name in _CREATED_AT_TABLES:
        _add_unknown_legacy_timestamp(table_name, "created_at")


def downgrade() -> None:
    for table_name in reversed(_CREATED_AT_TABLES):
        with op.batch_alter_table(table_name) as batch_op:
            batch_op.drop_column("created_at")
    with op.batch_alter_table("game_records") as batch_op:
        batch_op.drop_column("persisted_at")
    with op.batch_alter_table("app_config") as batch_op:
        batch_op.drop_column("updated_at")
        batch_op.drop_column("created_at")
