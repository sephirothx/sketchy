"""give a screenshot nobody decided about an end of its own

Revision ID: e7f8a9b0c1d2
Revises: d6e7f8a9b0c1
Create Date: 2026-09-09 23:40:00.000000

A bug report's screenshot was erased when the report was decided, and only
then. That is a ceiling exactly as long as somebody decides: a report nobody
ever triaged held up to 2 MiB of somebody's screen indefinitely, and it was
the one retained thing in the schema with no maximum age at all (#478).

`expired` joins `none`, `ready` and `erased` so the row can say which of the
two erasures happened. `erased` means a decision was made and took the
picture with it; `expired` means ninety days passed and nobody decided
anything. Labelling the second as the first would put a decision on the
record that never happened - and a reviewer opening the still-pending report
would have no way to tell.

The payload ban is structural, like the one beside it: a row whose status is
`expired` cannot hold pixels, whatever a future code path believes.

The index is the sweep's whole question - an undecided report still holding a
picture, oldest first - and the hourly overdue probe reads it too, so neither
scans the table.

Going back, an expired screenshot becomes `erased`. The pixels are gone
either way and the metadata is untouched; what a rollback loses is the
distinction, not evidence, and without the conversion the restored check
would reject every one of those rows.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "e7f8a9b0c1d2"
down_revision: str | Sequence[str] | None = "d6e7f8a9b0c1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("bug_reports") as batch:
        # A CHECK is its whole expression, so the status list is restated
        # rather than extended.
        batch.drop_constraint("ck_bug_reports_screenshot_status", type_="check")
        batch.create_check_constraint(
            "ck_bug_reports_screenshot_status",
            "screenshot_status IN ('none', 'ready', 'erased', 'expired')",
        )
        batch.create_check_constraint(
            "ck_bug_reports_screenshot_expired",
            "screenshot_status <> 'expired' OR screenshot_payload IS NULL",
        )
    op.create_index(
        "ix_bug_reports_screenshot_expiry",
        "bug_reports",
        ["created_at"],
        postgresql_where=sa.text("status = 'pending' AND screenshot_status = 'ready'"),
        sqlite_where=sa.text("status = 'pending' AND screenshot_status = 'ready'"),
    )


def downgrade() -> None:
    op.drop_index("ix_bug_reports_screenshot_expiry", table_name="bug_reports")
    # Before the check is restored, because it is validated against every row
    # present. An expired screenshot reads as an erased one again.
    op.execute(
        "UPDATE bug_reports SET screenshot_status = 'erased' "
        "WHERE screenshot_status = 'expired'"
    )
    with op.batch_alter_table("bug_reports") as batch:
        batch.drop_constraint("ck_bug_reports_screenshot_expired", type_="check")
        batch.drop_constraint("ck_bug_reports_screenshot_status", type_="check")
        batch.create_check_constraint(
            "ck_bug_reports_screenshot_status",
            "screenshot_status IN ('none', 'ready', 'erased')",
        )
