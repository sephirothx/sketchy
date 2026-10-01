"""Official lists stand on shelves

Revision ID: b4c5d6e7f8a1
Revises: a3b4c5d6e7f9
Create Date: 2026-10-01 00:00:00.000000

The room picker becomes a tree (#1374): each official list names a shelf, an
optional series within it, and its place there. Navigation rather than
content, so the seed rewrites them on every start; a player's list has none.
The columns start empty and the next start fills them.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "b4c5d6e7f8a1"
down_revision: str | Sequence[str] | None = "a3b4c5d6e7f9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("prompt_lists") as batch:
        batch.add_column(sa.Column("shelf", sa.String(length=32), nullable=True))
        batch.add_column(sa.Column("series", sa.String(length=32), nullable=True))
        batch.add_column(sa.Column("shelf_position", sa.Integer(), nullable=True))
        batch.create_check_constraint(
            "ck_prompt_lists_shelf_is_bundled",
            "shelf IS NULL OR is_bundled = true",
        )
        batch.create_check_constraint(
            "ck_prompt_lists_shelf_position",
            "(shelf IS NULL) = (shelf_position IS NULL)",
        )
        batch.create_check_constraint(
            "ck_prompt_lists_series_on_shelf",
            "series IS NULL OR shelf IS NOT NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("prompt_lists") as batch:
        batch.drop_constraint("ck_prompt_lists_series_on_shelf", type_="check")
        batch.drop_constraint("ck_prompt_lists_shelf_position", type_="check")
        batch.drop_constraint("ck_prompt_lists_shelf_is_bundled", type_="check")
        batch.drop_column("shelf_position")
        batch.drop_column("series")
        batch.drop_column("shelf")
