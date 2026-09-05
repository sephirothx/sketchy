"""index the foreign-key columns deletes scan

Revision ID: b2c5a9d3e470
Revises: a1b4f8c2d369
Create Date: 2026-09-06 01:30:00.000000

Eight foreign-key columns had no index leading with them, so deleting the
row they point at walked every referencing row (#551): four nullable
moderator/issuer references (SET NULL) get a partial index over the rows
where they are set, and the second column of four join tables gets a reverse
index for the RESTRICT and CASCADE checks that look that way.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "b2c5a9d3e470"
down_revision: str | Sequence[str] | None = "a1b4f8c2d369"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ACTOR_INDEXES = (
    ("ix_prompt_versions_moderated_by", "prompt_versions", "moderated_by_user_id"),
    ("ix_prompt_lists_moderated_by", "prompt_lists", "moderated_by_user_id"),
    ("ix_user_bans_revoked_by", "user_bans", "revoked_by_user_id"),
    ("ix_user_warnings_issued_by", "user_warnings", "issued_by_user_id"),
)
_REVERSE_INDEXES = (
    ("ix_prompt_list_revision_items_prompt_version_id", "prompt_list_revision_items", "prompt_version_id"),
    ("ix_prompt_version_aliases_alias_id", "prompt_version_aliases", "alias_id"),
    ("ix_prompt_version_tags_tag_id", "prompt_version_tags", "tag_id"),
    ("ix_prompt_list_revision_tags_tag_id", "prompt_list_revision_tags", "tag_id"),
)


def upgrade() -> None:
    for name, table, column in _ACTOR_INDEXES:
        op.create_index(
            name,
            table,
            [column],
            unique=False,
            postgresql_where=sa.text(f"{column} IS NOT NULL"),
            sqlite_where=sa.text(f"{column} IS NOT NULL"),
        )
    for name, table, column in _REVERSE_INDEXES:
        op.create_index(name, table, [column], unique=False)


def downgrade() -> None:
    for name, table, _ in reversed(_REVERSE_INDEXES):
        op.drop_index(name, table_name=table)
    for name, table, _ in reversed(_ACTOR_INDEXES):
        op.drop_index(name, table_name=table)
