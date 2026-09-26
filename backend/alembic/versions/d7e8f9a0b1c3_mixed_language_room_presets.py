"""a room preset may declare a mixed-language room

Revision ID: d7e8f9a0b1c3
Revises: c6d7e8f9a0b2
Create Date: 2026-09-26 18:00:00.000000

A room may now be mixed (`mul`, #1182): each seat plays in the language it
joined with, and the room draws only on content every one of them spells. A
preset carries the language the room will declare, so it admits `mul` too.
Nothing else stores a room's language: rooms live only in memory.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "d7e8f9a0b1c3"
down_revision: str | Sequence[str] | None = "c6d7e8f9a0b2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PROMPT_LANGUAGES = ("en", "de", "es", "fr", "it", "nl", "pt")
ROOM_LANGUAGES = (*PROMPT_LANGUAGES, "mul")


def _replace_check(values: tuple[str, ...]) -> None:
    with op.batch_alter_table("room_presets") as batch:
        batch.drop_constraint("ck_room_presets_prompt_language", type_="check")
        batch.create_check_constraint(
            "ck_room_presets_prompt_language",
            sa.column("prompt_language").in_(values),
        )


def upgrade() -> None:
    _replace_check(ROOM_LANGUAGES)


def downgrade() -> None:
    # A mixed preset has no single language to go back to; one that exists
    # refuses the restored constraint, so the downgrade fails loudly.
    _replace_check(PROMPT_LANGUAGES)
