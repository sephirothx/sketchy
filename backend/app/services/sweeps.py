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

Running is not complying, though, which is what #478 adds: a sweep that runs
every hour and removes five thousand rows an hour looks perfectly healthy
while a table grows by six thousand. So every sweep also measures what it
*left* - the age of the oldest row it should already have removed, and how
many such rows there are, both over the sweep's own eligibility predicate so
that rows a policy exempts are never counted as lateness - and the retention
loop checks that age against the table's stated SLA.
"""
from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
import os
import time
from typing import Any

from sqlalchemy import ColumnElement, Delete, Select, Update, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

DEFAULT_ROW_BUDGET = 5_000
DEFAULT_BATCH_ROWS = 500
DEFAULT_SECONDS_BUDGET = 30.0

# How far a backlog is counted before the answer stops being worth the scan.
# "More than ten thousand rows overdue" and "eight hundred thousand" call for
# the same action, and the second costs a sequential scan of the table every
# hour to say so. The age of the oldest overdue row is the unbounded-precision
# half of the pair; this half is a size, capped.
BACKLOG_CAP = 10_000


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


@dataclass(frozen=True)
class OverdueProbe:
    """How to ask a table what it still owes, in the two terms that matter.

    `oldest` is the earliest expiry among rows that are eligible **and not
    exempt** - the age of the oldest thing this sweep should already have
    removed. `backlog` is how many such rows there are, counted no further
    than `BACKLOG_CAP`.

    Both are measured on every run, not only on a run cut short. A gauge that
    appears only while a sweep is behind cannot be alerted on: an absent
    series does not compare greater than anything, so the rule that should
    fire is silent for exactly as long as nobody is looking. Emitting a zero
    when a table is clean is what makes "past its SLA" a question monitoring
    can answer.
    """

    oldest: Select
    backlog: Select


def overdue_probe(
    expiry: ColumnElement, *eligible: ColumnElement, cap: int = BACKLOG_CAP
) -> OverdueProbe:
    """The two questions above, over one table's own eligibility predicate.

    `eligible` must be the same predicate the sweep's candidate select uses,
    minus its ordering and limit - anything a policy exempts is excluded here
    too, so a permanently kept row never reads as a sweep falling behind.
    """
    return OverdueProbe(
        oldest=select(func.min(expiry)).where(*eligible),
        backlog=select(func.count()).select_from(
            select(expiry).where(*eligible).limit(cap).subquery()
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
    backlog: int | None
    # Whatever one sweep knows that the common shape does not - the guest
    # purge's two tiers, for one, where a single backlog number would hide
    # exactly the starvation the tiers exist to prevent.
    detail: dict[str, object]

    def __new__(
        cls,
        rows: int,
        *,
        name: str,
        batches: int = 0,
        seconds: float = 0.0,
        exhausted: bool = False,
        oldest_overdue_seconds: float | None = None,
        backlog: int | None = None,
        detail: dict[str, object] | None = None,
    ) -> SweepReport:
        report = super().__new__(cls, rows)
        report.name = name
        report.batches = batches
        report.seconds = seconds
        report.exhausted = exhausted
        report.oldest_overdue_seconds = oldest_overdue_seconds
        report.backlog = backlog
        report.detail = dict(detail or {})
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
            "backlog": self.backlog,
            **self.detail,
        }


async def _apply_in_batches(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    name: str,
    candidates: Select,
    statement_for: Callable[[Sequence[Any]], Delete | Update],
    budget: SweepBudget,
    probe: OverdueProbe | None,
    now: datetime | None,
    clock: Callable[[], float],
) -> SweepReport:
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
                # the tuple `statement_for` will match with `tuple_(...).in_`.
                keys = [row[0] if len(row) == 1 else tuple(row) for row in rows]
                changed = 0
                if keys:
                    result = await session.execute(statement_for(keys))
                    changed = int(result.rowcount or 0)
        if keys:
            batches += 1
            removed += changed
        if len(keys) < limit:
            break
    oldest_overdue_seconds: float | None = None
    backlog: int | None = None
    if probe is not None:
        async with session_factory() as session:
            earliest = await session.scalar(probe.oldest)
            backlog = int(await session.scalar(probe.backlog) or 0)
        oldest_overdue_seconds = 0.0
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
        backlog=backlog,
    )


async def delete_in_batches(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    name: str,
    candidates: Select,
    delete_for: Callable[[Sequence[Any]], Delete],
    budget: SweepBudget,
    probe: OverdueProbe | None = None,
    now: datetime | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> SweepReport:
    """Delete what `candidates` selects, a committed batch at a time, within `budget`.

    `candidates` is an ordered select of key values (its own LIMIT is
    replaced); `delete_for` turns one batch of those keys into the DELETE.
    Each batch is its own transaction, so a lock held for one batch is
    released before the next and nothing waits on the whole run. `probe`,
    when given, measures what the table still owes after the run - the age of
    the oldest overdue row and how many there are - which is what a retention
    SLA is checked against.

    Pass `now` as the eligibility cutoff rather than the wall clock: the
    overdue age is meant to be time spent *past eligibility*, not the row's
    own age, and those differ by the whole retention window.
    """
    return await _apply_in_batches(
        session_factory,
        name=name,
        candidates=candidates,
        statement_for=delete_for,
        budget=budget,
        probe=probe,
        now=now,
        clock=clock,
    )


async def erase_in_batches(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    name: str,
    candidates: Select,
    erase_for: Callable[[Sequence[Any]], Update],
    budget: SweepBudget,
    probe: OverdueProbe | None = None,
    now: datetime | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> SweepReport:
    """`delete_in_batches` for a retention window that clears a column, not a row.

    Some retention windows are over one field rather than the record holding
    it: an undecided bug report must lose its screenshot after ninety days and
    keep everything that makes it a report. The batching, the budget and the
    overdue probe are the same; only the statement differs, and what the
    report counts is rows changed rather than rows gone.
    """
    return await _apply_in_batches(
        session_factory,
        name=name,
        candidates=candidates,
        statement_for=erase_for,
        budget=budget,
        probe=probe,
        now=now,
        clock=clock,
    )
