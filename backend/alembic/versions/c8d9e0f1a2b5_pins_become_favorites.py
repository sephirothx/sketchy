"""pinned drawings become favorites

Revision ID: c8d9e0f1a2b5
Revises: b6c7d8e9f0a3
Create Date: 2026-10-28 00:00:00.000000

The six drawings a profile shows were called *Pinned drawings*; players call
them **Favorites** now (#1501), and the table, its constraints and its indexes
take the name with them so the schema and the code say one word. SQLite can
rename a table but not a constraint, so the table is rebuilt under the new
names and the rows copied across, both ways - nothing reads the old names.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "c8d9e0f1a2b5"
down_revision: str | Sequence[str] | None = "b6c7d8e9f0a3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UUID = sa.Uuid(as_uuid=True, native_uuid=True)
_COLUMNS = "user_id, turn_id, game_id, position, created_at"


def _create(table: str) -> None:
    op.create_table(
        table,
        sa.Column(
            "user_id", _UUID, sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
        ),
        sa.Column("turn_id", _UUID, primary_key=True),
        sa.Column("game_id", _UUID, nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("user_id", "position", name=f"uq_{table}_user_position"),
        sa.ForeignKeyConstraint(
            ["game_id", "turn_id"],
            ["turn_records.game_id", "turn_records.id"],
            name=f"fk_{table}_turn_same_game",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint("position >= 0 AND position < 6", name=f"ck_{table}_position"),
    )
    op.create_index(f"ix_{table}_turn_id", table, ["turn_id"])
    op.create_index(f"ix_{table}_game_id", table, ["game_id"])


def _move(source: str, target: str) -> None:
    _create(target)
    op.execute(f"INSERT INTO {target} ({_COLUMNS}) SELECT {_COLUMNS} FROM {source}")
    op.drop_index(f"ix_{source}_game_id", table_name=source)
    op.drop_index(f"ix_{source}_turn_id", table_name=source)
    op.drop_table(source)


def upgrade() -> None:
    _move("profile_drawing_pins", "profile_favorites")


def downgrade() -> None:
    _move("profile_favorites", "profile_drawing_pins")
