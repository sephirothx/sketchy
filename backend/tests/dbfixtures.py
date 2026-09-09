"""One database fixture for every suite that persists rows.

With ``TEST_DATABASE_URL`` set, tests run against the migrated external
database so dialect-specific behaviour - row locking, native UUID storage,
server defaults, READ COMMITTED interleavings - is actually exercised.
Without it they fall back to an in-memory SQLite database built from the
models.

Either way the connection is configured the way the application configures
its own (`app.db.configure_sqlite_connection`), and every SQLite connection
is checked to have foreign keys on. A raw `create_async_engine` does not turn
them on, so a suite built on one can pass while the database ignores the very
constraints its deletions rely on - #612 reproduced list and account
deletions that only failed once enforcement was real. Tests of SQLite's
file-backed concurrency explicitly use fresh temporary files instead.
"""

from __future__ import annotations

import os
from typing import Any

from sqlalchemy import event
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.schema import CreateIndex, CreateTable

from app.db import configure_sqlite_connection, get_engine_connect_args
from app.db.models import Base

SQLITE_MEMORY_URL = "sqlite+aiosqlite:///:memory:"


class ForeignKeysOffError(RuntimeError):
    """A test SQLite connection came up without foreign-key enforcement."""


def _assert_foreign_keys_enforced(dbapi_connection: Any, _: Any) -> None:
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys")
        (enabled,) = cursor.fetchone()
    finally:
        cursor.close()
    if int(enabled) != 1:
        raise ForeignKeysOffError(
            "test SQLite connection has PRAGMA foreign_keys off; the fixture "
            "must configure connections the way app.db does"
        )


def assert_disposable(url: str) -> None:
    """Refuse a database the suite must not empty.

    `create_test_db` deletes every application row of the database it is
    pointed at. A name carrying `test` is the convention CI and the README
    use; anything else is presumed to be somebody's data.
    """
    database_name = make_url(url).database or ""
    if "test" not in database_name.lower():
        raise RuntimeError(
            f"refusing to empty {database_name!r}: TEST_DATABASE_URL must name a "
            "disposable database whose name contains 'test'"
        )


def create_test_engine(url: str | None = None, *, role: str = "web") -> AsyncEngine:
    """An engine configured like the application's, for the URL given.

    Defaults to `TEST_DATABASE_URL`, then to in-memory SQLite. SQLite engines
    get the production pragmas and a per-connection foreign-key check.

    `role` picks the PostgreSQL budget, and defaults to the one nearly every
    test wants: a web request, with the statement timeout a player's request
    actually gets. A test that exercises work production runs on a different
    engine - `maintenance_engine()`, for a rebuild or a sweep - asks for that
    role instead, so it is held to the budget its own code path has rather
    than to one it would never run under.
    """
    resolved = url or os.environ.get("TEST_DATABASE_URL") or SQLITE_MEMORY_URL
    engine = create_async_engine(
        resolved, echo=False, connect_args=get_engine_connect_args(resolved, role=role)
    )
    if resolved.startswith("sqlite"):
        event.listen(engine.sync_engine, "connect", configure_sqlite_connection)
        event.listen(engine.sync_engine, "connect", _assert_foreign_keys_enforced)
    return engine


# Both schema scripts are compiled once per process. Several hundred tests
# build a database each, and compiling the same 150-odd statements for every
# one of them was most of what a fresh database cost (#660).
_SQLITE_SCHEMA_SCRIPT: str | None = None
_POSTGRESQL_WIPE_SCRIPT: str | None = None


def _sqlite_schema_script() -> str:
    """Every CREATE the models compile to for SQLite, as one script.

    The statements are the ones `Base.metadata.create_all(checkfirst=False)`
    would run, in its order, so the schema is identical - a test in
    `test_db_models.py` still proves the models match the migrations.
    Running them as one script costs one hop to aiosqlite's thread instead
    of one per statement.
    """
    global _SQLITE_SCHEMA_SCRIPT
    if _SQLITE_SCHEMA_SCRIPT is None:
        dialect = sqlite.dialect()
        statements = []
        for table in Base.metadata.sorted_tables:
            statements.append(str(CreateTable(table).compile(dialect=dialect)))
            statements.extend(
                str(CreateIndex(index).compile(dialect=dialect)) for index in table.indexes
            )
        _SQLITE_SCHEMA_SCRIPT = ";\n".join(s.strip() for s in statements) + ";"
    return _SQLITE_SCHEMA_SCRIPT


def _postgresql_wipe_script() -> str:
    """One DELETE per application table, children first, as one round trip.

    TRUNCATE was measured slower here - it rewrites every table's file even
    when empty - and a DELETE per statement is a round trip per table.
    """
    global _POSTGRESQL_WIPE_SCRIPT
    if _POSTGRESQL_WIPE_SCRIPT is None:
        quote = postgresql.dialect().identifier_preparer.quote
        _POSTGRESQL_WIPE_SCRIPT = "; ".join(
            f"DELETE FROM {quote(table.name)}" for table in reversed(Base.metadata.sorted_tables)
        )
    return _POSTGRESQL_WIPE_SCRIPT


async def _run_driver_script(conn: AsyncConnection, script: str) -> None:
    """Run a multi-statement script through the driver, in one round trip.

    SQLAlchemy prepares every statement it sends, and a prepared statement
    holds one statement; the drivers underneath both accept a script.
    """
    raw = await conn.get_raw_connection()
    driver = raw.driver_connection
    if hasattr(driver, "executescript"):  # aiosqlite
        await driver.executescript(script)
    else:  # asyncpg
        await driver.execute(script)


async def create_test_db(
    *, role: str = "web"
) -> tuple[async_sessionmaker[AsyncSession], AsyncEngine]:
    """A session factory and its engine over an empty, integrity-enforcing schema.

    See `create_test_engine` for `role`.
    """
    external_url = os.environ.get("TEST_DATABASE_URL")
    if external_url:
        assert_disposable(external_url)
        engine = create_test_engine(external_url, role=role)
        # The external database is migrated before this suite starts. Keep the
        # schema intact so tests exercise Alembic's output, while isolating
        # tests by removing application rows in dependency order.
        async with engine.begin() as conn:
            await _run_driver_script(conn, _postgresql_wipe_script())
    else:
        engine = create_test_engine(SQLITE_MEMORY_URL)
        async with engine.begin() as conn:
            # This connection owns a brand-new in-memory database.
            await _run_driver_script(conn, _sqlite_schema_script())

    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    return factory, engine
