"""Migration replay, downgrade, drift, and hand-written schema checks."""
from __future__ import annotations

import json
import os
import uuid
import warnings

import pytest
from alembic import command as alembic_command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text
from sqlalchemy.exc import DBAPIError, IntegrityError, SAWarning
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.db import create_db_engine, get_alembic_config
from app.db.models import Base

pytestmark = pytest.mark.asyncio


async def _migrate(engine: AsyncEngine, operation, target: str) -> None:
    config = get_alembic_config()

    def run(connection):
        config.attributes["connection"] = connection
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore",
                message=r".*ix_users_(?:username|email)_lower.*",
                category=SAWarning,
            )
            operation(config, target)

    async with engine.begin() as connection:
        await connection.run_sync(run)


async def _current_revisions(engine: AsyncEngine) -> set[str]:
    async with engine.connect() as connection:
        return await connection.run_sync(
            lambda sync_connection: set(
                MigrationContext.configure(sync_connection).get_current_heads()
            )
        )


async def _index_definition(
    engine: AsyncEngine, name: str = "ix_users_username_lower"
) -> str | None:
    async with engine.connect() as connection:
        if engine.dialect.name == "sqlite":
            statement = text(
                "SELECT sql FROM sqlite_master "
                "WHERE type = 'index' AND name = :name"
            )
        else:
            statement = text(
                "SELECT indexdef FROM pg_indexes "
                "WHERE schemaname = current_schema() "
                "AND indexname = :name"
            )
        return (await connection.execute(statement, {"name": name})).scalar_one_or_none()


async def _schema_differences(engine: AsyncEngine):
    def diff(connection):
        return compare_metadata(MigrationContext.configure(connection), Base.metadata)

    # SQLite cannot reflect expression indexes. The direct definition check in
    # this suite covers that deliberate autogenerate blind spot.
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message=r".*ix_users_(?:username|email)_lower.*",
            category=SAWarning,
        )
        warnings.filterwarnings(
            "ignore",
            message=r".*ix_users_(?:username|email)_lower.*",
            category=UserWarning,
        )
        async with engine.connect() as connection:
            differences = await connection.run_sync(diff)

    if engine.dialect.name != "sqlite":
        return differences

    # SQLite enforces ON DELETE on references added inline with ADD COLUMN, but
    # SQLAlchemy's SQLite DDL parser does not reflect the options for those
    # columns. Their PRAGMA values are asserted directly below instead of
    # accepting false remove/add-FK drift from Alembic autogeneration.
    inline_reference_columns = {
        ("turn_records", "prompt_version_id"),
        ("turn_records", "drawer_participant_id"),
        ("turn_guesses", "participant_id"),
        ("turn_guesses", "outcome_id"),
        ("user_bans", "source_report_id"),
    }
    return [
        difference
        for difference in differences
        if not (
            (
                difference[0] in {"add_fk", "remove_fk"}
                and (
                    difference[1].table.name,
                    next(iter(difference[1].column_keys)),
                )
                in inline_reference_columns
            )
            or (
                difference[0] == "add_constraint"
                and difference[1].name
                in {
                    "ck_turn_records_prompt_identity",
                    # SQLite enforces this as the inline column CHECK added
                    # without rebuilding the history parent table.
                    "ck_game_records_score_ledger_version",
                }
            )
        )
    ]


async def _sqlite_inline_reference_actions(engine: AsyncEngine) -> dict[tuple[str, str], str]:
    expected_columns = {
        ("turn_records", "prompt_version_id"),
        ("turn_records", "drawer_participant_id"),
        ("turn_guesses", "participant_id"),
        ("turn_guesses", "outcome_id"),
        ("user_bans", "source_report_id"),
    }
    actions: dict[tuple[str, str], str] = {}
    async with engine.connect() as connection:
        for table_name in {table for table, _ in expected_columns}:
            rows = (
                await connection.execute(
                    text(f"PRAGMA foreign_key_list({table_name})")
                )
            ).all()
            for row in rows:
                key = (table_name, row._mapping["from"])
                if key in expected_columns:
                    actions[key] = row._mapping["on_delete"]
    return actions


# The last revision whose schema still admits pre-feature ("legacy") rows.
# p8c3a6d9e147 tightened the schema to what current writers produce and
# refuses to upgrade a database still holding such rows, so the tests that
# prove older migrations preserved legacy data honestly now stop here.
LAST_LEGACY_TOLERANT_REVISION = "n7e2f5b8c934"


