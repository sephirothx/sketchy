"""Database engine, session management, and lifecycle initialization."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from alembic.config import Config as AlembicConfig
from alembic import command as alembic_command
from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

DEFAULT_DATABASE_URL = "sqlite+aiosqlite:///./sketchy.db"
SQLITE_BUSY_TIMEOUT_MS = 5_000


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


def create_db_engine(url: str | None = None) -> AsyncEngine:
    """Create an async SQLAlchemy engine instance."""
    resolved_url = url or get_database_url()
    engine = create_async_engine(
        resolved_url,
        echo=False,
        connect_args=get_engine_connect_args(resolved_url),
        future=True,
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


def _run_alembic_upgrade_sync(connection: Any, alembic_cfg: AlembicConfig) -> None:
    alembic_cfg.attributes["connection"] = connection
    alembic_command.upgrade(alembic_cfg, "head")


async def init_db(engine: AsyncEngine | None = None) -> None:
    """Initialize database schema by running Alembic migrations to head."""
    target_engine = engine or async_engine
    alembic_cfg = get_alembic_config()

    async with target_engine.begin() as conn:
        await conn.run_sync(_run_alembic_upgrade_sync, alembic_cfg)
