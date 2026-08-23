"""allow one open prompt content report per reporter and target

Revision ID: e8c2f5a91b04
Revises: d3f8b1e6c294
Create Date: 2026-08-23 21:10:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "e8c2f5a91b04"
down_revision: str | Sequence[str] | None = "d3f8b1e6c294"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Existing duplicates would block the unique index, so fold them first:
    # keep each reporter's earliest open report per target and dismiss the
    # rest, which is what a moderator would have done by hand.
    op.execute(
        """
        UPDATE prompt_content_reports
           SET status = 'dismissed'
         WHERE status = 'pending'
           AND id NOT IN (
               SELECT MIN(id) FROM prompt_content_reports
                WHERE status = 'pending'
                GROUP BY reporter_user_id, prompt_list_id, prompt_version_id
           )
        """
    )
    op.create_index(
        "uq_prompt_content_reports_open_list",
        "prompt_content_reports",
        ["reporter_user_id", "prompt_list_id"],
        unique=True,
        postgresql_where=sa.text("status = 'pending' AND prompt_version_id IS NULL"),
        sqlite_where=sa.text("status = 'pending' AND prompt_version_id IS NULL"),
    )
    op.create_index(
        "uq_prompt_content_reports_open_prompt",
        "prompt_content_reports",
        ["reporter_user_id", "prompt_version_id"],
        unique=True,
        postgresql_where=sa.text(
            "status = 'pending' AND prompt_version_id IS NOT NULL"
        ),
        sqlite_where=sa.text(
            "status = 'pending' AND prompt_version_id IS NOT NULL"
        ),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_prompt_content_reports_open_prompt",
        table_name="prompt_content_reports",
    )
    op.drop_index(
        "uq_prompt_content_reports_open_list",
        table_name="prompt_content_reports",
    )
