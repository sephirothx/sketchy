"""add stable prompt concepts and immutable localized versions

Revision ID: f3a7c1d9e502
Revises: e6c0a3b8d254
Create Date: 2026-08-22 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "f3a7c1d9e502"
down_revision: Union[str, Sequence[str], None] = "e6c0a3b8d254"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "prompt_concepts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "prompt_tags",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("slug", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column(
            "description",
            sa.String(length=255),
            server_default="",
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug"),
    )
    op.create_table(
        "prompt_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("concept_id", sa.Uuid(), nullable=False),
        sa.Column("language", sa.String(length=16), nullable=False),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("canonical_answer", sa.String(length=64), nullable=False),
        sa.Column("match_key", sa.String(length=64), nullable=False),
        sa.Column(
            "editorial_difficulty",
            sa.String(length=16),
            server_default="unspecified",
            nullable=False,
        ),
        sa.Column(
            "content_rating",
            sa.String(length=16),
            server_default="everyone",
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("language IN ('en')", name="ck_prompt_versions_language"),
        sa.CheckConstraint(
            "editorial_difficulty IN ('unspecified', 'easy', 'medium', 'hard')",
            name="ck_prompt_versions_editorial_difficulty",
        ),
        sa.CheckConstraint(
            "content_rating IN ('everyone', 'teen', 'mature')",
            name="ck_prompt_versions_content_rating",
        ),
        sa.CheckConstraint(
            "version >= 1", name="ck_prompt_versions_version_positive"
        ),
        sa.ForeignKeyConstraint(
            ["concept_id"], ["prompt_concepts.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "concept_id",
            "language",
            "version",
            name="uq_prompt_version_concept_language_version",
        ),
    )
    op.create_index(
        op.f("ix_prompt_versions_concept_id"),
        "prompt_versions",
        ["concept_id"],
    )
    op.create_table(
        "prompt_aliases",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("concept_id", sa.Uuid(), nullable=False),
        sa.Column("language", sa.String(length=16), nullable=False),
        sa.Column("answer", sa.String(length=64), nullable=False),
        sa.Column("match_key", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("language IN ('en')", name="ck_prompt_aliases_language"),
        sa.ForeignKeyConstraint(
            ["concept_id"], ["prompt_concepts.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "concept_id",
            "language",
            "match_key",
            name="uq_prompt_alias_concept_language_match_key",
        ),
    )
    op.create_index(
        op.f("ix_prompt_aliases_concept_id"),
        "prompt_aliases",
        ["concept_id"],
    )
    op.create_table(
        "prompt_version_aliases",
        sa.Column("prompt_version_id", sa.Uuid(), nullable=False),
        sa.Column("alias_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["alias_id"], ["prompt_aliases.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["prompt_version_id"], ["prompt_versions.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("prompt_version_id", "alias_id"),
    )
    op.create_table(
        "prompt_version_tags",
        sa.Column("prompt_version_id", sa.Uuid(), nullable=False),
        sa.Column("tag_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["prompt_version_id"], ["prompt_versions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["tag_id"], ["prompt_tags.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("prompt_version_id", "tag_id"),
    )


def downgrade() -> None:
    op.drop_table("prompt_version_tags")
    op.drop_table("prompt_version_aliases")
    op.drop_index(
        op.f("ix_prompt_aliases_concept_id"), table_name="prompt_aliases"
    )
    op.drop_table("prompt_aliases")
    op.drop_index(
        op.f("ix_prompt_versions_concept_id"), table_name="prompt_versions"
    )
    op.drop_table("prompt_versions")
    op.drop_table("prompt_tags")
    op.drop_table("prompt_concepts")
