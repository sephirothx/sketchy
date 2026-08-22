"""add selected turn prompt identity and truthful legacy provenance

Revision ID: d4b7f1a3c965
Revises: c3a6e9f2b854
Create Date: 2026-08-23 00:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "d4b7f1a3c965"
down_revision: str | Sequence[str] | None = "c3a6e9f2b854"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("turn_records") as batch_op:
        batch_op.add_column(
            sa.Column("prompt_version_id", sa.Uuid(), nullable=True)
        )
        batch_op.add_column(
            sa.Column(
                "prompt_source_kind",
                sa.String(length=24),
                server_default="legacy_unknown",
                nullable=False,
            )
        )
        batch_op.create_foreign_key(
            "fk_turn_records_prompt_version_id_prompt_versions",
            "prompt_versions",
            ["prompt_version_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch_op.create_index(
            "ix_turn_records_prompt_version_id", ["prompt_version_id"]
        )
        batch_op.create_check_constraint(
            "ck_turn_records_prompt_source_kind",
            "prompt_source_kind IN "
            "('legacy_unknown', 'curated', 'custom', 'builtin_fallback')",
        )
        batch_op.create_check_constraint(
            "ck_turn_records_prompt_identity",
            "(prompt_source_kind = 'curated' AND prompt_version_id IS NOT NULL) "
            "OR (prompt_source_kind != 'curated' AND prompt_version_id IS NULL)",
        )


def downgrade() -> None:
    with op.batch_alter_table("turn_records") as batch_op:
        batch_op.drop_constraint("ck_turn_records_prompt_identity", type_="check")
        batch_op.drop_constraint(
            "ck_turn_records_prompt_source_kind", type_="check"
        )
        batch_op.drop_index("ix_turn_records_prompt_version_id")
        batch_op.drop_constraint(
            "fk_turn_records_prompt_version_id_prompt_versions", type_="foreignkey"
        )
        batch_op.drop_column("prompt_source_kind")
        batch_op.drop_column("prompt_version_id")