async def _exercise_migration_chain(engine: AsyncEngine) -> None:
    script = ScriptDirectory.from_config(get_alembic_config())
    revisions = list(script.walk_revisions())
    assert len(revisions) >= 2, "migration replay requires more than one revision"
    head = revisions[0].revision
    foundation = revisions[-1].revision

    await _migrate(engine, alembic_command.upgrade, "head")
    assert await _current_revisions(engine) == {head}
    assert await _schema_differences(engine) == []
    if engine.dialect.name == "sqlite":
        assert await _sqlite_inline_reference_actions(engine) == {
            ("turn_records", "prompt_version_id"): "RESTRICT",
            ("turn_records", "drawer_participant_id"): "CASCADE",
            ("turn_guesses", "participant_id"): "SET NULL",
            ("turn_guesses", "outcome_id"): "CASCADE",
            # A suspension outlives the report it was decided from.
            ("user_bans", "source_report_id"): "SET NULL",
        }
    index_definition = await _index_definition(engine)
    assert index_definition is not None
    normalized_index = index_definition.lower()
    assert "unique" in normalized_index
    assert "lower" in normalized_index
    assert "username" in normalized_index
    assert "where" in normalized_index
    email_index = await _index_definition(engine, "ix_users_email_lower")
    assert email_index is not None
    assert "unique" in email_index.lower()
    assert "lower" in email_index.lower()
    assert "where" in email_index.lower()

    # Run the newest real revision backward and replay it.
    await _migrate(engine, alembic_command.downgrade, foundation)
    assert await _current_revisions(engine) == {foundation}
    assert await _index_definition(engine) is None
    await _migrate(engine, alembic_command.upgrade, "head")
    assert await _current_revisions(engine) == {head}
    assert await _index_definition(engine) is not None
    assert await _index_definition(engine, "ix_users_email_lower") is not None

    # Prove the entire chain can be removed, then rebuilt from an empty schema.
    await _migrate(engine, alembic_command.downgrade, "base")

    def table_names(sync_connection):
        return inspect(sync_connection).get_table_names()

    async with engine.connect() as connection:
        tables = set(await connection.run_sync(table_names))
    assert set(Base.metadata.tables).isdisjoint(tables)

    await _migrate(engine, alembic_command.upgrade, "head")
    assert await _current_revisions(engine) == {head}
    assert await _schema_differences(engine) == []
    assert await _index_definition(engine) is not None
    assert await _index_definition(engine, "ix_users_email_lower") is not None


async def test_sqlite_migration_chain_round_trip(tmp_path):
    engine = create_db_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'migration-round-trip.db'}"
    )
    try:
        await _exercise_migration_chain(engine)
    finally:
        await engine.dispose()


async def test_write_timestamp_migration_preserves_unknown_legacy_times(tmp_path):
    engine = create_db_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'write-timestamp-migration.db'}"
    )
    script = ScriptDirectory.from_config(get_alembic_config())
    previous = script.get_revision("a1e4c7d9b632").down_revision
    assert isinstance(previous, str)
    try:
        await _migrate(engine, alembic_command.upgrade, previous)
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO app_config (key, value) "
                    "VALUES ('legacy_secret', 'legacy')"
                )
            )

        await _migrate(engine, alembic_command.upgrade, LAST_LEGACY_TOLERANT_REVISION)
        async with engine.begin() as connection:
            legacy = (
                await connection.execute(
                    text(
                        "SELECT created_at, updated_at FROM app_config "
                        "WHERE key = 'legacy_secret'"
                    )
                )
            ).one()
            assert tuple(legacy) == (None, None)

            await connection.execute(
                text(
                    "INSERT INTO app_config (key, value) "
                    "VALUES ('new_secret', 'new')"
                )
            )
            current = (
                await connection.execute(
                    text(
                        "SELECT created_at, updated_at FROM app_config "
                        "WHERE key = 'new_secret'"
                    )
                )
            ).one()
            assert current.created_at is not None
            assert current.updated_at is not None
    finally:
        await engine.dispose()


