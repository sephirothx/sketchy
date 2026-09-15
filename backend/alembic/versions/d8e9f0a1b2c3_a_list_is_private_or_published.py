"""a list is private or published

Revision ID: d8e9f0a1b2c3
Revises: c7d8e9f0a1b2
Create Date: 2026-09-14 16:00:00.000000

`unlisted` is withdrawn (R-LIST-03). It was a list reachable by anyone holding
its share code, and publishing (R-LIST-11) made it a second way of saying the
same thing with none of the safeguards: a published list is gated, audited,
reviewable and rate-limited, while a share code was a bearer capability that
could be passed on without any of that and could not be taken back short of
turning the list private. A list is now private or it is published.

Every unlisted list becomes private - the one state its owner certainly
agreed to - and its code stops opening it. A room already pinned the revision
it plays, so a game in progress keeps its prompts. The share-code column, its
unique index and the check that paired it with `unlisted` go with the value.

Going back restores the column and the value but not the codes: they were
capabilities, and minting new ones would hand out access nobody granted. Every
list comes back private, which is what it was when the code stopped working.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "d8e9f0a1b2c3"
down_revision: str | Sequence[str] | None = "c7d8e9f0a1b2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "UPDATE prompt_lists SET visibility = 'private' WHERE visibility = 'unlisted'"
    )
    op.drop_index("ix_prompt_lists_share_code", table_name="prompt_lists")
    with op.batch_alter_table("prompt_lists") as batch:
        batch.drop_constraint("ck_prompt_lists_unlisted_share_code", type_="check")
        batch.drop_constraint("ck_prompt_lists_visibility", type_="check")
        batch.create_check_constraint(
            "ck_prompt_lists_visibility", "visibility IN ('private', 'public')"
        )
        batch.drop_column("share_code")


def downgrade() -> None:
    with op.batch_alter_table("prompt_lists") as batch:
        batch.add_column(sa.Column("share_code", sa.String(length=24), nullable=True))
        batch.drop_constraint("ck_prompt_lists_visibility", type_="check")
        batch.create_check_constraint(
            "ck_prompt_lists_visibility",
            "visibility IN ('private', 'unlisted', 'public')",
        )
        batch.create_check_constraint(
            "ck_prompt_lists_unlisted_share_code",
            "visibility != 'unlisted' OR share_code IS NOT NULL",
        )
    op.create_index(
        "ix_prompt_lists_share_code", "prompt_lists", ["share_code"], unique=True
    )
