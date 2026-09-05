"""What the server records about its own behaviour.

`RoomManager` has had the natural instrumentation points since it was written -
`create_room`, `add_player`, `remove_player`, `remove_room_if_empty` - and
counted nothing at any of them. Peak concurrency, room lifetime, disconnect and
reconnect rate, timer overruns and observed payload sizes were all unknowable,
which made the release load target unmeasurable and every performance question
a guess.

Two things are recorded, for two different questions.

Gauges live in memory. One worker owns every room, game and socket (#382), so
an in-process count is the true count and no cross-worker aggregation exists to
get wrong. They are exact and they vanish on restart, which is correct: a live
count of rooms is not a historical fact.

Events are buffered and written in batches. A row per join and disconnect
written inline would put a database round trip in the socket path, where a slow
write would be felt as lag in a drawing. The buffer is bounded and drops oldest
rather than growing without limit, because losing observations is much better
than losing the server that makes them - and the number dropped is itself
recorded, so the gap is visible rather than silent.
"""
from __future__ import annotations

from collections import Counter, deque
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta, timezone
from uuid import UUID
import argparse
import asyncio
import contextlib
import logging
import os

from sqlalchemy import delete, func, insert, select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.logging_config import configure_logging
from app.db.models import RuntimeEvent, RuntimeStatsDaily
from app.domain_values import RuntimeEventType
from app.auth.erasure import erased_identity_ids
from app.services.readiness import LoopHealth
from app.services.sweeps import (
    SweepBudget,
    SweepReport,
    delete_in_batches,
    sweep_budget_from_env,
)


logger = logging.getLogger(__name__)

MAX_BUFFERED_EVENTS = 5_000
DEFAULT_FLUSH_SECONDS = 15.0
DEFAULT_RETENTION_DAYS = 30


def retention_days(environ: dict[str, str] | None = None) -> int:
    values = os.environ if environ is None else environ
    raw = values.get("RUNTIME_EVENT_RETENTION_DAYS", "").strip()
    if not raw:
        return DEFAULT_RETENTION_DAYS
    try:
        days = int(raw)
    except ValueError:
        return DEFAULT_RETENTION_DAYS
    return days if days > 0 else DEFAULT_RETENTION_DAYS


def flush_seconds(environ: dict[str, str] | None = None) -> float:
    values = os.environ if environ is None else environ
    raw = values.get("RUNTIME_METRICS_FLUSH_SECONDS", "").strip()
    if not raw:
        return DEFAULT_FLUSH_SECONDS
    try:
        seconds = float(raw)
    except ValueError:
        return DEFAULT_FLUSH_SECONDS
    return seconds if seconds > 0 else DEFAULT_FLUSH_SECONDS


@dataclass(frozen=True)
class PendingEvent:
    event_type: str
    occurred_at: datetime
    room_id: str | None = None
    user_id: UUID | None = None
    value: int | None = None
    details: dict = field(default_factory=dict)


@dataclass
class Gauges:
    """Exactly what is live right now, and the most there has ever been."""

    rooms: int = 0
    players: int = 0
    active_games: int = 0
    peak_rooms: int = 0
    peak_players: int = 0
    peak_active_games: int = 0