async def test_prompt_identity_migration_marks_legacy_provenance_unknown(tmp_path):
    engine = create_db_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'prompt-identity-migration.db'}"
    )
    script = ScriptDirectory.from_config(get_alembic_config())
    previous = script.get_revision("d4b7f1a3c965").down_revision
    assert isinstance(previous, str)
    identifiers = {
        "user": uuid.uuid4().hex,
        "game": uuid.uuid4().hex,
        "participant": uuid.uuid4().hex,
        "turn": uuid.uuid4().hex,
        "guess": uuid.uuid4().hex,
    }
    try:
        await _migrate(engine, alembic_command.upgrade, previous)
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO users (id, display_name, state) "
                    "VALUES (:user, 'Legacy player', 'anonymous')"
                ),
                identifiers,
            )
            await connection.execute(
                text(
                    "INSERT INTO game_records "
                    "(id, payload_hash, room_name, scoring_mode, hint_mode, "
                    "drawing_seconds, total_rounds, player_count, started_at, "
                    "finished_at) VALUES "
                    "(:game, '', 'Legacy game', 'default', 'none', 90, 1, 1, "
                    "'2026-08-01 00:00:00', '2026-08-01 00:01:00')"
                ),
                identifiers,
            )
            await connection.execute(
                text(
                    "INSERT INTO game_participants "
                    "(id, game_id, user_id, display_name_snapshot, "
                    "is_anonymous_snapshot, final_score, final_rank) VALUES "
                    "(:participant, :game, :user, 'Legacy player', 1, 100, 1)"
                ),
                identifiers,
            )
            await connection.execute(
                text(
                    "INSERT INTO turn_records "
                    "(id, game_id, round_number, turn_number, drawer_user_id, "
                    "drawer_display_name_snapshot, drawer_is_anonymous_snapshot, "
                    "prompt, duration_seconds) VALUES "
                    "(:turn, :game, 1, 1, :user, 'Legacy player', 1, 'apple', 30)"
                ),
                identifiers,
            )
            await connection.execute(
                text(
                    "INSERT INTO turn_guesses "
                    "(id, turn_id, user_id, display_name_snapshot, "
                    "is_anonymous_snapshot, points_awarded, guess_time_seconds) "
                    "VALUES (:guess, :turn, :user, 'Legacy player', 1, 100, 10)"
                ),
                identifiers,
            )

        await _migrate(engine, alembic_command.upgrade, LAST_LEGACY_TOLERANT_REVISION)
        async with engine.connect() as connection:
            game_mode = await connection.scalar(
                text(
                    "SELECT prompt_source_mode FROM game_records WHERE id = :game"
                ),
                identifiers,
            )
            turn_identity = (
                await connection.execute(
                    text(
                        "SELECT prompt_source_kind, prompt_version_id, "
                        "drawer_participant_id "
                        "FROM turn_records WHERE id = :turn"
                    ),
                    identifiers,
                )
            ).one()
            guess_identity = (
                await connection.execute(
                    text(
                        "SELECT participant_id, outcome_id FROM turn_guesses "
                        "WHERE id = :guess"
                    ),
                    identifiers,
                )
            ).one()
            legacy_outcome = (
                await connection.execute(
                    text(
                        "SELECT id, participant_id, eligible, eligibility_reason, "
                        "outcome, terminal_state, correct_guess_time_seconds, "
                        "created_at FROM turn_participant_outcomes"
                    )
                )
            ).one()
        assert game_mode == "legacy_unknown"
        assert tuple(turn_identity) == (
            "legacy_unknown",
            None,
            identifiers["participant"],
        )
        assert tuple(guess_identity) == (
            identifiers["participant"],
            identifiers["guess"],
        )
        assert tuple(legacy_outcome) == (
            identifiers["guess"],
            identifiers["participant"],
            1,
            "eligible",
            "correct",
            "legacy_unknown",
            10.0,
            None,
        )

        # SQLite uses equivalent insert/update triggers because it cannot add a
        # table-level cross-column check without rebuilding this parent table.
        # PostgreSQL uses the named CHECK constraint directly.
        with pytest.raises(IntegrityError):
            async with engine.begin() as connection:
                await connection.execute(
                    text(
                        "UPDATE turn_records SET prompt_source_kind = 'curated' "
                        "WHERE id = :turn"
                    ),
                    identifiers,
                )
    finally:
        await engine.dispose()


async def test_score_ledger_migration_does_not_invent_legacy_events(tmp_path):
    engine = create_db_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'score-ledger-migration.db'}"
    )
    identifiers = {
        "user": uuid.uuid4().hex,
        "game": uuid.uuid4().hex,
        "participant": uuid.uuid4().hex,
        "turn": uuid.uuid4().hex,
        "event": uuid.uuid4().hex,
    }
    try:
        await _migrate(engine, alembic_command.upgrade, "f7d9c3a6b281")
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO users (id, display_name, state) "
                    "VALUES (:user, 'Legacy player', 'anonymous')"
                ),
                identifiers,
            )
            await connection.execute(
                text(
                    "INSERT INTO game_records "
                    "(id, payload_hash, room_name, scoring_mode, hint_mode, "
                    "drawing_seconds, total_rounds, player_count, started_at, finished_at) "
                    "VALUES (:game, '', 'Legacy score', 'default', 'none', 90, 1, 1, "
                    "'2026-08-01 00:00:00', '2026-08-01 00:01:00')"
                ),
                identifiers,
            )
            await connection.execute(
                text(
                    "INSERT INTO game_participants "
                    "(id, game_id, user_id, display_name_snapshot, "
                    "is_anonymous_snapshot, final_score, final_rank) "
                    "VALUES (:participant, :game, :user, 'Legacy player', 1, 100, 1)"
                ),
                identifiers,
            )
            await connection.execute(
                text(
                    "INSERT INTO turn_records "
                    "(id, game_id, round_number, turn_number, drawer_user_id, "
                    "drawer_participant_id, drawer_display_name_snapshot, "
                    "drawer_is_anonymous_snapshot, prompt, duration_seconds) "
                    "VALUES (:turn, :game, 1, 1, :user, :participant, "
                    "'Legacy player', 1, 'apple', 30)"
                ),
                identifiers,
            )

        await _migrate(engine, alembic_command.upgrade, LAST_LEGACY_TOLERANT_REVISION)
        async with engine.begin() as connection:
            assert await connection.scalar(
                text(
                    "SELECT score_ledger_version FROM game_records WHERE id = :game"
                ),
                identifiers,
            ) == 0
            assert await connection.scalar(text("SELECT count(*) FROM score_events")) == 0
            await connection.execute(
                text(
                    "INSERT INTO score_events "
                    "(id, game_id, participant_id, turn_id, event_order, event_type, "
                    "points_delta, scoring_version, rule_snapshot_version) "
                    "VALUES (:event, :game, :participant, :turn, 1, 'guess_award', "
                    "100, 0, 0)"
                ),
                identifiers,
            )
        with pytest.raises(DBAPIError, match="immutable"):
            async with engine.begin() as connection:
                await connection.execute(
                    text(
                        "UPDATE score_events SET points_delta = 99 WHERE id = :event"
                    ),
                    identifiers,
                )
    finally:
        await engine.dispose()


