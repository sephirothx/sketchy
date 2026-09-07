"""Every statement timed, and the pool asked what it will say about itself."""
from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import AsyncAdaptedQueuePool

from app.db import data_directory, instrument_engine, pool_gauges
from app.services.telemetry import Telemetry

from tests.dbfixtures import create_test_db


pytestmark = pytest.mark.asyncio


async def test_statements_are_timed_and_failures_counted_apart():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    store = Telemetry()
    instrument_engine(engine, store)
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
        assert store.db_queries.total() == 1
        assert store.db_query_errors.total() == 0
        assert store.db_duration.count() == 1

        with pytest.raises(OperationalError):
            async with engine.connect() as connection:
                await connection.execute(text("SELECT * FROM no_such_table"))
        assert store.db_queries.total() == 2
        assert store.db_query_errors.total() == 1
        # The failed statement is timed once, not once as a failure and
        # once as a success.
        assert store.db_duration.count() == 2
    finally:
        await engine.dispose()


async def test_a_pool_that_keeps_no_count_answers_none():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        assert pool_gauges(engine) is None
    finally:
        await engine.dispose()


def test_a_queue_pool_reports_its_capacity():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=AsyncAdaptedQueuePool,
        pool_size=2,
        max_overflow=1,
    )
    gauges = pool_gauges(engine)
    assert gauges is not None
    assert gauges.size == 2
    assert gauges.capacity == 3
    assert gauges.checked_out == 0
    assert pool_gauges(engine, max_overflow=5).capacity == 7


def test_the_data_directory_is_the_sqlite_file_folder_or_here(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert data_directory("sqlite+aiosqlite:///./sketchy.db") == str(tmp_path.resolve())
    assert data_directory("sqlite+aiosqlite:///:memory:") == str(tmp_path)
    assert data_directory("postgresql+asyncpg://u:p@h/db") == str(tmp_path)


async def test_the_queue_depths_are_answered_from_cache_inside_the_ttl():
    """A scraper and an open page together cost the database one pair of counts."""

    from app.services.queue_depths import QueueDepths, _age
    from datetime import datetime, timedelta, timezone

    factory, engine = await create_test_db()
    store = Telemetry()
    instrument_engine(engine, store)
    now = [100.0]
    depths = QueueDepths(factory, cache_seconds=10.0, clock=lambda: now[0])
    try:
        first = await depths.read()
        queries_after_first = store.db_queries.total()
        assert first.mail_outbox.pending == 0
        assert await depths.read() is first
        assert store.db_queries.total() == queries_after_first
        now[0] += 10.0
        assert await depths.read() is not first
        assert store.db_queries.total() > queries_after_first
    finally:
        await engine.dispose()

    # A naive timestamp from SQLite is read as UTC rather than refused.
    then = datetime.now(timezone.utc) - timedelta(seconds=30)
    assert _age(then.replace(tzinfo=None), datetime.now(timezone.utc)) >= 30
    assert _age(None, datetime.now(timezone.utc)) is None


async def test_concurrent_queue_reads_share_one_query():
    import asyncio


    from app.services.queue_depths import QueueDepths

    factory, engine = await create_test_db()
    store = Telemetry()
    instrument_engine(engine, store)
    depths = QueueDepths(factory, cache_seconds=10.0)
    try:
        results = await asyncio.gather(*(depths.read() for _ in range(5)))
        assert all(result is results[0] for result in results)
        assert store.db_queries.total() == 3  # one statement per durable queue
    finally:
        await engine.dispose()


def test_listeners_ignore_a_context_that_was_never_timed():
    """A statement whose start was not seen must not be charged a nonsense span."""
    from types import SimpleNamespace

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    store = Telemetry()
    listeners = instrument_engine(engine, store)
    context = SimpleNamespace()
    listeners.after(None, None, "SELECT 1", None, context, False)
    listeners.failed(SimpleNamespace(execution_context=context))
    assert store.db_queries.total() == 0
    # And a failure is charged once: the start is cleared as it is counted.
    listeners.before(None, None, "SELECT 1", None, context, False)
    listeners.failed(SimpleNamespace(execution_context=context))
    listeners.failed(SimpleNamespace(execution_context=context))
    listeners.after(None, None, "SELECT 1", None, context, False)
    assert store.db_queries.total() == 1
    assert store.db_query_errors.total() == 1


async def test_the_finished_game_queue_counts_live_rows_and_failed_ones_apart():
    """Pending and processing rows are the backlog and set its age; a failed
    row is counted on its own and never makes the backlog look old (#541)."""
    from datetime import datetime, timedelta, timezone

    from app.db.models import FinishedGameEnvelope, generate_uuid
    from app.services.queue_depths import QueueDepths

    factory, engine = await create_test_db()
    now = datetime.now(timezone.utc)

    def row(*, state: str, age_seconds: float, **extra) -> FinishedGameEnvelope:
        return FinishedGameEnvelope(
            game_id=generate_uuid(),
            envelope_version=1,
            payload=None if state == "failed" else b"x",
            byte_size=1,
            checksum_sha256="0" * 64,
            state=state,
            next_attempt_at=now,
            created_at=now - timedelta(seconds=age_seconds),
            **extra,
        )

    try:
        async with factory() as session:
            async with session.begin():
                session.add_all(
                    [
                        row(state="pending", age_seconds=20),
                        row(
                            state="processing",
                            age_seconds=90,
                            claimed_at=now,
                            claim_token=generate_uuid(),
                        ),
                        row(
                            state="failed",
                            age_seconds=7 * 86400,
                            failure_code="conflict",
                            failed_at=now,
                        ),
                    ]
                )
        snapshot = await QueueDepths(factory, cache_seconds=0.0).read()
    finally:
        await engine.dispose()

    assert snapshot.finished_games.pending == 2
    assert snapshot.finished_games.failed == 1
    assert 89 <= snapshot.finished_games.oldest_seconds <= 120
    assert snapshot.finished_games.as_json()["failed"] == 1
