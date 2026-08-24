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
    # One statement per index, because the indexes are what the fold has to
    # match: NULL is distinct from NULL in a unique index, so a list-level
    # report and a prompt-level one are governed by different keys.
    #
    # ROW_NUMBER rather than MIN(id): PostgreSQL has no MIN aggregate for uuid,
    # and SQLite only accepts one because it keeps uuids as text. Ordering by
    # a uuid is fine on both - it is the aggregate that does not exist.
    op.execute(
        """
        UPDATE prompt_content_reports
           SET status = 'dismissed'
         WHERE id IN (
             SELECT id FROM (
                 SELECT id, ROW_NUMBER() OVER (
                            PARTITION BY reporter_user_id, prompt_list_id
                            ORDER BY created_at, id
                        ) AS row_position
                   FROM prompt_content_reports
                  WHERE status = 'pending' AND prompt_version_id IS NULL
             ) ranked
             WHERE row_position > 1
         )
        """
    )
    op.execute(
        """
        UPDATE prompt_content_reports
           SET status = 'dismissed'
         WHERE id IN (
             SELECT id FROM (
                 SELECT id, ROW_NUMBER() OVER (
                            PARTITION BY reporter_user_id, prompt_version_id
                            ORDER BY created_at, id
                        ) AS row_position
                   FROM prompt_content_reports
                  WHERE status = 'pending' AND prompt_version_id IS NOT NULL
             ) ranked
             WHERE row_position > 1
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
