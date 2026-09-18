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
    # The database's volume is on another host; the working directory's is not it.
    assert data_directory("postgresql+asyncpg://u:p@h/db") is None


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


# --- cause, operation, pool wait (#892) ---------------------------------------


async def test_statements_and_transactions_carry_the_operation_around_them():
    from app.services.telemetry import database_operation, database_operation_of

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    store = Telemetry()
    instrument_engine(engine, store)

    @database_operation_of("gallery_page")
    async def page():
        async with engine.begin() as connection:
            await connection.execute(text("SELECT 1"))

    try:
        await page()
        with database_operation("not_a_known_operation"):
            async with engine.begin() as connection:
                await connection.execute(text("SELECT 2"))
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 3"))
        by_operation = {row["labels"][0]: row["count"] for row in store.db_duration.per_label()}
        assert by_operation == {"gallery_page": 1, "other": 2}
        transactions = {row["labels"][0]: row["count"] for row in store.db_transactions.per_label()}
        assert transactions["gallery_page"] == 1
        # Up to the web role's statement timeout, not 1 s.
        assert store.db_duration.buckets[-1] == 30.0
    finally:
        await engine.dispose()


def test_a_failure_is_labelled_by_its_sqlstate_class():
    from types import SimpleNamespace

    from app.db import classify_database_error

    def pg(code):
        return SimpleNamespace(pgcode=code)

    assert classify_database_error(pg("57014")) == "timeout"
    assert classify_database_error(pg("55P03")) == "lock_timeout"
    assert classify_database_error(pg("40P01")) == "deadlock"
    assert classify_database_error(pg("40001")) == "serialization"
    assert classify_database_error(pg("23505")) == "integrity"
    assert classify_database_error(pg("08006")) == "connection"
    assert classify_database_error(pg("42P01")) == "other"
    assert classify_database_error(ConnectionResetError()) == "connection"
    assert classify_database_error(None, is_disconnect=True) == "connection"
    # Wrapped the way SQLAlchemy wraps a driver error: the code is found inside.
    wrapped = RuntimeError("wrapper")
    wrapped.orig = pg("40P01")  # type: ignore[attr-defined]
    assert classify_database_error(wrapped) == "deadlock"


async def test_an_exhausted_pool_is_measured_as_wait_and_counted_as_a_timeout(tmp_path, monkeypatch):
    """The statement timer starts once a connection is held, so a request
    queueing for one looked fast, and one that gave up was counted nowhere."""
    from sqlalchemy.exc import TimeoutError as PoolTimeout

    from app.db import TimedQueuePool

    store = Telemetry()
    monkeypatch.setattr(TimedQueuePool, "store", store)
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'pool.db'}",
        poolclass=TimedQueuePool,
        pool_size=1,
        max_overflow=0,
        pool_timeout=0.3,
    )
    try:
        async with engine.connect() as held:
            await held.execute(text("SELECT 1"))
            with pytest.raises(PoolTimeout):
                async with engine.connect() as starved:
                    await starved.execute(text("SELECT 1"))
        assert store.db_pool_timeouts.total() == 1
        assert store.db_pool_wait.count() == 2
        waited = max(row["total"] for row in store.db_pool_wait.per_label())
        assert waited >= 0.3
        store.sources.pool = lambda: pool_gauges(engine)
        exposition = "\n".join(store.prometheus_lines())
        assert "sketchy_db_pool_timeouts_total 1" in exposition
        assert store.snapshot()["database"]["poolTimeoutsInWindow"] == 1
    finally:
        await engine.dispose()


@pytest.mark.skipif(
    not __import__("os").environ.get("TEST_DATABASE_URL"),
    reason="lock timeouts and deadlocks are PostgreSQL's",
)
async def test_a_lock_timeout_and_a_deadlock_each_count_under_their_own_cause():
    import asyncio
    import os

    from sqlalchemy.exc import DBAPIError

    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    store = Telemetry()
    instrument_engine(engine, store)
    try:
        async with engine.begin() as setup:
            await setup.execute(text("DROP TABLE IF EXISTS sketchy_lock_probe"))
            await setup.execute(text("CREATE TABLE sketchy_lock_probe (id int PRIMARY KEY)"))
            await setup.execute(text("INSERT INTO sketchy_lock_probe VALUES (1), (2)"))

        # Lock timeout: one side holds the row, the other gives up after 100 ms.
        async with engine.connect() as holder, engine.connect() as waiter:
            await holder.execute(text("SELECT * FROM sketchy_lock_probe WHERE id = 1 FOR UPDATE"))
            await waiter.execute(text("SET lock_timeout = '100ms'"))
            with pytest.raises(DBAPIError):
                await waiter.execute(text("UPDATE sketchy_lock_probe SET id = id WHERE id = 1"))
            await waiter.rollback()
            await holder.rollback()
        assert store.db_query_errors.get(("lock_timeout",)) == 1

        # Deadlock: each holds one row and asks for the other's.
        async with engine.connect() as left, engine.connect() as right:
            # deadlock_timeout (1 s by default) is superuser-only to change,
            # so detection takes that second.
            await left.execute(text("UPDATE sketchy_lock_probe SET id = id WHERE id = 1"))
            await right.execute(text("UPDATE sketchy_lock_probe SET id = id WHERE id = 2"))

            async def cross(connection, row):
                try:
                    await connection.execute(
                        text(f"UPDATE sketchy_lock_probe SET id = id WHERE id = {row}")
                    )
                    return None
                except DBAPIError as error:
                    return error

            results = await asyncio.gather(cross(left, 2), cross(right, 1))
            assert sum(result is not None for result in results) == 1
            await left.rollback()
            await right.rollback()
        assert store.db_query_errors.get(("deadlock",)) == 1
    finally:
        async with engine.begin() as cleanup:
            await cleanup.execute(text("DROP TABLE IF EXISTS sketchy_lock_probe"))
        await engine.dispose()


async def test_an_operator_engine_leaves_one_summary_line_when_disposed(caplog):
    """Nothing scrapes a process that lives a minute: the command's duration
    and work are one log line, counts only (#892)."""
    import logging

    from app.db import summarise_on_dispose

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    summarise_on_dispose(engine, role="maintenance", command="app.services.example")
    async with engine.begin() as connection:
        await connection.execute(text("CREATE TABLE t (i int)"))
        await connection.execute(text("INSERT INTO t VALUES (1), (2), (3)"))
        with pytest.raises(OperationalError):
            await connection.execute(text("SELECT * FROM missing"))
    with caplog.at_level(logging.INFO, logger="app.db.command"):
        await engine.dispose()
    [record] = [r for r in caplog.records if r.name == "app.db.command"]
    fields = record.fields
    assert fields["command"] == "app.services.example" and fields["role"] == "maintenance"
    assert fields["statements"] == 2 and fields["rows"] == 3 and fields["errors"] == 1
    assert fields["seconds"] >= 0
    assert "INSERT" not in record.getMessage()
