"""remember every language a player plays in, not only the default

Revision ID: e8f9a0b1c2d4
Revises: d7e8f9a0b1c3
Create Date: 2026-09-27 00:00:00.000000

`prompt_language` stays the default; the others a player plays in are an
ordered list beside it (#1209). Every existing account has none, which is
exactly the one-language behaviour it had before.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "e8f9a0b1c2d4"
down_revision: str | Sequence[str] | None = "d7e8f9a0b1c3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "user_settings",
        sa.Column(
            "extra_prompt_languages",
            sa.JSON(none_as_null=True).with_variant(
                postgresql.JSONB(none_as_null=True), "postgresql"
            ),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
    )


def downgrade() -> None:
    op.drop_column("user_settings", "extra_prompt_languages")
