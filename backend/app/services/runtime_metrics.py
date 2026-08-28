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
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from uuid import UUID
import argparse
import asyncio
import contextlib
import logging
import os

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.logging_config import configure_logging
from app.db.models import RuntimeEvent, RuntimeStatsDaily, generate_uuid
from app.domain_values import RuntimeEventType
from app.services.readiness import LoopHealth


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
        self.dropped_events = 0
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


async def flush_events(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    recorder: RuntimeMetrics | None = None,
) -> int:
    """Write buffered observations, and roll them into the daily totals.

    Both in one transaction: an event row that survives without its aggregate
    would be lost the day retention removes it.
    """
    source = recorder or metrics
    pending = source.drain()
    if not pending:
        return 0
    async with session_factory() as session:
        async with session.begin():
            session.add_all(
                RuntimeEvent(
                    id=generate_uuid(),
                    event_type=event.event_type,
                    occurred_at=event.occurred_at,
                    room_id=event.room_id,
                    user_id=event.user_id,
                    value=event.value,
                    details=event.details,
                )
                for event in pending
            )
            await _roll_up(session, pending)
    return len(pending)


async def _roll_up(session: AsyncSession, events: list[PendingEvent]) -> None:
    """Add a batch to `runtime_stats_daily`, which is kept for ever."""
    grouped: dict[tuple[date, str], list[int]] = {}
    counts: Counter[tuple[date, str]] = Counter()
    for event in events:
        key = (_utc_date(event.occurred_at), event.event_type)
        counts[key] += 1
        if event.value is not None:
            grouped.setdefault(key, []).append(event.value)

    for (stat_date, metric), occurrences in counts.items():
        values = grouped.get((stat_date, metric), [])
        row = await session.get(RuntimeStatsDaily, (stat_date, metric))
        if row is None:
            row = RuntimeStatsDaily(
                stat_date=stat_date,
                metric=metric,
                occurrences=0,
                value_sum=0,
                value_max=None,
            )
            session.add(row)
        row.occurrences += occurrences
        row.value_sum += sum(values)
        if values:
            row.value_max = max(max(values), row.value_max or 0)


async def purge_expired_events(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    days: int | None = None,
    now: datetime | None = None,
) -> int:
    """Drop raw rows past the retention window.

    The aggregates they were rolled into are permanent, so what is lost is the
    ability to ask about one particular minute a month ago - not the trend.
    That asymmetry is the whole reason for keeping two tables: unbounded event
    rows on an embedded database is a disk that fills up quietly.
    """
    cutoff = (now or datetime.now(timezone.utc)) - timedelta(
        days=days if days is not None else retention_days()
    )
    async with session_factory() as session:
        async with session.begin():
            result = await session.execute(
                delete(RuntimeEvent).where(RuntimeEvent.occurred_at < cutoff)
            )
            return int(result.rowcount or 0)


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
    from app.db import async_engine, async_session_factory, init_db

    try:
        await init_db()
        written = await flush_events(async_session_factory)
        removed = (
            await purge_expired_events(async_session_factory, days=args.days)
            if args.purge
            else 0
        )
        return written, removed
    finally:
        await async_engine.dispose()


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
