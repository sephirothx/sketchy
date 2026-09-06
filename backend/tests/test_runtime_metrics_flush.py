"""The metrics flush writes in bulk and accounts for every way it can lose a batch (#614)."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest
from sqlalchemy import event, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import RuntimeEvent, RuntimeStatsDaily
from app.domain_values import RuntimeEventType
from app.repositories.sqlalchemy import SqlAlchemyUserRepository
from app.services.runtime_metrics import (
    INSERT_CHUNK_ROWS,
    RuntimeMetrics,
    flush_events,
)

from tests.dbfixtures import create_test_db

pytestmark = pytest.mark.asyncio

EVENT_TYPES = [RuntimeEventType.ROOM_CREATED, RuntimeEventType.GAME_FINISHED]


def _capture(engine) -> list[str]:
    statements: list[str] = []

    def before(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", before)
    return statements


def _record(recorder: RuntimeMetrics, count: int, *, days: int = 3) -> None:
    base = datetime(2026, 8, 1, 12, tzinfo=timezone.utc)
    for index in range(count):
        recorder.record(
            EVENT_TYPES[index % len(EVENT_TYPES)],
            value=index % 17,
            now=base + timedelta(days=index % days, minutes=index),
        )


async def _totals(factory) -> tuple[int, dict[tuple[str, str], tuple[int, int, int | None]]]:
    async with factory() as session:
        raw = await session.scalar(select(func.count(RuntimeEvent.id)))
        rows = (await session.scalars(select(RuntimeStatsDaily))).all()
    return raw, {
        (row.stat_date.isoformat(), row.metric): (row.occurrences, row.value_sum, row.value_max)
        for row in rows
    }


def _expected(count: int, *, days: int = 3) -> dict[tuple[str, str], tuple[int, int, int | None]]:
    base = datetime(2026, 8, 1, 12, tzinfo=timezone.utc)
    expected: dict[tuple[str, str], list[int]] = {}
    for index in range(count):
        day = (base + timedelta(days=index % days, minutes=index)).date().isoformat()
        expected.setdefault((day, EVENT_TYPES[index % len(EVENT_TYPES)].value), []).append(index % 17)
    return {key: (len(values), sum(values), max(values)) for key, values in expected.items()}


@pytest.mark.parametrize("count", [1, 100, 5000])
async def test_a_flush_is_bounded_inserts_and_one_upsert_per_group_chunk(count):
    factory, engine = await create_test_db()
    try:
        recorder = RuntimeMetrics(max_buffered=10_000)
        _record(recorder, count)
        statements = _capture(engine)

        assert await flush_events(factory, recorder=recorder) == count

        inserts = [s for s in statements if s.lstrip().startswith("INSERT INTO runtime_events")]
        upserts = [s for s in statements if s.lstrip().startswith("INSERT INTO runtime_stats_daily")]
        selects = [s for s in statements if "runtime_stats_daily" in s and s.lstrip().startswith("SELECT")]
        assert len(inserts) == -(-count // INSERT_CHUNK_ROWS), "one executemany per chunk"
        assert not any("RETURNING" in s for s in inserts), "no ids come back"
        assert len(upserts) == 1 and "ON CONFLICT" in upserts[0]
        assert not selects, "no read per day and metric"
        raw, daily = await _totals(factory)
        assert raw == count and daily == _expected(count)
        assert recorder.buffered == 0
    finally:
        await engine.dispose()


async def test_a_second_flush_adds_to_the_same_days():
    factory, engine = await create_test_db()
    try:
        recorder = RuntimeMetrics()
        _record(recorder, 40)
        await flush_events(factory, recorder=recorder)
        _record(recorder, 40)
        await flush_events(factory, recorder=recorder)
        raw, daily = await _totals(factory)
        once = _expected(40)
        assert raw == 80
        assert daily == {key: (n * 2, total * 2, biggest) for key, (n, total, biggest) in once.items()}
    finally:
        await engine.dispose()


async def test_a_failed_transaction_keeps_the_batch_and_counts_the_failure(monkeypatch):
    factory, engine = await create_test_db()
    try:
        recorder = RuntimeMetrics()
        _record(recorder, 30)
        calls = {"n": 0}
        real = AsyncSession.execute

        async def flaky(self, *args, **kwargs):
            calls["n"] += 1
            if calls["n"] == 2:
                raise RuntimeError("the insert broke")
            return await real(self, *args, **kwargs)

        monkeypatch.setattr(AsyncSession, "execute", flaky)
        with pytest.raises(RuntimeError):
            await flush_events(factory, recorder=recorder)
        monkeypatch.setattr(AsyncSession, "execute", real)

        assert recorder.buffered == 30 and recorder.failed_flushes == 1
        assert recorder.dropped_events == 0
        assert (await _totals(factory)) == (0, {})

        assert await flush_events(factory, recorder=recorder) == 30
        raw, daily = await _totals(factory)
        assert raw == 30 and daily == _expected(30)
        assert recorder.buffered == 0
    finally:
        await engine.dispose()


async def test_a_cancelled_flush_keeps_the_batch_and_says_it_was_interrupted(monkeypatch):
    factory, engine = await create_test_db()
    try:
        recorder = RuntimeMetrics()
        _record(recorder, 10)
        real = AsyncSession.execute

        async def cancelled(self, *args, **kwargs):
            raise asyncio.CancelledError

        monkeypatch.setattr(AsyncSession, "execute", cancelled)
        with pytest.raises(asyncio.CancelledError):
            await flush_events(factory, recorder=recorder)
        monkeypatch.setattr(AsyncSession, "execute", real)
        assert recorder.buffered == 10 and recorder.interrupted_flushes == 1
        assert recorder.failed_flushes == 0
        assert await flush_events(factory, recorder=recorder) == 10
    finally:
        await engine.dispose()


async def test_a_cancel_during_commit_is_an_unknown_outcome_too(monkeypatch):
    """The server may have committed before the cancel reached the client;
    keeping the batch would insert it again. It is let go and counted as
    ambiguous, and the cancellation still propagates."""
    factory, engine = await create_test_db()
    try:
        recorder = RuntimeMetrics()
        _record(recorder, 7)
        real = AsyncSession.commit

        async def cancelled_mid_commit(self):
            await real(self)
            raise asyncio.CancelledError

        monkeypatch.setattr(AsyncSession, "commit", cancelled_mid_commit)
        with pytest.raises(asyncio.CancelledError):
            await flush_events(factory, recorder=recorder)
        monkeypatch.setattr(AsyncSession, "commit", real)

        assert recorder.buffered == 0
        assert recorder.ambiguous_batches == 1 and recorder.events_lost_to_ambiguity == 7
        assert recorder.interrupted_flushes == 1 and recorder.failed_flushes == 0
        assert await flush_events(factory, recorder=recorder) == 0
        async with factory() as session:
            assert await session.scalar(select(func.count()).select_from(RuntimeEvent)) == 7
    finally:
        await engine.dispose()


async def test_a_commit_of_unknown_outcome_lets_the_batch_go_and_says_how_many(monkeypatch):
    """Retrying a batch the server may have written would count it twice; a
    batch has no identity of its own, so the honest answer is to count it
    as lost to ambiguity rather than to guess."""
    factory, engine = await create_test_db()
    try:
        recorder = RuntimeMetrics()
        _record(recorder, 12)
        real = AsyncSession.commit

        async def vanished(self):
            raise ConnectionResetError("the server went away during COMMIT")

        monkeypatch.setattr(AsyncSession, "commit", vanished)
        with pytest.raises(Exception):  # noqa: B017 - the wrapped driver error
            await flush_events(factory, recorder=recorder)
        monkeypatch.setattr(AsyncSession, "commit", real)

        assert recorder.buffered == 0
        assert recorder.ambiguous_batches == 1 and recorder.events_lost_to_ambiguity == 12
        assert recorder.failed_flushes == 0
    finally:
        await engine.dispose()


async def test_an_event_naming_a_purged_or_erased_account_does_not_poison_the_batch():
    from app.auth.account_data import anonymize_account
    from app.db.models import generate_uuid

    factory, engine = await create_test_db()
    try:
        users = SqlAlchemyUserRepository(factory)
        live = await users.create_anonymous("Live")
        erased = await users.create_anonymous("Erased")
        await anonymize_account(factory, user_id=erased.id)
        never = generate_uuid()
        recorder = RuntimeMetrics()
        now = datetime(2026, 8, 3, 12, tzinfo=timezone.utc)
        recorder.record(RuntimeEventType.ROOM_CREATED, user_id=UUID(live.id), now=now)
        recorder.record(RuntimeEventType.ROOM_CREATED, user_id=UUID(erased.id), now=now)
        recorder.record(RuntimeEventType.ROOM_CREATED, user_id=never, now=now)

        assert await flush_events(factory, recorder=recorder) == 3

        async with factory() as session:
            rows = (await session.scalars(select(RuntimeEvent).order_by(RuntimeEvent.id))).all()
        assert [row.user_id for row in rows] == [UUID(live.id), None, None]
        raw, daily = await _totals(factory)
        assert raw == 3 and daily[("2026-08-03", "room.created")][0] == 3
    finally:
        await engine.dispose()


async def test_a_flush_takes_at_most_its_batch_and_the_overflow_is_still_counted():
    factory, engine = await create_test_db()
    try:
        recorder = RuntimeMetrics(max_buffered=50)
        _record(recorder, 60)
        assert recorder.dropped_events == 10 and recorder.buffered == 50
        assert await flush_events(factory, recorder=recorder, batch_size=20) == 20
        assert recorder.buffered == 30
        assert await flush_events(factory, recorder=recorder, batch_size=100) == 30
        raw, _ = await _totals(factory)
        assert raw == 50
    finally:
        await engine.dispose()
