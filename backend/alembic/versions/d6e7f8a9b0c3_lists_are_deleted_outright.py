"""A deleted prompt list goes at once, and revisions go for good

Revision ID: d6e7f8a9b0c3
Revises: c5d6e7f8a9b2
Create Date: 2026-10-01 00:00:00.000000

A deleted list was a tombstone (`deleted_at`) for a day while a sweep drained
its play history in budgeted batches, because the history held foreign keys
to it: deleting a list played in ten thousand games cascaded over ~300,000
rows (#1376 review). The history needs nothing from the list - each turn
stores its prompt text and version (#1358) - so `game_prompt_sources`,
`turn_prompt_offer_sources` and `prompt_usage_facts` keep the list id as an
opaque value with no foreign key, and a list is deleted outright (#1362).
A report's list pointer does too: deleting a list wrote to the report rows a
moderator's decision holds, which deadlocked against an account erasure.

Revisions go too: nothing has written one but bundled seeding since #1359,
and the seed's conflict check now compares the list row's own
`content_hash`, backfilled here from each bundled list's current revision.

The history tables are rebuilt rather than altered: SQLite cannot drop an
unnamed foreign key, and the copy is the same on both engines.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "d6e7f8a9b0c3"
down_revision: str | Sequence[str] | None = "c5d6e7f8a9b2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_JSON = sa.JSON(none_as_null=True).with_variant(
    postgresql.JSONB(none_as_null=True), "postgresql"
)
LANGUAGES = ("en", "de", "es", "fr", "it", "nl", "pt", "pl", "zxx")
_PUBLISHED = "visibility = 'public' AND moderation_state = 'active'"
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
_FACT_COLUMNS = (
    "id, batch_id, prompt_list_id, prompt_version_id, occurred_at, scoring_mode, "
    "hint_mode, offer_count, pick_count, correct_guess_count, total_guesser_count, "
    "created_at"
)
_SOURCES = (
    ("game_prompt_sources", "game_id", "game_records.id"),
    ("turn_prompt_offer_sources", "offer_id", "turn_prompt_offers.id"),
)


def _set_aside(table: str, indexes: Sequence[str]) -> str:
    """Rename `table` out of the way, freeing its key's name for the new one."""
    for index in indexes:
        op.drop_index(index, table_name=table)
    old = f"{table}_old"
    op.rename_table(table, old)
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        # Constraint and index names are schema-wide and survive a rename.
        op.execute(f"ALTER TABLE {old} DROP CONSTRAINT {table}_pkey")
        for (name,) in bind.execute(
            sa.text(
                "SELECT conname FROM pg_constraint "
                "WHERE conrelid = CAST(:old AS regclass) AND contype IN ('f', 'c')"
            ),
            {"old": old},
        ).all():
            op.execute(f'ALTER TABLE {old} DROP CONSTRAINT "{name}"')
    return old


