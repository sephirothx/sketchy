"""keep PostgreSQL from re-compressing stored drawings

Revision ID: b3c4d5e6f7a8
Revises: a2b3c4d5e6f7
Create Date: 2026-09-06 16:00:00.000000

A stored drawing is already deflated (#547), so PostgreSQL's TOAST
compression can only spend CPU on it and keep the bytes as they were. The
two payload columns that hold one are switched to EXTERNAL storage: still
out of line past the TOAST threshold, never compressed on the way there.
SQLite has no equivalent and nothing to do.
"""
from collections.abc import Sequence

from alembic import op


revision: str = "b3c4d5e6f7a8"
down_revision: str | Sequence[str] | None = "a2b3c4d5e6f7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PAYLOAD_COLUMNS = (
    ("turn_drawings", "payload"),
    ("player_report_drawing_evidence", "payload"),
)


def _set_storage(mode: str) -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    for table, column in _PAYLOAD_COLUMNS:
        op.execute(f"ALTER TABLE {table} ALTER COLUMN {column} SET STORAGE {mode}")


def upgrade() -> None:
    _set_storage("EXTERNAL")


def downgrade() -> None:
    _set_storage("EXTENDED")
