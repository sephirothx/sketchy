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
