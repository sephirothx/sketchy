"""Polish is a language to play in and to read the interface in

Revision ID: c0d1e2f3a4b6
Revises: b9c0d1e2f3a5
Create Date: 2026-09-30 00:00:00.000000

`pl` joins the seven (#771) as both a prompt language and an interface
locale, so every CHECK that enumerates either admits it: the four content
tables and the list localizations, the room preset (beside `mul`), the
player's default play language, and the two locale columns.

The downgrade restores the seven. A database holding Polish content refuses
the narrower constraints, so it fails loudly rather than guessing another
language for rows whose owner declared this one.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "c0d1e2f3a4b6"
down_revision: str | Sequence[str] | None = "b9c0d1e2f3a5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SEVEN = ("en", "de", "es", "fr", "it", "nl", "pt")
EIGHT = (*SEVEN, "pl")

# (table, constraint, column, extra values beside the languages)
_CHECKS = (
    ("prompt_versions", "ck_prompt_versions_language", "language", ("zxx",)),
    ("prompt_aliases", "ck_prompt_aliases_language", "language", ("zxx",)),
    ("prompt_lists", "ck_prompt_lists_language", "language", ("zxx",)),
    (
        "prompt_list_revisions",
        "ck_prompt_list_revisions_language",
        "language",
        ("zxx",),
    ),
    (
        "prompt_list_localizations",
        "ck_prompt_list_localizations_locale",
        "locale",
        (),
    ),
    ("room_presets", "ck_room_presets_prompt_language", "prompt_language", ("mul",)),
    ("user_settings", "ck_user_settings_prompt_language", "prompt_language", ()),
    ("user_settings", "ck_user_settings_locale", "locale", ()),
    ("email_outbox", "ck_email_outbox_locale", "locale", ()),
)


def _replace(languages: tuple[str, ...]) -> None:
    for table, name, column, extra in _CHECKS:
        with op.batch_alter_table(table) as batch:
            batch.drop_constraint(name, type_="check")
            batch.create_check_constraint(
                name, sa.column(column).in_((*languages, *extra))
            )


def upgrade() -> None:
    _replace(EIGHT)


def downgrade() -> None:
    _replace(SEVEN)
