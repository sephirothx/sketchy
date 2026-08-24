"""name the subject of entries three writers left blank

Revision ID: f7a2d4b83e06
Revises: e6c3a9d51248
Create Date: 2026-08-24 19:55:00.000000

"""
from collections.abc import Sequence

from alembic import op


revision: str = "f7a2d4b83e06"
down_revision: str | Sequence[str] | None = "e6c3a9d51248"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # a1c7e4b9d360 backfilled every entry that named a user. Three writers -
    # lifting a suspension, and making or removing a block - were not updated
    # to fill the pair, so entries written after that migration named a user in
    # target_user_id and left the ledger's subject empty. They are not missing
    # the fact, only the columns that render it, so the same backfill finishes
    # the job rather than guessing at anything.
    op.execute(
        """
        UPDATE audit_events
           SET target_type = 'user', target_id = CAST(target_user_id AS VARCHAR)
         WHERE target_user_id IS NOT NULL
           AND target_type IS NULL
        """
    )


def downgrade() -> None:
    # Nothing to undo: this only writes down what target_user_id already said.
    pass
