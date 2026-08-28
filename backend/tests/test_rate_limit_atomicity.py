"""A ceiling that concurrency can walk past is not a ceiling.

`check` read the bucket, decided, and wrote it back, guarded by
`SELECT … FOR UPDATE`. PostgreSQL honours that row lock; **SQLite ignores it**,
and SQLite is the documented default. Two attempts in flight together could
therefore both read the same count and both be admitted, so every limit built
on this - login, registration, room creation, guest provisioning - was soft by
roughly the number of requests in flight rather than hard at its number.
"""
from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.auth.rate_limit import PersistentRateLimiter, bucket_is_full
from app.db.models import AppConfig, AuthRateLimitBucket, Base


@pytest_asyncio.fixture
async def factory(tmp_path: Path):
    """A database two sessions can genuinely contend over.

    With `TEST_DATABASE_URL` set this is PostgreSQL, which is the half of the
    behaviour that already worked; without it, a SQLite **file** rather than
    `:memory:`, because an in-memory database hands every session the same
    connection and would serialise exactly what this is trying to overlap.
    """
    external = os.environ.get("TEST_DATABASE_URL")
    engine = create_async_engine(
        external or f"sqlite+aiosqlite:///{tmp_path / 'limits.db'}"
    )
    async with engine.begin() as connection:
        if external:
            for table in (AuthRateLimitBucket.__table__, AppConfig.__table__):
                await connection.execute(table.delete())
        else:
            await connection.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


@pytest.mark.asyncio
async def test_simultaneous_attempts_cannot_walk_past_the_ceiling(factory):
    limiter = PersistentRateLimiter(
        factory, scope="concurrent", limit=5, window_seconds=3600
    )

    verdicts = await asyncio.gather(*(limiter.check("one-caller") for _ in range(25)))

    assert verdicts.count(True) == 5, (
        f"admitted {verdicts.count(True)} of 25 against a limit of 5"
    )
    async with factory() as session:
        bucket = await session.scalar(
            select(AuthRateLimitBucket).where(
                AuthRateLimitBucket.scope == "concurrent"
            )
        )
    assert bucket is not None and bucket.attempt_count == 5


@pytest.mark.asyncio
async def test_simultaneous_first_attempts_make_one_bucket(factory):
    """The window has to start exactly once, however many arrive together."""
    limiter = PersistentRateLimiter(
        factory, scope="first", limit=3, window_seconds=3600
    )

    verdicts = await asyncio.gather(*(limiter.check("one-caller") for _ in range(10)))

    assert verdicts.count(True) == 3
    async with factory() as session:
        buckets = (
            await session.scalars(
                select(AuthRateLimitBucket).where(AuthRateLimitBucket.scope == "first")
            )
        ).all()
    assert len(buckets) == 1


@pytest.mark.asyncio
async def test_refunds_cannot_hand_back_more_than_was_taken(factory):
    limiter = PersistentRateLimiter(
        factory, scope="refunds", limit=5, window_seconds=3600
    )
    for _ in range(3):
        assert await limiter.check("one-caller") is True

    await asyncio.gather(*(limiter.refund("one-caller") for _ in range(10)))

    async with factory() as session:
        bucket = await session.scalar(
            select(AuthRateLimitBucket).where(AuthRateLimitBucket.scope == "refunds")
        )
    assert bucket is not None
    assert bucket.attempt_count == 0, "a refund went below what was spent"


@pytest.mark.parametrize(
    "attempts, expires_in, expected",
    [
        (5, 60, True),    # live and at its limit: refusing
        (4, 60, False),   # live with room: somebody's refund landed
        (5, -1, False),   # expired: somebody's roll is due, not a refusal
        (0, 60, False),   # live and empty: refunded to nothing
    ],
)
def test_only_a_live_bucket_at_its_limit_is_a_refusal(attempts, expires_in, expected):
    """A spend that misses and a roll that misses do not together prove the
    bucket is full: another caller's roll or refund can land between the two
    statements, leaving a row with room that matched neither. Presence is not
    a refusal, which is what made the loser of that race a false 429."""
    now = datetime(2026, 8, 28, tzinfo=timezone.utc)

    assert (
        bucket_is_full(attempts, now + timedelta(seconds=expires_in), 5, now)
        is expected
    )


@pytest.mark.asyncio
async def test_a_slot_freed_by_a_refund_is_given_to_the_next_caller(factory):
    """The end state the race is about: capacity exists, so the next attempt
    is admitted rather than refused for the row merely being there."""
    limiter = PersistentRateLimiter(
        factory, scope="freed", limit=1, window_seconds=3600
    )
    assert await limiter.check("one-caller") is True
    assert await limiter.check("one-caller") is False

    await limiter.refund("one-caller")

    assert await limiter.check("one-caller") is True