def _facts(*, list_fk: bool) -> list:
    return [
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("batch_id", sa.Uuid(), nullable=False),
        sa.Column("prompt_list_id", sa.Uuid(), nullable=True),
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
        *(
            [sa.ForeignKeyConstraint(["prompt_list_id"], ["prompt_lists.id"], ondelete="SET NULL")]
            if list_fk
            else []
        ),
        sa.ForeignKeyConstraint(["prompt_version_id"], ["prompt_versions.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    ]


def _rebuild_history(*, list_fk: bool) -> None:
    for table, owner, owner_target in _SOURCES:
        old = _set_aside(table, [f"ix_{table}_prompt_list_id"] if list_fk is False else [])
        op.create_table(
            table,
            sa.Column(owner, sa.Uuid(), nullable=False),
            sa.Column("prompt_list_id", sa.Uuid(), nullable=False),
            sa.ForeignKeyConstraint([owner], [owner_target], ondelete="CASCADE"),
            *(
                [sa.ForeignKeyConstraint(["prompt_list_id"], ["prompt_lists.id"], ondelete="CASCADE")]
                if list_fk
                else []
            ),
            sa.PrimaryKeyConstraint(owner, "prompt_list_id"),
        )
        # Back to a foreign key, a row naming a deleted list names nothing.
        keep = " WHERE prompt_list_id IN (SELECT id FROM prompt_lists)" if list_fk else ""
        op.execute(
            f"INSERT INTO {table} ({owner}, prompt_list_id) "
            f"SELECT {owner}, prompt_list_id FROM {old}{keep}"
        )
        op.drop_table(old)
        if list_fk:
            op.create_index(f"ix_{table}_prompt_list_id", table, ["prompt_list_id", owner])

    old = _set_aside(
        "prompt_usage_facts",
        ["ix_prompt_usage_facts_list_occurred_at", "ix_prompt_usage_facts_version_occurred_at"],
    )
    op.create_table("prompt_usage_facts", *_facts(list_fk=list_fk))
    copied = _FACT_COLUMNS
    if list_fk:
        copied = copied.replace(
            "prompt_list_id",
            "CASE WHEN prompt_list_id IN (SELECT id FROM prompt_lists) "
            "THEN prompt_list_id END",
        )
    op.execute(f"INSERT INTO prompt_usage_facts ({_FACT_COLUMNS}) SELECT {copied} FROM {old}")
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


def _report_list_fk(*, present: bool) -> None:
    """A report's list pointer loses (or regains) its foreign key."""
    if op.get_bind().dialect.name == "postgresql":
        if present:
            op.create_foreign_key(
                "prompt_content_reports_prompt_list_id_fkey",
                "prompt_content_reports",
                "prompt_lists",
                ["prompt_list_id"],
                ["id"],
                ondelete="SET NULL",
            )
            return
        for (name,) in op.get_bind().execute(
            sa.text(
                "SELECT conname FROM pg_constraint WHERE contype = 'f' "
                "AND conrelid = CAST('prompt_content_reports' AS regclass) "
                "AND confrelid = CAST('prompt_lists' AS regclass)"
            )
        ).all():
            op.execute(f'ALTER TABLE prompt_content_reports DROP CONSTRAINT "{name}"')
        return
    # SQLite names no constraint, so the batch names it in order to drop it.
    name = "fk_prompt_content_reports_prompt_list_id_prompt_lists"
    with op.batch_alter_table(
        "prompt_content_reports",
        naming_convention={"fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s"},
    ) as batch:
        if present:
            batch.create_foreign_key(
                name, "prompt_lists", ["prompt_list_id"], ["id"], ondelete="SET NULL"
            )
        else:
            batch.drop_constraint(name, type_="foreignkey")


def upgrade() -> None:
    # The seed's conflict check reads this from the list row from now on.
    op.execute(
        "UPDATE prompt_lists SET content_hash = COALESCE(("
        "SELECT r.content_hash FROM prompt_list_revisions r "
        "WHERE r.prompt_list_id = prompt_lists.id AND r.version = prompt_lists.version"
        "), content_hash) WHERE is_bundled"
    )

    _rebuild_history(list_fk=False)
    _report_list_fk(present=False)

    # A player's wording a revision was the last to name - replaced before
    # saves overwrote a working copy (#1359), or held only by a tombstone's
    # old revisions - loses that reference with the revisions. Stamped now,
    # so the unlisted sweep collects it a grace later unless a turn, an
    # offer, a fact, a report or a takedown still names it (#1394 review).
    # Bundled wordings are left as they were: seeding owns them.
    op.execute(
        "UPDATE prompt_versions SET unlisted_at = CURRENT_TIMESTAMP "
        "WHERE unlisted_at IS NULL "
        "AND id IN (SELECT i.prompt_version_id FROM prompt_list_revision_items i "
        "JOIN prompt_list_revisions r ON r.id = i.revision_id "
        "JOIN prompt_lists l ON l.id = r.prompt_list_id WHERE NOT l.is_bundled) "
        "AND id NOT IN (SELECT prompt_version_id FROM prompts p "
        "JOIN prompt_lists l ON l.id = p.prompt_list_id WHERE l.deleted_at IS NULL) "
        "AND id NOT IN (SELECT prompt_version_id FROM prompt_list_edition_items)"
    )

    # Tombstones go now; their versions were stamped when they were retired.
    # Their references are cleared by hand first: SQLite migrates with foreign
    # keys off, so no `CASCADE` or `SET NULL` would run for them (#1394 review).
    gone = "SELECT id FROM prompt_lists WHERE deleted_at IS NOT NULL"
    editions = f"SELECT id FROM prompt_list_editions WHERE prompt_list_id IN ({gone})"
    op.execute(f"UPDATE prompt_lists SET copied_from_edition_id = NULL WHERE copied_from_edition_id IN ({editions})")
    for table in ("prompt_list_edition_items", "prompt_list_edition_tags"):
        op.execute(f"DELETE FROM {table} WHERE edition_id IN ({editions})")
    op.execute(f"DELETE FROM prompt_list_editions WHERE prompt_list_id IN ({gone})")
    op.execute(f"UPDATE prompt_lists SET copied_from_list_id = NULL WHERE copied_from_list_id IN ({gone})")
    op.execute(f"UPDATE prompt_versions SET unlisted_from_list_id = NULL WHERE unlisted_from_list_id IN ({gone})")
    for table in ("prompts", "prompt_list_tags", "prompt_list_stars", "prompt_list_localizations"):
        op.execute(f"DELETE FROM {table} WHERE prompt_list_id IN ({gone})")
    op.execute(
        "DELETE FROM prompt_list_revision_items WHERE revision_id IN "
        f"(SELECT id FROM prompt_list_revisions WHERE prompt_list_id IN ({gone}))"
    )
    op.execute(
        "DELETE FROM prompt_list_revision_tags WHERE revision_id IN "
        f"(SELECT id FROM prompt_list_revisions WHERE prompt_list_id IN ({gone}))"
    )
    op.execute(f"DELETE FROM prompt_list_revisions WHERE prompt_list_id IN ({gone})")
    op.execute("DELETE FROM prompt_lists WHERE deleted_at IS NOT NULL")
    op.drop_index("ix_prompt_lists_published", table_name="prompt_lists")
    op.drop_index("ix_prompt_lists_deleted_at", table_name="prompt_lists")
    with op.batch_alter_table("prompt_lists") as batch:
        batch.drop_column("deleted_at")
    op.create_index(
        "ix_prompt_lists_published",
        "prompt_lists",
        ["published_at"],
        postgresql_where=sa.text(_PUBLISHED),
        sqlite_where=sa.text(_PUBLISHED),
    )

    op.drop_table("prompt_list_revision_tags")
    op.drop_table("prompt_list_revision_items")
    op.drop_table("prompt_list_revisions")


def downgrade() -> None:
    op.create_table(
        "prompt_list_revisions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("prompt_list_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("language", sa.String(length=16), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("letter_counts", _JSON, server_default=sa.text("'{}'"), nullable=False),
        sa.Column("letter_total", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "language IN (" + ", ".join(f"'{code}'" for code in LANGUAGES) + ")",
            name="ck_prompt_list_revisions_language",
        ),
        sa.CheckConstraint("version >= 1", name="ck_prompt_list_revisions_version_positive"),
        sa.ForeignKeyConstraint(["prompt_list_id"], ["prompt_lists.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("prompt_list_id", "version", name="uq_prompt_list_revision_version"),
    )
    op.create_table(
        "prompt_list_revision_items",
        sa.Column("revision_id", sa.Uuid(), nullable=False),
        sa.Column("prompt_version_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.CheckConstraint("position >= 0", name="ck_prompt_list_revision_items_position_nonnegative"),
        sa.ForeignKeyConstraint(["prompt_version_id"], ["prompt_versions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["revision_id"], ["prompt_list_revisions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("revision_id", "prompt_version_id"),
        sa.UniqueConstraint("revision_id", "position", name="uq_prompt_list_revision_item_position"),
    )
    op.create_index(
        "ix_prompt_list_revision_items_prompt_version_id",
        "prompt_list_revision_items",
        ["prompt_version_id"],
    )
    op.create_table(
        "prompt_list_revision_tags",
        sa.Column("revision_id", sa.Uuid(), nullable=False),
        sa.Column("tag_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["revision_id"], ["prompt_list_revisions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tag_id"], ["prompt_tags.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("revision_id", "tag_id"),
    )
    op.create_index("ix_prompt_list_revision_tags_tag_id", "prompt_list_revision_tags", ["tag_id"])

    op.drop_index("ix_prompt_lists_published", table_name="prompt_lists")
    with op.batch_alter_table("prompt_lists") as batch:
        batch.add_column(sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_prompt_lists_deleted_at", "prompt_lists", ["deleted_at"])
    where = f"{_PUBLISHED} AND deleted_at IS NULL"
    op.create_index(
        "ix_prompt_lists_published",
        "prompt_lists",
        ["published_at"],
        postgresql_where=sa.text(where),
        sqlite_where=sa.text(where),
    )

    op.execute(
        "UPDATE prompt_content_reports SET prompt_list_id = NULL "
        "WHERE prompt_list_id NOT IN (SELECT id FROM prompt_lists)"
    )
    _report_list_fk(present=True)
    _rebuild_history(list_fk=True)
