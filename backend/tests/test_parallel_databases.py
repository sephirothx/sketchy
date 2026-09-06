"""Parallel tests own distinct migrated databases and never drop their source."""
from __future__ import annotations

import os
from uuid import uuid4

import asyncpg
import pytest
from sqlalchemy.engine import make_url

from tests.dbfixtures import create_test_db
from tests.parallel_databases import WorkerDatabases


@pytest.mark.parametrize("url", [
    "postgresql+asyncpg://localhost/sketchy",
    "postgresql+asyncpg://test:password@localhost/live?application_name=test",
    "postgresql+asyncpg://localhost/",
])
def test_a_worker_name_cannot_make_an_unsafe_template_disposable(url):
    with pytest.raises(RuntimeError, match="refusing to empty"):
        WorkerDatabases(url)


def test_parallel_databases_require_postgresql():
    with pytest.raises(ValueError, match="PostgreSQL"):
        WorkerDatabases("sqlite+aiosqlite:///test.db")


@pytest.mark.asyncio
@pytest.mark.skipif(not os.environ.get("TEST_DATABASE_URL"), reason="requires PostgreSQL")
async def test_worker_clones_keep_migrations_and_isolate_rows_and_cleanup():
    # Empty the source with the usual fixture, then release it for cloning.
    _, engine = await create_test_db()
    await engine.dispose()
    manager = WorkerDatabases(os.environ["TEST_DATABASE_URL"])
    connections = []
    admin = await asyncpg.connect(manager.admin_url.render_as_string(hide_password=False))
    try:
        urls = [await manager.create(), await manager.create()]
        names = [make_url(url).database for url in urls]
        assert len(set(names)) == 2
        assert manager.template.database not in names
        assert all(len(name.encode()) <= 63 for name in names)
        ident = uuid4()
        for url in urls:
            connection = await asyncpg.connect(
                make_url(url).set(drivername="postgresql").render_as_string(hide_password=False)
            )
            connections.append(connection)
            assert await connection.fetchval("SELECT version_num FROM alembic_version")
            # A hand-written migration trigger, not just create_all's tables.
            assert await connection.fetchval(
                "SELECT count(*) FROM pg_trigger WHERE tgrelid = 'score_events'::regclass "
                "AND NOT tgisinternal"
            ) > 0
            await connection.execute(
                "INSERT INTO users (id, display_name) VALUES ($1, 'Isolated')", ident,
            )
        await connections[0].execute("DELETE FROM users WHERE id = $1", ident)
        assert await connections[0].fetchval("SELECT count(*) FROM users") == 0
        assert await connections[1].fetchval("SELECT count(*) FROM users") == 1
        # Also clean up a still-connected worker, as after a crash.
        await manager.close()
        assert not manager.names
        assert await admin.fetchval(
            "SELECT count(*) FROM pg_database WHERE datname = ANY($1::text[])", names,
        ) == 0
        assert await admin.fetchval(
            "SELECT count(*) FROM pg_database WHERE datname = $1", manager.template.database,
        ) == 1
        await manager.close()  # idempotent, never expands its ownership
    finally:
        for connection in connections:
            await connection.close()
        await manager.close()
        await admin.close()