async def test_daily_user_stats_migration_backfills_canonical_identity_totals(
    tmp_path,
):
    engine = create_db_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'user-stats-migration.db'}"
    )
    identifiers = {
        name: uuid.uuid4().hex
        for name in (
            "source",
            "target",
            "alias",
            "game",
            "source_seat",
            "target_seat",
            "first_turn",
            "second_turn",
            "outcome",
            "guess",
        )
    }
    try:
        await _migrate(engine, alembic_command.upgrade, "b9f3e5d7a201")
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO users (id, username, password_hash, display_name, state) "
                    "VALUES (:target, 'target', 'hash', 'Target', 'registered'), "
                    "(:source, NULL, NULL, 'Source', 'merged')"
                ),
                identifiers,
            )
            await connection.execute(
                text(
                    "INSERT INTO identity_aliases "
                    "(id, source_user_id, target_user_id) "
                    "VALUES (:alias, :source, :target)"
                ),
                identifiers,
            )
            await connection.execute(
                text(
                    "INSERT INTO game_records "
                    "(id, payload_hash, room_name, scoring_mode, hint_mode, "
                    "drawing_seconds, total_rounds, player_count, started_at, finished_at) "
                    "VALUES (:game, '', 'Projected legacy game', 'default', 'none', "
                    "90, 1, 2, '2026-08-20 11:55:00', '2026-08-20 12:00:00')"
                ),
                identifiers,
            )
            await connection.execute(
                text(
                    "INSERT INTO game_participants "
                    "(id, game_id, user_id, display_name_snapshot, "
                    "is_anonymous_snapshot, final_score, final_rank) VALUES "
                    "(:source_seat, :game, :source, 'Source', 1, 300, 1), "
                    "(:target_seat, :game, :target, 'Target', 0, 100, 2)"
                ),
                identifiers,
            )
            await connection.execute(
                text(
                    "INSERT INTO turn_records "
                    "(id, game_id, round_number, turn_number, drawer_user_id, "
                    "drawer_participant_id, drawer_display_name_snapshot, "
                    "drawer_is_anonymous_snapshot, prompt, duration_seconds) VALUES "
                    "(:first_turn, :game, 1, 1, :source, :source_seat, "
                    "'Source', 1, 'anchor', 20), "
                    "(:second_turn, :game, 1, 2, :target, :target_seat, "
                    "'Target', 0, 'bridge', 25)"
                ),
                identifiers,
            )
            await connection.execute(
                text(
                    "INSERT INTO turn_participant_outcomes "
                    "(id, turn_id, participant_id, eligible, eligibility_reason, "
                    "outcome, terminal_state, correct_guess_time_seconds) "
                    "VALUES (:outcome, :second_turn, :source_seat, 1, 'eligible', "
                    "'correct', 'active', 10)"
                ),
                identifiers,
            )
            await connection.execute(
                text(
                    "INSERT INTO turn_guesses "
                    "(id, turn_id, user_id, participant_id, outcome_id, "
                    "display_name_snapshot, is_anonymous_snapshot, "
                    "points_awarded, guess_time_seconds) "
                    "VALUES (:guess, :second_turn, :source, :source_seat, :outcome, "
                    "'Source', 1, 100, 10)"
                ),
                identifiers,
            )

        await _migrate(engine, alembic_command.upgrade, LAST_LEGACY_TOLERANT_REVISION)
        async with engine.connect() as connection:
            projection = (
                await connection.execute(
                    text(
                        "SELECT user_id, stat_date, games_played, games_won, "
                        "total_score, turns_played, prompts_guessed, drawings_made "
                        "FROM user_stats_daily"
                    )
                )
            ).one()
        assert tuple(projection) == (
            identifiers["target"],
            "2026-08-20",
            1,
            1,
            400,
            2,
            1,
            2,
        )

        await _migrate(engine, alembic_command.downgrade, "b9f3e5d7a201")
        async with engine.connect() as connection:
            assert await connection.scalar(
                text("SELECT count(*) FROM game_records")
            ) == 1
        await _migrate(engine, alembic_command.upgrade, LAST_LEGACY_TOLERANT_REVISION)
        async with engine.connect() as connection:
            assert await connection.scalar(
                text("SELECT games_played FROM user_stats_daily")
            ) == 1
    finally:
        await engine.dispose()


