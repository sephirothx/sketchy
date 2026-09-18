"""What one page of the community catalogue's star order costs (#901).

Seeds ``--lists`` published lists across ``--owners`` accounts and
``--stars`` stars (each fan stars a spread of lists), then times
``list_community(sort="stars")`` for the first and a deeper page, uncached
(every page ranks every published list, as before #901) and from a warm
ranking (what a page costs within the TTL). ``newest`` is timed for
reference: it walks ``ix_prompt_lists_published`` and never counted stars.

Runs on in-memory SQLite by default, or on the disposable PostgreSQL database
in ``TEST_DATABASE_URL``, whose tables are emptied first.

    TEST_DATABASE_URL=postgresql+asyncpg://sketchy:sketchy@127.0.0.1:5433/sketchy_test \\
      backend/.venv/bin/python benchmarks/catalogue_star_page.py --lists 5000 --stars 120000
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timedelta, timezone
import json
import os
import statistics
import sys
from time import perf_counter

BACKEND = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend")
sys.path.insert(0, BACKEND)

from sqlalchemy import insert, text  # noqa: E402

from app.db.models import PromptList, PromptListStar, User, generate_uuid  # noqa: E402
from app.repositories.sqlalchemy import SqlAlchemyPromptListRepository  # noqa: E402
from tests.dbfixtures import create_test_db  # noqa: E402


async def _seed(factory, lists: int, owners: int, stars: int) -> None:
    now = datetime.now(timezone.utc)
    owner_ids = [generate_uuid() for _ in range(owners)]
    list_ids = [generate_uuid() for _ in range(lists)]
    fans = max(1, stars // max(1, min(lists, 60)))
    fan_ids = [generate_uuid() for _ in range(fans)]
    async with factory() as session, session.begin():
        users = [
            {"id": user_id, "display_name": f"U{index}", "username": f"u{index}",
             "password_hash": "hash", "state": "registered"}
            for index, user_id in enumerate(owner_ids + fan_ids)
        ]
        for start in range(0, len(users), 2000):
            await session.execute(insert(User), users[start : start + 2000])
        rows = [
            {"id": list_id, "owner_user_id": owner_ids[index % owners], "slug": f"user-{list_id}",
             "name": f"List {index}", "description": "", "language": "en", "is_bundled": False,
             "visibility": "public", "moderation_state": "active", "version": 1,
             "published_at": now - timedelta(minutes=index)}
            for index, list_id in enumerate(list_ids)
        ]
        for start in range(0, len(rows), 2000):
            await session.execute(insert(PromptList), rows[start : start + 2000])
        given = []
        per_fan = max(1, stars // fans)
        for index, fan in enumerate(fan_ids):
            # Skewed: early lists collect more, as popular lists do.
            for offset in range(per_fan):
                given.append({"user_id": fan, "prompt_list_id": list_ids[(index * 7 + offset * offset) % lists]})
        unique = {(row["user_id"], row["prompt_list_id"]): row for row in given}
        rows = list(unique.values())[:stars]
        for start in range(0, len(rows), 5000):
            await session.execute(insert(PromptListStar), rows[start : start + 5000])
    async with factory() as session:
        await session.execute(text("ANALYZE"))
        await session.commit()


async def _time(repo, samples: int, **kwargs) -> dict:
    spent = []
    for _ in range(samples):
        started = perf_counter()
        await repo.list_community(**kwargs)
        spent.append(perf_counter() - started)
    spent.sort()
    return {
        "median_ms": round(statistics.median(spent) * 1000, 2),
        "p95_ms": round(spent[max(0, int(len(spent) * 0.95) - 1)] * 1000, 2),
    }


async def run(lists: int, owners: int, stars: int, samples: int) -> dict:
    factory, engine = await create_test_db()
    try:
        await _seed(factory, lists, owners, stars)
        uncached = SqlAlchemyPromptListRepository(factory)
        cached = SqlAlchemyPromptListRepository(factory, catalogue_ranking_ttl_seconds=3600)
        deep = {"cursor": None}
        page = await uncached.list_community(limit=24)
        for _ in range(3):
            page = await uncached.list_community(limit=24, cursor=page.next_cursor)
        deep["cursor"] = page.next_cursor
        await cached.list_community(limit=24)  # the one ranking read
        async with factory() as session:
            counted = await session.scalar(text("SELECT count(*) FROM prompt_list_stars"))
        return {
            "published_lists": lists,
            "stars": int(counted),
            "stars_first_page_uncached": await _time(uncached, samples, limit=24),
            "stars_fifth_page_uncached": await _time(uncached, samples, limit=24, cursor=deep["cursor"]),
            "stars_first_page_warm": await _time(cached, samples, limit=24),
            "stars_fifth_page_warm": await _time(cached, samples, limit=24, cursor=deep["cursor"]),
            "newest_first_page": await _time(uncached, samples, limit=24, sort="newest"),
        }
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lists", type=int, default=5000)
    parser.add_argument("--owners", type=int, default=500)
    parser.add_argument("--stars", type=int, default=120000)
    parser.add_argument("--samples", type=int, default=30)
    args = parser.parse_args()
    engine = "postgresql" if os.environ.get("TEST_DATABASE_URL", "").startswith("postgresql") else "sqlite"
    result = asyncio.run(run(args.lists, args.owners, args.stars, args.samples))
    print(json.dumps({"engine": engine, **result}, indent=2))


if __name__ == "__main__":
    main()
