"""the name style a record was made in, beside its colour

Revision ID: 8d4e2b7c9a1f
Revises: 61c3239afd30
Create Date: 2026-11-06 23:30:00.000000

A supporter's name style (#1476) shows in finished games, the Gallery and lobby
chat as it was worn then, the way their colour already does: each record that
snapshots a name colour now snapshots its style beside it. Nullable and
unchecked, so a row from before this - and a key for a style later retired -
reads as no style, and shows the colour.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "8d4e2b7c9a1f"
down_revision: str | Sequence[str] | None = "61c3239afd30"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_COLUMNS = (
    ("game_participants", "name_style_snapshot"),
    ("turn_records", "drawer_name_style_snapshot"),
    ("room_messages", "sender_name_style_snapshot"),
)


def upgrade() -> None:
    for table, column in _COLUMNS:
        op.add_column(table, sa.Column(column, sa.String(16), nullable=True))


def downgrade() -> None:
    for table, column in reversed(_COLUMNS):
        op.drop_column(table, column)
