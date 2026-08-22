"""add prompt language registry and localized list catalogue copy

Revision ID: a4d8e2c7f615
Revises: f3a7c1d9e502
Create Date: 2026-08-22 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "a4d8e2c7f615"
down_revision: Union[str, Sequence[str], None] = "f3a7c1d9e502"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_LANGUAGES = "'en', 'de', 'es', 'fr', 'it', 'nl', 'pt'"


def _replace_language_check(table: str, constraint: str, values: str) -> None:
    with op.batch_alter_table(table) as batch_op:
        batch_op.drop_constraint(constraint, type_="check")
        batch_op.create_check_constraint(constraint, f"language IN ({values})")


def upgrade() -> None:
    _replace_language_check(
        "prompt_lists", "ck_prompt_lists_language", _LANGUAGES
    )
    _replace_language_check(
        "prompt_versions", "ck_prompt_versions_language", _LANGUAGES
    )
    _replace_language_check(
        "prompt_aliases", "ck_prompt_aliases_language", _LANGUAGES
    )
    op.create_table(
        "prompt_list_localizations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("prompt_list_id", sa.Uuid(), nullable=False),
        sa.Column("locale", sa.String(length=16), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column(
            "description",
            sa.String(length=255),
            server_default="",
            nullable=False,
        ),
        sa.CheckConstraint(
            f"locale IN ({_LANGUAGES})",
            name="ck_prompt_list_localizations_locale",
        ),
        sa.ForeignKeyConstraint(
            ["prompt_list_id"], ["prompt_lists.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "prompt_list_id",
            "locale",
            name="uq_prompt_list_localization_locale",
        ),
    )
    op.create_index(
        op.f("ix_prompt_list_localizations_prompt_list_id"),
        "prompt_list_localizations",
        ["prompt_list_id"],
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_prompt_list_localizations_prompt_list_id"),
        table_name="prompt_list_localizations",
    )
    op.drop_table("prompt_list_localizations")

    # The old schema can represent only English. Removing unsupported content
    # is the only downgrade that keeps its language claims truthful.
    op.execute(sa.text("DELETE FROM prompt_aliases WHERE language <> 'en'"))
    op.execute(sa.text("DELETE FROM prompt_versions WHERE language <> 'en'"))
    op.execute(sa.text("DELETE FROM prompt_lists WHERE language <> 'en'"))
    _replace_language_check(
        "prompt_lists", "ck_prompt_lists_language", "'en'"
    )
    _replace_language_check(
        "prompt_versions", "ck_prompt_versions_language", "'en'"
    )
    _replace_language_check(
        "prompt_aliases", "ck_prompt_aliases_language", "'en'"
    )
