"""add drawing evidence to player reports

A report filed about the player drawing may carry the canvas as it stood
when the report was made. Copied into its own row rather than referenced:
the turn's own drawing keeps changing after the report, is written only when
the game ends, and is erased with the drawer's account. What the reporter saw
is what a moderator judges, so that is what is kept.

Revision ID: b1c5a9e3f470
Revises: a0b4f8d2e369
Create Date: 2026-09-05 12:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "b1c5a9e3f470"
down_revision: str | Sequence[str] | None = "a0b4f8d2e369"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "player_report_drawing_evidence",
        sa.Column("report_id", sa.Uuid(), nullable=False),
        sa.Column("turn_id_snapshot", sa.Uuid(), nullable=False),
        sa.Column("round_number", sa.Integer(), nullable=False),
        sa.Column("prompt_snapshot", sa.String(length=64), nullable=False),
        sa.Column("action_count", sa.Integer(), nullable=False),
        sa.Column("format_magic", sa.String(length=4), nullable=False),
        sa.Column("format_version", sa.Integer(), nullable=False),
        sa.Column("payload", sa.LargeBinary(), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("checksum_sha256", sa.String(length=64), nullable=False),
        sa.Column(
            "captured_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["report_id"], ["player_reports.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("report_id"),
        # Named explicitly so SQLite's batch mode can drop and rebuild them.
        sa.CheckConstraint(
            "byte_size > 0 AND byte_size <= 8388608",
            name="ck_report_drawing_evidence_byte_size",
        ),
        sa.CheckConstraint(
            "round_number >= 1 AND action_count >= 0",
            name="ck_report_drawing_evidence_counts",
        ),
    )


def downgrade() -> None:
    op.drop_table("player_report_drawing_evidence")
