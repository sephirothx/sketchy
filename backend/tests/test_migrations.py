"""Migration replay, downgrade, drift, and hand-written schema checks."""
from __future__ import annotations

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
            ("turn_records", "drawer_participant_id"): "SET NULL",
            ("turn_guesses", "participant_id"): "SET NULL",
            ("turn_guesses", "outcome_id"): "CASCADE",
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

        await _migrate(engine, alembic_command.upgrade, "head")
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

        await _migrate(engine, alembic_command.upgrade, "head")
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

        await _migrate(engine, alembic_command.upgrade, "head")
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

        await _migrate(engine, alembic_command.upgrade, "head")
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
