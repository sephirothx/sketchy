"""add exact game prompt sources and offers

Revision ID: c3a6e9f2b854
Revises: b2f5d8e1a743
Create Date: 2026-08-23 00:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "c3a6e9f2b854"
down_revision: str | Sequence[str] | None = "b2f5d8e1a743"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    source_mode_check = (
        "prompt_source_mode IN "
        "('legacy_unknown', 'curated', 'custom', 'mixed', 'builtin_fallback')"
    )
    if op.get_bind().dialect.name == "sqlite":
        # Keep the constraint inline without rebuilding the parent table;
        # rebuilding it would cascade-delete existing turns.
        op.execute(
            "ALTER TABLE game_records ADD COLUMN prompt_source_mode VARCHAR(24) "
            "DEFAULT 'legacy_unknown' NOT NULL "
            "CONSTRAINT ck_game_records_prompt_source_mode CHECK ("
            f"{source_mode_check})"
        )
    else:
        op.add_column(
            "game_records",
            sa.Column(
                "prompt_source_mode",
                sa.String(length=24),
                server_default="legacy_unknown",
                nullable=False,
            ),
        )
        op.create_check_constraint(
            "ck_game_records_prompt_source_mode",
            "game_records",
            source_mode_check,
        )

    op.create_table(
        "game_prompt_sources",
        sa.Column("game_id", sa.Uuid(), nullable=False),
        sa.Column("prompt_list_revision_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["game_id"], ["game_records.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["prompt_list_revision_id"],
            ["prompt_list_revisions.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("game_id", "prompt_list_revision_id"),
    )
    op.create_index(
        "ix_game_prompt_sources_prompt_list_revision_id",
        "game_prompt_sources",
        ["prompt_list_revision_id"],
    )

    op.create_table(
        "turn_prompt_offers",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("turn_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("prompt_version_id", sa.Uuid(), nullable=True),
        sa.Column("prompt_snapshot", sa.String(length=64), nullable=False),
        sa.Column("selected", sa.Boolean(), nullable=False),
        sa.Column("source_kind", sa.String(length=24), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "position >= 0", name="ck_turn_prompt_offers_position"
        ),
        sa.CheckConstraint(
            "source_kind IN ('curated', 'custom', 'builtin_fallback')",
            name="ck_turn_prompt_offers_source_kind",
        ),
        sa.ForeignKeyConstraint(
            ["turn_id"], ["turn_records.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["prompt_version_id"], ["prompt_versions.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "turn_id", "position", name="uq_turn_prompt_offers_turn_position"
        ),
    )
    op.create_index(
        "ix_turn_prompt_offers_turn_id", "turn_prompt_offers", ["turn_id"]
    )
    op.create_index(
        "ix_turn_prompt_offers_prompt_version_id",
        "turn_prompt_offers",
        ["prompt_version_id"],
    )
    op.create_index(
        "uq_turn_prompt_offers_selected",
        "turn_prompt_offers",
        ["turn_id"],
        unique=True,
        sqlite_where=sa.text("selected = 1"),
        postgresql_where=sa.text("selected"),
    )

    op.create_table(
        "turn_prompt_offer_sources",
        sa.Column("offer_id", sa.Uuid(), nullable=False),
        sa.Column("prompt_list_revision_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["offer_id"], ["turn_prompt_offers.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["prompt_list_revision_id"],
            ["prompt_list_revisions.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("offer_id", "prompt_list_revision_id"),
    )
    op.create_index(
        "ix_turn_prompt_offer_sources_prompt_list_revision_id",
        "turn_prompt_offer_sources",
        ["prompt_list_revision_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_turn_prompt_offer_sources_prompt_list_revision_id",
        table_name="turn_prompt_offer_sources",
    )
    op.drop_table("turn_prompt_offer_sources")
    op.drop_index(
        "uq_turn_prompt_offers_selected", table_name="turn_prompt_offers"
    )
    op.drop_index(
        "ix_turn_prompt_offers_prompt_version_id", table_name="turn_prompt_offers"
    )
    op.drop_index("ix_turn_prompt_offers_turn_id", table_name="turn_prompt_offers")
    op.drop_table("turn_prompt_offers")
    op.drop_index(
        "ix_game_prompt_sources_prompt_list_revision_id",
        table_name="game_prompt_sources",
    )
    op.drop_table("game_prompt_sources")
    if op.get_bind().dialect.name != "sqlite":
        op.drop_constraint(
            "ck_game_records_prompt_source_mode",
            "game_records",
            type_="check",
        )
    else:
        # Originally column-level and gone with the column; a later batch
        # rebuild of game_records re-emits it as a table-level constraint,
        # which SQLite refuses to leave dangling over a dropped column.
        inspector = sa.inspect(op.get_bind())
        if any(
            constraint.get("name") == "ck_game_records_prompt_source_mode"
            for constraint in inspector.get_check_constraints("game_records")
        ):
            with op.batch_alter_table("game_records") as batch_op:
                batch_op.drop_constraint(
                    "ck_game_records_prompt_source_mode", type_="check"
                )
    op.drop_column("game_records", "prompt_source_mode")
