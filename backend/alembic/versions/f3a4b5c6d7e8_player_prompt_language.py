"""remember which language a player plays in

Revision ID: f3a4b5c6d7e8
Revises: e7f8a9b0c1d2
Create Date: 2026-09-10 03:40:00.000000

A room declares its prompt language (R-PROMPT-02) and the lobby now leads with
the language its visitor plays in. The browser can say what that is, and for a
visitor with no account it is all there is to go on - but a header is a
property of the device, not of the person, so a player who sets it on their
laptop would have to set it again on their phone.

This is deliberately **not** an interface locale: it is the language a player
plays in, which is the same distinction `prompt_lists` draws between its
content language and its localized catalogue copy.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "f3a4b5c6d7e8"
down_revision: str | Sequence[str] | None = "e7f8a9b0c1d2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PROMPT_LANGUAGES = ("en", "de", "es", "fr", "it", "nl", "pt")


def upgrade() -> None:
    op.add_column(
        "user_settings",
        sa.Column(
            "prompt_language",
            sa.String(length=8),
            nullable=False,
            server_default="en",
        ),
    )
    with op.batch_alter_table("user_settings") as batch:
        batch.create_check_constraint(
            "ck_user_settings_prompt_language",
            sa.column("prompt_language").in_(PROMPT_LANGUAGES),
        )


def downgrade() -> None:
    with op.batch_alter_table("user_settings") as batch:
        batch.drop_constraint("ck_user_settings_prompt_language", type_="check")
    op.drop_column("user_settings", "prompt_language")
