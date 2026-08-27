"""record a throttled command as a runtime observation

Revision ID: l5b9d4f2a613
Revises: k4a8c3d1e592
Create Date: 2026-08-28 00:00:00.000000

Extends the stored event set with `command.throttled`, so that a caller being
held to their budget is visible rather than merely absorbed. One value, and
the coordinated review R-ENG-06 asks for: code, migration, contract, README
and glossary all move together.
"""
from collections.abc import Sequence

from alembic import op


revision: str = "l5b9d4f2a613"
down_revision: str | Sequence[str] | None = "k4a8c3d1e592"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EVENT_TYPES = (
    "'room.created', 'room.closed', 'player.joined', 'player.left', "
    "'player.disconnected', 'player.reconnected', 'player.evicted', "
    "'game.started', 'game.finished', 'game.abandoned', 'turn.ended', "
    "'timer.overran', 'canvas.payload_observed', 'drawing.stored', "
    "'recap.budget_dropped'"
)
EVENT_TYPES_WITH_THROTTLE = f"{EVENT_TYPES}, 'command.throttled'"


def upgrade() -> None:
    with op.batch_alter_table("runtime_events") as batch_op:
        batch_op.drop_constraint("ck_runtime_events_type", type_="check")
        batch_op.create_check_constraint(
            "ck_runtime_events_type", f"event_type IN ({EVENT_TYPES_WITH_THROTTLE})"
        )


def downgrade() -> None:
    # Rows recording the new type would violate the narrower constraint, and a
    # downgrade that fails halfway is worse than one that tidies first.
    op.execute("DELETE FROM runtime_events WHERE event_type = 'command.throttled'")
    # The roll-up keys the same values under `metric`.
    op.execute("DELETE FROM runtime_stats_daily WHERE metric = 'command.throttled'")
    with op.batch_alter_table("runtime_events") as batch_op:
        batch_op.drop_constraint("ck_runtime_events_type", type_="check")
        batch_op.create_check_constraint(
            "ck_runtime_events_type", f"event_type IN ({EVENT_TYPES})"
        )
