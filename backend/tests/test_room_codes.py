"""Room invite codes are globally reserved and stale links fail safely."""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.models import Base, RoomCodeReservation
from app.services.room_codes import RoomCodeAllocationError, RoomCodeService


pytestmark = pytest.mark.asyncio


async def _database():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


async def test_database_primary_key_retries_a_cross_request_collision():
    engine, factory = await _database()
    candidates = iter(("ABC123", "ABC123", "DEF456"))
    service = RoomCodeService(factory, code_factory=lambda: next(candidates))
    try:
        assert await service.allocate() == "ABC123"
        assert await service.allocate() == "DEF456"
        async with factory() as session:
            rows = (
                await session.scalars(
                    select(RoomCodeReservation).order_by(RoomCodeReservation.code)
                )
            ).all()
        assert [(row.code, row.kind) for row in rows] == [
            ("ABC123", "ephemeral"),
            ("DEF456", "ephemeral"),
        ]
    finally:
        await engine.dispose()


async def test_ephemeral_codes_retire_for_thirty_days_then_become_reusable():
    engine, factory = await _database()
    service = RoomCodeService(factory, code_factory=lambda: "ABC123")
    try:
        assert await service.allocate() == "ABC123"
        await service.retire_ephemeral("abc123")
        assert await service.is_retired("ABC123") is True

        async with factory() as session:
            reservation = await session.get(RoomCodeReservation, "ABC123")
            assert reservation is not None
            remaining = reservation.retired_until - datetime.now(timezone.utc)
            assert timedelta(days=29, hours=23) < remaining <= timedelta(days=30)

        async with factory() as session:
            async with session.begin():
                await session.execute(
                    update(RoomCodeReservation)
                    .where(RoomCodeReservation.code == "ABC123")
                    .values(
                        retired_until=datetime.now(timezone.utc)
                        - timedelta(seconds=1)
                    )
                )

        assert await service.is_retired("ABC123") is False
        assert await service.allocate() == "ABC123"
    finally:
        await engine.dispose()


async def test_startup_retires_only_orphaned_ephemeral_codes():
    """A persistent reservation predates #489 and is a permanent tombstone."""
    engine, factory = await _database()
    candidates = iter(("LIVE01",))
    service = RoomCodeService(factory, code_factory=lambda: next(candidates))
    try:
        assert await service.allocate() == "LIVE01"
        async with factory() as session:
            async with session.begin():
                session.add(RoomCodeReservation(code="KEEP01", kind="persistent"))
        assert await service.retire_orphaned_ephemeral() == 1
        assert await service.is_retired("LIVE01") is True

        # Never expires, never becomes allocatable, and an invite carrying it
        # is told the room has ended rather than that it was never found.
        await service.retire_ephemeral("KEEP01")
        async with factory() as session:
            persistent = await session.get(RoomCodeReservation, "KEEP01")
        assert persistent is not None
        assert persistent.kind == "persistent"
        assert persistent.retired_until is None
        assert await service.is_retired("KEEP01") is True
        assert await service.purge_expired() == 0
    finally:
        await engine.dispose()


async def test_unpublished_code_can_be_released_without_retirement():
    engine, factory = await _database()
    service = RoomCodeService(factory, code_factory=lambda: "UNUSED")
    try:
        assert await service.allocate() == "UNUSED"
        await service.release_unpublished("UNUSED")
        assert await service.allocate() == "UNUSED"
    finally:
        await engine.dispose()


# --- allocation's own failure paths -----------------------------------------
#
# A collision here is two rooms sharing an identity, so the guards around
# allocation matter more than the happy path they protect. None of them had a
# test: the code factory is trusted in production, every allocation in the
# suite succeeded on its first or second attempt, and no test ever asked about
# a code nobody reserved.


@pytest.mark.parametrize(
    "bad_code",
    [
        "SHORT",        # too few characters
        "TOOLONG7",     # too many
        "ABC-12",       # outside the alphabet
        "ABC 12",
        "",
    ],
)
async def test_a_code_factory_returning_an_invalid_code_is_refused(bad_code):
    """The alphabet and length are a contract, and a silent breach of it would
    put an unshareable code on a room."""
    engine, factory = await _database()
    # The service strips and upper-cases first, so a lowercase code is fine and
    # is not in this list; only genuinely invalid shapes reach the raise.
    service = RoomCodeService(factory, code_factory=lambda: bad_code)
    try:
        with pytest.raises(ValueError, match="invalid code"):
            await service.allocate()
        async with factory() as session:
            assert (await session.scalars(select(RoomCodeReservation))).all() == []
    finally:
        await engine.dispose()


async def test_allocation_gives_up_rather_than_looping_for_ever():
    """Every attempt colliding is a real state - a full or wedged table - and
    the caller needs an error rather than a hang."""
    engine, factory = await _database()
    service = RoomCodeService(factory, code_factory=lambda: "ABC123")
    try:
        assert await service.allocate() == "ABC123"
        with pytest.raises(RoomCodeAllocationError):
            await service.allocate()
    finally:
        await engine.dispose()


async def test_the_expired_purge_runs_once_per_allocation_not_once_per_collision():
    """The purge is the expensive half. Running it on every collision would
    turn a busy table into a scan storm."""
    engine, factory = await _database()
    service = RoomCodeService(factory, code_factory=lambda: "ABC123")
    purges = 0
    original = service.purge_expired

    async def counting_purge():
        nonlocal purges
        purges += 1
        return await original()

    service.purge_expired = counting_purge
    try:
        await service.allocate()
        with pytest.raises(RoomCodeAllocationError):
            await service.allocate()
        assert purges == 1, f"purged {purges} times across 64 collisions"
    finally:
        await engine.dispose()


async def test_a_code_nobody_reserved_is_not_reported_as_retired():
    """"Never existed" and "has ended" are different answers to an invite, and
    only one of them is true for a typo."""
    engine, factory = await _database()
    service = RoomCodeService(factory)
    try:
        assert await service.is_retired("ZZZZZZ") is False
    finally:
        await engine.dispose()
