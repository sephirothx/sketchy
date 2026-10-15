"""solo pool: the drawings Solo may serve, and the drawer's two ways out

Revision ID: e3f4a5b6c7d0
Revises: d2e3f4a5b6c9
Create Date: 2026-10-15 00:00:00.000000

Solo (#1434) serves strangers' drawings to guess. `solo_pool` is the
projection of game facts it draws from - a public game's curated turn that
somebody guessed, with a kept drawing of at least five actions - written with
the finished game and rebuilt by `python -m app.services.solo_pool`.

The drawer's consent is anonymity plus a way out: `user_settings.solo_opt_out`
for every drawing, `turn_drawings.solo_withdrawn_at` for one.

Nothing is deployed, so the pool starts empty; run the rebuild to fill it
from the games already recorded.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "e3f4a5b6c7d0"
down_revision: str | Sequence[str] | None = "d2e3f4a5b6c9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UUID = sa.Uuid(as_uuid=True, native_uuid=True)


def upgrade() -> None:
    op.create_table(
        "solo_pool",
        sa.Column(
            "turn_id",
            _UUID,
            sa.ForeignKey("turn_records.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "game_id", _UUID, sa.ForeignKey("game_records.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "concept_id",
            _UUID,
            sa.ForeignKey("prompt_concepts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("prompt_version_id", _UUID, nullable=False),
        sa.Column(
            "drawer_user_id", _UUID, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column("guesser_count", sa.SmallInteger(), nullable=False),
        sa.Column("correct_count", sa.SmallInteger(), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sample_key", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "guesser_count >= 1 AND correct_count >= 1 AND correct_count <= guesser_count",
            name="ck_solo_pool_counts",
        ),
        sa.CheckConstraint(
            "sample_key >= 0 AND sample_key < 2147483648", name="ck_solo_pool_sample_key"
        ),
    )
    op.create_index("ix_solo_pool_game_id", "solo_pool", ["game_id"])
    op.create_index("ix_solo_pool_concept_id", "solo_pool", ["concept_id"])
    op.create_index("ix_solo_pool_drawer_user_id", "solo_pool", ["drawer_user_id"])
    op.create_index("ix_solo_pool_sample_key", "solo_pool", ["sample_key"])
    op.add_column(
        "user_settings",
        sa.Column("solo_opt_out", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column(
        "turn_drawings",
        sa.Column("solo_withdrawn_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    if op.get_context().dialect.name == "postgresql":
        op.drop_column("turn_drawings", "solo_withdrawn_at")
        op.drop_column("user_settings", "solo_opt_out")
    else:
        with op.batch_alter_table("turn_drawings") as batch:
            batch.drop_column("solo_withdrawn_at")
        with op.batch_alter_table("user_settings") as batch:
            batch.drop_column("solo_opt_out")
    op.drop_index("ix_solo_pool_sample_key", table_name="solo_pool")
    op.drop_index("ix_solo_pool_drawer_user_id", table_name="solo_pool")
    op.drop_index("ix_solo_pool_concept_id", table_name="solo_pool")
    op.drop_index("ix_solo_pool_game_id", table_name="solo_pool")
    op.drop_table("solo_pool")
