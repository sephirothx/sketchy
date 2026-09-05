"""Bounded, batched deletion for every retention sweep.

Each retention window used to be enforced by a different shape of DELETE:
one unbounded statement for messages and runtime events, a loop of batches
with no ceiling for sessions, exports and outbox rows, an opportunistic
single batch for rate-limit buckets, nothing scheduled at all for tokens and
retired room codes, and a startup-only pass for shutdown abandonments. The
first queued chat batch even ran the message purge inside its own insert
transaction, so a purge backlog could cost a room its lines (#550).

`delete_in_batches` is the one shape they all take now. It selects a bounded,
deterministically ordered batch of ids, deletes exactly those in a
transaction of their own, and repeats until the table is clean or the run's
row or time budget is spent - in which case it says so, and the loop that
called it comes back sooner than its next scheduled tick. What it returns is
the count of rows actually removed, carrying the batches, the duration,
whether it was cut short and how far behind the oldest survivor is, so the
sweep is observable rather than merely believed.
"""
from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
import os
import time
from typing import Any

from sqlalchemy import Delete, Select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

DEFAULT_ROW_BUDGET = 5_000
DEFAULT_BATCH_ROWS = 500
DEFAULT_SECONDS_BUDGET = 30.0


@dataclass(frozen=True)
class SweepBudget:
    """What one run of one sweep may spend: rows removed, rows per batch, seconds."""

    rows: int = DEFAULT_ROW_BUDGET
    batch: int = DEFAULT_BATCH_ROWS
    seconds: float = DEFAULT_SECONDS_BUDGET

    def __post_init__(self) -> None:
        if self.rows < 1 or self.batch < 1:
            raise ValueError("a sweep budget needs at least one row and one row per batch")
        if self.seconds <= 0:
            raise ValueError("a sweep budget needs a positive time allowance")


def _positive(values: dict[str, str], name: str, default: float, cast) -> Any:
    raw = values.get(name, "").strip()
    if not raw:
        return default
    try:
        value = cast(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def sweep_budget_from_env(environ: dict[str, str] | None = None) -> SweepBudget:
    """The deployment's per-sweep, per-run allowance.

    `RETENTION_SWEEP_ROW_BUDGET`, `RETENTION_SWEEP_BATCH_ROWS` and
    `RETENTION_SWEEP_SECONDS_BUDGET`; each falls back to its default when
    unset, blank, unparsable or non-positive.
    """
    values = os.environ if environ is None else environ
    return SweepBudget(
        rows=_positive(values, "RETENTION_SWEEP_ROW_BUDGET", DEFAULT_ROW_BUDGET, int),
        batch=_positive(values, "RETENTION_SWEEP_BATCH_ROWS", DEFAULT_BATCH_ROWS, int),
        seconds=_positive(
            values, "RETENTION_SWEEP_SECONDS_BUDGET", DEFAULT_SECONDS_BUDGET, float
        ),
    )


class SweepReport(int):
    """How many rows a sweep removed, carrying how it got there.

    An `int`, so every caller and test that counted rows still does; the
    attributes are the account of the run that the loop logs and exposes.
    """

    name: str
    batches: int
    seconds: float
    exhausted: bool
    oldest_overdue_seconds: float | None

    def __new__(
        cls,
        rows: int,
        *,
        name: str,
        batches: int = 0,
        seconds: float = 0.0,
        exhausted: bool = False,
        oldest_overdue_seconds: float | None = None,
    ) -> SweepReport:
        report = super().__new__(cls, rows)
        report.name = name
        report.batches = batches
        report.seconds = seconds
        report.exhausted = exhausted
        report.oldest_overdue_seconds = oldest_overdue_seconds
        return report

    @property
    def rows(self) -> int:
        return int(self)

    def as_dict(self) -> dict[str, object]:
        return {
            "rows": int(self),
            "batches": self.batches,
            "seconds": round(self.seconds, 3),
            "exhausted": self.exhausted,
            "oldest_overdue_seconds": (
                None
                if self.oldest_overdue_seconds is None
                else round(self.oldest_overdue_seconds, 1)
            ),
        }


async def delete_in_batches(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    name: str,
    candidates: Select,
    delete_for: Callable[[Sequence[Any]], Delete],
    budget: SweepBudget,
    overdue: Select | None = None,
    now: datetime | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> SweepReport:
    """Delete what `candidates` selects, a committed batch at a time, within `budget`.

    `candidates` is an ordered select of key values (its own LIMIT is
    replaced); `delete_for` turns one batch of those keys into the DELETE.
    Each batch is its own transaction, so a lock held for one batch is
    released before the next and nothing waits on the whole run. `overdue`,
    when given, selects the earliest expiry still eligible after a run that
    was cut short, so the report can say how far behind the sweep is.
    """
    started = clock()
    removed = 0
    batches = 0
    exhausted = False
    while True:
        if removed >= budget.rows or clock() - started >= budget.seconds:
            exhausted = True
            break
        limit = min(budget.batch, budget.rows - removed)
        async with session_factory() as session:
            async with session.begin():
                rows = (await session.execute(candidates.limit(limit))).all()
                # One key column comes back as its value, a composite key as
                # the tuple `delete_for` will match with `tuple_(...).in_`.
                keys = [row[0] if len(row) == 1 else tuple(row) for row in rows]
                deleted = 0
                if keys:
                    result = await session.execute(delete_for(keys))
                    deleted = int(result.rowcount or 0)
        if keys:
            batches += 1
            removed += deleted
        if len(keys) < limit:
            break
    oldest_overdue_seconds: float | None = None
    if exhausted and overdue is not None:
        async with session_factory() as session:
            earliest = await session.scalar(overdue)
        if earliest is not None:
            if earliest.tzinfo is None:
                earliest = earliest.replace(tzinfo=timezone.utc)
            checked_at = now or datetime.now(timezone.utc)
            oldest_overdue_seconds = max(0.0, (checked_at - earliest).total_seconds())
    return SweepReport(
        removed,
        name=name,
        batches=batches,
        seconds=clock() - started,
        exhausted=exhausted,
        oldest_overdue_seconds=oldest_overdue_seconds,
    )
