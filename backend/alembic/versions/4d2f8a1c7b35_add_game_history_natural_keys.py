"""add game history natural keys

Revision ID: 4d2f8a1c7b35
Revises: 9b6f4e2d1a70
Create Date: 2026-08-22 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = "4d2f8a1c7b35"
down_revision: Union[str, Sequence[str], None] = "9b6f4e2d1a70"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Reject duplicate seats, turns, and correct guesses."""
    op.create_index(
        "uq_game_participants_game_user",
        "game_participants",
        ["game_id", "user_id"],
        unique=True,
    )
    op.create_index(
        "uq_turn_records_game_round_turn",
        "turn_records",
        ["game_id", "round_number", "turn_number"],
        unique=True,
    )
    op.create_index(
        "uq_turn_guesses_turn_user",
        "turn_guesses",
        ["turn_id", "user_id"],
        unique=True,
    )


def downgrade() -> None:
    """Remove game history natural-key constraints."""
    op.drop_index("uq_turn_guesses_turn_user", table_name="turn_guesses")
    op.drop_index("uq_turn_records_game_round_turn", table_name="turn_records")
    op.drop_index(
        "uq_game_participants_game_user", table_name="game_participants"
    )
