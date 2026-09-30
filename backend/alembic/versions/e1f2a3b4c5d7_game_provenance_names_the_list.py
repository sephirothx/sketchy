"""A finished game's provenance names the list, not the revision

Revision ID: e1f2a3b4c5d7
Revises: d0e1f2a3b4c9
Create Date: 2026-10-01 00:00:00.000000

`game_prompt_sources`, `turn_prompt_offer_sources` and `prompt_usage_facts`
pinned the exact list revision a game drew from, `RESTRICT` (#1358). That pin
is what forced a deleted list to become a tombstone and the reclaim to carry
holds, and no reader needs it: each turn stores its prompt text and version.
They name the list now. The two pointer tables go with the list; a usage fact
stays with its list set to null, so it takes a surrogate key.

Each table is rebuilt rather than altered in place: its key changes, and the
rows are converted through the revision they named, which says its list.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "e1f2a3b4c5d7"
down_revision: str | Sequence[str] | None = "d0e1f2a3b4c9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_FACT_CHECKS = (
    ("hint_mode IN ('none', 'checkpoints', 'purchase', 'wheel')", "ck_prompt_usage_facts_hint_mode"),
    ("scoring_mode IN ('none', 'default', 'pressure')", "ck_prompt_usage_facts_scoring_mode"),
    ("correct_guess_count <= total_guesser_count", "ck_prompt_usage_facts_correct_within_guessers"),
    ("correct_guess_count >= 0", "ck_prompt_usage_facts_correct_guesses"),
    ("offer_count >= 0", "ck_prompt_usage_facts_offers"),
    ("pick_count <= offer_count", "ck_prompt_usage_facts_picks_within_offers"),
    ("pick_count >= 0", "ck_prompt_usage_facts_picks"),
    ("total_guesser_count >= 0", "ck_prompt_usage_facts_total_guessers"),
)
_FACT_COUNTS = (
    "occurred_at, scoring_mode, hint_mode, offer_count, pick_count, "
    "correct_guess_count, total_guesser_count, created_at"
)


def _set_aside(table: str, indexes: Sequence[str]) -> str:
    """Rename `table` out of the way, freeing its key's name for the new one."""
    for index in indexes:
        op.drop_index(index, table_name=table)
    old = f"{table}_old"
    op.rename_table(table, old)
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        # The key's index keeps its name through a rename, and index names
        # are schema-wide: the new table's key would collide with it. The
        # foreign keys keep theirs too, and the new table's unnamed ones would
        # be named around them (`..._fkey1`), drifting from a database built
        # from the models; the copy needs none of them.
        op.execute(f"ALTER TABLE {old} DROP CONSTRAINT {table}_pkey")
        for (name,) in bind.execute(
            sa.text(
                "SELECT conname FROM pg_constraint "
                "WHERE conrelid = CAST(:old AS regclass) AND contype = 'f'"
            ),
            {"old": old},
        ).all():
            op.execute(f'ALTER TABLE {old} DROP CONSTRAINT "{name}"')
    return old


def _new_uuid() -> str:
    if op.get_bind().dialect.name == "postgresql":
        return "gen_random_uuid()"
    return "lower(hex(randomblob(16)))"


