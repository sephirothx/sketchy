"""record whether only an administrator may lift a suspension

Revision ID: c1d2e3f4a5b7
Revises: e8f9a0b1c2d4
Create Date: 2026-09-28 00:00:00.000000

A moderator may not lift a suspension an administrator placed, nor one of a
member of staff (R-BAN-01, #1239). Read from the roles held today, a demotion
moved that boundary: demote the administrator who placed it, or the staff
member under it, and a moderator could lift it. The boundary is recorded
when the suspension is placed (#1294 review).

A suspension already in force when this runs has no record of the roles it
was placed under, so it is taken to need an administrator: the conservative
reading of an unknown, and one an administrator can always lift. Revoked ones
are history and keep the default.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "c1d2e3f4a5b7"
down_revision: str | Sequence[str] | None = "e8f9a0b1c2d4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "user_bans",
        sa.Column("lift_requires_admin", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    user_bans = sa.table(
        "user_bans",
        sa.column("lift_requires_admin", sa.Boolean()),
        sa.column("revoked_at", sa.DateTime(timezone=True)),
    )
    op.execute(
        user_bans.update()
        .where(user_bans.c.revoked_at.is_(None))
        .values(lift_requires_admin=sa.true())
    )


def downgrade() -> None:
    with op.batch_alter_table("user_bans") as batch:
        batch.drop_column("lift_requires_admin")
