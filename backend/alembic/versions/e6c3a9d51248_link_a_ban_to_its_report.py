"""record which report a suspension was decided from

Revision ID: e6c3a9d51248
Revises: d5b8c2f4a917
Create Date: 2026-08-24 19:30:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "e6c3a9d51248"
down_revision: str | Sequence[str] | None = "d5b8c2f4a917"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # A plain nullable column and an index: no rebuild, so nothing referencing
    # user_bans is disturbed. Existing suspensions keep a null - they were
    # issued before anything recorded what they came from, and guessing would
    # be worse than saying nothing.
    if op.get_bind().dialect.name == "sqlite":
        # SQLite accepts a REFERENCES clause on ADD COLUMN as long as the
        # default is null, but alembic renders the constraint as a separate
        # ALTER, which it does not support. Raw DDL rather than batch mode:
        # rebuilding a table is what we spend migrations avoiding here.
        op.execute(
            sa.text(
                "ALTER TABLE user_bans ADD COLUMN source_report_id CHAR(32) "
                "REFERENCES player_reports(id) ON DELETE SET NULL"
            )
        )
    else:
        op.add_column(
            "user_bans",
            sa.Column(
                "source_report_id",
                sa.Uuid(as_uuid=True, native_uuid=True),
                sa.ForeignKey("player_reports.id", ondelete="SET NULL"),
                nullable=True,
            ),
        )
    op.create_index(
        "ix_user_bans_source_report_id", "user_bans", ["source_report_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_user_bans_source_report_id", table_name="user_bans")
    op.drop_column("user_bans", "source_report_id")
