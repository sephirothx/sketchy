"""add planned shutdown abandonment facts

Revision ID: g6e0b3d7f261
Revises: f4d8a2c6e150
Create Date: 2026-08-23 00:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "g6e0b3d7f261"
down_revision: str | Sequence[str] | None = "f4d8a2c6e150"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "planned_shutdown_abandonments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("game_id", sa.Uuid(), nullable=False),
        sa.Column("room_instance_id", sa.Uuid(), nullable=False),
        sa.Column("contract_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("reason", sa.String(length=24), nullable=False),
        sa.Column("phase", sa.String(length=24), nullable=False),
        sa.Column("round_number", sa.Integer(), nullable=False),
        sa.Column("completed_turn_count", sa.Integer(), nullable=False),
        sa.Column("seated_player_count", sa.Integer(), nullable=False),
        sa.Column("connected_player_count", sa.Integer(), nullable=False),
        sa.Column("spectator_count", sa.Integer(), nullable=False),
        sa.Column("canvas_action_count", sa.Integer(), nullable=False),
        sa.Column("game_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "observed_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "contract_version = 1", name="ck_shutdown_abandonment_contract"
        ),
        sa.CheckConstraint(
            "reason IN ('drain_timeout')", name="ck_shutdown_abandonment_reason"
        ),
        sa.CheckConstraint(
            "phase IN ('choosing_prompt', 'drawing', 'turn_results', 'game_end')",
            name="ck_shutdown_abandonment_phase",
        ),
        sa.CheckConstraint(
            "round_number >= 0 AND completed_turn_count >= 0",
            name="ck_shutdown_abandonment_progress",
        ),
        sa.CheckConstraint(
            "seated_player_count >= 0 AND connected_player_count >= 0 "
            "AND spectator_count >= 0 AND canvas_action_count >= 0",
            name="ck_shutdown_abandonment_counts",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_planned_shutdown_abandonments_game_id",
        "planned_shutdown_abandonments",
        ["game_id"],
        unique=True,
    )
    op.create_index(
        "ix_planned_shutdown_abandonments_room_instance_id",
        "planned_shutdown_abandonments",
        ["room_instance_id"],
    )
    op.create_index(
        "ix_planned_shutdown_abandonments_observed_at",
        "planned_shutdown_abandonments",
        ["observed_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_planned_shutdown_abandonments_observed_at",
        table_name="planned_shutdown_abandonments",
    )
    op.drop_index(
        "ix_planned_shutdown_abandonments_room_instance_id",
        table_name="planned_shutdown_abandonments",
    )
    op.drop_index(
        "ix_planned_shutdown_abandonments_game_id",
        table_name="planned_shutdown_abandonments",
    )
    op.drop_table("planned_shutdown_abandonments")