class RuntimeMetrics:
    def __init__(self, *, max_buffered: int = MAX_BUFFERED_EVENTS) -> None:
        self._buffer: deque[PendingEvent] = deque(maxlen=max_buffered)
        self._totals: Counter[str] = Counter()
        self.gauges = Gauges()
        # Four ways to lose an observation, counted apart (#614): the buffer
        # overflowed, a flush's transaction failed before its commit (the
        # batch stays buffered and goes next time - only overflow loses it),
        # a flush was cancelled mid-way (same), or a commit's outcome was
        # unknowable - the connection went away during COMMIT - and the batch
        # was let go rather than written twice.
        self.dropped_events = 0
        self.failed_flushes = 0
        self.interrupted_flushes = 0
        self.ambiguous_batches = 0
        self.events_lost_to_ambiguity = 0
        self.started_at = datetime.now(timezone.utc)

    def record(
        self,
        event_type: RuntimeEventType,
        *,
        room_id: str | None = None,
        user_id: UUID | None = None,
        value: int | None = None,
        details: dict | None = None,
        now: datetime | None = None,
    ) -> None:
        if len(self._buffer) == self._buffer.maxlen:
            # deque drops the oldest for us; counting it is what keeps the gap
            # from being invisible.
            self.dropped_events += 1
        self._buffer.append(
            PendingEvent(
                event_type=event_type.value,
                occurred_at=now or datetime.now(timezone.utc),
                room_id=room_id,
                user_id=user_id,
                value=value,
                details=details or {},
            )
        )
        self._totals[event_type.value] += 1

    def observe(
        self,
        *,
        rooms: int | None = None,
        players: int | None = None,
        active_games: int | None = None,
    ) -> None:
        """Set the live counts, taken from the thing that actually knows them.

        Passed in rather than derived by adding and subtracting: a gauge that
        accumulates drifts the first time an event is missed, and then lies
        for as long as the process runs.
        """
        if rooms is not None:
            self.gauges.rooms = rooms
            self.gauges.peak_rooms = max(self.gauges.peak_rooms, rooms)
        if players is not None:
            self.gauges.players = players
            self.gauges.peak_players = max(self.gauges.peak_players, players)
        if active_games is not None:
            self.gauges.active_games = active_games
            self.gauges.peak_active_games = max(
                self.gauges.peak_active_games, active_games
            )

    def totals(self) -> dict[str, int]:
        return dict(self._totals)

    def snapshot(self, limit: int | None = None) -> list[PendingEvent]:
        """The oldest buffered events, still buffered: a flush takes them
        off with `acknowledge` once their transaction has committed."""
        if limit is None:
            return list(self._buffer)
        return [event for _, event in zip(range(limit), self._buffer, strict=False)]

    def acknowledge(self, events: list[PendingEvent]) -> None:
        """Forget events a flush has written. Only what is still buffered is
        removed: the deque may have dropped some of them since the snapshot,
        and those were counted as dropped when it did."""
        written = {id(event) for event in events}
        while self._buffer and id(self._buffer[0]) in written:
            self._buffer.popleft()

    def drain(self) -> list[PendingEvent]:
        drained = list(self._buffer)
        self._buffer.clear()
        return drained

    @property
    def buffered(self) -> int:
        return len(self._buffer)


# One worker, one process, one recorder. Imported directly rather than passed
# through every call site, because instrumentation that is awkward to reach
# does not get added.
metrics = RuntimeMetrics()


def _utc_date(value: datetime) -> date:
    return value.astimezone(timezone.utc).date()


