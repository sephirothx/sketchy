"""A save overwrites a list's working copy

Revision ID: a3b4c5d6e7f9
Revises: f2a3b4c5d6e8
Create Date: 2026-10-01 00:00:00.000000

A save wrote the whole list again as a new immutable revision (#1359). The
list's `prompts` rows become its working copy, overwritten in place: they gain
the order the owner gave them, the list row gains the letter histogram that
lived on each revision, `prompt_list_tags` holds the working copy's tags, and a
version a save takes out of a working copy is stamped `unlisted_at`, so it is
collected a grace later rather than kept by a revision.
Each is filled from the revision the list is on now.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "a3b4c5d6e7f9"
down_revision: str | Sequence[str] | None = "f2a3b4c5d6e8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_JSON = sa.JSON(none_as_null=True).with_variant(
    postgresql.JSONB(none_as_null=True), "postgresql"
)
_CURRENT = (
    "FROM prompt_list_revisions r JOIN prompt_lists l "
    "ON l.id = r.prompt_list_id AND l.version = r.version"
)


def upgrade() -> None:
    with op.batch_alter_table("prompts") as batch:
        batch.add_column(
            sa.Column("position", sa.Integer(), server_default=sa.text("0"), nullable=False)
        )
    with op.batch_alter_table("prompt_lists") as batch:
        batch.add_column(
            sa.Column("letter_counts", _JSON, server_default=sa.text("'{}'"), nullable=False)
        )
        batch.add_column(
            sa.Column("letter_total", sa.Integer(), server_default=sa.text("0"), nullable=False)
        )
    op.create_table(
        "prompt_list_tags",
        sa.Column("prompt_list_id", sa.Uuid(), nullable=False),
        sa.Column("tag_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["prompt_list_id"], ["prompt_lists.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tag_id"], ["prompt_tags.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("prompt_list_id", "tag_id"),
    )
    op.create_index("ix_prompt_list_tags_tag_id", "prompt_list_tags", ["tag_id"])
    with op.batch_alter_table("prompt_versions") as batch:
        batch.add_column(sa.Column("unlisted_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("unlisted_from_list_id", sa.Uuid(), nullable=True))
        batch.create_foreign_key(
            "fk_prompt_versions_unlisted_from_list_id",
            "prompt_lists",
            ["unlisted_from_list_id"],
            ["id"],
            ondelete="SET NULL",
        )
    op.create_index(
        "ix_prompt_versions_unlisted_from_list",
        "prompt_versions",
        ["unlisted_from_list_id"],
        postgresql_where=sa.text("unlisted_from_list_id IS NOT NULL"),
        sqlite_where=sa.text("unlisted_from_list_id IS NOT NULL"),
    )
    op.create_index(
        "ix_prompt_versions_unlisted_at",
        "prompt_versions",
        ["unlisted_at"],
        postgresql_where=sa.text("unlisted_at IS NOT NULL"),
        sqlite_where=sa.text("unlisted_at IS NOT NULL"),
    )

    op.execute(
        "UPDATE prompts SET position = COALESCE(("
        "SELECT i.position FROM prompt_list_revision_items i "
        f"JOIN prompt_list_revisions r ON r.id = i.revision_id "
        "JOIN prompt_lists l ON l.id = r.prompt_list_id AND l.version = r.version "
        "WHERE r.prompt_list_id = prompts.prompt_list_id "
        "AND i.prompt_version_id = prompts.prompt_version_id), 0)"
    )
    op.execute(
        f"UPDATE prompt_lists SET letter_counts = (SELECT r.letter_counts {_CURRENT} "
        "WHERE r.prompt_list_id = prompt_lists.id), "
        f"letter_total = (SELECT r.letter_total {_CURRENT} "
        "WHERE r.prompt_list_id = prompt_lists.id) "
        f"WHERE EXISTS (SELECT 1 {_CURRENT} WHERE r.prompt_list_id = prompt_lists.id)"
    )
    op.execute(
        "INSERT INTO prompt_list_tags (prompt_list_id, tag_id) "
        f"SELECT r.prompt_list_id, t.tag_id {_CURRENT} "
        "JOIN prompt_list_revision_tags t ON t.revision_id = r.id"
    )


def downgrade() -> None:
    op.drop_index("ix_prompt_versions_unlisted_at", table_name="prompt_versions")
    op.drop_index("ix_prompt_versions_unlisted_from_list", table_name="prompt_versions")
    with op.batch_alter_table("prompt_versions") as batch:
        batch.drop_constraint("fk_prompt_versions_unlisted_from_list_id", type_="foreignkey")
        batch.drop_column("unlisted_from_list_id")
        batch.drop_column("unlisted_at")
    op.drop_index("ix_prompt_list_tags_tag_id", table_name="prompt_list_tags")
    op.drop_table("prompt_list_tags")
    with op.batch_alter_table("prompt_lists") as batch:
        batch.drop_column("letter_total")
        batch.drop_column("letter_counts")
    with op.batch_alter_table("prompts") as batch:
        batch.drop_column("position")
