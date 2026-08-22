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
from sqlalchemy.exc import SAWarning
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
            return await connection.run_sync(diff)


async def _exercise_migration_chain(engine: AsyncEngine) -> None:
    script = ScriptDirectory.from_config(get_alembic_config())
    revisions = list(script.walk_revisions())
    assert len(revisions) >= 2, "migration replay requires more than one revision"
    head = revisions[0].revision
    foundation = revisions[-1].revision

    await _migrate(engine, alembic_command.upgrade, "head")
    assert await _current_revisions(engine) == {head}
    assert await _schema_differences(engine) == []
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
