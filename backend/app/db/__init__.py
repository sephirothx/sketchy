"""Database engine, session management, and lifecycle initialization."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any
import warnings

from alembic.config import Config as AlembicConfig
from alembic import command as alembic_command
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import event, text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import SAWarning
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

DEFAULT_DATABASE_URL = "sqlite+aiosqlite:///./sketchy.db"
SQLITE_BUSY_TIMEOUT_MS = 5_000
POSTGRES_POOL_SIZE = 5
POSTGRES_MAX_OVERFLOW = 5
POSTGRES_POOL_TIMEOUT_SECONDS = 10
POSTGRES_POOL_RECYCLE_SECONDS = 1_800
POSTGRES_MIGRATION_LOCK_ID = int.from_bytes(b"SKETCHY", "big")


class DatabaseRevisionError(RuntimeError):
    """Raised when an externally managed database is not at Alembic head."""


def _configure_sqlite_connection(dbapi_connection: Any, _: Any) -> None:
    """Apply SQLite integrity and concurrency settings to every connection."""
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute(f"PRAGMA busy_timeout={SQLITE_BUSY_TIMEOUT_MS}")
    finally:
        cursor.close()


def get_database_url() -> str:
    """Read and normalize the database connection URL from environment."""
    url = os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL).strip()
    if not url:
        return DEFAULT_DATABASE_URL

    # Normalize common scheme prefixes to async driver counterparts
    if url.startswith("sqlite://") and not url.startswith("sqlite+aiosqlite://"):
        url = url.replace("sqlite://", "sqlite+aiosqlite://", 1)
    elif url.startswith("postgresql://") and not url.startswith("postgresql+asyncpg://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    elif url.startswith("postgres://") and not url.startswith("postgresql+asyncpg://"):
        url = url.replace("postgres://", "postgresql+asyncpg://", 1)

    return url


def get_engine_connect_args(url: str) -> dict[str, Any]:
    """Provide driver-specific engine parameters."""
    if url.startswith("sqlite"):
        return {"check_same_thread": False}
    return {}


def _integer_setting(name: str, default: int, *, minimum: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError as error:
        raise ValueError(f"{name} must be an integer") from error
    if value < minimum:
        raise ValueError(f"{name} must be at least {minimum}")
    return value


def get_engine_pool_options(url: str) -> dict[str, Any]:
    """Return deliberate production pool limits for PostgreSQL engines."""
    if not url.startswith("postgresql"):
        return {}
    return {
        "pool_pre_ping": True,
        "pool_size": _integer_setting(
            "DB_POOL_SIZE", POSTGRES_POOL_SIZE, minimum=1
        ),
        "max_overflow": _integer_setting(
            "DB_MAX_OVERFLOW", POSTGRES_MAX_OVERFLOW, minimum=0
        ),
        "pool_timeout": _integer_setting(
            "DB_POOL_TIMEOUT_SECONDS", POSTGRES_POOL_TIMEOUT_SECONDS, minimum=1
        ),
        "pool_recycle": _integer_setting(
            "DB_POOL_RECYCLE_SECONDS", POSTGRES_POOL_RECYCLE_SECONDS, minimum=1
        ),
    }


def create_db_engine(url: str | None = None) -> AsyncEngine:
    """Create an async SQLAlchemy engine instance."""
    resolved_url = url or get_database_url()
    engine = create_async_engine(
        resolved_url,
        echo=False,
        connect_args=get_engine_connect_args(resolved_url),
        future=True,
        **get_engine_pool_options(resolved_url),
    )
    if resolved_url.startswith("sqlite"):
        event.listen(engine.sync_engine, "connect", _configure_sqlite_connection)
    return engine


# Default process-wide engine and session factory
async_engine: AsyncEngine = create_db_engine()
async_session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
    async_engine,
    expire_on_commit=False,
    class_=AsyncSession,
)


def get_alembic_config(ini_path: Path | None = None) -> AlembicConfig:
    """Construct an Alembic Config object pointing to the repository alembic setup."""
    if ini_path is None:
        ini_path = Path(__file__).resolve().parent.parent.parent / "alembic.ini"
    cfg = AlembicConfig(str(ini_path))
    cfg.attributes["skip_logging_config"] = True
    return cfg


def _run_alembic_upgrade_sync(
    connection: Connection, alembic_cfg: AlembicConfig
) -> None:
    alembic_cfg.attributes["connection"] = connection
    # SQLite cannot reflect the one hand-written expression index. Revision
    # 9b6f4e2d1a70 and the migration suite pin its exact definition directly,
    # so suppress only this known warning while batch migrations reflect FKs.
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message=r".*ix_users_username_lower.*",
            category=SAWarning,
        )
        alembic_command.upgrade(alembic_cfg, "head")


def _database_revisions_sync(
    connection: Connection, alembic_cfg: AlembicConfig
) -> tuple[set[str], set[str]]:
    current = set(MigrationContext.configure(connection).get_current_heads())
    expected = set(ScriptDirectory.from_config(alembic_cfg).get_heads())
    return current, expected


async def upgrade_database(engine: AsyncEngine | None = None) -> None:
    """Upgrade to Alembic head, serializing PostgreSQL deploys."""
    target_engine = engine or async_engine
    alembic_cfg = get_alembic_config()

    async with target_engine.begin() as conn:
        if target_engine.dialect.name == "postgresql":
            # A transaction-scoped lock releases automatically on both commit
            # and rollback, including when migration DDL fails.
            await conn.execute(
                text("SELECT pg_advisory_xact_lock(:lock_id)"),
                {"lock_id": POSTGRES_MIGRATION_LOCK_ID},
            )
        await conn.run_sync(_run_alembic_upgrade_sync, alembic_cfg)


async def verify_database_head(engine: AsyncEngine | None = None) -> None:
    """Fail startup clearly when a managed database has not been migrated."""
    target_engine = engine or async_engine
    alembic_cfg = get_alembic_config()
    async with target_engine.connect() as conn:
        current, expected = await conn.run_sync(_database_revisions_sync, alembic_cfg)
    if current != expected:
        raise DatabaseRevisionError(
            "Database schema is not at Alembic head "
            f"(current: {sorted(current) or ['base']}; expected: {sorted(expected)}). "
            "Run `python -m app.db.migrate` before starting Sketchy."
        )


async def init_db(engine: AsyncEngine | None = None) -> None:
    """Prepare zero-config SQLite or verify externally managed databases."""
    target_engine = engine or async_engine
    if target_engine.dialect.name == "sqlite":
        await upgrade_database(target_engine)
    else:
        await verify_database_head(target_engine)
