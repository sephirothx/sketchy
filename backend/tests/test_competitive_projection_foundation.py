"""#388 keeps future competitive features fact-based and product-neutral."""

from app.db.models import Base


def test_recalculable_competitive_foundation_is_present_without_product_tables():
    required_source_columns = {
        "game_records": {
            "id",
            "started_at",
            "finished_at",
            "scoring_mode",
            "hint_mode",
            "scoring_version",
            "score_ledger_version",
            "rule_snapshot_version",
            "rule_snapshot",
            "prompt_source_mode",
            "player_count",
        },
        "game_participants": {
            "id",
            "game_id",
            "user_id",
            "final_score",
            "final_rank",
            "turns_played",
        },
        "identity_aliases": {
            "source_user_id",
            "target_user_id",
            "created_at",
        },
        "game_prompt_sources": {"game_id", "prompt_list_revision_id"},
        "turn_records": {
            "id",
            "game_id",
            "drawer_participant_id",
            "prompt_version_id",
            "prompt_source_kind",
            "duration_seconds",
            "guesser_count",
            "prompt_auto_picked",
            "stroke_count",
            "end_reason",
            "wrong_guess_count",
            "near_miss_count",
        },
        "turn_participant_outcomes": {
            "turn_id",
            "participant_id",
            "eligible",
            "eligibility_reason",
            "outcome",
            "terminal_state",
            "correct_guess_time_seconds",
            "wrong_guess_count",
            "near_miss_count",
            "hints_used",
            "points_spent_on_hints",
        },
        "score_events": {
            "game_id",
            "participant_id",
            "turn_id",
            "event_order",
            "event_type",
            "points_delta",
            "scoring_version",
            "rule_snapshot_version",
            "corrects_event_id",
        },
    }

    for table_name, required_columns in required_source_columns.items():
        actual_columns = set(Base.metadata.tables[table_name].columns.keys())
        assert required_columns <= actual_columns

    # #388 does not pick an algorithm, a season model, achievement definitions,
    # or a leaderboard product. Those may later be added as explicitly versioned,
    # rebuildable projections, never smuggled in as v1 mutable source counters.
    reserved_product_tables = {
        "ratings",
        "rating_events",
        "seasons",
        "achievements",
        "user_achievements",
        "leaderboard_entries",
    }
    assert reserved_product_tables.isdisjoint(Base.metadata.tables)
