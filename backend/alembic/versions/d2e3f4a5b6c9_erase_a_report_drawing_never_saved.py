"""erase a report's drawing whose turn was never saved

Revision ID: d2e3f4a5b6c9
Revises: c1d2e3f4a5b8
Create Date: 2026-10-13 00:00:00.000000

An administrator erases an illegal drawing through its saved row (#1419), and
a report's copy of it is held back by that row's stamp. A turn that was never
saved - the one an abandoned game was in the middle of, a game too small to
record, a failed write - has no row, so its copy stayed in front of every
moderator and in the reported player's notice (#1439). The copy now carries
the stamp itself: `player_report_drawing_evidence.moderation_erased_at`, with
a partial index over the few that are set, by turn.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "d2e3f4a5b6c9"
down_revision: str | Sequence[str] | None = "c1d2e3f4a5b8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ERASED = "moderation_erased_at IS NOT NULL"


def upgrade() -> None:
    op.add_column(
        "player_report_drawing_evidence",
        sa.Column("moderation_erased_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_report_drawing_evidence_erased_turn",
        "player_report_drawing_evidence",
        ["turn_id_snapshot"],
        postgresql_where=sa.text(_ERASED),
        sqlite_where=sa.text(_ERASED),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_report_drawing_evidence_erased_turn",
        table_name="player_report_drawing_evidence",
    )
    if op.get_context().dialect.name == "postgresql":
        op.drop_column("player_report_drawing_evidence", "moderation_erased_at")
        return
    with op.batch_alter_table("player_report_drawing_evidence") as batch:
        batch.drop_column("moderation_erased_at")
