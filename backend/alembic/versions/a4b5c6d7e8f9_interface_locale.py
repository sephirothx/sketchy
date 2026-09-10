"""remember which language a player reads the interface in

Revision ID: a4b5c6d7e8f9
Revises: f3a4b5c6d7e8
Create Date: 2026-09-11 00:00:00.000000

The interface is being translated (#759), so a player has a second language
preference and it is not the first one. `prompt_language` is the language they
*play* in - it decides what a room draws from and how a guess is folded.
`locale` is the language they *read* in. A Dutch speaker playing an English
room is ordinary, and one column could not describe them.

The registries are also bound by different things: a prompt language needs
matching semantics before it can exist at all (N-09), while an interface
locale needs only somebody to have written the words. They hold the same seven
values today and are free to diverge, which is the other reason this is its
own column rather than a reuse of that one.

Seeded from the browser at registration and a setting from then on, so the
choice follows a player to their other devices rather than living in whichever
one they happened to set it on.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "a4b5c6d7e8f9"
down_revision: str | Sequence[str] | None = "f3a4b5c6d7e8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INTERFACE_LOCALES = ("en", "de", "es", "fr", "it", "nl", "pt")


def upgrade() -> None:
    op.add_column(
        "user_settings",
        sa.Column(
            "locale",
            sa.String(length=8),
            nullable=False,
            server_default="en",
        ),
    )
    with op.batch_alter_table("user_settings") as batch:
        batch.create_check_constraint(
            "ck_user_settings_locale",
            sa.column("locale").in_(INTERFACE_LOCALES),
        )


def downgrade() -> None:
    with op.batch_alter_table("user_settings") as batch:
        batch.drop_constraint("ck_user_settings_locale", type_="check")
    op.drop_column("user_settings", "locale")
