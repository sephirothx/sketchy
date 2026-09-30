"""A copy names the list it came from, on the list

Revision ID: f2a3b4c5d6e8
Revises: e1f2a3b4c5d7
Create Date: 2026-10-01 00:00:00.000000

A copy recorded its origin as `forked_from_revision_id` on its own first
revision, and the copy count, the credit and the lineage all read it there
(R-LIST-17, R-LIST-20, R-LIST-21). Editing the copy superseded that revision,
so a sweep that reclaimed it took all three with it. `prompt_lists` gains
`copied_from_list_id` (SET NULL), filled from the old pointer, and the revision
column goes (#1361).
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "f2a3b4c5d6e8"
down_revision: str | Sequence[str] | None = "e1f2a3b4c5d7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_WHERE = "copied_from_list_id IS NOT NULL"


def upgrade() -> None:
    with op.batch_alter_table("prompt_lists") as batch:
        batch.add_column(sa.Column("copied_from_list_id", sa.Uuid(), nullable=True))
        batch.create_foreign_key(
            "fk_prompt_lists_copied_from_list_id",
            "prompt_lists",
            ["copied_from_list_id"],
            ["id"],
            ondelete="SET NULL",
        )
    op.execute(
        "UPDATE prompt_lists SET copied_from_list_id = ("
        "SELECT source.prompt_list_id FROM prompt_list_revisions copy "
        "JOIN prompt_list_revisions source ON source.id = copy.forked_from_revision_id "
        "WHERE copy.prompt_list_id = prompt_lists.id AND copy.version = 1) "
        "WHERE is_copy"
    )
    op.create_index(
        "ix_prompt_lists_copied_from",
        "prompt_lists",
        ["copied_from_list_id"],
        postgresql_where=sa.text(_WHERE),
        sqlite_where=sa.text(_WHERE),
    )
    op.drop_index(
        "ix_prompt_list_revisions_forked_from_revision_id",
        table_name="prompt_list_revisions",
    )
    with op.batch_alter_table("prompt_list_revisions") as batch:
        batch.drop_column("forked_from_revision_id")


def downgrade() -> None:
    with op.batch_alter_table("prompt_list_revisions") as batch:
        batch.add_column(sa.Column("forked_from_revision_id", sa.Uuid(), nullable=True))
        batch.create_foreign_key(
            "prompt_list_revisions_forked_from_revision_id_fkey",
            "prompt_list_revisions",
            ["forked_from_revision_id"],
            ["id"],
            ondelete="SET NULL",
        )
    op.create_index(
        "ix_prompt_list_revisions_forked_from_revision_id",
        "prompt_list_revisions",
        ["forked_from_revision_id"],
    )
    # Which of the original's revisions a copy was taken from was not kept;
    # the one the original is on now is the nearest true answer.
    op.execute(
        "UPDATE prompt_list_revisions SET forked_from_revision_id = ("
        "SELECT source.id FROM prompt_lists copy "
        "JOIN prompt_lists original ON original.id = copy.copied_from_list_id "
        "JOIN prompt_list_revisions source ON source.prompt_list_id = original.id "
        "AND source.version = original.version "
        "WHERE copy.id = prompt_list_revisions.prompt_list_id) "
        "WHERE version = 1"
    )
    op.drop_index("ix_prompt_lists_copied_from", table_name="prompt_lists")
    with op.batch_alter_table("prompt_lists") as batch:
        batch.drop_constraint("fk_prompt_lists_copied_from_list_id", type_="foreignkey")
        batch.drop_column("copied_from_list_id")