async def test_prompt_counter_migration_preserves_lifetime_totals(tmp_path):
    engine = create_db_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'prompt-fact-migration.db'}"
    )
    script = ScriptDirectory.from_config(get_alembic_config())
    previous = script.get_revision("e4b7c2d9a615").down_revision
    assert isinstance(previous, str)
    identifiers = {name: uuid.uuid4().hex for name in (
        "list", "concept", "version", "revision", "prompt"
    )}
    try:
        await _migrate(engine, alembic_command.upgrade, previous)
        async with engine.begin() as connection:
            await connection.execute(
                text("INSERT INTO prompt_concepts (id) VALUES (:concept)"),
                identifiers,
            )
            await connection.execute(
                text(
                    "INSERT INTO prompt_versions "
                    "(id, concept_id, language, version, canonical_answer, match_key) "
                    "VALUES (:version, :concept, 'en', 1, 'apple', 'apple')"
                ),
                identifiers,
            )
            await connection.execute(
                text(
                    "INSERT INTO prompt_lists (id, slug, name) "
                    "VALUES (:list, 'legacy', 'Legacy')"
                ),
                identifiers,
            )
            await connection.execute(
                text(
                    "INSERT INTO prompt_list_revisions "
                    "(id, prompt_list_id, version, language, content_hash) "
                    "VALUES (:revision, :list, 1, 'en', 'legacy-hash')"
                ),
                identifiers,
            )
            await connection.execute(
                text(
                    "INSERT INTO prompt_list_revision_items "
                    "(revision_id, prompt_version_id, position) "
                    "VALUES (:revision, :version, 0)"
                ),
                identifiers,
            )
            await connection.execute(
                text(
                    "INSERT INTO prompts "
                    "(id, prompt_list_id, concept_id, prompt_version_id, text, "
                    "offer_count, pick_count, correct_guess_count, "
                    "total_guesser_count) VALUES "
                    "(:prompt, :list, :concept, :version, 'apple', 9, 4, 7, 12)"
                ),
                identifiers,
            )

        await _migrate(engine, alembic_command.upgrade, LAST_LEGACY_TOLERANT_REVISION)
        async with engine.connect() as connection:
            fact = (
                await connection.execute(
                    text(
                        "SELECT offer_count, pick_count, correct_guess_count, "
                        "total_guesser_count, occurred_at, scoring_mode, hint_mode "
                        "FROM prompt_usage_facts"
                    )
                )
            ).one()
        assert tuple(fact[:4]) == (9, 4, 7, 12)
        assert tuple(fact[4:]) == (None, None, None)

        await _migrate(engine, alembic_command.downgrade, previous)
        async with engine.connect() as connection:
            restored = (
                await connection.execute(
                    text(
                        "SELECT offer_count, pick_count, correct_guess_count, "
                        "total_guesser_count FROM prompts WHERE id = :prompt"
                    ),
                    identifiers,
                )
            ).one()
        assert tuple(restored) == (9, 4, 7, 12)
    finally:
        await engine.dispose()


@pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"),
    reason="requires the disposable PostgreSQL CI database",
)
async def test_postgresql_migration_chain_round_trip():
    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    try:
        await _exercise_migration_chain(engine)
    finally:
        await engine.dispose()


async def test_audit_target_migration_says_who_existing_rows_were_about(tmp_path):
    """The pair has to describe rows written before it existed, or the ledger
    starts with a hole exactly where its oldest entries are."""
    engine = create_db_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'audit-target-migration.db'}"
    )
    identifiers = {
        name: uuid.uuid4().hex
        for name in ("actor", "subject", "about_user", "about_nobody")
    }
    try:
        await _migrate(engine, alembic_command.upgrade, "e8c2f5a91b04")
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO users (id, username, password_hash, display_name, state) "
                    "VALUES (:actor, 'actor', 'hash', 'Actor', 'registered'), "
                    "(:subject, 'subject', 'hash', 'Subject', 'registered')"
                ),
                identifiers,
            )
            await connection.execute(
                text(
                    "INSERT INTO audit_events "
                    "(id, event_type, actor_user_id, target_user_id, details) VALUES "
                    "(:about_user, 'report.resolved', :actor, :subject, '{}'), "
                    "(:about_nobody, 'retention.anonymous_purge', NULL, NULL, '{}')"
                ),
                identifiers,
            )

        await _migrate(engine, alembic_command.upgrade, "a1c7e4b9d360")

        async with engine.connect() as connection:
            rows = dict(
                (row.id, (row.target_type, row.target_id))
                for row in (
                    await connection.execute(
                        text("SELECT id, target_type, target_id FROM audit_events")
                    )
                ).all()
            )

        assert rows[identifiers["about_user"]] == (
            "user",
            identifiers["subject"],
        )
        # A bulk purge acts on no single row, and inventing one would be worse
        # than saying nothing.
        assert rows[identifiers["about_nobody"]] == (None, None)
    finally:
        await engine.dispose()


async def test_an_audit_target_cannot_be_half_recorded(tmp_path):
    """A type with no id names nothing; an id with no type is unresolvable."""
    engine = create_db_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'audit-target-constraint.db'}"
    )
    try:
        await _migrate(engine, alembic_command.upgrade, "head")
        async with engine.begin() as connection:
            await connection.execute(text("PRAGMA foreign_keys=ON"))
            for target_type, target_id in (
                ("prompt_list", None),
                (None, "a5f0"),
                ("invented_kind", "a5f0"),
            ):
                with pytest.raises(IntegrityError):
                    async with engine.begin() as attempt:
                        await attempt.execute(
                            text(
                                "INSERT INTO audit_events "
                                "(id, event_type, target_type, target_id, details) "
                                "VALUES (:id, 'prompt_list.takedown', :type, :ident, '{}')"
                            ),
                            {
                                "id": uuid.uuid4().hex,
                                "type": target_type,
                                "ident": target_id,
                            },
                        )
    finally:
        await engine.dispose()


