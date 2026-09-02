"""What `/api/ready` tests before it says this process can serve.

Readiness used to answer from the shutdown coordinator's own in-memory state
alone, which meant it could only ever report that the process had finished
starting and had not yet begun draining. A process whose database has gone
away, or whose background loops have stopped, answered exactly the same way -
so a load balancer kept routing to it and an automated rollback had nothing to
detect. The two checks here are the difference between "the event loop is
turning" and "this instance can authenticate a player, allocate a room code,
and write down what happens next".
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
import logging
import time

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


logger = logging.getLogger("sketchy.readiness")

# Short enough that a dependency check cannot itself become the thing holding
# the probe open, and well inside any sane probe timeout.
DATABASE_PROBE_TIMEOUT_SECONDS = 1.0
# A load balancer polls readiness every second or so, and several may poll at
# once. Without a cache the probe becomes its own load, and a database already
# under pressure gets the extra queries at the worst moment. Failures are
# cached alongside successes for the same reason - a broken dependency must
# not be retried once per probe.
DATABASE_PROBE_CACHE_SECONDS = 5.0


@dataclass
class LoopHealth:
    """One background loop's own account of how it is getting on.

    Every supervised loop swallows every exception but cancellation and carries on for
    ever, which keeps one bad row from stopping every later sweep - and also
    makes a loop that fails on every single iteration indistinguishable, from
    outside, from one that is working. These counters are that distinction,
    recorded by the loop itself.
    """

    name: str
    last_success: float | None = None
    last_failure: float | None = None
    consecutive_failures: int = 0
    total_failures: int = 0

    def record_success(self) -> None:
        self.last_success = time.monotonic()
        self.consecutive_failures = 0

    def record_failure(self) -> None:
        self.last_failure = time.monotonic()
        self.consecutive_failures += 1
        self.total_failures += 1

    def snapshot(self) -> dict[str, object]:
        now = time.monotonic()
        return {
            "consecutive_failures": self.consecutive_failures,
            "total_failures": self.total_failures,
            "seconds_since_success": (
                None if self.last_success is None else round(now - self.last_success, 3)
            ),
            "seconds_since_failure": (
                None if self.last_failure is None else round(now - self.last_failure, 3)
            ),
        }


@dataclass
class _Supervised:
    task: asyncio.Task[None]
    health: LoopHealth


@dataclass
class ReadinessProbe:
    """The dependency half of readiness, cached and bounded.

    Deliberately not a health *policy*: it reports what it found, and the
    endpoint decides what a finding means. Keeping the two apart is what lets
    a failing email sweep show up in `/api/health` without pulling a
    perfectly playable game server out of rotation.
    """

    session_factory: async_sessionmaker[AsyncSession]
    timeout_seconds: float = DATABASE_PROBE_TIMEOUT_SECONDS
    cache_seconds: float = DATABASE_PROBE_CACHE_SECONDS
    clock: Callable[[], float] = time.monotonic
    _loops: dict[str, _Supervised] = field(default_factory=dict)
    _cached_database: tuple[float, bool, str | None] | None = None
    # Held only across a cache *miss*. Without it, every probe arriving in the
    # window between expiry and the first result stored sees a stale entry and
    # opens its own session - so the moment the cache expires, the poll the
    # cache exists to absorb arrives in full. Their completions could also
    # land out of order and let an older failure overwrite a newer success.
    _probing: asyncio.Lock = field(default_factory=asyncio.Lock)

    # --- background loops ---------------------------------------------------

    def supervise(self, name: str, task: asyncio.Task[None], health: LoopHealth) -> None:
        """Take responsibility for a loop that has just been started."""
        self._loops[name] = _Supervised(task=task, health=health)

    def release(self) -> None:
        """Forget every loop, because the process is on its way out.

        Called from lifespan teardown before the loops are cancelled: a
        deliberately stopped loop is not a crashed one, and readiness has
        already gone 503 for the drain by then anyway.
        """
        self._loops.clear()

    def dead_loops(self) -> list[str]:
        """Loops whose task has finished. A loop that only errors is alive.

        `run_*_loop` never returns of its own accord, so a done task means the
        loop is gone - cancelled, or killed by something outside the body's
        own `except`. That is unambiguous, which is why it is the only loop
        condition allowed to fail readiness.
        """
        return sorted(name for name, entry in self._loops.items() if entry.task.done())

    def loop_snapshot(self) -> dict[str, object]:
        return {
            name: {"running": not entry.task.done(), **entry.health.snapshot()}
            for name, entry in sorted(self._loops.items())
        }

    # --- database -----------------------------------------------------------

    async def check_database(self) -> tuple[bool, str | None]:
        """Round-trip the database, answering from cache inside the TTL.

        One round-trip at a time: concurrent misses queue on the lock and the
        first result serves all of them, so a fleet of probes arriving
        together costs the database one `SELECT 1` rather than one each.
        Waiting is bounded by the probe's own timeout.
        """
        cached = self._fresh_result()
        if cached is not None:
            return cached

        async with self._probing:
            # Somebody else may have refreshed it while this probe queued.
            cached = self._fresh_result()
            if cached is not None:
                return cached
            return await self._probe()

    def last_database_result(self) -> dict[str, object] | None:
        """The most recent probe, however old, for the operations page.

        Not a probe itself: the page must not be a second load balancer.
        `None` before the first probe has run.
        """
        cached = self._cached_database
        if cached is None:
            return None
        return {
            "ok": cached[1],
            "reason": cached[2],
            "checkedAgoSeconds": round(max(0.0, self.clock() - cached[0]), 1),
        }

    def _fresh_result(self) -> tuple[bool, str | None] | None:
        cached = self._cached_database
        if cached is None or self.clock() - cached[0] >= self.cache_seconds:
            return None
        return cached[1], cached[2]

    async def _probe(self) -> tuple[bool, str | None]:
        try:
            await asyncio.wait_for(self._select_one(), timeout=self.timeout_seconds)
        except asyncio.CancelledError:
            raise
        except TimeoutError:
            reason = f"database did not answer within {self.timeout_seconds:g}s"
            logger.warning("readiness: %s", reason)
            result = (False, reason)
        except Exception as error:
            reason = f"database unavailable: {type(error).__name__}"
            logger.warning("readiness: %s", reason, exc_info=True)
            result = (False, reason)
        else:
            result = (True, None)

        # Timed from when the answer was obtained, not from when this probe
        # started queueing, so a slow round-trip does not shorten its own TTL.
        self._cached_database = (self.clock(), result[0], result[1])
        return result

    async def _select_one(self) -> None:
        async with self.session_factory() as session:
            await session.execute(text("SELECT 1"))
