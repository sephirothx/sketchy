"""add mode and status checks

Revision ID: 5f1c7a3d8e24
Revises: 2e8b6d4f9a13
Create Date: 2026-08-22 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = "5f1c7a3d8e24"
down_revision: Union[str, Sequence[str], None] = "2e8b6d4f9a13"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Constrain stored mode, outcome, and language values."""
    with op.batch_alter_table("game_records") as batch_op:
        batch_op.create_check_constraint(
            "ck_game_records_scoring_mode",
            "scoring_mode IN ('none', 'default', 'pressure')",
        )
        batch_op.create_check_constraint(
            "ck_game_records_hint_mode",
            "hint_mode IN ('none', 'checkpoints', 'purchase', 'wheel')",
        )
    with op.batch_alter_table("turn_records") as batch_op:
        batch_op.create_check_constraint(
            "ck_turn_records_end_reason",
            "end_reason IN ('all_guessed', 'timeout')",
        )
    with op.batch_alter_table("prompt_lists") as batch_op:
        batch_op.create_check_constraint(
            "ck_prompt_lists_language", "language IN ('en')"
        )


def downgrade() -> None:
    """Remove stored-value checks."""
    with op.batch_alter_table("prompt_lists") as batch_op:
        batch_op.drop_constraint("ck_prompt_lists_language", type_="check")
    with op.batch_alter_table("turn_records") as batch_op:
        batch_op.drop_constraint("ck_turn_records_end_reason", type_="check")
    with op.batch_alter_table("game_records") as batch_op:
        batch_op.drop_constraint("ck_game_records_hint_mode", type_="check")
        batch_op.drop_constraint("ck_game_records_scoring_mode", type_="check")
