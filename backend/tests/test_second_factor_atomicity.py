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
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth.second_factor import (
    SecondFactorOutcome,
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

    outcomes = await asyncio.gather(
        *(verify_second_factor(factory, user_id=user_id, code=code) for _ in range(10))
    )

    assert outcomes.count(SecondFactorOutcome.ACCEPTED) == 1, outcomes


async def test_parallel_wrong_codes_add_up_to_the_lock(enrolled, monkeypatch):
    factory, user_id, secret = enrolled
    right = code_at(secret, current_step(time.time()))
    wrong = "000000" if right != "000000" else "111111"
    read_together(monkeypatch, 12)

    outcomes = await asyncio.gather(
        *(verify_second_factor(factory, user_id=user_id, code=wrong) for _ in range(12))
    )

    # Each failure counted: the first four are refusals, and the fifth sets
    # the lock that every later one meets.
    assert outcomes.count(SecondFactorOutcome.REJECTED) == MAX_SECOND_FACTOR_FAILURES - 1, outcomes
    assert SecondFactorOutcome.LOCKED in outcomes
    # And the right code is refused while it holds.
    monkeypatch.undo()
    assert (
        await verify_second_factor(factory, user_id=user_id, code=right)
        == SecondFactorOutcome.LOCKED
    )
