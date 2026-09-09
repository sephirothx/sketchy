"""record what rule a warning or a suspension was about

Revision ID: a3b4c5d6e7f8
Revises: f2a3b4c5d6e7
Create Date: 2026-09-09 20:00:00.000000

A decision carried a moderator's sentence and nothing else, so a terse note
left the player it was about with only that sentence to work out what they had
done. The category is the moderator's own finding - never the reporters'
claim, which would tell the reported player how people they cannot see chose
to characterise them (R-MOD-12).

Optional, so a decision taken in a hurry is never blocked by it, and every
notice has to read correctly with it absent. The vocabulary is the six report
reasons: one set of words for what a complaint says and for what a moderator
found, rather than two that would have to be kept in step.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "a3b4c5d6e7f8"
down_revision: str | Sequence[str] | None = "f2a3b4c5d6e7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CATEGORIES = (
    "'harassment', 'offensive_drawing', 'inappropriate_name', 'cheating',"
    " 'spam', 'inappropriate_avatar'"
)


def upgrade() -> None:
    for table, name in (
        ("user_warnings", "ck_user_warnings_category"),
        ("user_bans", "ck_user_bans_category"),
    ):
        with op.batch_alter_table(table) as batch:
            batch.add_column(sa.Column("category", sa.String(length=32), nullable=True))
            batch.create_check_constraint(
                name, f"category IS NULL OR category IN ({_CATEGORIES})"
            )


def downgrade() -> None:
    for table, name in (
        ("user_bans", "ck_user_bans_category"),
        ("user_warnings", "ck_user_warnings_category"),
    ):
        with op.batch_alter_table(table) as batch:
            batch.drop_constraint(name, type_="check")
            batch.drop_column("category")
