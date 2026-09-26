"""a prompt list may be in no language at all

Revision ID: c6d7e8f9a0b2
Revises: a8b9c0d1e2f4
Create Date: 2026-09-26 12:00:00.000000

Some lists are not in a language: Pokémon, brands, famous people, places. Until
now such a list had to be saved once per language, and a room in another
language could not pick it (#821). `zxx` is BCP-47's "no linguistic content",
so the four content tables that carry a language admit it. Rooms and players
do not: a room still declares a language its guesses are folded under, and an
agnostic list is matched under that one.

A room preset now stores the language the room will declare. It used to be
derived from the preset's lists, and a preset of agnostic lists alone has
nothing to derive it from. No backfill: nothing is deployed, so an existing
preset takes the default and is checked against its lists when it is applied.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "c6d7e8f9a0b2"
down_revision: str | Sequence[str] | None = "a8b9c0d1e2f4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PROMPT_LANGUAGES = ("en", "de", "es", "fr", "it", "nl", "pt")
PROMPT_LIST_LANGUAGES = (*PROMPT_LANGUAGES, "zxx")

_CONTENT_CHECKS = (
    ("prompt_versions", "ck_prompt_versions_language"),
    ("prompt_aliases", "ck_prompt_aliases_language"),
    ("prompt_lists", "ck_prompt_lists_language"),
    ("prompt_list_revisions", "ck_prompt_list_revisions_language"),
)


def _replace_language_checks(values: tuple[str, ...]) -> None:
    for table, name in _CONTENT_CHECKS:
        with op.batch_alter_table(table) as batch:
            batch.drop_constraint(name, type_="check")
            batch.create_check_constraint(name, sa.column("language").in_(values))


def upgrade() -> None:
    _replace_language_checks(PROMPT_LIST_LANGUAGES)
    op.add_column(
        "room_presets",
        sa.Column(
            "prompt_language",
            sa.String(length=8),
            nullable=False,
            server_default="en",
        ),
    )
    with op.batch_alter_table("room_presets") as batch:
        batch.create_check_constraint(
            "ck_room_presets_prompt_language",
            sa.column("prompt_language").in_(PROMPT_LANGUAGES),
        )


def downgrade() -> None:
    with op.batch_alter_table("room_presets") as batch:
        batch.drop_constraint("ck_room_presets_prompt_language", type_="check")
    op.drop_column("room_presets", "prompt_language")
    # Agnostic content has no language to go back to, and inventing one would
    # rewrite what its owner declared. A database holding any refuses the
    # restored constraint, so the downgrade fails loudly instead.
    _replace_language_checks(PROMPT_LANGUAGES)
