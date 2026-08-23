"""add stored drawings for completed turns

Revision ID: d3f8b1e6c294
Revises: g6e0b3d7f261
Create Date: 2026-08-23 17:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.db.types import UTCDateTime


revision: str = "d3f8b1e6c294"
down_revision: str | Sequence[str] | None = "g6e0b3d7f261"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "turn_drawings",
        sa.Column("turn_id", sa.Uuid(), nullable=False),
        sa.Column("game_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("format_magic", sa.String(length=4), nullable=True),
        sa.Column("format_version", sa.Integer(), nullable=True),
        sa.Column("payload", sa.LargeBinary(), nullable=True),
        sa.Column("byte_size", sa.Integer(), nullable=True),
        sa.Column("checksum_sha256", sa.String(length=64), nullable=True),
        sa.Column("object_key", sa.String(length=256), nullable=True),
        sa.Column("unavailable_reason", sa.String(length=32), nullable=True),
        sa.Column("failure_code", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            UTCDateTime(),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            UTCDateTime(),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("stored_at", UTCDateTime(), nullable=True),
        sa.Column("deleted_at", UTCDateTime(), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending', 'ready', 'unavailable', 'failed', 'deleted')",
            name="ck_turn_drawings_status",
        ),
        sa.CheckConstraint(
            "status <> 'ready' OR ("
            "format_magic IS NOT NULL AND format_version IS NOT NULL "
            "AND byte_size IS NOT NULL AND checksum_sha256 IS NOT NULL "
            "AND (payload IS NOT NULL OR object_key IS NOT NULL))",
            name="ck_turn_drawings_ready_identity",
        ),
        sa.CheckConstraint(
            "status NOT IN ('unavailable', 'deleted') OR payload IS NULL",
            name="ck_turn_drawings_erased",
        ),
        sa.CheckConstraint(
            "(status = 'unavailable') = (unavailable_reason IS NOT NULL)",
            name="ck_turn_drawings_unavailable_reason",
        ),
        sa.CheckConstraint(
            "byte_size IS NULL OR (byte_size > 0 AND byte_size <= 8388608)",
            name="ck_turn_drawings_byte_size",
        ),
        sa.ForeignKeyConstraint(["game_id"], ["game_records.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["turn_id"], ["turn_records.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("turn_id"),
    )
    op.create_index("ix_turn_drawings_game_id", "turn_drawings", ["game_id"])
    op.create_index(
        "ix_turn_drawings_status_created_at",
        "turn_drawings",
        ["status", "created_at"],
    )


def downgrade() -> None:
    # Drawings exist nowhere else, so downgrading discards them. Games, turns
    # and every other history fact are untouched.
    op.drop_index("ix_turn_drawings_status_created_at", table_name="turn_drawings")
    op.drop_index("ix_turn_drawings_game_id", table_name="turn_drawings")
    op.drop_table("turn_drawings")