async def test_a_migrated_sqlite_database_refuses_an_invented_outcome(tmp_path):
    """The constraint has to exist on the dialect the default deployment uses.

    It rides on the column rather than in `__table_args__`, because a
    table-level check could only be added by rebuilding `game_records` - and a
    rebuild empties every child table through ON DELETE CASCADE.
    """
    engine = create_db_engine(f"sqlite+aiosqlite:///{tmp_path / 'outcome.db'}")
    try:
        await _migrate(engine, alembic_command.upgrade, "head")
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO game_records (id, payload_hash, room_name, "
                    "scoring_mode, hint_mode, drawing_seconds, total_rounds, "
                    "player_count, started_at, finished_at, outcome, "
                    "prompt_source_mode) VALUES "
                    "(:id, '', 'Room', 'default', 'none', 90, 1, 2, "
                    "'2026-08-24 12:00:00', '2026-08-24 12:10:00', 'abandoned', "
                    "'custom')"
                ),
                {"id": uuid.uuid4().hex},
            )
        with pytest.raises(IntegrityError):
            async with engine.begin() as connection:
                await connection.execute(
                    text(
                        "INSERT INTO game_records (id, payload_hash, room_name, "
                        "scoring_mode, hint_mode, drawing_seconds, total_rounds, "
                        "player_count, started_at, finished_at, outcome, "
                        "prompt_source_mode) VALUES "
                        "(:id, '', 'Room', 'default', 'none', 90, 1, 2, "
                        "'2026-08-24 12:00:00', '2026-08-24 12:10:00', 'invented', "
                        "'custom')"
                    ),
                    {"id": uuid.uuid4().hex},
                )
    finally:
        await engine.dispose()


async def test_a_migration_run_that_orphans_rows_fails_loudly(tmp_path):
    """Migrations run with SQLite foreign keys off, so nothing complains at the
    moment a rebuild goes wrong. This is the complaint, moved to the end."""
    from app.db import assert_references_intact

    engine = create_db_engine(f"sqlite+aiosqlite:///{tmp_path / 'orphan.db'}")
    try:
        await _migrate(engine, alembic_command.upgrade, "head")
        async with engine.begin() as connection:
            await connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
            await connection.execute(
                text(
                    "INSERT INTO game_participants (id, game_id, "
                    "display_name_snapshot, is_anonymous_snapshot, final_score, "
                    "final_rank) VALUES (:id, :missing, 'Orphan', 1, 0, 1)"
                ),
                {"id": uuid.uuid4().hex, "missing": uuid.uuid4().hex},
            )

        def check(sync_connection):
            assert_references_intact(sync_connection)

        async with engine.connect() as connection:
            with pytest.raises(RuntimeError, match="dangling references"):
                await connection.run_sync(check)
    finally:
        await engine.dispose()


async def test_the_open_report_folds_keep_the_earliest_of_each_duplicate(tmp_path):
    """Both dedupe migrations fold before their index can refuse the rows.

    They originally did it with MIN(id), which SQLite accepts and PostgreSQL
    has no such aggregate for, so neither migration could run there at all.
    This exercises the fold itself; the PostgreSQL job proves the SQL is
    portable by running the same chain.
    """
    engine = create_db_engine(f"sqlite+aiosqlite:///{tmp_path / 'folds.db'}")
    ids = {name: uuid.uuid4().hex for name in ("reporter", "target", "other")}
    try:
        await _migrate(engine, alembic_command.upgrade, "c4d1a8e35b72")
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO users (id, username, password_hash, display_name, state) "
                    "VALUES (:reporter, 'reporter', 'h', 'Reporter', 'registered'), "
                    "(:target, 'target', 'h', 'Target', 'registered'), "
                    "(:other, 'other', 'h', 'Other', 'registered')"
                ),
                ids,
            )
            # Three open reports from one person about the same player: only
            # the earliest may survive, or the index cannot be created.
            for index in range(3):
                await connection.execute(
                    text(
                        "INSERT INTO player_reports (id, reporter_user_id, "
                        "reported_user_id, reason, details, status, "
                        "context_snapshot, created_at) VALUES "
                        "(:id, :reporter, :target, 'spam', :details, 'pending', "
                        "'{}', :created_at)"
                    ),
                    {
                        "id": uuid.uuid4().hex,
                        "reporter": ids["reporter"],
                        "target": ids["target"],
                        "details": f"complaint {index}",
                        "created_at": f"2026-08-2{index + 1} 12:00:00",
                    },
                )
            # A report about somebody else is a different key and must survive.
            await connection.execute(
                text(
                    "INSERT INTO player_reports (id, reporter_user_id, "
                    "reported_user_id, reason, details, status, "
                    "context_snapshot, created_at) VALUES "
                    "(:id, :reporter, :other, 'spam', 'about another player', "
                    "'pending', '{}', '2026-08-24 12:00:00')"
                ),
                {"id": uuid.uuid4().hex, "reporter": ids["reporter"], "other": ids["other"]},
            )

        await _migrate(engine, alembic_command.upgrade, "head")

        async with engine.connect() as connection:
            surviving = (
                await connection.execute(
                    text(
                        "SELECT details FROM player_reports WHERE status = 'pending' "
                        "ORDER BY created_at"
                    )
                )
            ).scalars().all()
        # The earliest of the three, and the one about somebody else.
        assert surviving == ["complaint 0", "about another player"]
    finally:
        await engine.dispose()


