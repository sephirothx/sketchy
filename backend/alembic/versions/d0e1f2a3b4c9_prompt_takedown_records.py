"""A takedown is recorded per owner, not searched for in every revision

Revision ID: d0e1f2a3b4c9
Revises: c0d1e2f3a4b6
Create Date: 2026-10-01 00:00:00.000000

`prompt_takedowns` holds one row per owner a hidden word reaches (#1357). A
save reads it instead of searching every revision of every list the owner has
held, so revisions no longer double as the takedown record and the reclaim
drops its hidden-word and pending-report holds.

Pre-launch, so nothing is backfilled: no database holds takedowns anybody keeps.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "d0e1f2a3b4c9"
down_revision: str | Sequence[str] | None = "c0d1e2f3a4b6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "prompt_takedowns",
        sa.Column(
            "owner_user_id",
            sa.Uuid(as_uuid=True, native_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "concept_id",
            sa.Uuid(as_uuid=True, native_uuid=True),
            sa.ForeignKey("prompt_concepts.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_prompt_takedowns_concept", "prompt_takedowns", ["concept_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_prompt_takedowns_concept", table_name="prompt_takedowns")
    op.drop_table("prompt_takedowns")
