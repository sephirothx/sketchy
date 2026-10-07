"""gallery by sharing: share rows, share notices, first-share and withdrawal times

Revision ID: e7f8a9b0c1d4
Revises: d6e7f8a9b0c3
Create Date: 2026-10-07 00:00:00.000000

A drawing used to be in the Gallery because its game was public (#524); now
it is there because somebody shared it (#1430). `turn_drawing_shares` holds
who did, one row per sharer's seat; `turn_drawings.gallery_shared_at` is the
earliest of them, kept on the drawing row so the Gallery orders by a column,
and `gallery_withdrawn_at` is the drawer's act of taking it back out.
`drawing_share_notices` tells a drawer once that somebody else shared their
drawing. The Gallery's ranking indexes become partial on the shared rows,
since those are the only rows any order reads.

Nothing is deployed, so nothing is carried across: no drawing is shared after
this runs, and the pins - which now imply a share (R-PIN-03) - are cleared
rather than turned into shares nobody made. The index and column changes on
`turn_drawings` run in the revision's transaction for the same reason
(`d7e8f9a0b1c2` explains why `autocommit_block()` is not available to it).

Going back drops the tables, the columns and the partial indexes and
restores the status-prefixed ones; the cleared pins do not come back.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "e7f8a9b0c1d4"
down_revision: str | Sequence[str] | None = "d6e7f8a9b0c3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SHARED = "gallery_shared_at IS NOT NULL"
_UUID = sa.Uuid(as_uuid=True, native_uuid=True)


def upgrade() -> None:
    # online-ddl: nothing is deployed; the table has no live writer to lock out.
    op.drop_index("ix_turn_drawings_gallery_top", table_name="turn_drawings")
    # online-ddl: nothing is deployed; the table has no live writer to lock out.
    op.drop_index("ix_turn_drawings_gallery_hot", table_name="turn_drawings")
    with op.batch_alter_table("turn_drawings") as batch:
        batch.add_column(
            sa.Column("gallery_shared_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch.add_column(
            sa.Column("gallery_withdrawn_at", sa.DateTime(timezone=True), nullable=True)
        )
    # online-ddl: nothing is deployed; the table has no live writer to lock out.
    op.create_index(
        "ix_turn_drawings_gallery_top",
        "turn_drawings",
        ["reaction_count", "gallery_shared_at"],
        postgresql_where=sa.text(_SHARED),
        sqlite_where=sa.text(_SHARED),
    )
    # online-ddl: nothing is deployed; the table has no live writer to lock out.
    op.create_index(
        "ix_turn_drawings_gallery_hot",
        "turn_drawings",
        ["hot_score"],
        postgresql_where=sa.text(_SHARED),
        sqlite_where=sa.text(_SHARED),
    )
    # online-ddl: nothing is deployed; the table has no live writer to lock out.
    op.create_index(
        "ix_turn_drawings_gallery_new",
        "turn_drawings",
        ["gallery_shared_at"],
        postgresql_where=sa.text(_SHARED),
        sqlite_where=sa.text(_SHARED),
    )
    # Every drawing ranked by Hot until now carried a score off its game's
    # finish; an unshared drawing's score is zero from here on (R-GAL-05).
    # online-ddl: nothing is deployed; there are no live rows to batch over.
    op.execute("UPDATE turn_drawings SET hot_score = 0")

    op.create_table(
        "turn_drawing_shares",
        sa.Column("turn_id", _UUID, primary_key=True),
        sa.Column("participant_id", _UUID, primary_key=True),
        sa.Column("game_id", _UUID, nullable=False),
        sa.Column(
            "user_id",
            _UUID,
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["game_id", "turn_id"],
            ["turn_records.game_id", "turn_records.id"],
            name="fk_turn_drawing_shares_turn_same_game",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["game_id", "participant_id"],
            ["game_participants.game_id", "game_participants.id"],
            name="fk_turn_drawing_shares_seat_same_game",
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_turn_drawing_shares_participant_id",
        "turn_drawing_shares",
        ["participant_id"],
    )
    op.create_index(
        "ix_turn_drawing_shares_user_id", "turn_drawing_shares", ["user_id"]
    )

    op.create_table(
        "drawing_share_notices",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column(
            "user_id",
            _UUID,
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("game_id", _UUID, nullable=False),
        sa.Column("turn_id", _UUID, nullable=False),
        sa.Column("sharer_participant_id", _UUID, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["game_id", "turn_id"],
            ["turn_records.game_id", "turn_records.id"],
            name="fk_drawing_share_notices_turn_same_game",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["game_id", "sharer_participant_id"],
            ["game_participants.game_id", "game_participants.id"],
            name="fk_drawing_share_notices_sharer_same_game",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("turn_id", name="uq_drawing_share_notices_turn_id"),
    )
    op.create_index(
        "ix_drawing_share_notices_user_pending",
        "drawing_share_notices",
        ["user_id", "acknowledged_at"],
    )
    op.create_index(
        "ix_drawing_share_notices_sharer",
        "drawing_share_notices",
        ["sharer_participant_id"],
    )

    op.execute("DELETE FROM profile_drawing_pins")


def downgrade() -> None:
    op.drop_index("ix_drawing_share_notices_sharer", table_name="drawing_share_notices")
    op.drop_index(
        "ix_drawing_share_notices_user_pending", table_name="drawing_share_notices"
    )
    op.drop_table("drawing_share_notices")
    op.drop_index("ix_turn_drawing_shares_user_id", table_name="turn_drawing_shares")
    op.drop_index(
        "ix_turn_drawing_shares_participant_id", table_name="turn_drawing_shares"
    )
    op.drop_table("turn_drawing_shares")
    op.drop_index("ix_turn_drawings_gallery_new", table_name="turn_drawings")
    op.drop_index("ix_turn_drawings_gallery_hot", table_name="turn_drawings")
    op.drop_index("ix_turn_drawings_gallery_top", table_name="turn_drawings")
    with op.batch_alter_table("turn_drawings") as batch:
        batch.drop_column("gallery_withdrawn_at")
        batch.drop_column("gallery_shared_at")
    op.create_index(
        "ix_turn_drawings_gallery_top", "turn_drawings", ["status", "reaction_count"]
    )
    op.create_index(
        "ix_turn_drawings_gallery_hot", "turn_drawings", ["status", "hot_score"]
    )
