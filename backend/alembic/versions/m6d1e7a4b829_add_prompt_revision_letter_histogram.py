"""store a letter histogram alongside each prompt-list revision

Revision ID: m6d1e7a4b829
Revises: l5b9d4f2a613
Create Date: 2026-08-28 00:00:00.000000

Wheel pricing asks how common each letter is among the answers a game can
draw. That is a distribution, not the words, and a revision is immutable - so
it can be counted once here instead of keeping every room's prompt pool
resident to count it again per game.

`letter_counts` holds the a-z tallies the price reads; `letter_total` counts
*every* alphabetic character, including those outside a-z, because it is the
divisor and a language with such letters must keep the ratios it has today.
"""
import uuid
from collections import Counter
from collections.abc import Sequence
from string import ascii_lowercase

import sqlalchemy as sa
from alembic import op


revision: str = "m6d1e7a4b829"
down_revision: str | Sequence[str] | None = "l5b9d4f2a613"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Revisions per slice. Small enough that one slice - its IDs and its answers
# - is a bounded allocation however large the corpus has grown, large enough
# that the walk is a handful of queries rather than one per revision.
BACKFILL_BATCH_SIZE = 500
# The type `prompt_list_revisions.id` is declared with, so the paging
# cursor compares as the column sorts on either backend.
_REVISION_ID = sa.Uuid(as_uuid=True, native_uuid=True)


def upgrade() -> None:
    with op.batch_alter_table("prompt_list_revisions") as batch_op:
        batch_op.add_column(
            sa.Column(
                "letter_counts",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'{}'"),
            )
        )
        batch_op.add_column(
            sa.Column(
                "letter_total",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("0"),
            )
        )

    # Backfill from the same answers `resolve_selection` would have offered:
    # active versions only, so a hidden prompt is not priced into a revision it
    # can no longer be drawn from.
    #
    # Revision history grows without bound - every edit of every owned list
    # leaves one behind - so this walks it a slice at a time rather than
    # materialising every answer in the corpus at once. The migration lock is
    # held for the whole of this, and an upgrade that needs the whole corpus
    # resident to start is one that gets worse as the corpus does.
    bind = op.get_bind()

    encode = sa.JSON().bind_processor(bind.dialect)
    cursor = None

    while True:
        # Keyset pagination rather than a list of every revision ID: history is
        # unbounded, and reading all of it just to slice it locally is the same
        # allocation this batching exists to avoid, only in cheaper units.
        page = sa.text(
            "SELECT id FROM prompt_list_revisions "
            + ("WHERE id > :cursor " if cursor is not None else "")
            + "ORDER BY id LIMIT :limit"
        )
        parameters = {"limit": BACKFILL_BATCH_SIZE}
        if cursor is not None:
            # Bound as the column's own type: SQLite stores these as hex text
            # and PostgreSQL as native uuid, and an untyped parameter compares
            # the way the driver guesses rather than the way the column sorts.
            page = page.bindparams(sa.bindparam("cursor", type_=_REVISION_ID))
            parameters["cursor"] = cursor
        batch = [row[0] for row in bind.execute(page, parameters)]
        if not batch:
            break
        cursor = batch[-1] if isinstance(batch[-1], uuid.UUID) else uuid.UUID(batch[-1])

        answers: dict[object, list[str]] = {revision_id: [] for revision_id in batch}
        rows = bind.execute(
            sa.text(
                """
                SELECT i.revision_id AS revision_id, v.canonical_answer AS answer
                FROM prompt_list_revision_items AS i
                JOIN prompt_versions AS v ON v.id = i.prompt_version_id
                WHERE v.moderation_state = 'active'
                  AND i.revision_id IN :revision_ids
                """
            ).bindparams(sa.bindparam("revision_ids", expanding=True)),
            {"revision_ids": batch},
        )
        for revision_id, answer in rows:
            answers[revision_id].append(answer)

        for revision_id, revision_answers in answers.items():
            if not revision_answers:
                # No active answers: the columns' defaults already say so.
                continue
            counts = Counter(
                char
                for answer in revision_answers
                for char in answer.lower()
                if char.isalpha()
            )
            bind.execute(
                sa.text(
                    "UPDATE prompt_list_revisions "
                    "SET letter_counts = :counts, letter_total = :total "
                    "WHERE id = :id"
                ),
                {
                    "counts": encode(
                        {
                            letter: counts[letter]
                            for letter in ascii_lowercase
                            if counts[letter]
                        }
                    ),
                    "total": sum(counts.values()),
                    "id": revision_id,
                },
            )


def downgrade() -> None:
    with op.batch_alter_table("prompt_list_revisions") as batch_op:
        batch_op.drop_column("letter_total")
        batch_op.drop_column("letter_counts")
