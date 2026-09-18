"""drop the indexes nothing reads, and leave room for heap-only updates

Revision ID: a1c2e3f4b5d6
Revises: f4a5b6c7d8e9
Create Date: 2026-09-18 00:00:00.000000

Seven indexes had no reader in the application (#890). The two that cost
the most: `ix_auth_sessions_idle_expires_at`, whose column moves with every
throttled session touch and so made every touch a non-heap-only update
writing into all six indexes of the table; and
`ix_room_messages_game_turn_created`, the largest index on the table with the
most rows, which no statement filters by. The others are a partial index no
query's plan uses, a correlation column nothing looks up by, and three that
served only cascades from parents deleted with their whole game.

The five tables updated in place far more often than inserted get
`fillfactor = 85`, so an update that changes no indexed column finds room on
its page. PostgreSQL only; SQLite has no storage parameters. Existing pages
keep their fill until rewritten, which on a pre-launch database is nothing.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "a1c2e3f4b5d6"
down_revision: str | Sequence[str] | None = "f4a5b6c7d8e9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (index, table, columns) - recreated as they were on the way down.
_DROPPED = (
    ("ix_auth_sessions_idle_expires_at", "auth_sessions", ["idle_expires_at"]),
    ("ix_room_messages_game_turn_created", "room_messages", ["game_id", "turn_id", "created_at"]),
    (
        "ix_planned_shutdown_abandonments_room_instance_id",
        "planned_shutdown_abandonments",
        ["room_instance_id"],
    ),
    ("ix_turn_records_drawer_participant_id", "turn_records", ["drawer_participant_id"]),
    ("ix_score_events_turn_id", "score_events", ["turn_id"]),
    ("ix_turn_drawing_reactions_game_id", "turn_drawing_reactions", ["game_id"]),
)
_UNANNOUNCED = "status = 'accepted' AND acceptance_announced_at IS NULL"

_UPDATED_IN_PLACE = (
    "auth_sessions",
    "auth_rate_limit_buckets",
    "auth_login_lockouts",
    "user_stats_daily",
    "runtime_stats_daily",
)


def upgrade() -> None:
    for name, table, _columns in _DROPPED:
        op.drop_index(name, table_name=table)
    op.drop_index("ix_friendships_acceptance_unannounced", table_name="friendships")
    if op.get_bind().dialect.name == "postgresql":
        for table in _UPDATED_IN_PLACE:
            op.execute(f"ALTER TABLE {table} SET (fillfactor = 85)")


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        for table in _UPDATED_IN_PLACE:
            op.execute(f"ALTER TABLE {table} RESET (fillfactor)")
    op.create_index(
        "ix_friendships_acceptance_unannounced",
        "friendships",
        ["requested_by_id"],
        postgresql_where=sa.text(_UNANNOUNCED),
        sqlite_where=sa.text(_UNANNOUNCED),
    )
    for name, table, columns in reversed(_DROPPED):
        op.create_index(name, table, columns)
