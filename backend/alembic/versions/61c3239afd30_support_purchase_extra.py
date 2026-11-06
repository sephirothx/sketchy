"""what part of a payment was the one-time extra

Revision ID: 61c3239afd30
Revises: 7a9b0c1d2e3f
Create Date: 2026-11-06 21:00:00.000000

`support_purchases.extra_minor` is the part of `amount_minor` that was the
optional extra, as the provider's line items report it, tax included, so the
payments list can show the split (R-SUP-19). Zero for every row today: none
was recorded. On SQLite the check rides the new column, as `name_style`'s does.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "61c3239afd30"
down_revision: str | Sequence[str] | None = "7a9b0c1d2e3f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CHECK = "extra_minor >= 0 AND extra_minor <= amount_minor"


def upgrade() -> None:
    if op.get_context().dialect.name == "postgresql":
        op.add_column(
            "support_purchases",
            sa.Column("extra_minor", sa.Integer(), server_default="0", nullable=False),
        )
        op.create_check_constraint(
            "ck_support_purchases_extra", "support_purchases", _CHECK, postgresql_not_valid=True
        )
        op.execute("ALTER TABLE support_purchases VALIDATE CONSTRAINT ck_support_purchases_extra")
    else:
        op.execute(
            "ALTER TABLE support_purchases ADD COLUMN extra_minor INTEGER NOT NULL DEFAULT 0 "
            f"CONSTRAINT ck_support_purchases_extra CHECK ({_CHECK})"
        )


def downgrade() -> None:
    if op.get_context().dialect.name == "postgresql":
        op.drop_constraint("ck_support_purchases_extra", "support_purchases", type_="check")
    op.drop_column("support_purchases", "extra_minor")
