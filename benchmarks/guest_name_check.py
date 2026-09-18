"""What the guest-name check costs a guest chat line, by how many are online (#900).

Seeds ``--online`` accounts (one in five a guest), opens a presence socket for
each, and times ``online_guest_holding`` for a name nobody holds - the common
case, and the most expensive one, since nothing short-circuits it - two ways:
through the database with every online id (what each guest lobby line, seat
join and rename paid before #900), and from a warm presence identity cache
(what they pay now). Reports the median and p95 of ``--samples`` calls.

Runs on in-memory SQLite by default, or on the disposable PostgreSQL database
in ``TEST_DATABASE_URL``, whose tables are emptied first.

    TEST_DATABASE_URL=postgresql+asyncpg://sketchy:sketchy@127.0.0.1:5433/sketchy_test \\
      backend/.venv/bin/python benchmarks/guest_name_check.py --online 200 1000 3000
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import sys
from time import perf_counter

BACKEND = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend")
sys.path.insert(0, BACKEND)

from sqlalchemy import insert  # noqa: E402

from app.db.models import User, generate_uuid  # noqa: E402
from app.repositories.sqlalchemy import SqlAlchemyUserRepository  # noqa: E402
from app.services.guest_names import online_guest_holding  # noqa: E402
from app.services.presence import (  # noqa: E402
    PresenceIdentity,
    PresenceIdentityCache,
    PresenceRegistry,
)
from tests.dbfixtures import create_test_db  # noqa: E402


def _summary(samples: list[float]) -> dict:
    ordered = sorted(samples)
    return {
        "median_ms": round(statistics.median(ordered) * 1000, 3),
        "p95_ms": round(ordered[max(0, int(len(ordered) * 0.95) - 1)] * 1000, 3),
    }


async def measure(online: int, samples: int) -> dict:
    factory, engine = await create_test_db()
    try:
        repo = SqlAlchemyUserRepository(factory)
        registry = PresenceRegistry()
        identities = PresenceIdentityCache(repo, max_cached=online + 10)
        rows = []
        for index in range(online):
            guest = index % 5 == 0
            rows.append(
                {
                    "id": generate_uuid(),
                    "display_name": f"player{index}",
                    "username": None if guest else f"player{index}",
                    "password_hash": None if guest else "hash",
                    "state": "anonymous" if guest else "registered",
                }
            )
        async with factory() as session, session.begin():
            for start in range(0, online, 1000):
                await session.execute(insert(User), rows[start : start + 1000])
        for row in rows:
            user_id = str(row["id"])
            registry.note_socket_opened(f"sid-{user_id}", user_id)
            identities.remember(
                PresenceIdentity(
                    user_id=user_id,
                    display_name=row["display_name"],
                    name_color=None,
                    is_anonymous=row["state"] == "anonymous",
                    avatar_key=None,
                )
            )

        async def timed(cache) -> list[float]:
            spent = []
            for _ in range(samples):
                started = perf_counter()
                held = await online_guest_holding(
                    "nobody-has-this",
                    claimant_id=None,
                    registry=registry,
                    user_repo=repo,
                    choosing=True,
                    identities=cache,
                )
                spent.append(perf_counter() - started)
                assert held is None
            return spent

        await timed(None)  # warm the connection and the statement cache
        return {
            "online": online,
            "database": _summary(await timed(None)),
            "warm_cache": _summary(await timed(identities)),
        }
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--online", type=int, nargs="+", default=[200, 1000, 3000])
    parser.add_argument("--samples", type=int, default=50)
    args = parser.parse_args()
    engine = "postgresql" if os.environ.get("TEST_DATABASE_URL", "").startswith("postgresql") else "sqlite"
    results = [asyncio.run(measure(count, args.samples)) for count in args.online]
    print(json.dumps({"engine": engine, "results": results}, indent=2))


if __name__ == "__main__":
    main()
