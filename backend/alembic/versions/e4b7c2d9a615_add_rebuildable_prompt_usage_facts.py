"""replace mutable prompt counters with immutable usage facts

Revision ID: e4b7c2d9a615
Revises: d2a6f9c4b718
Create Date: 2026-08-23 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "e4b7c2d9a615"
down_revision: Union[str, Sequence[str], None] = "d2a6f9c4b718"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "prompt_usage_facts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("batch_id", sa.Uuid(), nullable=False),
        sa.Column("prompt_list_revision_id", sa.Uuid(), nullable=False),
        sa.Column("prompt_version_id", sa.Uuid(), nullable=False),
        # Imported legacy counters cannot truthfully claim a time or rules.
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("scoring_mode", sa.String(length=16), nullable=True),
        sa.Column("hint_mode", sa.String(length=16), nullable=True),
        sa.Column(
            "offer_count", sa.Integer(), server_default="0", nullable=False
        ),
        sa.Column(
            "pick_count", sa.Integer(), server_default="0", nullable=False
        ),
        sa.Column(
            "correct_guess_count",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "total_guesser_count",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "offer_count >= 0", name="ck_prompt_usage_facts_offers"
        ),
        sa.CheckConstraint(
            "pick_count >= 0", name="ck_prompt_usage_facts_picks"
        ),
        sa.CheckConstraint(
            "correct_guess_count >= 0",
            name="ck_prompt_usage_facts_correct_guesses",
        ),
        sa.CheckConstraint(
            "total_guesser_count >= 0",
            name="ck_prompt_usage_facts_total_guessers",
        ),
        sa.CheckConstraint(
            "scoring_mode IN ('none', 'default', 'pressure')",
            name="ck_prompt_usage_facts_scoring_mode",
        ),
        sa.CheckConstraint(
            "hint_mode IN ('none', 'checkpoints', 'purchase', 'wheel')",
            name="ck_prompt_usage_facts_hint_mode",
        ),
        sa.ForeignKeyConstraint(
            ["prompt_list_revision_id"],
            ["prompt_list_revisions.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["prompt_version_id"], ["prompt_versions.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "batch_id",
            "prompt_list_revision_id",
            "prompt_version_id",
            name="uq_prompt_usage_fact_batch_revision_version",
        ),
    )
    op.create_index(
        op.f("ix_prompt_usage_facts_batch_id"),
        "prompt_usage_facts",
        ["batch_id"],
    )
    op.create_index(
        "ix_prompt_usage_facts_revision_occurred_at",
        "prompt_usage_facts",
        ["prompt_list_revision_id", "occurred_at"],
    )
    op.create_index(
        "ix_prompt_usage_facts_version_occurred_at",
        "prompt_usage_facts",
        ["prompt_version_id", "occurred_at"],
    )

    # Preserve pre-v1 counters without inventing when or under which rules they
    # occurred. An unbounded lifetime read includes them; a time/mode filter
    # naturally excludes these explicitly unknown dimensions.
    op.execute(
        sa.text(
            """
            INSERT INTO prompt_usage_facts (
                id, batch_id, prompt_list_revision_id, prompt_version_id,
                occurred_at, scoring_mode, hint_mode,
                offer_count, pick_count, correct_guess_count,
                total_guesser_count, created_at
            )
            SELECT
                p.id, p.id, r.id, p.prompt_version_id,
                NULL, NULL, NULL,
                p.offer_count, p.pick_count, p.correct_guess_count,
                p.total_guesser_count, CURRENT_TIMESTAMP
            FROM prompts AS p
            JOIN prompt_lists AS l ON l.id = p.prompt_list_id
            JOIN prompt_list_revisions AS r
              ON r.prompt_list_id = l.id AND r.version = l.version
            WHERE p.prompt_version_id IS NOT NULL
              AND (
                p.offer_count != 0 OR p.pick_count != 0
                OR p.correct_guess_count != 0 OR p.total_guesser_count != 0
              )
            """
        )
    )

    with op.batch_alter_table("prompts") as batch_op:
        batch_op.drop_column("total_guesser_count")
        batch_op.drop_column("correct_guess_count")
        batch_op.drop_column("pick_count")
        batch_op.drop_column("offer_count")


def downgrade() -> None:
    with op.batch_alter_table("prompts") as batch_op:
        batch_op.add_column(
            sa.Column(
                "offer_count", sa.Integer(), server_default="0", nullable=False
            )
        )
        batch_op.add_column(
            sa.Column(
                "pick_count", sa.Integer(), server_default="0", nullable=False
            )
        )
        batch_op.add_column(
            sa.Column(
                "correct_guess_count",
                sa.Integer(),
                server_default="0",
                nullable=False,
            )
        )
        batch_op.add_column(
            sa.Column(
                "total_guesser_count",
                sa.Integer(),
                server_default="0",
                nullable=False,
            )
        )

    # A downgrade cannot recover per-game dimensions in the old shape, but it
    # can faithfully restore the lifetime totals for each list/concept row.
    for column in (
        "offer_count",
        "pick_count",
        "correct_guess_count",
        "total_guesser_count",
    ):
        op.execute(
            sa.text(
                f"""
                UPDATE prompts
                SET {column} = COALESCE((
                    SELECT SUM(f.{column})
                    FROM prompt_usage_facts AS f
                    JOIN prompt_list_revisions AS r
                      ON r.id = f.prompt_list_revision_id
                    JOIN prompt_versions AS v
                      ON v.id = f.prompt_version_id
                    WHERE r.prompt_list_id = prompts.prompt_list_id
                      AND v.concept_id = prompts.concept_id
                ), 0)
                """
            )
        )

    op.drop_index(
        "ix_prompt_usage_facts_version_occurred_at",
        table_name="prompt_usage_facts",
    )
    op.drop_index(
        "ix_prompt_usage_facts_revision_occurred_at",
        table_name="prompt_usage_facts",
    )
    op.drop_index(
        op.f("ix_prompt_usage_facts_batch_id"),
        table_name="prompt_usage_facts",
    )
    op.drop_table("prompt_usage_facts")
