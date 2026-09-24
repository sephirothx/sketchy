"""A code spent twice, and a lock that parallel guesses never trip (#1019).

`verify_second_factor` read the row, decided, and wrote the decision back. On
PostgreSQL's READ COMMITTED two requests with the same code both read the old
`last_step` and were both accepted, and N parallel wrong codes each read
`failed_attempts = 0` and each wrote 1, so the five-failure lock never
tripped - leaving only the per-address limit, which an attacker holding a
stolen staff cookie sidesteps on `/step-up` with more addresses.

Run against PostgreSQL when `TEST_DATABASE_URL` is set, which is the database
the race is real on; otherwise against a SQLite *file*, since an in-memory
database hands every session one connection and would serialise exactly what
this overlaps.
"""
from __future__ import annotations

import asyncio
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID

import pytest_asyncio
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth.second_factor import (
    SECOND_FACTOR_LOCKOUT,
    SecondFactorOutcome,
    disable_second_factor,
    verify_second_factor,
)
from app.auth.totp import (
    MAX_SECOND_FACTOR_FAILURES,
    code_at,
    current_step,
    generate_secret,
)
from app.db import create_db_engine
from app.db.models import Base, UserSecondFactor
from app.repositories.sqlalchemy import SqlAlchemyUserRepository
from tests.dbfixtures import create_test_db


@pytest_asyncio.fixture
async def enrolled(tmp_path: Path):
    """A factory over a database two sessions can contend in, and an account
    with a confirmed factor: `(factory, user_id, secret)`."""
    if os.environ.get("TEST_DATABASE_URL"):
        factory, engine = await create_test_db()
    else:
        engine = create_db_engine(f"sqlite+aiosqlite:///{tmp_path / 'factor.db'}")
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all, checkfirst=False)
        factory = async_sessionmaker(engine, expire_on_commit=False)
    user = await SqlAlchemyUserRepository(factory).create_anonymous("Racing")
    secret = generate_secret()
    async with factory() as session:
        async with session.begin():
            session.add(
                UserSecondFactor(
                    user_id=UUID(user.id),
                    secret=secret,
                    confirmed_at=datetime.now(timezone.utc),
                )
            )
    try:
        yield factory, user.id, secret
    finally:
        await engine.dispose()


def read_together(monkeypatch, parties: int) -> None:
    """Hold every request just after it has read the factor, until all of
    them have: the widest window a read-then-write decision can have, made
    deterministic rather than left to the scheduler."""
    barrier = asyncio.Barrier(parties)
    original = AsyncSession.get

    async def get_then_wait(self, entity, *args, **kwargs):
        row = await original(self, entity, *args, **kwargs)
        if entity is UserSecondFactor:
            await barrier.wait()
        return row

    monkeypatch.setattr(AsyncSession, "get", get_then_wait)


async def test_one_code_sent_many_times_at_once_is_accepted_once(enrolled, monkeypatch):
    factory, user_id, secret = enrolled
    code = code_at(secret, current_step(time.time()))
    read_together(monkeypatch, 10)

    outcomes = await asyncio.wait_for(
        asyncio.gather(
            *(verify_second_factor(factory, user_id=user_id, code=code) for _ in range(10))
        ),
        timeout=10,
    )

    assert outcomes.count(SecondFactorOutcome.ACCEPTED) == 1, outcomes


async def test_parallel_wrong_codes_add_up_to_the_lock(enrolled, monkeypatch):
    factory, user_id, secret = enrolled
    right = code_at(secret, current_step(time.time()))
    wrong = "000000" if right != "000000" else "111111"
    read_together(monkeypatch, 12)

    outcomes = await asyncio.wait_for(
        asyncio.gather(
            *(verify_second_factor(factory, user_id=user_id, code=wrong) for _ in range(12))
        ),
        timeout=10,
    )

    # Each failure counted: the first four are refusals, and the fifth sets
    # the lock that every later one meets.
    assert outcomes.count(SecondFactorOutcome.REJECTED) == MAX_SECOND_FACTOR_FAILURES - 1, outcomes
    assert SecondFactorOutcome.LOCKED in outcomes
    monkeypatch.undo()
    # The misses past the fifth met the lock and counted nothing, so the
    # count starts from zero when it lifts.
    assert await stored(factory, user_id, "failed_attempts") == 0
    # And the right code is refused while it holds.
    assert (
        await verify_second_factor(factory, user_id=user_id, code=right)
        == SecondFactorOutcome.LOCKED
    )


async def stored(factory, user_id: str, column: str):
    async with factory() as session:
        row = await session.get(UserSecondFactor, UUID(user_id))
        return getattr(row, column)


def after_the_read(monkeypatch, action) -> None:
    """Run `action` once, between the factor being read and the decision
    being written - the moment a parallel request can change the row."""
    original = AsyncSession.get
    pending = [action]

    async def get_then_act(self, entity, *args, **kwargs):
        row = await original(self, entity, *args, **kwargs)
        if entity is UserSecondFactor and pending:
            await pending.pop()()
        return row

    monkeypatch.setattr(AsyncSession, "get", get_then_act)


async def test_a_right_code_meets_a_lock_set_since_it_was_read(enrolled, monkeypatch):
    factory, user_id, secret = enrolled
    code = code_at(secret, current_step(time.time()))

    async def lock():
        async with factory() as session:
            async with session.begin():
                await session.execute(
                    update(UserSecondFactor)
                    .where(UserSecondFactor.user_id == UUID(user_id))
                    .values(locked_until=datetime.now(timezone.utc) + timedelta(minutes=5))
                )

    after_the_read(monkeypatch, lock)
    outcome = await verify_second_factor(factory, user_id=user_id, code=code)
    assert outcome == SecondFactorOutcome.LOCKED


async def test_a_code_for_a_replaced_secret_is_not_credited(enrolled, monkeypatch):
    factory, user_id, secret = enrolled
    code = code_at(secret, current_step(time.time()))

    async def replace():
        async with factory() as session:
            async with session.begin():
                await session.execute(
                    update(UserSecondFactor)
                    .where(UserSecondFactor.user_id == UUID(user_id))
                    .values(secret=generate_secret())
                )

    after_the_read(monkeypatch, replace)
    outcome = await verify_second_factor(factory, user_id=user_id, code=code)
    assert outcome == SecondFactorOutcome.REJECTED
    assert await stored(factory, user_id, "last_step") == 0


async def test_a_factor_removed_since_it_was_read_is_not_reported_as_a_lock(
    enrolled, monkeypatch
):
    factory, user_id, _secret = enrolled

    async def remove():
        await disable_second_factor(factory, user_id=user_id)

    after_the_read(monkeypatch, remove)
    outcome = await verify_second_factor(factory, user_id=user_id, code="000000")
    assert outcome == SecondFactorOutcome.NOT_ENROLLED


async def test_the_lock_deadline_is_stored_in_utc_whatever_the_caller_passes(enrolled):
    """A deadline written through CASE skips the column type unless it is
    given one; SQLite then kept the caller's wall clock."""
    factory, user_id, _secret = enrolled
    elsewhere = datetime.now(timezone(timedelta(hours=-5)))
    for _ in range(MAX_SECOND_FACTOR_FAILURES):
        outcome = await verify_second_factor(
            factory, user_id=user_id, code="000000", now=elsewhere
        )
    assert outcome == SecondFactorOutcome.LOCKED
    locked_until = await stored(factory, user_id, "locked_until")
    assert locked_until - elsewhere == SECOND_FACTOR_LOCKOUT
