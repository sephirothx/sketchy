"""a session remembers the browser it was last used from

Revision ID: a8b9c0d1e2f4
Revises: b5c6d7e8f9a1
Create Date: 2026-09-24 20:00:00.000000

A session used from a browser it was not issued to is an anomaly (R-AUTH-22),
and the comparison was always against `device_label` - the browser it was
issued to - which never moved. A browser whose coarse label changed for good
(a desktop-site switch, DevTools device emulation, a browser update that
changes the label) then counted as a fresh anomaly on every request: an audit
row per request from any cookie, and a staff session whose step-up was
cleared on every request, so it could never pass a step-up gate again (#1016).

`last_device_label` is the browser the session was last seen from, and the
anomaly compares against that. `device_label` keeps meaning what the session
was issued to. NULL means "the one it was issued to", so no backfill.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "a8b9c0d1e2f4"
down_revision: str | Sequence[str] | None = "b5c6d7e8f9a1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "auth_sessions",
        sa.Column("last_device_label", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("auth_sessions", "last_device_label")
