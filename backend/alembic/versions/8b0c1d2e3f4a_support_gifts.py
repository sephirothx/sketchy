"""who gave a supporter pass, and the inbox entry that says so

Revision ID: 8b0c1d2e3f4a
Revises: 9c1d2e3f4a5b
Create Date: 2026-11-02 21:00:00.000000

A gift is a purchase whose `user_id` is the beneficiary, so status, the mark and
the refund rule need no change (#1540). Nobody has bought anything yet.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "8b0c1d2e3f4a"
down_revision: str | Sequence[str] | None = "9c1d2e3f4a5b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UUID = sa.Uuid(as_uuid=True, native_uuid=True)
_KINDS = (
    "'warning', 'drawing_shared', 'friend_request', 'friend_accepted', 'game_invite', "
    "'reports_reviewed', 'role', 'supporter_started', 'supporter_ending'"
)


def _swap_kinds(condition: str) -> None:
    with op.batch_alter_table("inbox_entries") as batch:
        batch.drop_constraint("ck_inbox_entries_kind", type_="check")
        batch.create_check_constraint("ck_inbox_entries_kind", condition)


def upgrade() -> None:
    with op.batch_alter_table("support_purchases") as batch:
        batch.add_column(sa.Column("gifted_by_user_id", _UUID, nullable=True))
        batch.add_column(
            sa.Column("gift_anonymous", sa.Boolean(), server_default=sa.false(), nullable=False)
        )
        batch.add_column(
            sa.Column("is_gift", sa.Boolean(), server_default=sa.false(), nullable=False)
        )
        batch.create_foreign_key(
            "fk_support_purchases_gifted_by_user_id",
            "users",
            ["gifted_by_user_id"],
            ["id"],
            ondelete="SET NULL",
        )
    op.create_index(
        "ix_support_purchases_gifted_by_user_id", "support_purchases", ["gifted_by_user_id"]
    )
    _swap_kinds(f"kind IN ({_KINDS}, 'supporter_gifted')")


def downgrade() -> None:
    op.execute("DELETE FROM inbox_entries WHERE kind = 'supporter_gifted'")
    _swap_kinds(f"kind IN ({_KINDS})")
    op.drop_index("ix_support_purchases_gifted_by_user_id", table_name="support_purchases")
    with op.batch_alter_table("support_purchases") as batch:
        batch.drop_constraint("fk_support_purchases_gifted_by_user_id", type_="foreignkey")
        batch.drop_column("is_gift")
        batch.drop_column("gift_anonymous")
        batch.drop_column("gifted_by_user_id")
