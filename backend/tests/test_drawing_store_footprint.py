"""The one series that says whether inline drawing storage is still fine (#471).

#471 chose to keep drawing bytes in the primary database on measured sizes,
and named a size at which that choice is reopened. A trigger nobody can
observe is not a trigger, so the store's size is a gauge - which means it has
to be right, cheap, and absent rather than wrong where it cannot be taken.
"""
from __future__ import annotations

import asyncio
import os

import pytest
from sqlalchemy import text

from app.db import instrument_engine
from app.services.drawing_storage import DrawingStoreFootprint, DrawingStoreSize
from app.services.telemetry import Telemetry

from tests.dbfixtures import create_test_db

pytestmark = pytest.mark.asyncio

ON_POSTGRESQL = os.environ.get("TEST_DATABASE_URL", "").startswith("postgresql")


async def test_a_reading_is_absent_rather_than_guessed_at_off_postgresql():
    """SQLite has no relation-size catalogue, and is not a deployment target."""
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        assert await DrawingStoreFootprint(factory, cache_seconds=0.0).read() is None
    finally:
        await engine.dispose()


async def test_the_scrape_omits_the_series_when_there_is_no_reading():
    """An absent reading emits no lines at all, rather than a zero that would
    read as an empty store and silence the trigger."""
    from app.api.operations import _drawing_store_lines

    assert _drawing_store_lines(None) == []
    lines = _drawing_store_lines(DrawingStoreSize(4096, 3))
    assert "sketchy_drawing_store_bytes 4096" in lines
    assert "sketchy_drawing_store_rows 3" in lines


async def test_a_failing_reading_does_not_fail_the_scrape():
    """The gauge costs a query; every other series in the scrape is process
    memory, and an outage is exactly when they are being asked for."""
    from app.api.operations import _drawing_store_for_scrape

    class Broken:
        async def read(self):
            raise RuntimeError("database is down")

    assert await _drawing_store_for_scrape(Broken()) is None


@pytest.mark.skipif(not ON_POSTGRESQL, reason="relation sizes are a PostgreSQL catalogue")
async def test_the_reading_counts_toast_not_just_the_heap():
    """The payloads live out of line, so the heap alone understates the store
    by about forty times - which would keep the gauge under any threshold for
    ever. This is the assertion that pins `pg_total_relation_size`."""
    factory, engine = await create_test_db()
    try:
        async with factory() as session:
            await session.execute(text("DELETE FROM turn_drawings"))
            await session.commit()
        empty = await DrawingStoreFootprint(factory, cache_seconds=0.0).read()
        assert empty is not None and empty.ready_rows == 0

        async with factory() as session:
            heap = await session.scalar(text("SELECT pg_relation_size('turn_drawings')"))
            total = await session.scalar(
                text("SELECT pg_total_relation_size('turn_drawings')")
            )
        # Whatever the row population, the reported number is the one a backup
        # moves: the relation with its TOAST and its indexes, never the heap.
        assert empty.total_bytes == total
        assert total >= heap
    finally:
        await engine.dispose()


@pytest.mark.skipif(not ON_POSTGRESQL, reason="relation sizes are a PostgreSQL catalogue")
async def test_readings_are_cached_so_a_page_and_a_scraper_share_one_lookup():
    factory, engine = await create_test_db()
    store = Telemetry()
    instrument_engine(engine, store)
    now = [100.0]
    footprint = DrawingStoreFootprint(factory, cache_seconds=300.0, clock=lambda: now[0])
    try:
        first = await footprint.read()
        after_first = store.db_queries.total()
        assert await footprint.read() is first
        assert store.db_queries.total() == after_first
        now[0] += 300.0
        assert await footprint.read() is not first
        assert store.db_queries.total() > after_first
    finally:
        await engine.dispose()


@pytest.mark.skipif(not ON_POSTGRESQL, reason="relation sizes are a PostgreSQL catalogue")
async def test_concurrent_reads_share_one_lookup():
    factory, engine = await create_test_db()
    store = Telemetry()
    instrument_engine(engine, store)
    footprint = DrawingStoreFootprint(factory, cache_seconds=300.0)
    try:
        results = await asyncio.gather(*(footprint.read() for _ in range(5)))
        assert all(result is results[0] for result in results)
        assert store.db_queries.total() == 2  # the size, and the row count
    finally:
        await engine.dispose()
