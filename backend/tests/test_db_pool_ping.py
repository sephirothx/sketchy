"""A pooled connection is checked for free, and pinged only after a quiet spell (#973)."""
from __future__ import annotations

import asyncio
import os

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db import (
    POSTGRES_POOL_PING_IDLE_SECONDS,
    get_engine_connect_args,
    get_engine_pool_options,
    install_idle_ping,
    pool_ping_idle_seconds,
)


PG_URL = os.environ.get("TEST_DATABASE_URL", "")
ON_POSTGRESQL = PG_URL.startswith("postgresql")
needs_postgresql = pytest.mark.skipif(
    not ON_POSTGRESQL, reason="the checkout ping is configured for PostgreSQL only"
)


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_the_idle_threshold_defaults_and_is_overridable(monkeypatch):
    monkeypatch.delenv("DB_POOL_PING_IDLE_SECONDS", raising=False)
    assert pool_ping_idle_seconds() == POSTGRES_POOL_PING_IDLE_SECONDS == 30
    monkeypatch.setenv("DB_POOL_PING_IDLE_SECONDS", "5")
    assert pool_ping_idle_seconds() == 5
    assert "pool_pre_ping" not in get_engine_pool_options("postgresql+asyncpg://db/x")


async def _pinged_engine(clock):
    engine = create_async_engine(
        PG_URL,
        connect_args=get_engine_connect_args(PG_URL),
        **{**get_engine_pool_options(PG_URL), "pool_size": 1, "max_overflow": 0},
    )
    install_idle_ping(engine, idle_seconds=30, clock=clock)
    pings: list[int] = []
    dialect = engine.sync_engine.dialect
    real_ping = dialect.do_ping

    def counted(dbapi_connection):
        pings.append(1)
        return real_ping(dbapi_connection)

    dialect.do_ping = counted
    return engine, async_sessionmaker(engine), pings, dialect


async def _backend_pid(factory) -> int:
    async with factory() as session:
        return (await session.execute(text("SELECT pg_backend_pid()"))).scalar_one()


@needs_postgresql
async def test_a_busy_connection_is_not_pinged():
    """The ping `pool_pre_ping` sent on every checkout was three round trips
    before a session's own work; a connection in steady use needs none."""
    engine, factory, pings, _ = await _pinged_engine(Clock())
    try:
        for _ in range(5):
            await _backend_pid(factory)
        assert pings == []
    finally:
        await engine.dispose()


@needs_postgresql
async def test_a_connection_quiet_for_the_threshold_is_pinged_once():
    clock = Clock()
    engine, factory, pings, _ = await _pinged_engine(clock)
    try:
        first = await _backend_pid(factory)
        clock.now += 31
        assert await _backend_pid(factory) == first
        assert pings == [1]
        await _backend_pid(factory)  # just returned again: no second ping
        assert pings == [1]
    finally:
        await engine.dispose()


@needs_postgresql
async def test_a_connection_the_server_ended_is_replaced_without_a_ping():
    """A terminated backend closes its socket, which the driver has seen by
    the next checkout: the caller gets a fresh connection, not the error."""
    engine, factory, pings, _ = await _pinged_engine(Clock())
    other = create_async_engine(PG_URL)
    try:
        victim = await _backend_pid(factory)
        async with other.connect() as connection:
            await connection.execute(text("SELECT pg_terminate_backend(:pid)"), {"pid": victim})
        await asyncio.sleep(0.2)  # the close reaches the idle connection's protocol
        assert await _backend_pid(factory) != victim
        assert pings == []
    finally:
        await other.dispose()
        await engine.dispose()


@needs_postgresql
async def test_a_quiet_connection_that_fails_its_ping_is_replaced():
    """What only a ping finds: a peer that vanished without closing anything.
    Simulated by a failing ping, since a half-open socket cannot be made on
    loopback."""
    clock = Clock()
    engine, factory, pings, dialect = await _pinged_engine(clock)
    try:
        first = await _backend_pid(factory)
        clock.now += 31

        def failing(_dbapi_connection):
            pings.append(1)
            raise OSError("peer vanished")

        dialect.do_ping = failing
        assert await _backend_pid(factory) != first
        assert pings == [1]
    finally:
        await engine.dispose()


@needs_postgresql
async def test_one_statement_reads_open_no_transaction(monkeypatch):
    """A lone SELECT is its own snapshot; BEGIN and ROLLBACK around it were two
    of its three round trips. Counted at the driver adapter, which starts a
    server transaction before any statement not run under AUTOCOMMIT."""
    from sqlalchemy.dialects.postgresql.asyncpg import AsyncAdapt_asyncpg_connection

    from app.auth.blocks import BlockService
    from app.db.models import User, generate_uuid
    from app.repositories.sqlalchemy import SqlAlchemyUserRepository
    from tests.dbfixtures import create_test_db

    factory, engine = await create_test_db()
    try:
        user_id = generate_uuid()
        async with factory() as session:
            async with session.begin():
                session.add(User(id=user_id, username="Reader", display_name="Reader"))
        started: list[int] = []
        real_start = AsyncAdapt_asyncpg_connection._start_transaction

        async def counted(self):
            if self.isolation_level != "autocommit":  # the adapter's own early return
                started.append(1)
            return await real_start(self)

        monkeypatch.setattr(AsyncAdapt_asyncpg_connection, "_start_transaction", counted)
        repo = SqlAlchemyUserRepository(factory)
        assert (await repo.get_by_id(str(user_id))).display_name == "Reader"
        assert (await repo.get_by_username("reader")) is not None
        assert await BlockService(factory).blockers_of(str(user_id)) == frozenset()
        assert started == []
        # And an ordinary session still gets its transaction.
        async with factory() as session:
            await session.execute(text("SELECT 1"))
        assert started == [1]
    finally:
        await engine.dispose()
