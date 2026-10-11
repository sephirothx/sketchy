"""words hidden with their list: which list's takedown hid a word

Revision ID: c1d2e3f4a5b8
Revises: b0c1d2e3f4a7
Create Date: 2026-10-11 00:00:00.000000

A list hidden for its words takes them down (#1425). The words shared the
list's decision byline, which is also how a word's own decision finds its
copies - so restoring one word restored every word of the list, and a
second takedown left the words on the first byline, out of reach of the
restore. `prompt_versions.hidden_with_list_id` names the list instead, and
each word keeps a byline of its own. Nullable and unindexed: it is read
only through the owner's takedown records.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "c1d2e3f4a5b8"
down_revision: str | Sequence[str] | None = "b0c1d2e3f4a7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "prompt_versions",
        sa.Column("hidden_with_list_id", sa.Uuid(as_uuid=True, native_uuid=True), nullable=True),
    )


def downgrade() -> None:
    if op.get_context().dialect.name == "postgresql":
        op.drop_column("prompt_versions", "hidden_with_list_id")
        return
    with op.batch_alter_table("prompt_versions") as batch:
        batch.drop_column("hidden_with_list_id")
