"""stage a finished game before unpacking it into history

Revision ID: e6f7a8b9c0d1
Revises: d5e6f7a8b9c0
Create Date: 2026-09-08 10:00:00.000000

A finished game used to be written straight into six history tables in one
transaction, three attempts, ten seconds, and then forgotten (#482 made the
loss countable). `finished_game_envelopes` is the durable handoff (#541):
the whole game - history, drawings, prompt usage - is staged as one bounded
row first, and a supervised loop replays it with backoff, deleting the row
on success and keeping it, payload dropped, on terminal failure.
`prompt_usage_batches` records that a usage batch was written and with
what content, so a retry can tell identical from conflicting and a batch
of zero facts from one never written.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "e6f7a8b9c0d1"
down_revision: str | Sequence[str] | None = "d5e6f7a8b9c0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "finished_game_envelopes",
        sa.Column("game_id", sa.Uuid(), nullable=False),
        sa.Column("envelope_version", sa.Integer(), nullable=False),
        sa.Column("payload", sa.LargeBinary(), nullable=True),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("checksum_sha256", sa.String(length=64), nullable=False),
        sa.Column(
            "state", sa.String(length=16), server_default=sa.text("'pending'"), nullable=False
        ),
        sa.Column(
            "history_state",
            sa.String(length=16),
            server_default=sa.text("'pending'"),
            nullable=False,
        ),
        sa.Column(
            "usage_state",
            sa.String(length=16),
            server_default=sa.text("'pending'"),
            nullable=False,
        ),
        sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("claim_token", sa.Uuid(), nullable=True),
        sa.Column("failure_code", sa.String(length=16), nullable=True),
        sa.Column("last_error", sa.String(length=200), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "state IN ('pending', 'processing', 'failed')",
            name="ck_finished_game_envelopes_state",
        ),
        sa.CheckConstraint(
            "history_state IN ('pending', 'done', 'none')",
            name="ck_finished_game_envelopes_history",
        ),
        sa.CheckConstraint(
            "usage_state IN ('pending', 'done', 'none')",
            name="ck_finished_game_envelopes_usage",
        ),
        sa.CheckConstraint(
            "failure_code IN ('conflict', 'exhausted', 'unreadable')",
            name="ck_finished_game_envelopes_failure",
        ),
        sa.CheckConstraint("attempts >= 0", name="ck_finished_game_envelopes_attempts"),
        sa.CheckConstraint("byte_size >= 0", name="ck_finished_game_envelopes_byte_size"),
        sa.CheckConstraint(
            "(state = 'failed') = (failed_at IS NOT NULL AND failure_code IS NOT NULL)",
            name="ck_finished_game_envelopes_failed",
        ),
        sa.CheckConstraint(
            "state = 'failed' OR payload IS NOT NULL",
            name="ck_finished_game_envelopes_payload",
        ),
        sa.CheckConstraint(
            "(state = 'processing') = (claimed_at IS NOT NULL AND claim_token IS NOT NULL)",
            name="ck_finished_game_envelopes_claim",
        ),
        sa.PrimaryKeyConstraint("game_id"),
    )
    op.create_index(
        "ix_finished_game_envelopes_due",
        "finished_game_envelopes",
        ["state", "next_attempt_at"],
        unique=False,
    )
    op.create_table(
        "prompt_usage_batches",
        sa.Column("batch_id", sa.Uuid(), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("fact_count", sa.Integer(), nullable=False),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("fact_count >= 0", name="ck_prompt_usage_batches_fact_count"),
        sa.PrimaryKeyConstraint("batch_id"),
    )


def downgrade() -> None:
    op.drop_table("prompt_usage_batches")
    op.drop_index("ix_finished_game_envelopes_due", table_name="finished_game_envelopes")
    op.drop_table("finished_game_envelopes")
