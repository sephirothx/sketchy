"""the supporter pass's purchase ledger and the hide-my-mark setting

Revision ID: d9e0f1a2b3c6
Revises: c8d9e0f1a2b5
Create Date: 2026-11-02 00:00:00.000000

`support_purchases` records what a provider told us, one row per event; status
is a query over it, never a stored flag (#1472). `user_settings` gains
`show_supporter_mark`, on by default. Nobody has bought anything yet, so the
table starts empty.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "d9e0f1a2b3c6"
down_revision: str | Sequence[str] | None = "c8d9e0f1a2b5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UUID = sa.Uuid(as_uuid=True, native_uuid=True)


def upgrade() -> None:
    op.create_table(
        "support_purchases",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column(
            "user_id", _UUID, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column("provider", sa.String(16), nullable=False),
        sa.Column("provider_event_id", sa.String(128), nullable=False),
        sa.Column("provider_order_id", sa.String(128), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("amount_minor", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "provider IN ('paddle', 'stub')", name="ck_support_purchases_provider"
        ),
        sa.CheckConstraint(
            "kind IN ('purchase', 'refund', 'chargeback')", name="ck_support_purchases_kind"
        ),
        sa.CheckConstraint(
            "(kind = 'purchase' AND period_start IS NOT NULL "
            "AND (period_end IS NULL OR period_end > period_start)) OR "
            "(kind <> 'purchase' AND period_start IS NULL AND period_end IS NULL)",
            name="ck_support_purchases_period",
        ),
        sa.CheckConstraint("amount_minor >= 0", name="ck_support_purchases_amount"),
        sa.UniqueConstraint(
            "provider", "provider_event_id", name="uq_support_purchases_provider_event"
        ),
    )
    op.create_index(
        "ix_support_purchases_order", "support_purchases", ["provider", "provider_order_id"]
    )
    op.create_index("ix_support_purchases_user_id", "support_purchases", ["user_id"])
    op.add_column(
        "user_settings",
        sa.Column(
            "show_supporter_mark", sa.Boolean(), server_default=sa.true(), nullable=False
        ),
    )


def downgrade() -> None:
    if op.get_context().dialect.name == "postgresql":
        op.drop_column("user_settings", "show_supporter_mark")
    else:
        with op.batch_alter_table("user_settings") as batch:
            batch.drop_column("show_supporter_mark")
    op.drop_index("ix_support_purchases_user_id", table_name="support_purchases")
    op.drop_index("ix_support_purchases_order", table_name="support_purchases")
    op.drop_table("support_purchases")
