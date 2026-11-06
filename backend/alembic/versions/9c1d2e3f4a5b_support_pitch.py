"""what the supporter pass tells a player, and the nudge they can close

Revision ID: 9c1d2e3f4a5b
Revises: e0f1a2b3c4d7
Create Date: 2026-11-02 18:00:00.000000

Two inbox kinds, when a pass starts and fourteen days before it ends or renews,
and `user_settings.supporter_nudge_dismissed`, so the end-of-game line stays
closed on every device (#1475).
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "9c1d2e3f4a5b"
down_revision: str | Sequence[str] | None = "e0f1a2b3c4d7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_KINDS = (
    "'warning', 'drawing_shared', 'friend_request', 'friend_accepted', 'game_invite', "
    "'reports_reviewed', 'role'"
)


def _swap_kinds(condition: str) -> None:
    with op.batch_alter_table("inbox_entries") as batch:
        batch.drop_constraint("ck_inbox_entries_kind", type_="check")
        batch.create_check_constraint("ck_inbox_entries_kind", condition)


def upgrade() -> None:
    op.add_column(
        "user_settings",
        sa.Column(
            "supporter_nudge_dismissed", sa.Boolean(), server_default=sa.false(), nullable=False
        ),
    )
    _swap_kinds(f"kind IN ({_KINDS}, 'supporter_started', 'supporter_ending')")


def downgrade() -> None:
    op.execute("DELETE FROM inbox_entries WHERE kind IN ('supporter_started', 'supporter_ending')")
    _swap_kinds(f"kind IN ({_KINDS})")
    with op.batch_alter_table("user_settings") as batch:
        batch.drop_column("supporter_nudge_dismissed")