async def test_letter_histogram_migration_counts_every_member(tmp_path):
    """The backfill prices a revision from everything it holds.

    Moderation state is mutable and membership is not, so counting the former
    would leave the tallies wrong the first time a version was hidden or
    restored - and a revision whose content was all hidden would carry a zero
    total, dropping wheel pricing onto the drawn sample. Letters outside a-z
    are absent from the tallies but present in the divisor, which is what keeps
    a non-English list's ratios unchanged.
    """
    engine = create_db_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'letter-histogram-migration.db'}"
    )
    script = ScriptDirectory.from_config(get_alembic_config())
    previous = script.get_revision("m6d1e7a4b829").down_revision
    assert isinstance(previous, str)
    identifiers = {
        "list": uuid.uuid4().hex,
        "revision": uuid.uuid4().hex,
        # A second revision holding only hidden content, to show the walk
        # covers more than one and prices membership rather than state.
        "empty_revision": uuid.uuid4().hex,
        "active_concept": uuid.uuid4().hex,
        "hidden_concept": uuid.uuid4().hex,
        "active": uuid.uuid4().hex,
        "hidden": uuid.uuid4().hex,
    }
    try:
        await _migrate(engine, alembic_command.upgrade, previous)
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO prompt_lists "
                    "(id, slug, name, language, is_bundled, visibility, "
                    "moderation_state, version) VALUES "
                    "(:list, 'legacy', 'Legacy list', 'en', 1, 'public', "
                    "'active', 1)"
                ),
                identifiers,
            )
            await connection.execute(
                text(
                    "INSERT INTO prompt_list_revisions "
                    "(id, prompt_list_id, version, language, content_hash) "
                    "VALUES (:revision, :list, 1, 'en', '')"
                ),
                identifiers,
            )
            await connection.execute(
                text(
                    "INSERT INTO prompt_list_revisions "
                    "(id, prompt_list_id, version, language, content_hash) "
                    "VALUES (:empty_revision, :list, 2, 'en', '')"
                ),
                identifiers,
            )
            for key, answer, state in (
                ("active", "café", "active"),
                ("hidden", "zzz", "hidden"),
            ):
                await connection.execute(
                    text(
                        f"INSERT INTO prompt_concepts (id) VALUES (:{key}_concept)"
                    ),
                    identifiers,
                )
                await connection.execute(
                    text(
                        "INSERT INTO prompt_versions "
                        "(id, concept_id, language, version, canonical_answer, "
                        "match_key, moderation_state) VALUES "
                        f"(:{key}, :{key}_concept, 'en', 1, '{answer}', "
                        f"'{answer}', '{state}')"
                    ),
                    identifiers,
                )
            for position, key in enumerate(("active", "hidden")):
                await connection.execute(
                    text(
                        "INSERT INTO prompt_list_revision_items "
                        "(revision_id, prompt_version_id, position) VALUES "
                        f"(:revision, :{key}, {position})"
                    ),
                    identifiers,
                )
            await connection.execute(
                text(
                    "INSERT INTO prompt_list_revision_items "
                    "(revision_id, prompt_version_id, position) VALUES "
                    "(:empty_revision, :hidden, 0)"
                ),
                identifiers,
            )

        await _migrate(engine, alembic_command.upgrade, "head")
        async with engine.connect() as connection:
            row = (
                await connection.execute(
                    text(
                        "SELECT letter_counts, letter_total "
                        "FROM prompt_list_revisions WHERE id = :revision"
                    ),
                    identifiers,
                )
            ).one()

        counts = row[0] if isinstance(row[0], dict) else json.loads(row[0])
        # "café": c, a, f counted; "é" is alphabetic, so it lifts the divisor
        # without being priceable. "zzz" is hidden today, but it is a member of
        # this revision and a moderator can restore it, so it is counted.
        assert counts == {"a": 1, "c": 1, "f": 1, "z": 3}
        assert row[1] == 7

        async with engine.connect() as connection:
            empty = (
                await connection.execute(
                    text(
                        "SELECT letter_counts, letter_total "
                        "FROM prompt_list_revisions WHERE id = :empty_revision"
                    ),
                    identifiers,
                )
            ).one()

        # A revision holding only hidden content is still priced: it has
        # members, and a zero total would drop pricing onto the drawn sample.
        empty_counts = empty[0] if isinstance(empty[0], dict) else json.loads(empty[0])
        assert empty_counts == {"z": 3}
        assert empty[1] == 3
    finally:
        await engine.dispose()


