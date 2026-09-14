"""let a player-owned list be published, and starred

Revision ID: f8a9b0c1d2e3
Revises: b5c6d7e8f9a0
Create Date: 2026-09-10 10:20:00.000000

`public` was reserved: `ck_prompt_lists_public_is_bundled` said a public list
had to be bundled, so the official catalogue was the only thing that could
hold the value. N-04 reserved it deliberately, and #398 withdraws that -
R-LIST-11 makes publishing an explicit act a player can take.

Dropping the check is not enough on its own, because the value alone does not
say the act happened. `published_at` is the act's record, and the new check
makes the two inseparable at rest: a public row without the moment it became
public cannot exist, whatever writes it. That matters more than a timestamp
usually would, since publishing is gated, audited and rate-limited (R-LIST-12)
and a row that could go public without one of those is the hole worth closing
in the schema rather than in a code path.

Bundled lists are public and have always been. They are backfilled to their
own `created_at` rather than to now: the official catalogue has been published
since it was seeded, and stamping today's date on it would say the deployment
published it during this migration.

`prompt_list_stars` is the other half. It is a table of facts rather than a
counter on the list (R-LIST-16) - the rows are the truth, every count derives
from them, a double-star cannot inflate anything, and a deleted account takes
its stars with it through the cascade rather than leaving a number too high.
The partial index is the catalogue's whole question, and the stars index is
the count's, which reads the other way round from the primary key.

Going back drops the stars - they are derived social data, nothing pins them,
and no finished game reads one. Any list that was published is returned to
private first, because the restored check would otherwise reject every
player-owned public row; the share code a list may also hold is untouched, so
an unlisted one is unaffected either way. What a rollback loses is who had
published what, which is recoverable from the audit ledger.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "f8a9b0c1d2e3"
down_revision: str | Sequence[str] | None = "b5c6d7e8f9a0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_PUBLISHED_WHERE = (
    "visibility = 'public' AND moderation_state = 'active' AND deleted_at IS NULL"
)


def upgrade() -> None:
    op.add_column(
        "prompt_lists", sa.Column("published_at", sa.DateTime(timezone=True))
    )
    # Before the check is added: it is validated against every row present, and
    # the bundled catalogue is already public.
    op.execute(
        "UPDATE prompt_lists SET published_at = created_at "
        "WHERE visibility = 'public' AND published_at IS NULL"
    )
    with op.batch_alter_table("prompt_lists") as batch:
        batch.drop_constraint("ck_prompt_lists_public_is_bundled", type_="check")
        batch.create_check_constraint(
            "ck_prompt_lists_published_at",
            "visibility <> 'public' OR published_at IS NOT NULL",
        )
    op.create_index(
        "ix_prompt_lists_published",
        "prompt_lists",
        ["published_at"],
        postgresql_where=sa.text(_PUBLISHED_WHERE),
        sqlite_where=sa.text(_PUBLISHED_WHERE),
    )

    op.create_table(
        "prompt_list_stars",
        sa.Column(
            "user_id",
            sa.Uuid(as_uuid=True, native_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "prompt_list_id",
            sa.Uuid(as_uuid=True, native_uuid=True),
            sa.ForeignKey("prompt_lists.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_prompt_list_stars_list", "prompt_list_stars", ["prompt_list_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_prompt_list_stars_list", table_name="prompt_list_stars")
    op.drop_table("prompt_list_stars")

    op.drop_index("ix_prompt_lists_published", table_name="prompt_lists")
    # Before the old check comes back, for the reason the upgrade backfilled
    # before adding the new one. A published player-owned list becomes private
    # again; the bundled catalogue keeps the value it always had.
    op.execute(
        "UPDATE prompt_lists SET visibility = 'private' "
        "WHERE visibility = 'public' AND is_bundled = false"
    )
    with op.batch_alter_table("prompt_lists") as batch:
        batch.drop_constraint("ck_prompt_lists_published_at", type_="check")
        batch.create_check_constraint(
            "ck_prompt_lists_public_is_bundled",
            "visibility <> 'public' OR is_bundled = true",
        )
        batch.drop_column("published_at")
