"""add immutable identity aliases

Revision ID: d8b3f6a1c470
Revises: c7a1e4d8b250
Create Date: 2026-08-22 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "d8b3f6a1c470"
down_revision: Union[str, Sequence[str], None] = "c7a1e4d8b250"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "identity_aliases",
        sa.Column("id", sa.Uuid(native_uuid=True), nullable=False),
        sa.Column("source_user_id", sa.Uuid(native_uuid=True), nullable=False),
        sa.Column("target_user_id", sa.Uuid(native_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "source_user_id != target_user_id", name="ck_identity_alias_distinct"
        ),
        sa.ForeignKeyConstraint(
            ["source_user_id"], ["users.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["target_user_id"], ["users.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_user_id"),
    )
    op.create_index(
        op.f("ix_identity_aliases_target_user_id"),
        "identity_aliases",
        ["target_user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_identity_aliases_target_user_id"), table_name="identity_aliases"
    )
    op.drop_table("identity_aliases")
