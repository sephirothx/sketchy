"""record an abandoned history write as a runtime observation

Revision ID: y8f2d6b0c147
Revises: x7e1c5a9b036
Create Date: 2026-09-02 00:00:00.000000

Extends the stored event set with `history.write_abandoned`, so that a
finished game whose history the server gave up writing - because the
database timed out or refused it - is counted rather than merely logged
(#482). The swallow itself is unchanged; what changes is that the loss is now
a number an alert rule can watch.
"""
from collections.abc import Sequence

from alembic import op


revision: str = "y8f2d6b0c147"
down_revision: str | Sequence[str] | None = "x7e1c5a9b036"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EVENT_TYPES = (
    "'room.created', 'room.closed', 'player.joined', 'player.left', "
    "'player.disconnected', 'player.reconnected', 'player.evicted', "
    "'game.started', 'game.finished', 'game.abandoned', 'turn.ended', "
    "'timer.overran', 'canvas.payload_observed', 'drawing.stored', "
    "'recap.budget_dropped', 'command.throttled'"
)
EVENT_TYPES_WITH_ABANDONED = f"{EVENT_TYPES}, 'history.write_abandoned'"


def upgrade() -> None:
    with op.batch_alter_table("runtime_events") as batch_op:
        batch_op.drop_constraint("ck_runtime_events_type", type_="check")
        batch_op.create_check_constraint(
            "ck_runtime_events_type", f"event_type IN ({EVENT_TYPES_WITH_ABANDONED})"
        )


def downgrade() -> None:
    # Rows recording the new type would violate the narrower constraint, and a
    # downgrade that fails halfway is worse than one that tidies first.
    op.execute("DELETE FROM runtime_events WHERE event_type = 'history.write_abandoned'")
    # The roll-up keys the same values under `metric`.
    op.execute("DELETE FROM runtime_stats_daily WHERE metric = 'history.write_abandoned'")
    with op.batch_alter_table("runtime_events") as batch_op:
        batch_op.drop_constraint("ck_runtime_events_type", type_="check")
        batch_op.create_check_constraint(
            "ck_runtime_events_type", f"event_type IN ({EVENT_TYPES})"
        )
