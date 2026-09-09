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

Nothing is backfilled. Existing rows are `unscoped` and, if already decided,
would violate the decision-group check, so the check is added only for rows
written from here on - which, before launch, is all of them.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "e1f2a3b4c5d6"
down_revision: str | Sequence[str] | None = "d0e1f2a3b4c5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


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
