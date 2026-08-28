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
from app.auth.mail import DeliveryResult, deliver_pending
from app.services.readiness import LoopHealth


logger = logging.getLogger(__name__)

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
    """Deliver due messages for ever, surviving every failure but cancellation."""
    interval = interval_seconds or sweep_interval_seconds()
    while True:
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
        except asyncio.CancelledError:
            raise
        except Exception:
            # A sweep that raises must not take the loop down with it, or one
            # bad row stops every later message. Counted rather than only
            # logged, so a sweep failing every time is visible from outside.
            if health is not None:
                health.record_failure()
            logger.exception("email sweep failed")
        await asyncio.sleep(interval)


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
    from app.db import async_engine, async_session_factory, init_db

    try:
        await init_db()
        return await deliver_pending(async_session_factory, batch_size=args.batch_size)
    finally:
        await async_engine.dispose()


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
