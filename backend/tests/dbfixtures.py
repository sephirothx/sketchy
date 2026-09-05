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
deletions that only failed once enforcement was real. No test module builds
its own engine any more; that is the point of this file.
"""

from __future__ import annotations

import os
from typing import Any

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

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
    database_name = url.rsplit("/", 1)[-1].split("?", 1)[0]
    if "test" not in database_name.lower():
        raise RuntimeError(
            f"refusing to empty {database_name!r}: TEST_DATABASE_URL must name a "
            "disposable database whose name contains 'test'"
        )


def create_test_engine(url: str | None = None) -> AsyncEngine:
    """An engine configured like the application's, for the URL given.

    Defaults to `TEST_DATABASE_URL`, then to in-memory SQLite. SQLite engines
    get the production pragmas and a per-connection foreign-key check.
    """
    resolved = url or os.environ.get("TEST_DATABASE_URL") or SQLITE_MEMORY_URL
    engine = create_async_engine(
        resolved, echo=False, connect_args=get_engine_connect_args(resolved)
    )
    if resolved.startswith("sqlite"):
        event.listen(engine.sync_engine, "connect", configure_sqlite_connection)
        event.listen(engine.sync_engine, "connect", _assert_foreign_keys_enforced)
    return engine


async def create_test_db() -> tuple[async_sessionmaker[AsyncSession], AsyncEngine]:
    """A session factory and its engine over an empty, integrity-enforcing schema."""
    external_url = os.environ.get("TEST_DATABASE_URL")
    if external_url:
        assert_disposable(external_url)
        engine = create_test_engine(external_url)
        # The external database is migrated before this suite starts. Keep the
        # schema intact so tests exercise Alembic's output, while isolating
        # tests by removing application rows in dependency order.
        async with engine.begin() as conn:
            for table in reversed(Base.metadata.sorted_tables):
                await conn.execute(table.delete())
    else:
        engine = create_test_engine(SQLITE_MEMORY_URL)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    return factory, engine
