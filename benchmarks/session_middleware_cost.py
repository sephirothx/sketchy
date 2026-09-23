#!/usr/bin/env python3
"""What resolving a session costs a request that has no use for one (#974).

Two questions, priced separately:

* **The wrapper.** `BaseHTTPMiddleware` runs the rest of the application in a
  task of its own behind a pair of memory streams. That machinery is paid per
  request whatever the middleware then does, so it is measured against a
  plain-ASGI middleware doing the same work.
* **The gate.** The session cookie is `Path=/`, so a browser sends it with the
  shell, the bundle and every font: before this change each of those resolved
  a session. The static path is measured with the gate and without it.

A real session cookie is sent, against a temporary SQLite database with one
account signed in: resolving it is the work the gate skips, and measuring the
gate without it would measure nothing. Two figures per cell: the loop
thread's own CPU, and the whole process's - the difference is aiosqlite's
worker thread, where the session read actually runs, so the first is the one
to compare and the second is what the machine pays.

The absolute numbers depend on the machine and on how quiet it is; what the
table says is the *ratio* between its rows, which one run measures together.

Usage:
  backend/.venv/bin/python benchmarks/session_middleware_cost.py --requests 2000
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
import tempfile
from time import process_time, thread_time

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND_DIR = os.path.join(ROOT_DIR, "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

os.environ.setdefault("IP_HASH_SECRET", "benchmark-secret")

from fastapi import FastAPI  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from starlette.middleware.base import BaseHTTPMiddleware  # noqa: E402
from starlette.responses import PlainTextResponse  # noqa: E402

from app.auth.middleware import SessionAuthMiddleware  # noqa: E402


class PassThrough(BaseHTTPMiddleware):
    """The wrapper alone: what `BaseHTTPMiddleware` costs before any work."""

    async def dispatch(self, request, call_next):
        return await call_next(request)


def application(*, wrapper: bool, session: bool, factory) -> FastAPI:
    app = FastAPI()

    @app.get("/api/whoami")
    async def whoami():
        return {"userId": None}

    @app.get("/assets/index-AbCdEf12.js")
    async def asset():
        return PlainTextResponse("console.log(1)")

    if session:
        app.add_middleware(SessionAuthMiddleware, session_factory=factory)
    if wrapper:
        app.add_middleware(PassThrough)
    return app


def fresh(path: str) -> str:
    """The database file, emptied: one run's accounts are not another's."""
    if os.path.exists(path):
        os.remove(path)
    return path


async def signed_in_database(path: str):
    """A SQLite file with one account and one live session; its cookie."""
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.auth.sessions import cookie_name, create_session
    from app.db.models import Base
    from app.repositories.sqlalchemy import SqlAlchemyUserRepository

    engine = create_async_engine(f"sqlite+aiosqlite:///{fresh(path)}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    account = await SqlAlchemyUserRepository(factory).create_anonymous("Bench")
    issued = await create_session(factory, user_id=account.id, device_label="Benchmark")
    return engine, factory, {cookie_name(): issued.token}


async def cost(app: FastAPI, path: str, requests: int, cookies) -> tuple[float, float]:
    """Per request: microseconds of CPU on the loop's own thread, and of the
    whole process - which here also counts the client driving it."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://bench", cookies=cookies
    ) as http:
        for _ in range(50):
            await http.get(path)
        started_loop, started_all = thread_time(), process_time()
        for _ in range(requests):
            answer = await http.get(path)
            assert answer.status_code == 200, answer.status_code
        return (
            (thread_time() - started_loop) * 1_000_000 / requests,
            (process_time() - started_all) * 1_000_000 / requests,
        )


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--requests", type=int, default=2000)
    parser.add_argument(
        "--database",
        default="",
        help="SQLite file to build the signed-in account in; a temporary one by default",
    )
    arguments = parser.parse_args()

    import app.auth.middleware as middleware_module

    database = arguments.database or os.path.join(
        tempfile.mkdtemp(prefix="sketchy-session-cost-"), "accounts.db"
    )
    engine, factory, cookies = await signed_in_database(database)
    try:
        api = "/api/whoami"
        static = "/assets/index-AbCdEf12.js"
        plain = application(wrapper=False, session=False, factory=factory)
        gated = application(wrapper=False, session=True, factory=factory)
        wrapped = application(wrapper=True, session=True, factory=factory)

        rows = [
            ("nothing in front", await cost(plain, api, arguments.requests, cookies),
             await cost(plain, static, arguments.requests, cookies)),
            ("session middleware", await cost(gated, api, arguments.requests, cookies),
             await cost(gated, static, arguments.requests, cookies)),
        ]
        # The gate off: what every asset paid before this change.
        prefix = middleware_module.SESSION_PATH_PREFIX
        middleware_module.SESSION_PATH_PREFIX = "/"
        try:
            rows.append(
                ("…resolving every path", await cost(gated, api, arguments.requests, cookies),
                 await cost(gated, static, arguments.requests, cookies))
            )
        finally:
            middleware_module.SESSION_PATH_PREFIX = prefix
        rows.append(
            ("…behind a BaseHTTPMiddleware", await cost(wrapped, api, arguments.requests, cookies),
             await cost(wrapped, static, arguments.requests, cookies))
        )

        print(
            f"{'Stack':<30} | {'/api/whoami µs':>15} | {'/assets/… µs':>15}"
            "   (loop thread; process in brackets)"
        )
        print("-" * 68)
        for name, api_cost, static_cost in rows:
            print(
                f"{name:<30} | {api_cost[0]:>8.1f} ({api_cost[1]:>5.0f}) | "
                f"{static_cost[0]:>8.1f} ({static_cost[1]:>5.0f})"
            )
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