def _fact_columns(list_column: str, list_target: str, list_ondelete: str, *, surrogate: bool):
    return [
        *([sa.Column("id", sa.Uuid(), nullable=False)] if surrogate else []),
        sa.Column("batch_id", sa.Uuid(), nullable=False),
        sa.Column(list_column, sa.Uuid(), nullable=surrogate),
        sa.Column("prompt_version_id", sa.Uuid(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("scoring_mode", sa.String(length=16), nullable=False),
        sa.Column("hint_mode", sa.String(length=16), nullable=False),
        sa.Column("offer_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("pick_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("correct_guess_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("total_guesser_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        *(sa.CheckConstraint(check, name=name) for check, name in _FACT_CHECKS),
        sa.ForeignKeyConstraint([list_column], [list_target], ondelete=list_ondelete),
        sa.ForeignKeyConstraint(["prompt_version_id"], ["prompt_versions.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint(
            *(("id",) if surrogate else ("batch_id", list_column, "prompt_version_id"))
        ),
    ]


def upgrade() -> None:
    for table, owner, owner_target in (
        ("game_prompt_sources", "game_id", "game_records.id"),
        ("turn_prompt_offer_sources", "offer_id", "turn_prompt_offers.id"),
    ):
        old = _set_aside(table, [f"ix_{table}_prompt_list_revision_id"])
        op.create_table(
            table,
            sa.Column(owner, sa.Uuid(), nullable=False),
            sa.Column("prompt_list_id", sa.Uuid(), nullable=False),
            sa.ForeignKeyConstraint([owner], [owner_target], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["prompt_list_id"], ["prompt_lists.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint(owner, "prompt_list_id"),
        )
        op.execute(
            f"INSERT INTO {table} ({owner}, prompt_list_id) "
            f"SELECT DISTINCT o.{owner}, r.prompt_list_id FROM {old} o "
            "JOIN prompt_list_revisions r ON r.id = o.prompt_list_revision_id"
        )
        op.drop_table(old)
        op.create_index(f"ix_{table}_prompt_list_id", table, ["prompt_list_id"])

    old = _set_aside(
        "prompt_usage_facts",
        ["ix_prompt_usage_facts_revision_occurred_at", "ix_prompt_usage_facts_version_occurred_at"],
    )
    op.create_table(
        "prompt_usage_facts",
        *_fact_columns("prompt_list_id", "prompt_lists.id", "SET NULL", surrogate=True),
    )
    op.execute(
        "INSERT INTO prompt_usage_facts "
        f"(id, batch_id, prompt_list_id, prompt_version_id, {_FACT_COUNTS}) "
        f"SELECT {_new_uuid()}, o.batch_id, r.prompt_list_id, o.prompt_version_id, "
        + ", ".join(f"o.{column.strip()}" for column in _FACT_COUNTS.split(","))
        + f" FROM {old} o JOIN prompt_list_revisions r ON r.id = o.prompt_list_revision_id"
    )
    op.drop_table(old)
    op.create_index(
        "ix_prompt_usage_facts_list_occurred_at",
        "prompt_usage_facts",
        ["prompt_list_id", "occurred_at"],
    )
    op.create_index(
        "ix_prompt_usage_facts_version_occurred_at",
        "prompt_usage_facts",
        ["prompt_version_id", "occurred_at"],
    )


# A list's provenance goes back to the revision it is on now: which one a game
# drew from was not kept, and the list's current one is the nearest true answer.
_CURRENT = (
    "JOIN prompt_lists l ON l.id = o.prompt_list_id "
    "JOIN prompt_list_revisions r ON r.prompt_list_id = l.id AND r.version = l.version"
)


def downgrade() -> None:
    old = _set_aside(
        "prompt_usage_facts",
        ["ix_prompt_usage_facts_list_occurred_at", "ix_prompt_usage_facts_version_occurred_at"],
    )
    op.create_table(
        "prompt_usage_facts",
        *_fact_columns(
            "prompt_list_revision_id", "prompt_list_revisions.id", "CASCADE", surrogate=False
        ),
    )
    op.execute(
        "INSERT INTO prompt_usage_facts "
        f"(batch_id, prompt_list_revision_id, prompt_version_id, {_FACT_COUNTS}) "
        "SELECT o.batch_id, r.id, o.prompt_version_id, "
        + ", ".join(f"o.{column.strip()}" for column in _FACT_COUNTS.split(","))
        + f" FROM {old} o {_CURRENT}"
    )
    op.drop_table(old)
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

    for table, owner, owner_target in (
        ("game_prompt_sources", "game_id", "game_records.id"),
        ("turn_prompt_offer_sources", "offer_id", "turn_prompt_offers.id"),
    ):
        old = _set_aside(table, [f"ix_{table}_prompt_list_id"])
        op.create_table(
            table,
            sa.Column(owner, sa.Uuid(), nullable=False),
            sa.Column("prompt_list_revision_id", sa.Uuid(), nullable=False),
            sa.ForeignKeyConstraint([owner], [owner_target], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(
                ["prompt_list_revision_id"], ["prompt_list_revisions.id"], ondelete="RESTRICT"
            ),
            sa.PrimaryKeyConstraint(owner, "prompt_list_revision_id"),
        )
        op.execute(
            f"INSERT INTO {table} ({owner}, prompt_list_revision_id) "
            f"SELECT o.{owner}, r.id FROM {old} o {_CURRENT}"
        )
        op.drop_table(old)
        op.create_index(
            f"ix_{table}_prompt_list_revision_id", table, ["prompt_list_revision_id"]
        )
