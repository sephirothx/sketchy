"""add rebuildable daily user statistics projection

Revision ID: c0a4e6f8b312
Revises: b9f3e5d7a201
Create Date: 2026-08-23 00:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "c0a4e6f8b312"
down_revision: str | Sequence[str] | None = "b9f3e5d7a201"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _backfill_sql(*, day: str) -> str:
    canonical = "COALESCE(ia.target_user_id, gp.user_id)"
    return f"""
        WITH participant_days AS (
            SELECT
                {canonical} AS user_id,
                {day.format(alias='g')} AS stat_date,
                COUNT(DISTINCT gp.game_id) AS games_played,
                COUNT(DISTINCT CASE WHEN gp.final_rank = 1 THEN gp.game_id END)
                    AS games_won,
                SUM(gp.final_score) AS total_score
            FROM game_participants gp
            JOIN game_records g ON g.id = gp.game_id
            LEFT JOIN identity_aliases ia ON ia.source_user_id = gp.user_id
            WHERE gp.user_id IS NOT NULL
            GROUP BY {canonical}, {day.format(alias='g')}
        )
        INSERT INTO user_stats_daily (
            user_id, stat_date, games_played, games_won, total_score,
            turns_played, prompts_guessed, drawings_made, updated_at
        )
        SELECT
            pd.user_id,
            pd.stat_date,
            pd.games_played,
            pd.games_won,
            pd.total_score,
            (
                SELECT COUNT(DISTINCT tr.id)
                FROM turn_records tr
                JOIN game_records tg ON tg.id = tr.game_id
                WHERE {day.format(alias='tg')} = pd.stat_date
                  AND EXISTS (
                      SELECT 1
                      FROM game_participants gp2
                      LEFT JOIN identity_aliases ia2
                        ON ia2.source_user_id = gp2.user_id
                      WHERE gp2.game_id = tr.game_id
                        AND COALESCE(ia2.target_user_id, gp2.user_id) = pd.user_id
                  )
            ) AS turns_played,
            (
                SELECT COUNT(guess.id)
                FROM turn_guesses guess
                JOIN turn_records gt ON gt.id = guess.turn_id
                JOIN game_records gg ON gg.id = gt.game_id
                LEFT JOIN identity_aliases gia
                  ON gia.source_user_id = guess.user_id
                WHERE {day.format(alias='gg')} = pd.stat_date
                  AND COALESCE(gia.target_user_id, guess.user_id) = pd.user_id
            ) AS prompts_guessed,
            (
                SELECT COUNT(draw.id)
                FROM turn_records draw
                JOIN game_records dg ON dg.id = draw.game_id
                LEFT JOIN identity_aliases dia
                  ON dia.source_user_id = draw.drawer_user_id
                WHERE {day.format(alias='dg')} = pd.stat_date
                  AND COALESCE(dia.target_user_id, draw.drawer_user_id) = pd.user_id
            ) AS drawings_made,
            CURRENT_TIMESTAMP
        FROM participant_days pd
    """


def upgrade() -> None:
    op.create_table(
        "user_stats_daily",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("stat_date", sa.Date(), nullable=False),
        sa.Column("games_played", sa.Integer(), server_default="0", nullable=False),
        sa.Column("games_won", sa.Integer(), server_default="0", nullable=False),
        sa.Column("total_score", sa.Integer(), server_default="0", nullable=False),
        sa.Column("turns_played", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "prompts_guessed", sa.Integer(), server_default="0", nullable=False
        ),
        sa.Column("drawings_made", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "games_played >= 0 AND games_won >= 0 "
            "AND games_won <= games_played AND turns_played >= 0 "
            "AND prompts_guessed >= 0 AND drawings_made >= 0",
            name="ck_user_stats_daily_nonnegative",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "stat_date"),
    )
    op.create_index(
        "ix_user_stats_daily_stat_date", "user_stats_daily", ["stat_date"]
    )

    day = (
        "date({alias}.finished_at)"
        if op.get_bind().dialect.name == "sqlite"
        else "({alias}.finished_at AT TIME ZONE 'UTC')::date"
    )
    op.execute(_backfill_sql(day=day))


def downgrade() -> None:
    op.drop_index("ix_user_stats_daily_stat_date", table_name="user_stats_daily")
    op.drop_table("user_stats_daily")
