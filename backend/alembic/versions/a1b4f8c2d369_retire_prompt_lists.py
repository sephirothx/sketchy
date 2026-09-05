"""retire prompt lists instead of deleting pinned revisions

Revision ID: a1b4f8c2d369
Revises: b1c5a9e3f470
Create Date: 2026-09-06 00:30:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.db.types import UTCDateTime


revision: str = "a1b4f8c2d369"
down_revision: str | Sequence[str] | None = "b1c5a9e3f470"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("prompt_lists") as batch:
        batch.add_column(sa.Column("deleted_at", UTCDateTime(), nullable=True))
    op.create_index(
        "ix_prompt_lists_deleted_at", "prompt_lists", ["deleted_at"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_prompt_lists_deleted_at", table_name="prompt_lists")
    with op.batch_alter_table("prompt_lists") as batch:
        batch.drop_column("deleted_at")
