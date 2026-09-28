"""remember when a session's anomaly was last written to the ledger

Revision ID: b9c0d1e2f3a5
Revises: c1d2e3f4a5b7
Create Date: 2026-09-28 00:00:00.000000

The ledger records a session's device anomalies at most once per interval
(#1242). Throttled against `anomaly_at`, which every switch moves, a client
switching every second wrote one row and never another; the interval is
measured from the last row written instead, claimed by a conditional UPDATE
(#1299 review).
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "b9c0d1e2f3a5"
down_revision: str | Sequence[str] | None = "c1d2e3f4a5b7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "auth_sessions",
        sa.Column("anomaly_audited_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    with op.batch_alter_table("auth_sessions") as batch:
        batch.drop_column("anomaly_audited_at")
