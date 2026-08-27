"""add bug reports

Revision ID: j3f7b2e9c481
Revises: h2c4f8a1d635
Create Date: 2026-08-27 00:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "j3f7b2e9c481"
down_revision: str | Sequence[str] | None = "h2c4f8a1d635"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TARGET_TYPES = "'user', 'prompt_list', 'prompt_version', 'room', 'app_config'"
TARGET_TYPES_WITH_BUG_REPORT = f"{TARGET_TYPES}, 'bug_report'"


def upgrade() -> None:
    op.create_table(
        "bug_reports",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("reporter_user_id", sa.Uuid(), nullable=True),
        sa.Column("area", sa.String(length=32), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("summary", sa.String(length=200), nullable=False),
        sa.Column("details", sa.Text(), nullable=False),
        sa.Column("build_sha", sa.String(length=64), nullable=True),
        sa.Column("route", sa.String(length=255), nullable=True),
        sa.Column("room_code", sa.String(length=16), nullable=True),
        sa.Column("game_id", sa.Uuid(), nullable=True),
        sa.Column("turn_id", sa.Uuid(), nullable=True),
        sa.Column("client_context", sa.JSON(), nullable=False),
        sa.Column("server_context", sa.JSON(), nullable=False),
        sa.Column(
            "screenshot_status",
            sa.String(length=16),
            server_default="none",
            nullable=False,
        ),
        sa.Column("screenshot_payload", sa.LargeBinary(), nullable=True),
        sa.Column("screenshot_content_type", sa.String(length=64), nullable=True),
        sa.Column("screenshot_byte_size", sa.Integer(), nullable=True),
        sa.Column("screenshot_width", sa.Integer(), nullable=True),
        sa.Column("screenshot_height", sa.Integer(), nullable=True),
        sa.Column("screenshot_checksum_sha256", sa.String(length=64), nullable=True),
        sa.Column(
            "status", sa.String(length=16), server_default="pending", nullable=False
        ),
        sa.Column("reviewed_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("resolution_note", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "area IN ('drawing_and_canvas', 'guessing_and_chat', 'rounds_and_scoring',"
            " 'rooms_and_lobby', 'prompt_lists', 'account_and_settings',"
            " 'connection_and_sync', 'performance', 'accessibility', 'other')",
            name="ck_bug_reports_area",
        ),
        sa.CheckConstraint(
            "severity IN ('blocks_play', 'major', 'minor')",
            name="ck_bug_reports_severity",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'resolved', 'dismissed')",
            name="ck_bug_reports_status",
        ),
        sa.CheckConstraint(
            "screenshot_status IN ('none', 'ready', 'erased')",
            name="ck_bug_reports_screenshot_status",
        ),
        sa.CheckConstraint(
            "screenshot_status <> 'ready' OR ("
            "screenshot_payload IS NOT NULL AND screenshot_byte_size IS NOT NULL "
            "AND screenshot_checksum_sha256 IS NOT NULL "
            "AND screenshot_content_type IS NOT NULL)",
            name="ck_bug_reports_screenshot_ready_identity",
        ),
        sa.CheckConstraint(
            "screenshot_status <> 'erased' OR screenshot_payload IS NULL",
            name="ck_bug_reports_screenshot_erased",
        ),
        sa.CheckConstraint(
            "screenshot_status <> 'none' OR screenshot_payload IS NULL",
            name="ck_bug_reports_screenshot_absent",
        ),
        sa.CheckConstraint(
            "screenshot_byte_size IS NULL OR ("
            "screenshot_byte_size > 0 AND screenshot_byte_size <= 2097152)",
            name="ck_bug_reports_screenshot_byte_size",
        ),
        sa.CheckConstraint(
            "status = 'pending' OR reviewed_at IS NOT NULL",
            name="ck_bug_reports_reviewed_identity",
        ),
        sa.ForeignKeyConstraint(
            ["reporter_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["reviewed_by_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_bug_reports_reporter_user_id", "bug_reports", ["reporter_user_id"])
    op.create_index(
        "ix_bug_reports_reviewed_by_user_id", "bug_reports", ["reviewed_by_user_id"]
    )
    op.create_index(
        "ix_bug_reports_status_created_at", "bug_reports", ["status", "created_at"]
    )

    # The ledger has to be able to name the thing that was acted on, and
    # `audit_events.target_type` is a closed set. Widening it is part of adding
    # the table, not a separate change.
    with op.batch_alter_table("audit_events") as batch:
        batch.drop_constraint("ck_audit_events_target_type", type_="check")
        batch.create_check_constraint(
            "ck_audit_events_target_type",
            f"target_type IS NULL OR target_type IN ({TARGET_TYPES_WITH_BUG_REPORT})",
        )


def downgrade() -> None:
    # Entries naming a bug report would violate the narrower constraint, and a
    # downgrade that silently discarded ledger rows would be worse than one
    # that refuses. They lose their target rather than their existence.
    op.execute(
        """
        UPDATE audit_events
           SET target_type = NULL, target_id = NULL
         WHERE target_type = 'bug_report'
        """
    )
    with op.batch_alter_table("audit_events") as batch:
        batch.drop_constraint("ck_audit_events_target_type", type_="check")
        batch.create_check_constraint(
            "ck_audit_events_target_type",
            f"target_type IS NULL OR target_type IN ({TARGET_TYPES})",
        )
    op.drop_index("ix_bug_reports_status_created_at", table_name="bug_reports")
    op.drop_index("ix_bug_reports_reviewed_by_user_id", table_name="bug_reports")
    op.drop_index("ix_bug_reports_reporter_user_id", table_name="bug_reports")
    op.drop_table("bug_reports")
