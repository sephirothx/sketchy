"""Index game records by finish time

Revision ID: 7e4397d646c6
Revises: 0ca6057bc76d
Create Date: 2026-08-19 18:08:14.335321

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7e4397d646c6'
down_revision: Union[str, Sequence[str], None] = '0ca6057bc76d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    Plain ``create_index`` rather than ``batch_alter_table``: creating an index
    is native on SQLite, so batch mode would copy the whole table for nothing -
    and reflect it, and through its foreign keys the ``users`` table, whose
    expression-based username index cannot be reflected on SQLite and warns.
    """
    op.create_index("ix_game_records_finished_at", "game_records", ["finished_at"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_game_records_finished_at", table_name="game_records")
