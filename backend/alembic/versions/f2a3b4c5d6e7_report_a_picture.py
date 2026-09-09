"""report a picture from the lobby or a profile, and say when it changed

Revision ID: f2a3b4c5d6e7
Revises: e1f2a3b4c5d6
Create Date: 2026-09-09 16:00:00.000000

A picture was reportable only from inside a room, which is the one place it is
least visible: it is on every lobby row and on the profile page, and a player
who objects to one is usually not sitting at a table with its owner (#620).

`profile` joins the report scopes. A complaint about the account itself rather
than about anything it said belongs to no room instance and no line of chat,
so it takes the same shape the lobby does - no instance, one bucket per
account - and several people objecting to one picture become one incident
rather than several.

`reported_avatar_key` records which picture the complaint was about. It is not
a way to fetch that picture back: `uploaded_avatar_assets` deletes the old row
the moment a new one is uploaded, so this key can name something already gone.
That is the point - a reviewer is told the picture has changed since the
report instead of silently judging a different one, and then acts on the one
the account actually carries now.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "f2a3b4c5d6e7"
down_revision: str | Sequence[str] | None = "e1f2a3b4c5d6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("player_reports") as batch:
        batch.add_column(
            sa.Column("reported_avatar_key", sa.String(length=80), nullable=True)
        )
        # The scope check has to be restated rather than extended: a CHECK is
        # its whole expression.
        batch.drop_constraint("ck_player_reports_scope", type_="check")
        batch.create_check_constraint(
            "ck_player_reports_scope",
            "scope IN ('room', 'lobby', 'profile', 'unscoped')",
        )
        # A profile report names no room either, so it joins the side of the
        # instance pairing that must stay null.
        batch.drop_constraint("ck_player_reports_scope_instance", type_="check")
        batch.create_check_constraint(
            "ck_player_reports_scope_instance",
            "(scope = 'room' AND room_instance_id IS NOT NULL)"
            " OR (scope <> 'room' AND room_instance_id IS NULL)",
        )


def downgrade() -> None:
    with op.batch_alter_table("player_reports") as batch:
        batch.drop_constraint("ck_player_reports_scope_instance", type_="check")
        batch.create_check_constraint(
            "ck_player_reports_scope_instance",
            "(scope = 'room' AND room_instance_id IS NOT NULL)"
            " OR (scope <> 'room' AND room_instance_id IS NULL)",
        )
        batch.drop_constraint("ck_player_reports_scope", type_="check")
        batch.create_check_constraint(
            "ck_player_reports_scope",
            "scope IN ('room', 'lobby', 'unscoped')",
        )
        batch.drop_column("reported_avatar_key")