async def test_letter_histogram_migration_pages_past_the_first_batch(tmp_path):
    """More revisions than one slice holds, so the walk has to continue.

    The backfill pages by keyset rather than reading every revision ID, so a
    corpus larger than one batch is exactly where a wrong cursor shows up: it
    would stop after the first page and leave the rest unpriced.
    """
    engine = create_db_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'letter-histogram-paging.db'}"
    )
    script = ScriptDirectory.from_config(get_alembic_config())
    previous = script.get_revision("m6d1e7a4b829").down_revision
    assert isinstance(previous, str)

    # Loaded from the migration itself: the point is to exceed whatever it
    # pages by, not whatever this test guessed it pages by.
    batch_size = ScriptDirectory.from_config(get_alembic_config()).get_revision(
        "m6d1e7a4b829"
    ).module.BACKFILL_BATCH_SIZE
    total_revisions = batch_size * 2 + 3
    list_id = uuid.uuid4().hex
    concept_id = uuid.uuid4().hex
    version_id = uuid.uuid4().hex
    revision_ids = [uuid.uuid4().hex for _ in range(total_revisions)]
    try:
        await _migrate(engine, alembic_command.upgrade, previous)
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO prompt_lists "
                    "(id, slug, name, language, is_bundled, visibility, "
                    "moderation_state, version) VALUES "
                    "(:id, 'paged', 'Paged', 'en', 1, 'public', 'active', 1)"
                ),
                {"id": list_id},
            )
            await connection.execute(
                text("INSERT INTO prompt_concepts (id) VALUES (:id)"),
                {"id": concept_id},
            )
            await connection.execute(
                text(
                    "INSERT INTO prompt_versions "
                    "(id, concept_id, language, version, canonical_answer, "
                    "match_key, moderation_state) VALUES "
                    "(:id, :concept, 'en', 1, 'ox', 'ox', 'active')"
                ),
                {"id": version_id, "concept": concept_id},
            )
            await connection.execute(
                text(
                    "INSERT INTO prompt_list_revisions "
                    "(id, prompt_list_id, version, language, content_hash) "
                    "VALUES (:id, :list, :version, 'en', '')"
                ),
                [
                    {"id": rid, "list": list_id, "version": index + 1}
                    for index, rid in enumerate(revision_ids)
                ],
            )
            # Every revision holds the same one-prompt membership, so each must
            # come back priced - including the ones past the first page.
            await connection.execute(
                text(
                    "INSERT INTO prompt_list_revision_items "
                    "(revision_id, prompt_version_id, position) "
                    "VALUES (:id, :version, 0)"
                ),
                [{"id": rid, "version": version_id} for rid in revision_ids],
            )

        await _migrate(engine, alembic_command.upgrade, "head")
        async with engine.connect() as connection:
            priced = await connection.scalar(
                text(
                    "SELECT count(*) FROM prompt_list_revisions "
                    "WHERE letter_total = 2"
                )
            )

        assert priced == total_revisions
    finally:
        await engine.dispose()


async def test_the_tightening_refuses_a_database_with_legacy_rows(tmp_path):
    """p8c3a6d9e147 assumes a pre-production database. One that still holds
    pre-feature rows must be rebuilt (docs/database.md, Pre-v1 note), and the
    migration says so instead of fabricating timestamps or deleting history."""
    engine = create_db_engine(f"sqlite+aiosqlite:///{tmp_path / 'refuse.db'}")
    try:
        script = ScriptDirectory.from_config(get_alembic_config())
        before_timestamps = script.get_revision("a1e4c7d9b632").down_revision
        assert isinstance(before_timestamps, str)
        await _migrate(engine, alembic_command.upgrade, before_timestamps)
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO app_config (key, value) "
                    "VALUES ('legacy_secret', 'legacy')"
                )
            )
        with pytest.raises(Exception, match="rebuild this pre-production database"):
            await _migrate(engine, alembic_command.upgrade, "head")
    finally:
        await engine.dispose()


async def test_coherence_migration_backfills_outcome_game_ids(tmp_path):
    """r1e5c8f3a469 adds outcomes' game_id over live rows: the value is copied
    from the turn that owns each outcome, never invented, and the composite
    constraints only tighten after every row carries it."""
    engine = create_db_engine(f"sqlite+aiosqlite:///{tmp_path / 'backfill.db'}")
    game_id = uuid.uuid4().hex
    seat_id = uuid.uuid4().hex
    turn_id = uuid.uuid4().hex
    try:
        await _migrate(engine, alembic_command.upgrade, "q9d4b7e2f358")
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO game_records (id, payload_hash, room_name, "
                    "scoring_mode, hint_mode, drawing_seconds, total_rounds, "
                    "player_count, started_at, finished_at, outcome, "
                    "prompt_source_mode) VALUES (:id, '', 'Backfill', 'default', "
                    "'none', 90, 1, 1, '2026-08-24 12:00:00', "
                    "'2026-08-24 12:10:00', 'finished', 'custom')"
                ),
                {"id": game_id},
            )
            await connection.execute(
                text(
                    "INSERT INTO game_participants (id, game_id, final_score, "
                    "final_rank, is_anonymous_snapshot, display_name_snapshot) "
                    "VALUES (:id, :game_id, 10, 1, 1, 'Seat')"
                ),
                {"id": seat_id, "game_id": game_id},
            )
            await connection.execute(
                text(
                    "INSERT INTO turn_records (id, game_id, round_number, "
                    "turn_number, drawer_participant_id, "
                    "drawer_display_name_snapshot, drawer_is_anonymous_snapshot, "
                    "prompt, prompt_source_kind, duration_seconds) VALUES "
                    "(:id, :game_id, 1, 1, :seat, 'Seat', 1, 'anchor', "
                    "'custom', 10)"
                ),
                {"id": turn_id, "game_id": game_id, "seat": seat_id},
            )
            await connection.execute(
                text(
                    "INSERT INTO turn_participant_outcomes (id, turn_id, "
                    "participant_id, eligible, eligibility_reason, outcome, "
                    "terminal_state) VALUES (:id, :turn, :seat, 1, 'eligible', "
                    "'no_attempt', 'active')"
                ),
                {"id": uuid.uuid4().hex, "turn": turn_id, "seat": seat_id},
            )

        await _migrate(engine, alembic_command.upgrade, "head")
        async with engine.begin() as connection:
            backfilled = (
                await connection.execute(
                    text("SELECT game_id FROM turn_participant_outcomes")
                )
            ).scalar_one()
        assert backfilled == game_id
    finally:
        await engine.dispose()
