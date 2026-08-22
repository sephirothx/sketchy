"""add prompt-level moderation and durable content reports

Revision ID: d2a6f9c4b718
Revises: c8f2a5d1e374
Create Date: 2026-08-23 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "d2a6f9c4b718"
down_revision: Union[str, Sequence[str], None] = "c8f2a5d1e374"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("prompt_versions") as batch_op:
        batch_op.add_column(
            sa.Column(
                "moderation_state",
                sa.String(length=16),
                server_default="active",
                nullable=False,
            )
        )
        batch_op.add_column(
            sa.Column("moderated_by_user_id", sa.Uuid(), nullable=True)
        )
        batch_op.add_column(
            sa.Column("moderated_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.create_check_constraint(
            "ck_prompt_versions_moderation_state",
            "moderation_state IN ('active', 'under_review', 'hidden')",
        )
        batch_op.create_foreign_key(
            "fk_prompt_versions_moderated_by_user_id_users",
            "users",
            ["moderated_by_user_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_index(
            op.f("ix_prompt_versions_moderation_state"),
            ["moderation_state"],
            unique=False,
        )

    op.create_table(
        "prompt_content_reports",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("reporter_user_id", sa.Uuid(), nullable=True),
        sa.Column("reported_owner_user_id", sa.Uuid(), nullable=True),
        sa.Column("prompt_list_id", sa.Uuid(), nullable=True),
        sa.Column("prompt_version_id", sa.Uuid(), nullable=True),
        sa.Column("target_type", sa.String(length=16), nullable=False),
        sa.Column("list_name_snapshot", sa.String(length=64), nullable=False),
        sa.Column("prompt_snapshot", sa.String(length=64), nullable=True),
        sa.Column("reason", sa.String(length=32), nullable=False),
        sa.Column("details", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=16),
            server_default="pending",
            nullable=False,
        ),
        sa.Column("reviewed_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("resolution_note", sa.Text(), nullable=True),
        sa.Column(
            "resolution_moderation_state", sa.String(length=16), nullable=True
        ),
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
            "target_type IN ('list', 'prompt')",
            name="ck_prompt_content_reports_target_type",
        ),
        sa.CheckConstraint(
            "(target_type = 'list' AND prompt_snapshot IS NULL) OR "
            "(target_type = 'prompt' AND prompt_snapshot IS NOT NULL)",
            name="ck_prompt_content_reports_target_snapshot",
        ),
        sa.CheckConstraint(
            "reporter_user_id IS NULL OR reported_owner_user_id IS NULL "
            "OR reporter_user_id != reported_owner_user_id",
            name="ck_prompt_content_reports_not_self",
        ),
        sa.CheckConstraint(
            "reason IN ('inappropriate', 'hateful_or_abusive', 'sexual_content', "
            "'violence', 'spam', 'other')",
            name="ck_prompt_content_reports_reason",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'resolved', 'dismissed')",
            name="ck_prompt_content_reports_status",
        ),
        sa.CheckConstraint(
            "resolution_moderation_state IN ('active', 'under_review', 'hidden')",
            name="ck_prompt_content_reports_resolution_state",
        ),
        sa.ForeignKeyConstraint(
            ["reporter_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["reported_owner_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["prompt_list_id"], ["prompt_lists.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["prompt_version_id"], ["prompt_versions.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["reviewed_by_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_prompt_content_reports_reporter_user_id"),
        "prompt_content_reports",
        ["reporter_user_id"],
    )
    op.create_index(
        op.f("ix_prompt_content_reports_reported_owner_user_id"),
        "prompt_content_reports",
        ["reported_owner_user_id"],
    )
    op.create_index(
        op.f("ix_prompt_content_reports_prompt_list_id"),
        "prompt_content_reports",
        ["prompt_list_id"],
    )
    op.create_index(
        op.f("ix_prompt_content_reports_prompt_version_id"),
        "prompt_content_reports",
        ["prompt_version_id"],
    )
    op.create_index(
        op.f("ix_prompt_content_reports_reviewed_by_user_id"),
        "prompt_content_reports",
        ["reviewed_by_user_id"],
    )
    op.create_index(
        "ix_prompt_content_reports_status_created_at",
        "prompt_content_reports",
        ["status", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_prompt_content_reports_status_created_at",
        table_name="prompt_content_reports",
    )
    op.drop_index(
        op.f("ix_prompt_content_reports_reviewed_by_user_id"),
        table_name="prompt_content_reports",
    )
    op.drop_index(
        op.f("ix_prompt_content_reports_prompt_version_id"),
        table_name="prompt_content_reports",
    )
    op.drop_index(
        op.f("ix_prompt_content_reports_prompt_list_id"),
        table_name="prompt_content_reports",
    )
    op.drop_index(
        op.f("ix_prompt_content_reports_reported_owner_user_id"),
        table_name="prompt_content_reports",
    )
    op.drop_index(
        op.f("ix_prompt_content_reports_reporter_user_id"),
        table_name="prompt_content_reports",
    )
    op.drop_table("prompt_content_reports")

    with op.batch_alter_table("prompt_versions") as batch_op:
        batch_op.drop_index(op.f("ix_prompt_versions_moderation_state"))
        batch_op.drop_constraint(
            "fk_prompt_versions_moderated_by_user_id_users",
            type_="foreignkey",
        )
        batch_op.drop_constraint(
            "ck_prompt_versions_moderation_state", type_="check"
        )
        batch_op.drop_column("moderated_at")
        batch_op.drop_column("moderated_by_user_id")
        batch_op.drop_column("moderation_state")
