"""Publishing makes an immutable edition of a list's working copy

Revision ID: c5d6e7f8a9b2
Revises: b4c5d6e7f8a1
Create Date: 2026-10-01 00:00:00.000000

Publication was a state of the list, so every save reached the catalogue at
once and nothing could be approved as it stood (#1360). Publishing now
snapshots the working copy into a `prompt_list_editions` row with its items
and tags: one `published` and at most one `under_review` per list. A list
already published gets its working copy as edition 1 - live, or pending when
the list was held for review, the hold moving from the list to the edition.
A copy also names the edition it was taken from, while it lasts.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "c5d6e7f8a9b2"
down_revision: str | Sequence[str] | None = "b4c5d6e7f8a1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_JSON = sa.JSON(none_as_null=True).with_variant(
    postgresql.JSONB(none_as_null=True), "postgresql"
)
LANGUAGES = ("en", "de", "es", "fr", "it", "nl", "pt", "pl", "zxx")


def _new_uuid() -> str:
    if op.get_bind().dialect.name == "postgresql":
        return "gen_random_uuid()"
    return "lower(hex(randomblob(16)))"


def upgrade() -> None:
    op.create_table(
        "prompt_list_editions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("prompt_list_id", sa.Uuid(), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("description", sa.Text(), server_default="", nullable=False),
        sa.Column("language", sa.String(length=16), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("letter_counts", _JSON, server_default=sa.text("'{}'"), nullable=False),
        sa.Column("letter_total", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "state IN ('published', 'under_review')", name="ck_prompt_list_editions_state"
        ),
        sa.CheckConstraint("number >= 1", name="ck_prompt_list_editions_number_positive"),
        sa.CheckConstraint(
            sa.column("language").in_(LANGUAGES), name="ck_prompt_list_editions_language"
        ),
        sa.ForeignKeyConstraint(["prompt_list_id"], ["prompt_lists.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("prompt_list_id", "number", name="uq_prompt_list_edition_number"),
    )
    op.create_index(
        "uq_prompt_list_editions_one_per_state",
        "prompt_list_editions",
        ["prompt_list_id", "state"],
        unique=True,
    )
    op.create_table(
        "prompt_list_edition_items",
        sa.Column("edition_id", sa.Uuid(), nullable=False),
        sa.Column("prompt_version_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["edition_id"], ["prompt_list_editions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["prompt_version_id"], ["prompt_versions.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("edition_id", "prompt_version_id"),
        sa.UniqueConstraint("edition_id", "position", name="uq_prompt_list_edition_item_position"),
    )
    op.create_index(
        "ix_prompt_list_edition_items_prompt_version_id",
        "prompt_list_edition_items",
        ["prompt_version_id"],
    )
    op.create_table(
        "prompt_list_edition_tags",
        sa.Column("edition_id", sa.Uuid(), nullable=False),
        sa.Column("tag_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["edition_id"], ["prompt_list_editions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tag_id"], ["prompt_tags.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("edition_id", "tag_id"),
    )
    op.create_index(
        "ix_prompt_list_edition_tags_tag_id", "prompt_list_edition_tags", ["tag_id"]
    )
    with op.batch_alter_table("prompt_lists") as batch:
        batch.add_column(
            sa.Column("edition_count", sa.Integer(), server_default=sa.text("0"), nullable=False)
        )
        batch.add_column(
            sa.Column("content_hash", sa.String(length=64), server_default="", nullable=False)
        )
        batch.add_column(sa.Column("copied_from_edition_id", sa.Uuid(), nullable=True))
        batch.create_foreign_key(
            "fk_prompt_lists_copied_from_edition_id",
            "prompt_list_editions",
            ["copied_from_edition_id"],
            ["id"],
            ondelete="SET NULL",
        )
    # Deleting an edition walks the copies made from it (SET NULL).
    op.create_index(
        "ix_prompt_lists_copied_from_edition",
        "prompt_lists",
        ["copied_from_edition_id"],
        postgresql_where=sa.text("copied_from_edition_id IS NOT NULL"),
        sqlite_where=sa.text("copied_from_edition_id IS NOT NULL"),
    )

    # What is published now becomes edition 1: live, or pending if held.
    op.execute(
        "INSERT INTO prompt_list_editions (id, prompt_list_id, number, state, name, "
        "description, language, content_hash, letter_counts, letter_total, created_at, "
        f"published_at) SELECT {_new_uuid()}, id, 1, "
        "CASE WHEN moderation_state = 'under_review' THEN 'under_review' ELSE 'published' END, "
        "name, description, language, '', letter_counts, letter_total, "
        "COALESCE(published_at, updated_at), "
        "CASE WHEN moderation_state = 'under_review' THEN NULL ELSE published_at END "
        "FROM prompt_lists WHERE visibility = 'public' AND NOT is_bundled "
        "AND deleted_at IS NULL"
    )
    op.execute(
        "INSERT INTO prompt_list_edition_items (edition_id, prompt_version_id, position) "
        "SELECT e.id, p.prompt_version_id, p.position FROM prompt_list_editions e "
        "JOIN prompts p ON p.prompt_list_id = e.prompt_list_id"
    )
    op.execute(
        "INSERT INTO prompt_list_edition_tags (edition_id, tag_id) "
        "SELECT e.id, t.tag_id FROM prompt_list_editions e "
        "JOIN prompt_list_tags t ON t.prompt_list_id = e.prompt_list_id"
    )
    op.execute(
        "UPDATE prompt_lists SET moderation_state = 'active' "
        "WHERE moderation_state = 'under_review' AND NOT is_bundled"
    )
    op.execute(
        "UPDATE prompt_lists SET edition_count = 1 WHERE id IN "
        "(SELECT prompt_list_id FROM prompt_list_editions)"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE prompt_lists SET moderation_state = 'under_review' WHERE id IN "
        "(SELECT prompt_list_id FROM prompt_list_editions WHERE state = 'under_review')"
    )
    op.drop_index("ix_prompt_lists_copied_from_edition", table_name="prompt_lists")
    with op.batch_alter_table("prompt_lists") as batch:
        batch.drop_constraint("fk_prompt_lists_copied_from_edition_id", type_="foreignkey")
        batch.drop_column("copied_from_edition_id")
        batch.drop_column("content_hash")
        batch.drop_column("edition_count")
    op.drop_index("ix_prompt_list_edition_tags_tag_id", table_name="prompt_list_edition_tags")
    op.drop_table("prompt_list_edition_tags")
    op.drop_index(
        "ix_prompt_list_edition_items_prompt_version_id", table_name="prompt_list_edition_items"
    )
    op.drop_table("prompt_list_edition_items")
    op.drop_index("uq_prompt_list_editions_one_per_state", table_name="prompt_list_editions")
    op.drop_table("prompt_list_editions")
