"""add versioned game rule snapshots

Revision ID: b2f5d8e1a743
Revises: a1e4c7d9b632
Create Date: 2026-08-23 00:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "b2f5d8e1a743"
down_revision: str | Sequence[str] | None = "a1e4c7d9b632"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Zero/empty is an explicit legacy marker: the historical parameters cannot
    # be reconstructed safely from the mode name alone.
    with op.batch_alter_table("game_records") as batch_op:
        batch_op.add_column(
            sa.Column(
                "scoring_version",
                sa.Integer(),
                server_default=sa.text("0"),
                nullable=False,
            )
        )
        batch_op.add_column(
            sa.Column(
                "rule_snapshot_version",
                sa.Integer(),
                server_default=sa.text("0"),
                nullable=False,
            )
        )
        batch_op.add_column(
            sa.Column(
                "rule_snapshot",
                sa.JSON(),
                server_default=sa.text("'{}'"),
                nullable=False,
            )
        )
        batch_op.create_check_constraint(
            "ck_game_records_scoring_version", "scoring_version >= 0"
        )
        batch_op.create_check_constraint(
            "ck_game_records_rule_snapshot_version", "rule_snapshot_version >= 0"
        )


def downgrade() -> None:
    with op.batch_alter_table("game_records") as batch_op:
        batch_op.drop_constraint(
            "ck_game_records_rule_snapshot_version", type_="check"
        )
        batch_op.drop_constraint("ck_game_records_scoring_version", type_="check")
        batch_op.drop_column("rule_snapshot")
        batch_op.drop_column("rule_snapshot_version")
        batch_op.drop_column("scoring_version")
