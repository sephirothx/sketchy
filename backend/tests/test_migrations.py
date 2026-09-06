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
    return differences


async def _sqlite_inline_reference_actions(engine: AsyncEngine) -> dict[tuple[str, str], str]:
    """ON DELETE actions SQLite actually enforces for the references whose
    action the application relies on, read from the pragma rather than
    from what SQLAlchemy reflects."""
    expected_columns = {
        ("turn_records", "prompt_version_id"),
        ("turn_records", "drawer_participant_id"),
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


async def _assert_hand_written_indexes(engine: AsyncEngine) -> None:
    """The two expression indexes autogenerate cannot see (#557)."""
    for name, column in (
        ("ix_users_username_lower", "username"),
        ("ix_users_email_lower", "email"),
    ):
        definition = await _index_definition(engine, name)
        assert definition is not None, name
        normalized = definition.lower()
        assert "unique" in normalized
        assert "lower" in normalized
        assert column in normalized
        assert "where" in normalized


async def _assert_payload_storage(engine: AsyncEngine, expected: str) -> None:
    """Stored drawings are deflated already, so PostgreSQL keeps them out of
    line uncompressed: EXTERNAL ('e'), not the EXTENDED ('x') default. Alembic
    does not compare storage, so the chain test pins it directly."""
    if engine.dialect.name != "postgresql":
        return
    async with engine.connect() as connection:
        rows = (
            await connection.execute(
                text(
                    "SELECT attrelid::regclass::text, attstorage::text FROM pg_attribute "
                    "WHERE attname = 'payload' AND attrelid IN "
                    "('turn_drawings'::regclass, 'player_report_drawing_evidence'::regclass)"
                )
            )
        ).all()
    assert {(table, storage) for table, storage in rows} == {
        ("turn_drawings", expected),
        ("player_report_drawing_evidence", expected),
    }


async def _exercise_migration_chain(engine: AsyncEngine) -> None:
    """The baseline (#557) and what came after it: build to head, prove it
    matches the models, run the newest revision backward and forward, remove
    everything, and build it again from nothing."""
    script = ScriptDirectory.from_config(get_alembic_config())
    revisions = list(script.walk_revisions())
    assert [revision.revision for revision in revisions] == [
        "b3c4d5e6f7a8",
        "a2b3c4d5e6f7",
        "f0a1b2c3d4e5",
    ]
    head = revisions[0].revision
    foundation = revisions[-1].revision

    await _migrate(engine, alembic_command.upgrade, "head")
    assert await _current_revisions(engine) == {head}
    assert await _schema_differences(engine) == []
    if engine.dialect.name == "sqlite":
        assert await _sqlite_inline_reference_actions(engine) == {
            ("turn_records", "prompt_version_id"): "RESTRICT",
            ("turn_records", "drawer_participant_id"): "CASCADE",
            # A suspension outlives the report it was decided from.
            ("user_bans", "source_report_id"): "SET NULL",
        }
    await _assert_hand_written_indexes(engine)
    await _assert_payload_storage(engine, "e")

    # Run the newest revisions backward and replay them.
    await _migrate(engine, alembic_command.downgrade, foundation)
    assert await _current_revisions(engine) == {foundation}
    await _assert_payload_storage(engine, "x")
    await _migrate(engine, alembic_command.upgrade, "head")
    assert await _current_revisions(engine) == {head}
    assert await _schema_differences(engine) == []
    await _assert_payload_storage(engine, "e")

    # Prove the whole schema can be removed, then rebuilt from an empty database.
    await _migrate(engine, alembic_command.downgrade, "base")
    assert await _current_revisions(engine) == set()
    assert await _index_definition(engine) is None

    def table_names(sync_connection):
        return inspect(sync_connection).get_table_names()

    async with engine.connect() as connection:
        tables = set(await connection.run_sync(table_names))
    assert set(Base.metadata.tables).isdisjoint(tables)

    await _migrate(engine, alembic_command.upgrade, "head")
    assert await _current_revisions(engine) == {head}
    assert await _schema_differences(engine) == []
    await _assert_hand_written_indexes(engine)


async def test_sqlite_migration_chain_round_trip(tmp_path):
    engine = create_db_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'migration-round-trip.db'}"
    )
    try:
        await _exercise_migration_chain(engine)
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

    Autogenerate renders table-level checks and silently drops column-level
    ones; this is the one that was column-level when the baseline was cut
    (#557), and the proof that it made the crossing.
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


async def test_a_migrated_database_keeps_score_events_immutable(tmp_path):
    """The append-only trigger is hand-written DDL the baseline has to carry
    on both dialects (R-HIST-11); the SQLite side is proven here and the
    PostgreSQL side by the repository suite on that engine."""
    engine = create_db_engine(f"sqlite+aiosqlite:///{tmp_path / 'ledger.db'}")
    identifiers = {
        "user": uuid.uuid4().hex,
        "game": uuid.uuid4().hex,
        "participant": uuid.uuid4().hex,
        "turn": uuid.uuid4().hex,
    }
    try:
        await _migrate(engine, alembic_command.upgrade, "head")
        async with engine.begin() as connection:
            await connection.execute(
                text("INSERT INTO users (id, display_name) VALUES (:user, 'Ledger')"),
                identifiers,
            )
            await connection.execute(
                text(
                    "INSERT INTO game_records (id, payload_hash, room_name, "
                    "scoring_mode, hint_mode, drawing_seconds, total_rounds, "
                    "player_count, started_at, finished_at, outcome, "
                    "prompt_source_mode, scoring_version, score_ledger_version, "
                    "rule_snapshot_version) VALUES "
                    "(:game, '', 'Room', 'default', 'none', 90, 1, 1, "
                    "'2026-01-01 00:00:00', '2026-01-01 00:10:00', 'finished', "
                    "'custom', 1, 1, 1)"
                ),
                identifiers,
            )
            await connection.execute(
                text(
                    "INSERT INTO game_participants (id, game_id, user_id, "
                    "display_name_snapshot, is_anonymous_snapshot, final_score, "
                    "final_rank) VALUES (:participant, :game, :user, 'Ledger', 1, 100, 1)"
                ),
                identifiers,
            )
            await connection.execute(
                text(
                    "INSERT INTO turn_records (id, game_id, round_number, turn_number, "
                    "drawer_user_id, drawer_participant_id, drawer_display_name_snapshot, "
                    "drawer_is_anonymous_snapshot, prompt, duration_seconds, "
                    "prompt_source_kind) VALUES (:turn, :game, 1, 1, :user, "
                    ":participant, 'Ledger', 1, 'apple', 30, 'custom')"
                ),
                identifiers,
            )
            await connection.execute(
                text(
                    "INSERT INTO score_events (game_id, event_order, participant_id, "
                    "turn_id, event_type, points_delta) VALUES "
                    "(:game, 1, :participant, :turn, 'guess_award', 100)"
                ),
                identifiers,
            )
        with pytest.raises(DBAPIError, match="immutable"):
            async with engine.begin() as connection:
                await connection.execute(
                    text(
                        "UPDATE score_events SET points_delta = 99 "
                        "WHERE game_id = :game AND event_order = 1"
                    ),
                    identifiers,
                )
    finally:
        await engine.dispose()
