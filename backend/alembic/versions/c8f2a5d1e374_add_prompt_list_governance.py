"""add prompt list ownership, visibility, moderation, and provenance

Revision ID: c8f2a5d1e374
Revises: b7e1c4d9a263
Create Date: 2026-08-23 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "c8f2a5d1e374"
down_revision: Union[str, Sequence[str], None] = "b7e1c4d9a263"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("prompt_lists") as batch_op:
        batch_op.add_column(sa.Column("owner_user_id", sa.Uuid(), nullable=True))
        batch_op.add_column(
            sa.Column(
                "visibility",
                sa.String(length=16),
                server_default="private",
                nullable=False,
            )
        )
        batch_op.add_column(
            sa.Column("share_code", sa.String(length=24), nullable=True)
        )
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
        batch_op.add_column(
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            )
        )
        batch_op.add_column(
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            )
        )
        batch_op.create_check_constraint(
            "ck_prompt_lists_visibility",
            "visibility IN ('private', 'unlisted', 'public')",
        )
        batch_op.create_check_constraint(
            "ck_prompt_lists_moderation_state",
            "moderation_state IN ('active', 'under_review', 'hidden')",
        )
        batch_op.create_check_constraint(
            "ck_prompt_lists_bundled_owner",
            "is_bundled = false OR owner_user_id IS NULL",
        )
        batch_op.create_check_constraint(
            "ck_prompt_lists_unlisted_share_code",
            "visibility != 'unlisted' OR share_code IS NOT NULL",
        )
        batch_op.create_foreign_key(
            "fk_prompt_lists_owner_user_id_users",
            "users",
            ["owner_user_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_foreign_key(
            "fk_prompt_lists_moderated_by_user_id_users",
            "users",
            ["moderated_by_user_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_index(
            op.f("ix_prompt_lists_owner_user_id"),
            ["owner_user_id"],
            unique=False,
        )
        batch_op.create_index(
            op.f("ix_prompt_lists_visibility"), ["visibility"], unique=False
        )
        batch_op.create_index(
            op.f("ix_prompt_lists_share_code"), ["share_code"], unique=True
        )
        batch_op.create_index(
            op.f("ix_prompt_lists_moderation_state"),
            ["moderation_state"],
            unique=False,
        )

    op.execute(
        sa.text("UPDATE prompt_lists SET visibility = 'public' WHERE is_bundled")
    )

    with op.batch_alter_table("prompt_list_revisions") as batch_op:
        batch_op.add_column(
            sa.Column("forked_from_revision_id", sa.Uuid(), nullable=True)
        )
        batch_op.create_foreign_key(
            "fk_prompt_list_revisions_forked_from_revision_id",
            "prompt_list_revisions",
            ["forked_from_revision_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_index(
            op.f("ix_prompt_list_revisions_forked_from_revision_id"),
            ["forked_from_revision_id"],
            unique=False,
        )

    op.create_table(
        "prompt_list_revision_tags",
        sa.Column("revision_id", sa.Uuid(), nullable=False),
        sa.Column("tag_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["revision_id"], ["prompt_list_revisions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["tag_id"], ["prompt_tags.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("revision_id", "tag_id"),
    )


def downgrade() -> None:
    op.drop_table("prompt_list_revision_tags")
    with op.batch_alter_table("prompt_list_revisions") as batch_op:
        batch_op.drop_index(
            op.f("ix_prompt_list_revisions_forked_from_revision_id")
        )
        batch_op.drop_constraint(
            "fk_prompt_list_revisions_forked_from_revision_id",
            type_="foreignkey",
        )
        batch_op.drop_column("forked_from_revision_id")

    with op.batch_alter_table("prompt_lists") as batch_op:
        batch_op.drop_index(op.f("ix_prompt_lists_moderation_state"))
        batch_op.drop_index(op.f("ix_prompt_lists_share_code"))
        batch_op.drop_index(op.f("ix_prompt_lists_visibility"))
        batch_op.drop_index(op.f("ix_prompt_lists_owner_user_id"))
        batch_op.drop_constraint(
            "fk_prompt_lists_moderated_by_user_id_users", type_="foreignkey"
        )
        batch_op.drop_constraint(
            "fk_prompt_lists_owner_user_id_users", type_="foreignkey"
        )
        batch_op.drop_constraint(
            "ck_prompt_lists_unlisted_share_code", type_="check"
        )
        batch_op.drop_constraint("ck_prompt_lists_bundled_owner", type_="check")
        batch_op.drop_constraint(
            "ck_prompt_lists_moderation_state", type_="check"
        )
        batch_op.drop_constraint("ck_prompt_lists_visibility", type_="check")
        batch_op.drop_column("updated_at")
        batch_op.drop_column("created_at")
        batch_op.drop_column("moderated_at")
        batch_op.drop_column("moderated_by_user_id")
        batch_op.drop_column("moderation_state")
        batch_op.drop_column("share_code")
        batch_op.drop_column("visibility")
        batch_op.drop_column("owner_user_id")
