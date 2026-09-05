"""add reactions to drawings

Revision ID: z9a3e7c1d258
Revises: y8f2d6b0c147
Create Date: 2026-09-05 10:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.db.types import UTCDateTime


revision: str = "z9a3e7c1d258"
down_revision: str | Sequence[str] | None = "y8f2d6b0c147"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD_NONNEGATIVE = (
    "games_played >= 0 AND games_won >= 0 "
    "AND games_won <= games_played AND turns_played >= 0 "
    "AND prompts_guessed >= 0 "
    "AND drawings_made >= 0"
)
_NEW_NONNEGATIVE = _OLD_NONNEGATIVE + " AND reactions_received >= 0"


def upgrade() -> None:
    op.create_table(
        "turn_drawing_reactions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("game_id", sa.Uuid(), nullable=False),
        sa.Column("turn_id", sa.Uuid(), nullable=False),
        sa.Column("participant_id", sa.Uuid(), nullable=False),
        sa.Column("emoji", sa.String(length=16), nullable=False),
        sa.Column("set_version", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            UTCDateTime(),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            UTCDateTime(),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "emoji IN ('heart', 'laugh', 'wow', 'fire')",
            name="ck_turn_drawing_reactions_emoji",
        ),
        sa.CheckConstraint(
            "set_version >= 1", name="ck_turn_drawing_reactions_set_version"
        ),
        sa.ForeignKeyConstraint(
            ["game_id", "turn_id"],
            ["turn_records.game_id", "turn_records.id"],
            name="fk_turn_drawing_reactions_turn_same_game",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["game_id", "participant_id"],
            ["game_participants.game_id", "game_participants.id"],
            name="fk_turn_drawing_reactions_seat_same_game",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "turn_id",
            "participant_id",
            name="uq_turn_drawing_reactions_turn_participant",
        ),
    )
    op.create_index(
        "ix_turn_drawing_reactions_game_id", "turn_drawing_reactions", ["game_id"]
    )
    op.create_index(
        "ix_turn_drawing_reactions_participant_id",
        "turn_drawing_reactions",
        ["participant_id"],
    )

    # The projection's non-negative rule is one combined constraint, so the
    # new counter joins it by recreating it rather than adding a second.
    with op.batch_alter_table("user_stats_daily") as batch:
        batch.add_column(
            sa.Column(
                "reactions_received",
                sa.Integer(),
                server_default=sa.text("0"),
                nullable=False,
            )
        )
        batch.drop_constraint("ck_user_stats_daily_nonnegative", type_="check")
        batch.create_check_constraint(
            "ck_user_stats_daily_nonnegative", _NEW_NONNEGATIVE
        )


def downgrade() -> None:
    with op.batch_alter_table("user_stats_daily") as batch:
        batch.drop_constraint("ck_user_stats_daily_nonnegative", type_="check")
        batch.create_check_constraint(
            "ck_user_stats_daily_nonnegative", _OLD_NONNEGATIVE
        )
        batch.drop_column("reactions_received")
    # Reactions exist nowhere else, so downgrading discards them. Games, turns
    # and every other history fact are untouched.
    op.drop_index(
        "ix_turn_drawing_reactions_participant_id", table_name="turn_drawing_reactions"
    )
    op.drop_index(
        "ix_turn_drawing_reactions_game_id", table_name="turn_drawing_reactions"
    )
    op.drop_table("turn_drawing_reactions")
