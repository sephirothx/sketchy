"""name what an audited action was performed on

Revision ID: a1c7e4b9d360
Revises: e8c2f5a91b04
Create Date: 2026-08-24 10:20:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "a1c7e4b9d360"
down_revision: str | Sequence[str] | None = "e8c2f5a91b04"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


TARGET_TYPES = "'user', 'prompt_list', 'prompt_version', 'room', 'app_config'"


def upgrade() -> None:
    with op.batch_alter_table("audit_events") as batch:
        batch.add_column(sa.Column("target_type", sa.String(length=32), nullable=True))
        batch.add_column(sa.Column("target_id", sa.String(length=64), nullable=True))
        batch.create_check_constraint(
            "ck_audit_events_target_pair",
            "(target_type IS NULL AND target_id IS NULL) OR "
            "(target_type IS NOT NULL AND target_id IS NOT NULL)",
        )
        batch.create_check_constraint(
            "ck_audit_events_target_type",
            f"target_type IS NULL OR target_type IN ({TARGET_TYPES})",
        )
    op.create_index(
        "ix_audit_events_target", "audit_events", ["target_type", "target_id"]
    )

    # Existing rows already name a user in target_user_id; the pair simply says
    # so in the terms every later row will use. Rows with no target - a bulk
    # retention purge acts on no single row - stay null on both.
    op.execute(
        """
        UPDATE audit_events
           SET target_type = 'user', target_id = CAST(target_user_id AS VARCHAR)
         WHERE target_user_id IS NOT NULL
        """
    )


def downgrade() -> None:
    op.drop_index("ix_audit_events_target", table_name="audit_events")
    with op.batch_alter_table("audit_events") as batch:
        batch.drop_constraint("ck_audit_events_target_type", type_="check")
        batch.drop_constraint("ck_audit_events_target_pair", type_="check")
        batch.drop_column("target_id")
        batch.drop_column("target_type")
