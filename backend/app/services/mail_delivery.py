"""The loop that empties the email outbox.

Queueing and delivering are separate on purpose - see `app.auth.mail` - so
something has to do the delivering. In a single-worker deployment (#382) that
is one task inside the application, which needs no scheduler, no broker, and no
second process to forget to start.

The same work is available as a command for deployments that would rather run
it from cron, and for looking at what is stuck.
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
import os

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.logging_config import configure_logging
from app.auth.mail import (
    DEFAULT_BATCH_SIZE,
    DeliveryResult,
    deliver_pending,
    on_queued,
    purge_expired_outbox_entries,
)
from app.services.readiness import LoopHealth


logger = logging.getLogger(__name__)

PURGE_INTERVAL_SECONDS = 3600.0

DEFAULT_INTERVAL_SECONDS = 30.0


def sweep_interval_seconds(environ: dict[str, str] | None = None) -> float:
    values = os.environ if environ is None else environ
    raw = values.get("EMAIL_SWEEP_SECONDS", "").strip()
    if not raw:
        return DEFAULT_INTERVAL_SECONDS
    try:
        seconds = float(raw)
    except ValueError:
        return DEFAULT_INTERVAL_SECONDS
    return seconds if seconds > 0 else DEFAULT_INTERVAL_SECONDS


async def run_delivery_loop(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    interval_seconds: float | None = None,
    health: LoopHealth | None = None,
) -> None:
    """Deliver due messages for ever, surviving every failure but cancellation.

    Woken by every commit that queues a message (`on_queued`), and by the
    interval for what nothing woke it for - a retry coming due, a message
    queued by another process. A sweep that came back full sweeps again at
    once: the rest of a burst is due now, not in `interval` (#1255).
    """
    interval = interval_seconds or sweep_interval_seconds()
    wake = asyncio.Event()
    stop_listening = on_queued(wake.set)
    clock = asyncio.get_running_loop().time
    last_purge = clock()
    try:
        while True:
            # Cleared before the sweep rather than after, so a message queued
            # while this one sends is not left for the interval.
            wake.clear()
            full = await _sweep(session_factory, health)
            if clock() - last_purge >= PURGE_INTERVAL_SECONDS:
                last_purge = clock()
                await _purge(session_factory, health)
            if full:
                await asyncio.sleep(0)
                continue
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(wake.wait(), timeout=interval)
    finally:
        stop_listening()


async def _sweep(
    session_factory: async_sessionmaker[AsyncSession], health: LoopHealth | None
) -> bool:
    """One delivery sweep; whether it took a whole batch."""
    try:
        result = await deliver_pending(session_factory)
        if health is not None:
            health.record_success()
        if result.attempted:
            logger.info(
                "email sweep: %d sent, %d deferred, %d given up on",
                result.sent,
                result.deferred,
                result.failed,
            )
        return result.attempted >= DEFAULT_BATCH_SIZE
    except asyncio.CancelledError:
        raise
    except Exception:
        # A sweep that raises must not take the loop down with it, or one
        # bad row stops every later message. Counted rather than only
        # logged, so a sweep failing every time is visible from outside.
        if health is not None:
            health.record_failure()
        logger.exception("email sweep failed")
        return False


async def _purge(
    session_factory: async_sessionmaker[AsyncSession], health: LoopHealth | None
) -> None:
    """Hourly, not per sweep: retention has day-scale precision. Rides the
    delivery loop so nobody has to remember to start a second one."""
    try:
        removed = await purge_expired_outbox_entries(session_factory)
        if removed:
            logger.info("email sweep: purged %d expired rows", removed)
    except asyncio.CancelledError:
        raise
    except Exception:
        if health is not None:
            health.record_failure()
        logger.exception("email purge failed")


def start_delivery_loop(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    health: LoopHealth | None = None,
) -> asyncio.Task[None]:
    return asyncio.create_task(run_delivery_loop(session_factory, health=health))


async def stop_delivery_loop(task: asyncio.Task[None] | None) -> None:
    if task is None:
        return
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


async def _run(args) -> DeliveryResult:
    from app.db import init_db, maintenance_engine

    engine, factory = maintenance_engine()
    try:
        await init_db(engine)
        return await deliver_pending(factory, batch_size=args.batch_size)
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Deliver queued account emails and report what happened."
    )
    parser.add_argument("--batch-size", type=int, default=50)
    args = parser.parse_args()
    # Whoever runs this wants to see what happened, not only a count -
    # on a deployment with no SMTP the log line is the message.
    configure_logging()
    result = asyncio.run(_run(args))
    print(
        f"Attempted {result.attempted}: {result.sent} sent, "
        f"{result.deferred} deferred, {result.failed} given up on."
    )


if __name__ == "__main__":
    main()
