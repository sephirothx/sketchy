"""add prompt server defaults

Revision ID: 2e8b6d4f9a13
Revises: 7c3a9e5b2d41
Create Date: 2026-08-22 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "2e8b6d4f9a13"
down_revision: Union[str, Sequence[str], None] = "7c3a9e5b2d41"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Make raw and bulk prompt inserts use the same defaults as the ORM."""
    with op.batch_alter_table("prompt_lists") as batch_op:
        batch_op.alter_column("description", server_default="")
        batch_op.alter_column("language", server_default="en")
        batch_op.alter_column("is_bundled", server_default=sa.true())
        batch_op.alter_column("version", server_default=sa.text("1"))
    with op.batch_alter_table("prompts") as batch_op:
        for column_name in (
            "offer_count",
            "pick_count",
            "correct_guess_count",
            "total_guesser_count",
        ):
            batch_op.alter_column(column_name, server_default=sa.text("0"))


def downgrade() -> None:
    """Return prompt defaults to ORM-only behavior."""
    with op.batch_alter_table("prompts") as batch_op:
        for column_name in (
            "offer_count",
            "pick_count",
            "correct_guess_count",
            "total_guesser_count",
        ):
            batch_op.alter_column(column_name, server_default=None)
    with op.batch_alter_table("prompt_lists") as batch_op:
        batch_op.alter_column("version", server_default=None)
        batch_op.alter_column("is_bundled", server_default=None)
        batch_op.alter_column("language", server_default=None)
        batch_op.alter_column("description", server_default=None)
