"""history bounds checks, and no placing for an abandoned game

game_records and turn_records gain the numeric bounds their sibling
settings tables have always pinned, game_participants.final_rank becomes
nullable so an abandoned game's row can actually carry no placing
(R-HIST-06 promised as much of the row itself), and audit_events.created_at
gets the index the admin ledger's newest-first read has always implied.

Revision ID: q9d4b7e2f358
Revises: p8c3a6d9e147
Create Date: 2026-08-29 00:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "q9d4b7e2f358"
down_revision: str | Sequence[str] | None = "p8c3a6d9e147"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("game_records") as batch_op:
        batch_op.create_check_constraint(
            "ck_game_records_player_count", "player_count >= 1"
        )
        batch_op.create_check_constraint(
            "ck_game_records_total_rounds", "total_rounds >= 1"
        )
        batch_op.create_check_constraint(
            "ck_game_records_drawing_seconds", "drawing_seconds > 0"
        )
        batch_op.create_check_constraint(
            "ck_game_records_time_order", "started_at <= finished_at"
        )

    with op.batch_alter_table("turn_records") as batch_op:
        batch_op.create_check_constraint(
            "ck_turn_records_duration", "duration_seconds > 0"
        )
        batch_op.create_check_constraint(
            "ck_turn_records_counts_nonnegative",
            "round_number >= 1 AND turn_number >= 1 AND guesser_count >= 0 "
            "AND wrong_guess_count >= 0 AND near_miss_count >= 0 "
            "AND stroke_count >= 0",
        )

    with op.batch_alter_table("game_participants") as batch_op:
        batch_op.alter_column(
            "final_rank", existing_type=sa.Integer(), nullable=True
        )
        batch_op.create_check_constraint(
            "ck_game_participants_final_rank",
            "final_rank IS NULL OR final_rank >= 1",
        )
    # Existing seats on games that never finished lose their stored score-order
    # ranks, matching what the writer stores from now on (R-HIST-06: no placing
    # in the row). The downgrade below re-derives exactly these values, so the
    # two directions are honest inverses.
    op.execute(
        "UPDATE game_participants SET final_rank = NULL WHERE game_id IN "
        "(SELECT id FROM game_records WHERE outcome != 'finished')"
    )

    op.create_index("ix_audit_events_created_at", "audit_events", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_audit_events_created_at", table_name="audit_events")

    with op.batch_alter_table("game_participants") as batch_op:
        batch_op.drop_constraint("ck_game_participants_final_rank", type_="check")
    # Restoring NOT NULL needs the abandoned rows' placings back; a score-order
    # rank is the value the pre-change writer stored for them.
    bind = op.get_bind()
    # Every non-finished outcome, not only 'abandoned' - anything unranked.
    unfinished_games = sa.text(
        "SELECT id FROM game_records WHERE outcome != 'finished'"
    )
    seat_rows = sa.text(
        "SELECT id, final_score FROM game_participants "
        "WHERE game_id = :game_id ORDER BY final_score DESC"
    )
    for (game_id,) in bind.execute(unfinished_games):
        rank = 0
        previous_score = None
        for position, (participant_id, score) in enumerate(
            bind.execute(seat_rows, {"game_id": game_id}), start=1
        ):
            if score != previous_score:
                rank = position
                previous_score = score
            bind.execute(
                sa.text(
                    "UPDATE game_participants SET final_rank = :rank "
                    "WHERE id = :id"
                ),
                {"rank": rank, "id": participant_id},
            )
    with op.batch_alter_table("game_participants") as batch_op:
        batch_op.alter_column(
            "final_rank", existing_type=sa.Integer(), nullable=False
        )

    with op.batch_alter_table("turn_records") as batch_op:
        batch_op.drop_constraint(
            "ck_turn_records_counts_nonnegative", type_="check"
        )
        batch_op.drop_constraint("ck_turn_records_duration", type_="check")

    with op.batch_alter_table("game_records") as batch_op:
        batch_op.drop_constraint("ck_game_records_time_order", type_="check")
        batch_op.drop_constraint("ck_game_records_drawing_seconds", type_="check")
        batch_op.drop_constraint("ck_game_records_total_rounds", type_="check")
        batch_op.drop_constraint("ck_game_records_player_count", type_="check")
