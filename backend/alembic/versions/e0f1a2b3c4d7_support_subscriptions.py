"""what renews a supporter pass, and the mail that confirms stopping it

Revision ID: e0f1a2b3c4d7
Revises: d9e0f1a2b3c6
Create Date: 2026-11-02 12:00:00.000000

A purchase names the subscription behind it, and `cancellation` joins the
ledger's kinds, so the page can say "ends" instead of "renews" with no flag to
fall out of step (#1473). The outbox learns the confirmation a cancellation
owes (§312k). Nobody has bought anything yet, so nothing needs backfilling.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "e0f1a2b3c4d7"
down_revision: str | Sequence[str] | None = "d9e0f1a2b3c6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_KINDS = "'purchase', 'refund', 'chargeback'"
_TEMPLATES = (
    "'verify_email', 'reset_password', 'password_changed', 'account_banned', 'content_hidden'"
)


def _swap_check(table: str, name: str, condition: str) -> None:
    with op.batch_alter_table(table) as batch:
        batch.drop_constraint(name, type_="check")
        batch.create_check_constraint(name, condition)


def upgrade() -> None:
    op.add_column(
        "support_purchases",
        sa.Column("provider_subscription_id", sa.String(128), nullable=True),
    )
    op.create_index(
        "ix_support_purchases_subscription",
        "support_purchases",
        ["provider_subscription_id"],
    )
    _swap_check(
        "support_purchases",
        "ck_support_purchases_kind",
        f"kind IN ({_KINDS}, 'cancellation')",
    )
    _swap_check(
        "email_outbox",
        "ck_email_outbox_template",
        f"template IN ({_TEMPLATES}, 'support_cancelled')",
    )


def downgrade() -> None:
    op.execute("DELETE FROM email_outbox WHERE template = 'support_cancelled'")
    _swap_check("email_outbox", "ck_email_outbox_template", f"template IN ({_TEMPLATES})")
    op.execute("DELETE FROM support_purchases WHERE kind = 'cancellation'")
    _swap_check("support_purchases", "ck_support_purchases_kind", f"kind IN ({_KINDS})")
    op.drop_index("ix_support_purchases_subscription", table_name="support_purchases")
    with op.batch_alter_table("support_purchases") as batch:
        batch.drop_column("provider_subscription_id")
