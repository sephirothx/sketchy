"""admit the stored size of a drawing as a runtime event

Revision ID: c3e4f5a6b7d8
Revises: b2d3e4f5a6c7
Create Date: 2026-09-18 02:00:00.000000

`drawing.stored` carries a drawing's wire-frame size; nothing recorded what
was written to the database, so the encoding's ratio could only be had from
a scan of `turn_drawings` (#895). `drawing.encoded` carries the stored bytes,
and its daily roll-up keeps the ratio after the raw events go.

Going back removes the value from the check; raw events of that type are
deleted first, since the older check would refuse them. They are thirty-day
diagnostics, and their daily totals stay.
"""
from collections.abc import Sequence

from alembic import op


revision: str = "c3e4f5a6b7d8"
down_revision: str | Sequence[str] | None = "b2d3e4f5a6c7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_BEFORE = (
    "room.created", "room.closed", "player.joined", "player.left",
    "player.disconnected", "player.reconnected", "player.evicted",
    "game.started", "game.finished", "game.abandoned", "turn.ended",
    "timer.overran", "canvas.payload_observed", "drawing.stored",
    "recap.budget_dropped", "command.throttled", "history.write_abandoned",
)
_AFTER = (*_BEFORE[:14], "drawing.encoded", *_BEFORE[14:])


def _check(values: tuple[str, ...]) -> str:
    return "event_type IN (" + ", ".join(f"'{value}'" for value in values) + ")"


def upgrade() -> None:
    with op.batch_alter_table("runtime_events") as batch:
        batch.drop_constraint("ck_runtime_events_type", type_="check")
        batch.create_check_constraint("ck_runtime_events_type", _check(_AFTER))


def downgrade() -> None:
    op.execute("DELETE FROM runtime_events WHERE event_type = 'drawing.encoded'")
    with op.batch_alter_table("runtime_events") as batch:
        batch.drop_constraint("ck_runtime_events_type", type_="check")
        batch.create_check_constraint("ck_runtime_events_type", _check(_BEFORE))
