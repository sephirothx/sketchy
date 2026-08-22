"""add stable game persistence identity payload hash

Revision ID: f6d1a8c3e520
Revises: e4b7c2d9a615
Create Date: 2026-08-23 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "f6d1a8c3e520"
down_revision: Union[str, Sequence[str], None] = "e4b7c2d9a615"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # The primary key already provides the stable uniqueness boundary. Legacy
    # rows get an empty digest because their original input payload cannot be
    # reconstructed exactly; every new application write supplies SHA-256.
    with op.batch_alter_table("game_records") as batch_op:
        batch_op.add_column(
            sa.Column(
                "payload_hash",
                sa.String(length=64),
                server_default="",
                nullable=False,
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("game_records") as batch_op:
        batch_op.drop_column("payload_hash")