# asyncpg binds at most 32,767 parameters per statement; the insert chunk is
# sized from the table's own column count so adding a column shrinks the
# chunk rather than breaking the flush.
_PARAMETER_CEILING = 30_000
INSERT_CHUNK_ROWS = max(1, _PARAMETER_CEILING // len(RuntimeEvent.__table__.columns))
FLUSH_BATCH_EVENTS = 5_000


class _CommitOutcomeUnknown(Exception):
    """The COMMIT itself raised: the batch may or may not be on disk."""


def _daily_insert(session: AsyncSession):
    dialect = session.get_bind().dialect.name
    if dialect == "postgresql":
        return postgresql_insert(RuntimeStatsDaily), func.greatest
    if dialect == "sqlite":
        return sqlite_insert(RuntimeStatsDaily), func.max
    raise RuntimeError(f"Unsupported runtime metrics dialect: {dialect}")


async def _normalize_account_references(
    session: AsyncSession, pending: list[PendingEvent]
) -> list[PendingEvent]:
    """Detach an observation from an account that is gone or erased.

    One buffered event naming a purged guest would fail the whole batch's
    foreign key; the erasure barrier (app.auth.erasure) says which accounts
    an observation may no longer point at, and the event keeps everything
    but the reference.
    """
    referenced = {event.user_id for event in pending if event.user_id is not None}
    if not referenced:
        return pending
    erased = await erased_identity_ids(session, referenced)
    if not erased:
        return pending
    return [
        replace(event, user_id=None) if event.user_id in erased else event
        for event in pending
    ]


async def flush_events(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    recorder: RuntimeMetrics | None = None,
    batch_size: int = FLUSH_BATCH_EVENTS,
) -> int:
    """Write buffered observations, and roll them into the daily totals.

    Both in one transaction: an event row that survives without its aggregate
    would be lost the day retention removes it. The batch stays buffered
    until that transaction has committed, so a failure keeps it for the
    next flush rather than losing it silently (#614); the raw rows go in
    bounded chunks with no returned ids, and the daily totals are grouped
    here and written as one ordered upsert per chunk instead of a read and
    a write per day and metric.
    """
    source = recorder or metrics
    pending = source.snapshot(batch_size)
    if not pending:
        return 0
    try:
        async with session_factory() as session:
            await session.begin()
            try:
                written = await _normalize_account_references(session, pending)
                rows = [
                    {
                        "event_type": event.event_type,
                        "occurred_at": event.occurred_at,
                        "room_id": event.room_id,
                        "user_id": event.user_id,
                        "value": event.value,
                        "details": event.details or None,
                    }
                    for event in written
                ]
                for start in range(0, len(rows), INSERT_CHUNK_ROWS):
                    # `inline()`: without it a one-row insert on PostgreSQL
                    # fetches the generated id with RETURNING, which nothing
                    # here reads.
                    await session.execute(
                        insert(RuntimeEvent).inline(),
                        rows[start : start + INSERT_CHUNK_ROWS],
                    )
                await _roll_up(session, written)
            except BaseException:
                await session.rollback()
                raise
            try:
                await session.commit()
            except Exception as error:
                raise _CommitOutcomeUnknown() from error
    except _CommitOutcomeUnknown:
        source.acknowledge(pending)
        source.ambiguous_batches += 1
        source.events_lost_to_ambiguity += len(pending)
        raise
    except asyncio.CancelledError:
        source.interrupted_flushes += 1
        raise
    except Exception:
        source.failed_flushes += 1
        raise
    source.acknowledge(pending)
    return len(pending)


async def _roll_up(session: AsyncSession, events: list[PendingEvent]) -> None:
    """Add a batch to `runtime_stats_daily`, which is kept for ever.

    Grouped in memory by day and metric, then upserted in ascending
    (day, metric) order - the same order every flush takes, so two writers
    cannot deadlock on the rows - with additive occurrences and sum and a
    greatest-of max, `updated_at` set explicitly in the assignment.
    """
    occurrences: Counter[tuple[date, str]] = Counter()
    sums: Counter[tuple[date, str]] = Counter()
    maxima: dict[tuple[date, str], int] = {}
    for event in events:
        key = (_utc_date(event.occurred_at), event.event_type)
        occurrences[key] += 1
        if event.value is not None:
            sums[key] += event.value
            maxima[key] = max(maxima.get(key, event.value), event.value)
    rows = [
        {
            "stat_date": stat_date,
            "metric": metric,
            "occurrences": count,
            "value_sum": sums[(stat_date, metric)],
            "value_max": maxima.get((stat_date, metric)),
        }
        for (stat_date, metric), count in sorted(occurrences.items())
    ]
    statement_for, greatest = _daily_insert(session)
    for start in range(0, len(rows), INSERT_CHUNK_ROWS):
        statement = statement_for.values(rows[start : start + INSERT_CHUNK_ROWS])
        excluded = statement.excluded
        await session.execute(
            statement.on_conflict_do_update(
                index_elements=["stat_date", "metric"],
                set_={
                    "occurrences": RuntimeStatsDaily.occurrences + excluded.occurrences,
                    "value_sum": RuntimeStatsDaily.value_sum + excluded.value_sum,
                    "value_max": greatest(
                        func.coalesce(RuntimeStatsDaily.value_max, excluded.value_max),
                        func.coalesce(excluded.value_max, RuntimeStatsDaily.value_max),
                    ),
                    "updated_at": func.now(),
                },
            )
        )


async def purge_expired_events(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    days: int | None = None,
    now: datetime | None = None,
    budget: SweepBudget | None = None,
) -> SweepReport:
    """Drop raw rows past the retention window, a committed batch at a time.

    The aggregates they were rolled into are permanent, so what is lost is the
    ability to ask about one particular minute a month ago - not the trend.
    That asymmetry is the whole reason for keeping two tables: unbounded event
    rows on an embedded database is a disk that fills up quietly.
    """
    cutoff = (now or datetime.now(timezone.utc)) - timedelta(
        days=days if days is not None else retention_days()
    )
    return await delete_in_batches(
        session_factory,
        name="runtime_events",
        candidates=select(RuntimeEvent.id)
        .where(RuntimeEvent.occurred_at < cutoff)
        .order_by(RuntimeEvent.occurred_at, RuntimeEvent.id),
        delete_for=lambda ids: delete(RuntimeEvent).where(RuntimeEvent.id.in_(ids)),
        budget=budget or sweep_budget_from_env(),
        overdue=select(func.min(RuntimeEvent.occurred_at)).where(
            RuntimeEvent.occurred_at < cutoff
        ),
        now=cutoff,
    )


async def run_metrics_loop(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    interval_seconds: float | None = None,
    health: LoopHealth | None = None,
) -> None:
    """Flush for ever, purging once a day's worth of flushes have gone by."""
    interval = interval_seconds or flush_seconds()
    since_purge = 0.0
    while True:
        try:
            await flush_events(session_factory)
            since_purge += interval
            if since_purge >= 3600:
                since_purge = 0.0
                removed = await purge_expired_events(session_factory)
                if removed:
                    logger.info("runtime metrics: purged %d expired events", removed)
            # Last, so an iteration whose purge failed does not also report a
            # success. On a purge cycle the earlier placement recorded both,
            # and `last_success` advancing past a failed iteration is worse
            # than useless - it is the number an alert would trust.
            if health is not None:
                health.record_success()
        except asyncio.CancelledError:
            raise
        except Exception:
            # One bad batch must not stop every later observation. Counted
            # rather than only logged, so a flush failing every time is
            # visible from outside - these are the observations #472 needs.
            if health is not None:
                health.record_failure()
            logger.exception("runtime metrics flush failed")
        await asyncio.sleep(interval)


def start_metrics_loop(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    health: LoopHealth | None = None,
) -> asyncio.Task[None]:
    return asyncio.create_task(run_metrics_loop(session_factory, health=health))


async def stop_metrics_loop(
    task: asyncio.Task[None] | None,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
) -> None:
    """Stop the loop, writing whatever it was holding.

    A planned restart should not lose the observations describing it.
    """
    if task is None:
        return
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
    if session_factory is not None:
        with contextlib.suppress(Exception):
            await flush_events(session_factory)


async def daily_totals(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    days: int = 30,
    now: datetime | None = None,
) -> list[dict]:
    """The permanent aggregates, newest day first."""
    since = _utc_date((now or datetime.now(timezone.utc)) - timedelta(days=days))
    async with session_factory() as session:
        rows = (
            await session.execute(
                select(RuntimeStatsDaily)
                .where(RuntimeStatsDaily.stat_date >= since)
                .order_by(
                    RuntimeStatsDaily.stat_date.desc(), RuntimeStatsDaily.metric
                )
            )
        ).scalars().all()
    return [
        {
            "date": row.stat_date.isoformat(),
            "metric": row.metric,
            "occurrences": row.occurrences,
            "valueSum": row.value_sum,
            "valueMax": row.value_max,
        }
        for row in rows
    ]


async def recent_events(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    limit: int = 100,
    event_type: str | None = None,
    room_id: str | None = None,
    user_id: UUID | None = None,
) -> list[dict]:
    """Raw observations, newest first, for looking at one thing in particular."""
    async with session_factory() as session:
        statement = select(RuntimeEvent).order_by(RuntimeEvent.occurred_at.desc())
        if event_type:
            statement = statement.where(RuntimeEvent.event_type == event_type)
        if room_id:
            statement = statement.where(RuntimeEvent.room_id == room_id)
        if user_id is not None:
            statement = statement.where(RuntimeEvent.user_id == user_id)
        rows = (await session.execute(statement.limit(limit))).scalars().all()
    return [
        {
            "id": str(row.id),
            "eventType": row.event_type,
            "occurredAt": row.occurred_at.isoformat(),
            "roomId": row.room_id,
            "userId": str(row.user_id) if row.user_id else None,
            "value": row.value,
            "details": row.details,
        }
        for row in rows
    ]


async def stored_event_count(
    session_factory: async_sessionmaker[AsyncSession],
) -> int:
    async with session_factory() as session:
        return int(
            await session.scalar(select(func.count(RuntimeEvent.id))) or 0
        )


async def _run_cli(args) -> tuple[int, int]:
    from app.db import init_db, maintenance_engine

    engine, factory = maintenance_engine()
    try:
        await init_db(engine)
        written = await flush_events(factory)
        removed = (
            await purge_expired_events(factory, days=args.days) if args.purge else 0
        )
        return written, removed
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Flush buffered runtime observations and, with --purge, drop raw "
            "rows past the retention window. The running server does both on "
            "its own; this is for cron-driven deployments and for looking."
        )
    )
    parser.add_argument("--purge", action="store_true")
    parser.add_argument("--days", type=int, default=None)
    args = parser.parse_args()
    # Whoever runs this wants to see what happened, not only a count -
    # on a deployment with no SMTP the log line is the message.
    configure_logging()
    written, removed = asyncio.run(_run_cli(args))
    print(f"Wrote {written} observations; purged {removed} expired rows.")


if __name__ == "__main__":
    main()
