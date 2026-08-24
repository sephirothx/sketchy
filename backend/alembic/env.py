"""Alembic environment configuration for async migrations."""
from __future__ import annotations

import asyncio
from logging.config import fileConfig
import os

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context
from app.db.models import Base
from app.db import assert_references_intact, get_database_url

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
if config.config_file_name is not None and not config.attributes.get("skip_logging_config"):
    try:
        fileConfig(config.config_file_name)
    except Exception:
        pass

# Target metadata for autogenerate support
target_metadata = Base.metadata


def get_url() -> str:
    """Resolve database URL dynamically from environment or default."""
    url = config.get_main_option("sqlalchemy.url")
    if not url or url.startswith("driver://"):
        return get_database_url()
    return url


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """Run migrations using an active synchronous connection.

    SQLite runs the chain with foreign keys off. Batch mode rebuilds a table by
    copy, drop, rename, and with enforcement on, DROP TABLE performs an
    implicit DELETE that fires ON DELETE CASCADE - so altering any table that
    others point at silently empties them and then hands back a table that
    still looks correct. Measured, not assumed.

    The pragma is set here rather than inside a migration because SQLite
    ignores it once a transaction is open, and by the time a migration in the
    middle of the chain runs, one is. Nothing is being skipped that matters:
    migrations move schema, not application writes, and every reference is
    checked again at the end.
    """
    if connection.dialect.name == "sqlite":
        connection.exec_driver_sql("PRAGMA foreign_keys=OFF")

    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        render_as_batch=True,
    )

    try:
        with context.begin_transaction():
            context.run_migrations()
        if connection.dialect.name == "sqlite":
            assert_references_intact(connection)
    finally:
        if connection.dialect.name == "sqlite":
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")


async def run_async_migrations() -> None:
    """Create async engine from config and run migrations."""
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = get_url()

    connectable = async_engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    connection = config.attributes.get("connection")
    if connection is not None:
        do_run_migrations(connection)
        return

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        # Running inside an active event loop without provided connection
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            executor.submit(lambda: asyncio.run(run_async_migrations())).result()
    else:
        asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
