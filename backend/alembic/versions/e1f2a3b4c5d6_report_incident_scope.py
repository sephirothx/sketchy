"""record where a report happened and which decision covered it

Revision ID: e1f2a3b4c5d6
Revises: d0e1f2a3b4c5
Create Date: 2026-09-09 10:00:00.000000

Reports of one incident are reviewed and decided together (#620). Two facts
have to be on the row before anything can group on them.

`scope` and `room_instance_id` say where the complaint happened. Both report
routes already worked this out and threw it away: the socket path holds the
live room, and the REST path proves every cited line came from one room
instance or all from the lobby. A paired check keeps them one fact rather
than two columns that can disagree.

`decision_group_id` says which decision covered the report - minted once per
moderator action rather than once per report, so a decision over an incident
leaves every report it covered pointing at the same value. Time-ordered, so
the closed-case stream can page decisions from an ordered index scan.

Existing rows take `unscoped`, which is what they are: none of them recorded
where the complaint happened, so none of them may be grouped by it.

A report already decided is backfilled to be its own decision group, because
that is what it was - every decision before this migration covered exactly one
report. Without it the decision-group check would refuse the table: a CHECK is
validated against every row present, not only the ones written after it.

The group ids are minted **in decision order**, not copied from the reports.
Both are UUIDv7, so either would satisfy the column - but the closed-case
stream reads *newest decision first* straight off this id, and a report's own
id is time-ordered by when it was **filed**. Copying it would sort migrated
cases by when they were complained about, putting one decided months ago ahead
of one decided yesterday whenever the older complaint was reviewed later.
"""
from collections.abc import Sequence
import uuid

import sqlalchemy as sa
from alembic import op


revision: str = "e1f2a3b4c5d6"
down_revision: str | Sequence[str] | None = "d0e1f2a3b4c5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _backfill_decision_groups(table_name: str) -> None:
    """Give every already-decided report a group of its own, in decision order.

    Each was decided on its own, so each is its own group. The id is minted
    here rather than copied from the report because the closed-case stream
    reads *newest decision first* straight off it: a report's own id is
    time-ordered by when it was filed, which is not the same order and is not
    the one that stream means.

    One statement per row, which is what ordering demands and what a one-time
    walk of an old table can afford; the ids are handed out in a single
    ordered pass, so the relative order of the decisions is exact even where
    their timestamps tie.
    """
    table = sa.table(
        table_name,
        sa.column("id", sa.Uuid()),
        sa.column("status", sa.String()),
        sa.column("decision_group_id", sa.Uuid()),
        sa.column("reviewed_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    connection = op.get_bind()
    decided = (
        connection.execute(
            sa.select(table.c.id)
            .where(table.c.status != "pending", table.c.decision_group_id.is_(None))
            .order_by(
                sa.func.coalesce(table.c.reviewed_at, table.c.updated_at).asc(),
                table.c.id.asc(),
            )
        )
        .scalars()
        .all()
    )
    for report_id in decided:
        connection.execute(
            table.update()
            .where(table.c.id == report_id)
            .values(decision_group_id=uuid.uuid7())
        )


def upgrade() -> None:
    with op.batch_alter_table("player_reports") as batch:
        batch.add_column(
            sa.Column(
                "scope",
                sa.String(length=16),
                nullable=False,
                server_default="unscoped",
            )
        )
        batch.add_column(sa.Column("room_instance_id", sa.Uuid(), nullable=True))
        batch.add_column(sa.Column("decision_group_id", sa.Uuid(), nullable=True))
    # Before the check, not after: it is validated against every row already
    # in the table.
    _backfill_decision_groups("player_reports")
    with op.batch_alter_table("player_reports") as batch:
        batch.create_check_constraint(
            "ck_player_reports_scope",
            "scope IN ('room', 'lobby', 'unscoped')",
        )
        batch.create_check_constraint(
            "ck_player_reports_scope_instance",
            "(scope = 'room' AND room_instance_id IS NOT NULL)"
            " OR (scope <> 'room' AND room_instance_id IS NULL)",
        )
        batch.create_check_constraint(
            "ck_player_reports_decision_group",
            "status = 'pending' OR decision_group_id IS NOT NULL",
        )
    op.create_index(
        "ix_player_reports_decision_group",
        "player_reports",
        ["decision_group_id"],
        postgresql_where=sa.text("decision_group_id IS NOT NULL"),
        sqlite_where=sa.text("decision_group_id IS NOT NULL"),
    )

    with op.batch_alter_table("prompt_content_reports") as batch:
        batch.add_column(sa.Column("decision_group_id", sa.Uuid(), nullable=True))
    _backfill_decision_groups("prompt_content_reports")
    with op.batch_alter_table("prompt_content_reports") as batch:
        batch.create_check_constraint(
            "ck_prompt_content_reports_decision_group",
            "status = 'pending' OR decision_group_id IS NOT NULL",
        )
    op.create_index(
        "ix_prompt_content_reports_decision_group",
        "prompt_content_reports",
        ["decision_group_id"],
        postgresql_where=sa.text("decision_group_id IS NOT NULL"),
        sqlite_where=sa.text("decision_group_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_prompt_content_reports_decision_group",
        table_name="prompt_content_reports",
    )
    with op.batch_alter_table("prompt_content_reports") as batch:
        batch.drop_constraint(
            "ck_prompt_content_reports_decision_group", type_="check"
        )
        batch.drop_column("decision_group_id")

    op.drop_index("ix_player_reports_decision_group", table_name="player_reports")
    with op.batch_alter_table("player_reports") as batch:
        batch.drop_constraint("ck_player_reports_decision_group", type_="check")
        batch.drop_constraint("ck_player_reports_scope_instance", type_="check")
        batch.drop_constraint("ck_player_reports_scope", type_="check")
        batch.drop_column("decision_group_id")
        batch.drop_column("room_instance_id")
        batch.drop_column("scope")
