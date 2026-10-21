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


def _open_target(columns: list[str], *, drop_first: bool = True) -> None:
    if drop_first:
        op.drop_index("uq_player_reports_open_target", table_name="player_reports")
    op.create_index(
        "uq_player_reports_open_target", "player_reports", columns, unique=True,
        postgresql_where=sa.text("status = 'pending'"), sqlite_where=sa.text("status = 'pending'"),
    )


def upgrade() -> None:
    # A Solo report is the reporter's on their serve, and the report row is
    # marked so their export leaves it out: its ids would lead to the drawer.
    op.add_column(
        "player_reports",
        sa.Column("via_solo", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    # One open report per reporter and player, counted apart for Solo: a Solo
    # report must never make another door's report a 409 (#1494 review).
    _open_target(["reporter_user_id", "reported_user_id", "via_solo"])
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


# A reporter's open Solo report and open report from another door about the
# same player: allowed here, not before.
_TWIN_REPORTS = """
SELECT count(*) FROM player_reports AS solo
JOIN player_reports AS other
  ON other.reporter_user_id = solo.reporter_user_id
 AND other.reported_user_id = solo.reported_user_id
WHERE solo.via_solo AND NOT other.via_solo
  AND solo.status = 'pending' AND other.status = 'pending'
"""


def downgrade() -> None:
    # The older index holds one open report per reporter and player. Closing
    # one of a pair here would be a moderation decision nobody made, and
    # deleting it would lose its evidence: refuse, before anything changes,
    # until a moderator has decided one of each pair (#1494 review).
    twins = op.get_bind().execute(sa.text(_TWIN_REPORTS)).scalar()
    if twins:
        raise RuntimeError(
            f"{twins} reporter/player pair(s) hold an open Solo report and another open "
            "report. The schema before this revision allows one open report per pair; "
            "decide one report of each pair, then downgrade again."
        )
    with op.batch_alter_table("solo_serves") as batch:
        batch.drop_column("report_details")
        batch.drop_column("reported_at")
    _open_target(["reporter_user_id", "reported_user_id"], drop_first=True)
    with op.batch_alter_table("player_reports") as batch:
        batch.drop_column("via_solo")
    op.drop_index("ix_solo_gallery_shares_held", table_name="solo_gallery_shares")
    op.drop_index("ix_solo_gallery_shares_user_id", table_name="solo_gallery_shares")
    op.drop_table("solo_gallery_shares")
