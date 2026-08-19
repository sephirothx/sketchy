"""Round, participant and guess analytics columns

Revision ID: 0ca6057bc76d
Revises: 264a248789d1
Create Date: 2026-08-19 15:43:01.111931

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0ca6057bc76d'
down_revision: Union[str, Sequence[str], None] = '264a248789d1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    Plain ``add_column`` rather than ``batch_alter_table``: adding a column is
    one of the few things SQLite does natively, so batch mode would copy three
    tables into replacements for no gain. It would also reflect each table and,
    through their foreign keys, the ``users`` table - whose case-insensitive
    username index is expression-based and cannot be reflected on SQLite,
    producing a warning on every migration run.

    Every column carries a server default. These tables already hold finished
    games, and a NOT NULL column with no default cannot be added to a table
    with rows in it - the migration would fail on the first real database it
    met. Zero is also the honest value for a game played before any of this
    was measured.
    """
    zero = sa.text("0")

    op.add_column(
        "game_participants",
        sa.Column("turns_played", sa.Integer(), nullable=False, server_default=zero),
    )

    op.add_column(
        "round_guesses",
        sa.Column("hints_used", sa.Integer(), nullable=False, server_default=zero),
    )
    op.add_column(
        "round_guesses",
        sa.Column(
            "points_spent_on_hints", sa.Integer(), nullable=False, server_default=zero
        ),
    )
    op.add_column(
        "round_guesses",
        sa.Column(
            "wrong_guesses_before", sa.Integer(), nullable=False, server_default=zero
        ),
    )

    op.add_column(
        "round_records",
        sa.Column("guesser_count", sa.Integer(), nullable=False, server_default=zero),
    )
    op.add_column(
        "round_records",
        sa.Column("word_auto_picked", sa.Boolean(), nullable=False, server_default=zero),
    )
    op.add_column(
        "round_records",
        sa.Column("stroke_count", sa.Integer(), nullable=False, server_default=zero),
    )
    op.add_column(
        "round_records",
        sa.Column(
            "end_reason",
            sa.String(length=16),
            nullable=False,
            server_default="timeout",
        ),
    )
    op.add_column(
        "round_records",
        sa.Column(
            "wrong_guess_count", sa.Integer(), nullable=False, server_default=zero
        ),
    )
    op.add_column(
        "round_records",
        sa.Column("near_miss_count", sa.Integer(), nullable=False, server_default=zero),
    )


def downgrade() -> None:
    """Downgrade schema.

    Batch mode here, unlike in ``upgrade``: dropping a column is native only on
    SQLite 3.35 and later, so the table copy is what makes this work anywhere.
    """
    with op.batch_alter_table("round_records", schema=None) as batch_op:
        batch_op.drop_column("near_miss_count")
        batch_op.drop_column("wrong_guess_count")
        batch_op.drop_column("end_reason")
        batch_op.drop_column("stroke_count")
        batch_op.drop_column("word_auto_picked")
        batch_op.drop_column("guesser_count")

    with op.batch_alter_table("round_guesses", schema=None) as batch_op:
        batch_op.drop_column("wrong_guesses_before")
        batch_op.drop_column("points_spent_on_hints")
        batch_op.drop_column("hints_used")

    with op.batch_alter_table("game_participants", schema=None) as batch_op:
        batch_op.drop_column("turns_played")
