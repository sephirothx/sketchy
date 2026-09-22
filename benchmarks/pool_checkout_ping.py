#!/usr/bin/env python3
"""What a pooled connection pays before its first statement (#973).

`pool_pre_ping` pinged on every checkout, and on asyncpg a ping is BEGIN, a
statement and ROLLBACK: three round trips before each session's own work, on
connections that are almost always in steady use. The replacement asks the
driver whether the connection is already closed - free, no round trip - and
pings only one that has been idle for `DB_POOL_PING_IDLE_SECONDS`.

Measured as a session would feel it: open a session, run one trivial
statement, close it, over and over, on one pooled connection.

Usage:
  DATABASE_URL=postgresql+asyncpg://user:password@localhost:5432/sketchy_bench \\
    backend/.venv/bin/python benchmarks/pool_checkout_ping.py --sessions 300
"""
from __future__ import annotations

import argparse
import asyncio
import os
import statistics
import sys
from time import perf_counter

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND_DIR = os.path.join(ROOT_DIR, "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from app.db import get_engine_connect_args, get_engine_pool_options, install_idle_ping  # noqa: E402


async def timed(url: str, *, pre_ping: bool, idle_ping: bool, sessions: int) -> list[float]:
    """Milliseconds from opening a session to having its answer, per session."""
    options = {**get_engine_pool_options(url), "pool_size": 1, "max_overflow": 0}
    options.pop("pool_pre_ping", None)
    engine = create_async_engine(
        url, connect_args=get_engine_connect_args(url), pool_pre_ping=pre_ping, **options
    )
    if idle_ping:
        install_idle_ping(engine, idle_seconds=30)
    factory = async_sessionmaker(engine)
    samples: list[float] = []
    try:
        for index in range(sessions + 20):
            started = perf_counter()
            async with factory() as session:
                await session.execute(text("SELECT 1"))
            if index >= 20:  # the first few open the connection
                samples.append((perf_counter() - started) * 1000)
    finally:
        await engine.dispose()
    return samples


def report(name: str, samples: list[float]) -> None:
    ordered = sorted(samples)
    p95 = ordered[int(len(ordered) * 0.95)]
    print(f"{name:<34} | {statistics.median(samples):>9.3f} | {p95:>9.3f} | {max(samples):>9.3f}")


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sessions", type=int, default=300)
    parser.add_argument("--url", default=os.environ.get("DATABASE_URL", ""))
    arguments = parser.parse_args()
    if not arguments.url.startswith("postgresql"):
        raise SystemExit("Set DATABASE_URL to a PostgreSQL database; SQLite has no round trip to save.")

    print(f"{'Checkout':<34} | {'median ms':>9} | {'p95 ms':>9} | {'max ms':>9}")
    print("-" * 68)
    report("pre-ping on every checkout", await timed(arguments.url, pre_ping=True, idle_ping=False, sessions=arguments.sessions))
    report("closed-socket check only", await timed(arguments.url, pre_ping=False, idle_ping=True, sessions=arguments.sessions))
    report("neither", await timed(arguments.url, pre_ping=False, idle_ping=False, sessions=arguments.sessions))


if __name__ == "__main__":
    asyncio.run(main())
