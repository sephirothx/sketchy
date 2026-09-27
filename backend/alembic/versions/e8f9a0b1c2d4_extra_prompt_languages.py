"""remember every language a player plays in, not only the default

Revision ID: e8f9a0b1c2d4
Revises: d7e8f9a0b1c3
Create Date: 2026-09-27 00:00:00.000000

`prompt_language` stays the default; the others a player plays in are an
ordered list beside it (#1209). Every existing account has none, which is
exactly the one-language behaviour it had before. Two CHECKs bound what a JSON
column can be bounded by on both engines - its text is a short list, and never
names the default - so two racing PATCHes cannot store the default twice.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "e8f9a0b1c2d4"
down_revision: str | Sequence[str] | None = "d7e8f9a0b1c3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Mirrors `EXTRA_PROMPT_LANGUAGES_TEXT_MAX` in the models.
TEXT_MAX = 48


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
    with op.batch_alter_table("user_settings") as batch:
        batch.create_check_constraint(
            "ck_user_settings_extra_prompt_languages_list",
            sa.text(
                "CAST(extra_prompt_languages AS TEXT) LIKE '[%' "
                f"AND length(CAST(extra_prompt_languages AS TEXT)) <= {TEXT_MAX}"
            ),
        )
        batch.create_check_constraint(
            "ck_user_settings_default_not_extra",
            sa.text(
                "CAST(extra_prompt_languages AS TEXT) NOT LIKE ('%\"' || prompt_language || '\"%')"
            ),
        )


def downgrade() -> None:
    with op.batch_alter_table("user_settings") as batch:
        batch.drop_constraint("ck_user_settings_default_not_extra", type_="check")
        batch.drop_constraint("ck_user_settings_extra_prompt_languages_list", type_="check")
    op.drop_column("user_settings", "extra_prompt_languages")
