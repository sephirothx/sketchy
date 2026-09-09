"""tell a reporter their report was looked at

Revision ID: b4c5d6e7f8a9
Revises: a3b4c5d6e7f8
Create Date: 2026-09-09 21:00:00.000000

Reporting into silence is what teaches people not to bother. A reporter is
told their report was reviewed and closed - and nothing else: what was decided
is the reported player's business, and an outcome told back to whoever asked
would make a report a way to learn things about somebody.

`reporter_notified_at` is what stops it being said twice. Nullable, because
most reports have not been decided yet and none of the existing ones has been
announced.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "b4c5d6e7f8a9"
down_revision: str | Sequence[str] | None = "a3b4c5d6e7f8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("player_reports") as batch:
        batch.add_column(
            sa.Column("reporter_notified_at", sa.DateTime(timezone=True), nullable=True)
        )
    # The reader asks one question - "any of mine decided and not yet said?" -
    # so it is answered from an index over exactly that, and only for the rows
    # that can still answer yes.
    op.create_index(
        "ix_player_reports_reporter_unannounced",
        "player_reports",
        ["reporter_user_id"],
        postgresql_where=sa.text(
            "reporter_notified_at IS NULL AND status <> 'pending'"
        ),
        sqlite_where=sa.text("reporter_notified_at IS NULL AND status <> 'pending'"),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_player_reports_reporter_unannounced", table_name="player_reports"
    )
    with op.batch_alter_table("player_reports") as batch:
        batch.drop_column("reporter_notified_at")
