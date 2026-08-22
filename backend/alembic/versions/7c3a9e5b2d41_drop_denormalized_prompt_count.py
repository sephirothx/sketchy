"""drop denormalized prompt count

Revision ID: 7c3a9e5b2d41
Revises: 4d2f8a1c7b35
Create Date: 2026-08-22 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "7c3a9e5b2d41"
down_revision: Union[str, Sequence[str], None] = "4d2f8a1c7b35"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Derive prompt-list counts from membership instead of stored state."""
    with op.batch_alter_table("prompt_lists") as batch_op:
        batch_op.drop_column("prompt_count")


def downgrade() -> None:
    """Restore and populate the legacy denormalized count."""
    with op.batch_alter_table("prompt_lists") as batch_op:
        batch_op.add_column(
            sa.Column(
                "prompt_count",
                sa.Integer(),
                server_default=sa.text("0"),
                nullable=False,
            )
        )
    op.execute(
        sa.text(
            "UPDATE prompt_lists SET prompt_count = ("
            "SELECT count(*) FROM prompts "
            "WHERE prompts.prompt_list_id = prompt_lists.id)"
        )
    )
