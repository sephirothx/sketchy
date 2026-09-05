"""Build account data exports one at a time from the durable job table.

The `data_exports` table is the queue (R-PRIV-03): a request writes a `pending`
row and returns, and this loop is what turns the row into a document. One loop,
one job at a time, so two accounts asking together cost the process one build's
memory rather than two - the bound the single-worker model (N-01) needs, since
one build's working set is every player's latency.

The loop is woken by the request that wrote the row and otherwise sweeps every
`EXPORT_SWEEP_SECONDS`, which is also the retry: a row left `processing` by a
crashed process is reclaimed by the sweep once it is older than the stale
window, and a row written by the operator's CLI is picked up the same way. It
is supervised like the mail and retention loops, so a loop that has stopped
fails readiness while one that is merely erroring is counted, not hidden.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import os

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth.account_data import (
    DEFAULT_EXPORT_BATCH_SIZE,
    process_pending_data_exports,
)
from app.services.readiness import LoopHealth

logger = logging.getLogger(__name__)

DEFAULT_INTERVAL_SECONDS = 60.0


def sweep_interval_seconds(environ: dict[str, str] | None = None) -> float:
    values = os.environ if environ is None else environ
    raw = values.get("EXPORT_SWEEP_SECONDS", "").strip()
    if not raw:
        return DEFAULT_INTERVAL_SECONDS
    try:
        seconds = float(raw)
    except ValueError:
        return DEFAULT_INTERVAL_SECONDS
    return seconds if seconds > 0 else DEFAULT_INTERVAL_SECONDS


class DataExportWorker:
    """The one place export documents are built while the server runs."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        interval_seconds: float | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._interval = interval_seconds or sweep_interval_seconds()
        self._wake = asyncio.Event()

    @property
    def interval_seconds(self) -> float:
        return self._interval

    def wake(self) -> None:
        """Ask for a sweep now. Safe from any coroutine on the loop."""
        self._wake.set()

    async def drain(self) -> int:
        """Build every due job, one at a time, until a sweep finds nothing."""
        total = 0
        while True:
            completed = await process_pending_data_exports(
                self._session_factory, limit=DEFAULT_EXPORT_BATCH_SIZE
            )
            total += completed
            if completed == 0:
                return total

    async def run(self, *, health: LoopHealth | None = None) -> None:
        """Sweep for ever, surviving every failure but cancellation."""
        while True:
            # Cleared before the sweep rather than after, so a request that
            # arrives mid-build is not forgotten until the next interval.
            self._wake.clear()
            try:
                completed = await self.drain()
                if health is not None:
                    health.record_success()
                if completed:
                    logger.info("export sweep: built %d document(s)", completed)
            except asyncio.CancelledError:
                raise
            except Exception:
                # The sweep's own query failing must not take the loop down,
                # or one bad moment stops every later export. Counted, so a
                # sweep failing every time is visible from outside.
                if health is not None:
                    health.record_failure()
                logger.exception("export sweep failed")
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._wake.wait(), timeout=self._interval)

    def start(self, *, health: LoopHealth | None = None) -> asyncio.Task[None]:
        return asyncio.create_task(self.run(health=health))


async def stop_export_worker(task: asyncio.Task[None] | None) -> None:
    """Cancel the loop; a build in flight hands its job back (see account_data)."""
    if task is None:
        return
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
