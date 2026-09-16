"""gallery ranking columns on turn_drawings

Revision ID: c1d2e3f4a5b6
Revises: b0c1d2e3f4a5
Create Date: 2026-09-15 19:00:00.000000

The Gallery (#524) orders every kept public drawing by reactions - Top by
the count, Hot by reddit's decayed score - and Top over the whole history
cannot count reaction rows on read. So each drawing row carries
`reaction_count` and `hot_score`, set by every reaction write under the
row's lock and rebuilt from the rows by `app.services.gallery_ranking`: a
disposable projection, never a counter that is trusted (R-GAL-05).

Both are backfilled here from the reaction rows, the score in Python
because a logarithm is not spelled alike on both engines: a drawing
written before this revision would otherwise rank under every drawing
written after it until an operator rebuilt the projections.

Going back drops both columns and their indexes; nothing else reads them.
"""
from collections.abc import Sequence
from datetime import timezone
import math

import sqlalchemy as sa
from alembic import op


revision: str = "c1d2e3f4a5b6"
down_revision: str | Sequence[str] | None = "b0c1d2e3f4a5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("turn_drawings") as batch:
        batch.add_column(
            sa.Column(
                "reaction_count",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("0"),
            )
        )
        batch.add_column(
            sa.Column(
                "hot_score", sa.Float(), nullable=False, server_default=sa.text("0")
            )
        )
        batch.create_check_constraint(
            "ck_turn_drawings_reaction_count", "reaction_count >= 0"
        )
        batch.create_index(
            "ix_turn_drawings_gallery_top", ["status", "reaction_count"]
        )
        batch.create_index("ix_turn_drawings_gallery_hot", ["status", "hot_score"])
    op.execute(
        "UPDATE turn_drawings SET reaction_count = ("
        "SELECT COUNT(*) FROM turn_drawing_reactions "
        "WHERE turn_drawing_reactions.turn_id = turn_drawings.turn_id)"
    )
    _backfill_hot_scores()


# `app.services.gallery_ranking.hot_score`, copied rather than imported: a
# migration must keep meaning what it meant when it ran, whatever the
# service later becomes.
_HOT_DECAY_SECONDS = 45_000


def _backfill_hot_scores() -> None:
    connection = op.get_bind()
    drawings = sa.table(
        "turn_drawings",
        sa.column("turn_id", sa.Uuid(as_uuid=True, native_uuid=True)),
        sa.column("game_id", sa.Uuid(as_uuid=True, native_uuid=True)),
        sa.column("reaction_count", sa.Integer()),
        sa.column("hot_score", sa.Float()),
    )
    games = sa.table(
        "game_records",
        sa.column("id", sa.Uuid(as_uuid=True, native_uuid=True)),
        sa.column("finished_at", sa.DateTime(timezone=True)),
    )
    rows = connection.execute(
        sa.select(drawings.c.turn_id, games.c.finished_at, drawings.c.reaction_count)
        .select_from(drawings.join(games, games.c.id == drawings.c.game_id))
    ).all()
    for turn_id, finished_at, count in rows:
        if finished_at.tzinfo is None:
            finished_at = finished_at.replace(tzinfo=timezone.utc)
        score = math.log10(max(int(count), 1)) + finished_at.timestamp() / _HOT_DECAY_SECONDS
        connection.execute(
            sa.update(drawings)
            .where(drawings.c.turn_id == turn_id)
            .values(hot_score=score)
        )


def downgrade() -> None:
    with op.batch_alter_table("turn_drawings") as batch:
        batch.drop_index("ix_turn_drawings_gallery_hot")
        batch.drop_index("ix_turn_drawings_gallery_top")
        batch.drop_constraint("ck_turn_drawings_reaction_count", type_="check")
        batch.drop_column("hot_score")
        batch.drop_column("reaction_count")
