"""PostgreSQL connections carry the role's server-enforced budgets (#555)."""
from __future__ import annotations

import asyncio
import os

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db import (
    POSTGRES_ROLE_BUDGETS,
    create_db_engine,
    get_engine_connect_args,
    postgres_server_settings,
)
from app.db.models import User
from app.repositories.sqlalchemy import SqlAlchemyUserRepository

from tests.dbfixtures import create_test_db


PG_URL = os.environ.get("TEST_DATABASE_URL", "")
ON_POSTGRESQL = PG_URL.startswith("postgresql")


def test_each_role_has_its_own_budget_and_name(monkeypatch):
    for role, (statement, lock, idle) in POSTGRES_ROLE_BUDGETS.items():
        settings = postgres_server_settings(role)
        assert settings == {
            "application_name": f"sketchy-{role}",
            "statement_timeout": str(statement * 1000),
            "lock_timeout": str(lock * 1000),
            "idle_in_transaction_session_timeout": str(idle * 1000),
        }
    monkeypatch.setenv("DB_STATEMENT_TIMEOUT_SECONDS", "7")
    monkeypatch.setenv("DB_MIGRATION_LOCK_TIMEOUT_SECONDS", "2")
    assert postgres_server_settings("web")["statement_timeout"] == "7000"
    assert postgres_server_settings("migration")["lock_timeout"] == "2000"
    assert postgres_server_settings("maintenance")["lock_timeout"] == "5000"
    monkeypatch.setenv("DB_LOCK_TIMEOUT_SECONDS", "0")
    with pytest.raises(ValueError, match="at least 1"):
        postgres_server_settings("web")
    with pytest.raises(ValueError, match="unknown database role"):
        postgres_server_settings("reporting")


def test_sqlite_connections_are_untouched():
    assert get_engine_connect_args("sqlite+aiosqlite:///:memory:") == {
        "check_same_thread": False
    }
    assert get_engine_connect_args("sqlite+aiosqlite:///x.db", role="maintenance") == {
        "check_same_thread": False
    }
    assert "server_settings" in get_engine_connect_args("postgresql+asyncpg://db/x")


@pytest.mark.skipif(not ON_POSTGRESQL, reason="server settings are a PostgreSQL feature")
@pytest.mark.parametrize("role", sorted(POSTGRES_ROLE_BUDGETS))
async def test_the_server_shows_the_role_settings_on_every_connection(role):
    engine = create_db_engine(PG_URL, role=role)
    try:
        expected = postgres_server_settings(role)
        for _ in range(2):  # a second checkout, and after a dispose: a fresh connection
            async with engine.connect() as connection:
                shown_name = (
                    await connection.execute(text("SHOW application_name"))
                ).scalar_one()
                # SHOW renders 600000ms as "10min"; ask for seconds instead.
                shown = {
                    name: float(
                        (
                            await connection.execute(
                                text(
                                    f"SELECT EXTRACT(EPOCH FROM "
                                    f"current_setting('{name}')::interval)"
                                )
                            )
                        ).scalar_one()
                    )
                    for name in (
                        "statement_timeout",
                        "lock_timeout",
                        "idle_in_transaction_session_timeout",
                    )
                }
            assert shown_name == expected["application_name"]
            for name, seconds in shown.items():
                assert seconds == int(expected[name]) / 1000, name
            await engine.dispose()
    finally:
        await engine.dispose()


@pytest.mark.skipif(not ON_POSTGRESQL, reason="server-enforced budgets are a PostgreSQL feature")
async def test_a_blocked_statement_and_a_lock_wait_fail_at_their_budgets_and_the_pool_recovers(
    monkeypatch,
):
    # The lock budget is the shorter of the two, so a lock wait fails as a
    # lock timeout rather than being caught by the statement budget first.
    monkeypatch.setenv("DB_STATEMENT_TIMEOUT_SECONDS", "3")
    monkeypatch.setenv("DB_LOCK_TIMEOUT_SECONDS", "1")
    factory, fixture_engine = await create_test_db()
    engine = create_db_engine(PG_URL, role="web")
    budgeted = async_sessionmaker(engine, expire_on_commit=False)
    try:
        guest = await SqlAlchemyUserRepository(factory).create_anonymous("Locked")

        async with budgeted() as session:
            with pytest.raises(DBAPIError, match="canceling statement due to statement timeout"):
                await session.execute(text("SELECT pg_sleep(10)"))
        # The connection that timed out is still a connection: the pool
        # hands it, or a fresh one, straight back into service.
        async with budgeted() as session:
            assert (await session.execute(text("SELECT 1"))).scalar_one() == 1

        async with factory() as holder:
            async with holder.begin():
                await holder.execute(
                    select(User).where(User.display_name == "Locked").with_for_update()
                )
                async with budgeted() as waiter:
                    started = asyncio.get_event_loop().time()
                    with pytest.raises(DBAPIError, match="canceling statement due to lock timeout"):
                        await waiter.execute(
                            select(User).where(User.id == guest.id).with_for_update()
                        )
                    assert asyncio.get_event_loop().time() - started < 5
        async with budgeted() as session:
            assert (await session.execute(text("SELECT 1"))).scalar_one() == 1
    finally:
        await engine.dispose()
        await fixture_engine.dispose()


@pytest.mark.skipif(not ON_POSTGRESQL, reason="server-enforced budgets are a PostgreSQL feature")
async def test_an_abandoned_transaction_is_ended_by_the_server_and_the_pool_recovers(
    monkeypatch,
):
    monkeypatch.setenv("DB_IDLE_TRANSACTION_TIMEOUT_SECONDS", "1")
    engine = create_db_engine(PG_URL, role="web")
    budgeted = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with budgeted() as session:
            await session.execute(text("SELECT 1"))  # opens the transaction
            await asyncio.sleep(1.5)
            with pytest.raises(DBAPIError):
                await session.execute(text("SELECT 1"))
        # pool_pre_ping notices the terminated connection and replaces it.
        async with budgeted() as session:
            assert (await session.execute(text("SELECT 1"))).scalar_one() == 1
    finally:
        await engine.dispose()
