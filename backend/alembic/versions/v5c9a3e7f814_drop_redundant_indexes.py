"""drop the indexes a composite already covers

Seventeen single-column indexes duplicated the leading column of a
composite index, unique constraint, or primary key on the same table. The
composite already serves every lookup and range scan on its own prefix, so
each was a second B-tree over a strict subset of the first: storage, and
one more index to maintain on every write - several of them on the tables
the finished-game transaction inserts into in bulk.

Revision ID: v5c9a3e7f814
Revises: u4b8f2d6e793
Create Date: 2026-08-29 00:00:00.000000

"""
from collections.abc import Sequence

from alembic import op


revision: str = "v5c9a3e7f814"
down_revision: str | Sequence[str] | None = "u4b8f2d6e793"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# (index, table, column) - the column is what the index is rebuilt from on
# downgrade, and what the composite covering it leads with.
REDUNDANT: tuple[tuple[str, str, str], ...] = (
    ("ix_runtime_stats_daily_stat_date", "runtime_stats_daily", "stat_date"),
    ("ix_data_exports_user_id", "data_exports", "user_id"),
    ("ix_game_participants_game_id", "game_participants", "game_id"),
    ("ix_prompt_aliases_concept_id", "prompt_aliases", "concept_id"),
    ("ix_prompt_versions_concept_id", "prompt_versions", "concept_id"),
    ("ix_role_change_notices_user_id", "role_change_notices", "user_id"),
    ("ix_room_presets_owner_user_id", "room_presets", "owner_user_id"),
    (
        "ix_prompt_list_localizations_prompt_list_id",
        "prompt_list_localizations",
        "prompt_list_id",
    ),
    (
        "ix_prompt_list_revisions_prompt_list_id",
        "prompt_list_revisions",
        "prompt_list_id",
    ),
    ("ix_prompts_prompt_list_id", "prompts", "prompt_list_id"),
    ("ix_turn_records_game_id", "turn_records", "game_id"),
    ("ix_score_events_game_id", "score_events", "game_id"),
    (
        "ix_turn_participant_outcomes_turn_id",
        "turn_participant_outcomes",
        "turn_id",
    ),
    ("ix_turn_prompt_offers_turn_id", "turn_prompt_offers", "turn_id"),
    ("ix_turn_guesses_turn_id", "turn_guesses", "turn_id"),
    ("ix_user_bans_user_id", "user_bans", "user_id"),
    ("ix_user_warnings_user_id", "user_warnings", "user_id"),
)


def upgrade() -> None:
    for index, table, _column in REDUNDANT:
        op.drop_index(index, table_name=table)


def downgrade() -> None:
    for index, table, column in reversed(REDUNDANT):
        op.create_index(index, table, [column])
