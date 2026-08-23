"""One database fixture for suites that must also run on PostgreSQL.

With ``TEST_DATABASE_URL`` set, tests run against the migrated external
database so dialect-specific behaviour - row locking, native UUID storage,
server defaults - is actually exercised. Without it they fall back to an
in-memory SQLite database built from the models.
"""

from __future__ import annotations

import os

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.db.models import Base


async def create_test_db() -> tuple[async_sessionmaker[AsyncSession], AsyncEngine]:
    external_url = os.environ.get("TEST_DATABASE_URL")
    if external_url:
        engine = create_async_engine(external_url, echo=False)
        # The external database is migrated before this suite starts. Keep the
        # schema intact so tests exercise Alembic's output, while isolating
        # tests by removing application rows in dependency order.
        async with engine.begin() as conn:
            for table in reversed(Base.metadata.sorted_tables):
                await conn.execute(table.delete())
        factory = async_sessionmaker(
            engine, expire_on_commit=False, class_=AsyncSession
        )
        return factory, engine

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    return factory, engine
