"""add immutable prompt list revisions and stable prompt links

Revision ID: b7e1c4d9a263
Revises: a4d8e2c7f615
Create Date: 2026-08-22 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "b7e1c4d9a263"
down_revision: Union[str, Sequence[str], None] = "a4d8e2c7f615"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_LANGUAGES = "'en', 'de', 'es', 'fr', 'it', 'nl', 'pt'"


def upgrade() -> None:
    op.create_table(
        "prompt_list_revisions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("prompt_list_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("language", sa.String(length=16), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "version >= 1", name="ck_prompt_list_revisions_version_positive"
        ),
        sa.CheckConstraint(
            f"language IN ({_LANGUAGES})",
            name="ck_prompt_list_revisions_language",
        ),
        sa.ForeignKeyConstraint(
            ["prompt_list_id"], ["prompt_lists.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "prompt_list_id", "version", name="uq_prompt_list_revision_version"
        ),
    )
    op.create_index(
        op.f("ix_prompt_list_revisions_prompt_list_id"),
        "prompt_list_revisions",
        ["prompt_list_id"],
    )
    op.create_table(
        "prompt_list_revision_items",
        sa.Column("revision_id", sa.Uuid(), nullable=False),
        sa.Column("prompt_version_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "position >= 0",
            name="ck_prompt_list_revision_items_position_nonnegative",
        ),
        sa.ForeignKeyConstraint(
            ["prompt_version_id"], ["prompt_versions.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["revision_id"], ["prompt_list_revisions.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("revision_id", "prompt_version_id"),
        sa.UniqueConstraint(
            "revision_id",
            "position",
            name="uq_prompt_list_revision_item_position",
        ),
    )
    with op.batch_alter_table("prompts") as batch_op:
        batch_op.add_column(sa.Column("concept_id", sa.Uuid(), nullable=True))
        batch_op.add_column(
            sa.Column("prompt_version_id", sa.Uuid(), nullable=True)
        )
        batch_op.create_foreign_key(
            "fk_prompts_concept_id_prompt_concepts",
            "prompt_concepts",
            ["concept_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch_op.create_foreign_key(
            "fk_prompts_prompt_version_id_prompt_versions",
            "prompt_versions",
            ["prompt_version_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch_op.create_unique_constraint(
            "uq_prompt_list_concept", ["prompt_list_id", "concept_id"]
        )
        batch_op.create_index(
            op.f("ix_prompts_concept_id"), ["concept_id"], unique=False
        )
        batch_op.create_index(
            op.f("ix_prompts_prompt_version_id"),
            ["prompt_version_id"],
            unique=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("prompts") as batch_op:
        batch_op.drop_index(op.f("ix_prompts_prompt_version_id"))
        batch_op.drop_index(op.f("ix_prompts_concept_id"))
        batch_op.drop_constraint("uq_prompt_list_concept", type_="unique")
        batch_op.drop_constraint(
            "fk_prompts_prompt_version_id_prompt_versions", type_="foreignkey"
        )
        batch_op.drop_constraint(
            "fk_prompts_concept_id_prompt_concepts", type_="foreignkey"
        )
        batch_op.drop_column("prompt_version_id")
        batch_op.drop_column("concept_id")
    op.drop_table("prompt_list_revision_items")
    op.drop_index(
        op.f("ix_prompt_list_revisions_prompt_list_id"),
        table_name="prompt_list_revisions",
    )
    op.drop_table("prompt_list_revisions")
