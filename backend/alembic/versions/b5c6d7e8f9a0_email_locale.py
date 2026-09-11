"""write each queued message in the language its recipient chose

Revision ID: b5c6d7e8f9a0
Revises: a4b5c6d7e8f9
Create Date: 2026-09-11 00:30:00.000000

Email is the one place the server legitimately writes prose, because there is
no client at the other end to write it (R-I18N-01). So it is also the only
place the reader's language has to be *stored* rather than resolved.

Frozen at queue time rather than read at send time. The outbox is a durable
queue swept by a loop, so a send can happen hours after the queue - and
resolving late would mean a preference changed in between silently
re-languages a message that was already composed, including the message about
the security event that prompted the change.

`en` for the rows already queued and for an account with no locale of its
own: it is what they would have been written in anyway.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "b5c6d7e8f9a0"
down_revision: str | Sequence[str] | None = "a4b5c6d7e8f9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INTERFACE_LOCALES = ("en", "de", "es", "fr", "it", "nl", "pt")


def upgrade() -> None:
    op.add_column(
        "email_outbox",
        sa.Column("locale", sa.String(length=8), nullable=False, server_default="en"),
    )
    with op.batch_alter_table("email_outbox") as batch:
        batch.create_check_constraint(
            "ck_email_outbox_locale", sa.column("locale").in_(INTERFACE_LOCALES)
        )


def downgrade() -> None:
    with op.batch_alter_table("email_outbox") as batch:
        batch.drop_constraint("ck_email_outbox_locale", type_="check")
    op.drop_column("email_outbox", "locale")
