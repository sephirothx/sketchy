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
from collections import Counter
from collections.abc import Sequence
from string import ascii_lowercase

import sqlalchemy as sa
from alembic import op


revision: str = "m6d1e7a4b829"
down_revision: str | Sequence[str] | None = "l5b9d4f2a613"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


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
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            """
            SELECT i.revision_id AS revision_id, v.canonical_answer AS answer
            FROM prompt_list_revision_items AS i
            JOIN prompt_versions AS v ON v.id = i.prompt_version_id
            WHERE v.moderation_state = 'active'
            """
        )
    ).all()

    answers: dict[object, list[str]] = {}
    for revision_id, answer in rows:
        answers.setdefault(revision_id, []).append(answer)

    for revision_id, revision_answers in answers.items():
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
                "counts": sa.JSON().bind_processor(bind.dialect)(
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
