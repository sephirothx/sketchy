"""How much work the two durable queues are holding, and for how long.

Mail and account exports are both written down first and carried out later,
which is what makes them survive a restart - and also what lets them back up
quietly. A sweeper that has stopped delivering shows in `/api/health` as a
loop failing; a sweeper that is delivering more slowly than mail arrives does
not show anywhere, and neither does an export whose owning task died with the
process that started it. The oldest waiting entry is the number that catches
both.

Two small aggregate queries, answered from a cache for a few seconds so that
a scraper and an open operations page together cost the database one pair of
counts rather than one per poll.
"""
from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
import time

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import DataExport, EmailOutboxEntry, FinishedGameEnvelope
from app.domain_values import DataExportStatus, EmailOutboxState, FinishedGameHandoffState


DEFAULT_CACHE_SECONDS = 10.0


@dataclass(frozen=True)
class QueueDepth:
    pending: int
    oldest_seconds: float | None

    def as_json(self) -> dict[str, object]:
        return {
            "pending": self.pending,
            "oldestSeconds": None
            if self.oldest_seconds is None
            else round(self.oldest_seconds, 1),
        }


@dataclass(frozen=True)
class HandoffDepth(QueueDepth):
    """The finished-game queue also counts what it gave up on (#541)."""

    failed: int = 0

    def as_json(self) -> dict[str, object]:
        return {**super().as_json(), "failed": self.failed}


@dataclass(frozen=True)
class QueueSnapshot:
    mail_outbox: QueueDepth
    data_exports: QueueDepth
    finished_games: HandoffDepth


def _age(oldest: datetime | None, now: datetime) -> float | None:
    if oldest is None:
        return None
    if oldest.tzinfo is None:
        oldest = oldest.replace(tzinfo=timezone.utc)
    return max(0.0, (now - oldest).total_seconds())


class QueueDepths:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        cache_seconds: float = DEFAULT_CACHE_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._session_factory = session_factory
        self._cache_seconds = cache_seconds
        self._clock = clock
        self._cached: tuple[float, QueueSnapshot] | None = None
        self._reading = asyncio.Lock()

    async def read(self) -> QueueSnapshot:
        fresh = self._fresh()
        if fresh is not None:
            return fresh
        async with self._reading:
            fresh = self._fresh()
            if fresh is not None:
                return fresh
            snapshot = await self._query()
            self._cached = (self._clock(), snapshot)
            return snapshot

    def _fresh(self) -> QueueSnapshot | None:
        cached = self._cached
        if cached is None or self._clock() - cached[0] >= self._cache_seconds:
            return None
        return cached[1]

    async def _query(self) -> QueueSnapshot:
        now = datetime.now(timezone.utc)
        async with self._session_factory() as session:
            mail_count, mail_oldest = (
                await session.execute(
                    select(func.count(), func.min(EmailOutboxEntry.created_at)).where(
                        EmailOutboxEntry.state == EmailOutboxState.PENDING.value
                    )
                )
            ).one()
            export_count, export_oldest = (
                await session.execute(
                    select(func.count(), func.min(DataExport.created_at)).where(
                        DataExport.status.in_(
                            (
                                DataExportStatus.PENDING.value,
                                DataExportStatus.PROCESSING.value,
                            )
                        )
                    )
                )
            ).one()
            # One statement for the third queue too: live rows and failed
            # rows are the two groups, and the oldest matters only for live.
            handoff_count = 0
            handoff_failed = 0
            handoff_oldest = None
            for state, count, oldest in (
                await session.execute(
                    select(
                        FinishedGameEnvelope.state,
                        func.count(),
                        func.min(FinishedGameEnvelope.created_at),
                    ).group_by(FinishedGameEnvelope.state)
                )
            ).all():
                if state == FinishedGameHandoffState.FAILED.value:
                    handoff_failed += int(count or 0)
                    continue
                handoff_count += int(count or 0)
                # `created_at` is NOT NULL, so a group that exists has a min.
                handoff_oldest = (
                    oldest if handoff_oldest is None else min(handoff_oldest, oldest)
                )
        return QueueSnapshot(
            mail_outbox=QueueDepth(int(mail_count or 0), _age(mail_oldest, now)),
            data_exports=QueueDepth(int(export_count or 0), _age(export_oldest, now)),
            finished_games=HandoffDepth(
                int(handoff_count or 0), _age(handoff_oldest, now), int(handoff_failed or 0)
            ),
        )
