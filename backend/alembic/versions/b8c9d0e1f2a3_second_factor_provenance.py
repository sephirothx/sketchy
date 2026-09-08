"""record whether a second factor was bound by somebody with the password

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
Create Date: 2026-09-08 18:00:00.000000

Setting up two-factor authentication asked for the password, which is a lot
to ask of a player doing something optional - and the reason it asked was not
really about that moment. It was about promotion: the role gate checked that
a second factor *existed*, not whose it was, so a factor planted with a stolen
cookie would have become the staff factor.

`password_proved_at` moves that question to where it belongs. Enrolment is
free; the column records whether anybody proved the password while binding
the factor, and only the role gate insists on it.

Existing rows are deliberately left null rather than backfilled as proved.
The revision that creates the table is `a7b8c9d0e1f2`, one step back and not
yet released, so there are no such rows to rescue - and were there any, a
blanket backfill would be the wrong answer to them. By the time this column
exists a factor can have been bound with no password at all, so "a row is
here" is not evidence of "its owner put it here"; marking every row proved
would hand provenance to exactly the planted factor the role gate exists to
refuse. Null fails closed, and the way out of it is one `confirm-owner` call,
which asks for the password and a code from the factor - something its owner
can give and somebody who planted it cannot.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "b8c9d0e1f2a3"
down_revision: str | Sequence[str] | None = "a7b8c9d0e1f2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "user_second_factors",
        sa.Column("password_proved_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("user_second_factors", "password_proved_at")
