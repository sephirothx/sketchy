"""The test database survives what the application does to a connection.

One in-memory SQLite database sits behind one pooled connection. A statement
cancelled mid-flight - the block lookup on the chat path gives up after two
seconds and moves on, by design - makes SQLAlchemy discard the connection,
and a replacement `:memory:` connection is a brand-new empty database. Every
later statement in the test then fails with "no such table", far from the
cancellation that caused it (seen once on CI in test_message_retention.py).
"""
from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import select, text

from app.db.models import User

from tests.dbfixtures import create_test_db


# Enough work to keep SQLite busy well past the timeout below.
SLOW_QUERY = text(
    "WITH RECURSIVE n(i) AS (SELECT 1 UNION ALL SELECT i + 1 FROM n WHERE i < 20000000) "
    "SELECT count(*) FROM n"
)


async def test_a_statement_cancelled_mid_flight_does_not_lose_the_database():
    factory, engine = await create_test_db()
    try:
        async with factory() as session:
            async with session.begin():
                session.add(User(display_name="Still here"))

        async def slow_read() -> None:
            async with factory() as session:
                await session.execute(SLOW_QUERY)

        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(slow_read(), timeout=0.2)

        async with factory() as session:
            names = (await session.scalars(select(User.display_name))).all()
        assert names == ["Still here"], "the schema and the rows outlive a cancelled statement"
    finally:
        await engine.dispose()
