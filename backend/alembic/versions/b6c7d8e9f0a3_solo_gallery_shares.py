"""solo gallery shares: a drawing a Solo player put in the Gallery

Revision ID: b6c7d8e9f0a3
Revises: a5b6c7d8e9f2
Create Date: 2026-10-15 00:00:00.000000

A Solo player (#1434) may share a drawing they were served, under its
drawer's name, as anybody who sat in the game may (R-SHARE-02, amended). They
sat in no seat, so the share hangs off the account in a table of its own,
which the Gallery's projections count beside `turn_drawing_shares`. A share
of a drawing in a Daily still open somewhere waits (`release_at`) until the
date has ended everywhere. A Solo report is kept on the reporter's serve
(`reported_at`, `report_details`) and its report row marked `via_solo`, so
the reporter's export never carries the turn or game behind it.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "b6c7d8e9f0a3"
down_revision: str | Sequence[str] | None = "a5b6c7d8e9f2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UUID = sa.Uuid(as_uuid=True, native_uuid=True)
_HELD = "release_at IS NOT NULL"


def upgrade() -> None:
    # A Solo report is the reporter's on their serve, and the report row is
    # marked so their export leaves it out: its ids would lead to the drawer.
    op.add_column(
        "player_reports",
        sa.Column("via_solo", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("solo_serves", sa.Column("reported_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("solo_serves", sa.Column("report_details", sa.Text(), nullable=True))
    op.create_table(
        "solo_gallery_shares",
        sa.Column(
            "turn_id", _UUID, sa.ForeignKey("turn_records.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "user_id", _UUID, sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("release_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("entered_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "(release_at IS NULL) = (entered_at IS NOT NULL)", name="ck_solo_gallery_shares_held"
        ),
    )
    op.create_index("ix_solo_gallery_shares_user_id", "solo_gallery_shares", ["user_id"])
    op.create_index(
        "ix_solo_gallery_shares_held",
        "solo_gallery_shares",
        ["release_at"],
        postgresql_where=sa.text(_HELD),
        sqlite_where=sa.text(_HELD),
    )


def downgrade() -> None:
    with op.batch_alter_table("solo_serves") as batch:
        batch.drop_column("report_details")
        batch.drop_column("reported_at")
    with op.batch_alter_table("player_reports") as batch:
        batch.drop_column("via_solo")
    op.drop_index("ix_solo_gallery_shares_held", table_name="solo_gallery_shares")
    op.drop_index("ix_solo_gallery_shares_user_id", table_name="solo_gallery_shares")
    op.drop_table("solo_gallery_shares")
