"""allow one open player report per reporter and player

Revision ID: d5b8c2f4a917
Revises: c4d1a8e35b72
Create Date: 2026-08-24 18:40:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "d5b8c2f4a917"
down_revision: str | Sequence[str] | None = "c4d1a8e35b72"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Existing duplicates would block the index, so fold them first: keep each
    # reporter's earliest open report about a player and dismiss the rest,
    # which is what a moderator would have done by hand. The same fold the
    # content reports got in e8c2f5a91b04.
    # ROW_NUMBER rather than MIN(id): PostgreSQL has no MIN aggregate for uuid.
    # The same mistake was copied here from e8c2f5a91b04, and neither could run
    # on PostgreSQL at all - CI is the only place that dialect is exercised.
    op.execute(
        """
        UPDATE player_reports
           SET status = 'dismissed'
         WHERE id IN (
             SELECT id FROM (
                 SELECT id, ROW_NUMBER() OVER (
                            PARTITION BY reporter_user_id, reported_user_id
                            ORDER BY created_at, id
                        ) AS row_position
                   FROM player_reports
                  WHERE status = 'pending'
             ) ranked
             WHERE row_position > 1
         )
        """
    )
    # An index, not a table rebuild - `game_records` taught us what a rebuild
    # costs, and player_reports has children of its own.
    op.create_index(
        "uq_player_reports_open_target",
        "player_reports",
        ["reporter_user_id", "reported_user_id"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
        sqlite_where=sa.text("status = 'pending'"),
    )


def downgrade() -> None:
    op.drop_index("uq_player_reports_open_target", table_name="player_reports")
