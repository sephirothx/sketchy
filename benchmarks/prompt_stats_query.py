"""What the public Prompt stats read costs as usage facts pile up (#1424).

Facts are kept forever (R-PRIV-05), and the read aggregates every fact a
bundled list has ever had. Seeds the English Standard list and ``--facts``
usage facts spread over two years, then times the read for all time and the
last 30 days, three ways:

- ``joined``: the read as it was before #1424 - every fact joined to its
  prompt version, then grouped by concept;
- ``by version``: facts summed per version first, and only those few
  thousand rows joined and grouped by concept;
- the repository's read, once and then within its TTL, which runs no
  aggregate.

For each, the median wall time and, from ``EXPLAIN (ANALYZE, BUFFERS)``, the
temp blocks a sort spilled. ``work_mem`` is set to ``--work-mem`` (the
issue measured at 8MB).

Measured 2026-10-11, PostgreSQL 17, 2.1M facts, 8MB: all time 118.6 ms
joined, 88.6 ms by version; 30 days 52.8 ms and 56.1 ms (the window's index
scan dominates); no temp spill either way on this data - the issue's 85 MB
spill came from a GroupAggregate plan this planner did not choose here. A
read within the TTL is a dictionary lookup.

PostgreSQL only: it measures PostgreSQL's plan. The disposable database in
``TEST_DATABASE_URL`` has its tables emptied first.

    TEST_DATABASE_URL=postgresql+asyncpg://sketchy:sketchy@127.0.0.1:5433/sketchy_test \\
      backend/.venv/bin/python benchmarks/prompt_stats_query.py --facts 2100000
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
import shutil
import statistics
import sys
import tempfile
from time import perf_counter

BACKEND = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend")
sys.path.insert(0, BACKEND)

from sqlalchemy import text  # noqa: E402

from app.db.seed import DEFAULT_PROMPT_LISTS_DIR, seed_prompt_lists  # noqa: E402
from app.domain_values import HINT_MODES, SCORING_MODES  # noqa: E402
from app.repositories.sqlalchemy import SqlAlchemyPromptListRepository  # noqa: E402
from tests.dbfixtures import create_test_db  # noqa: E402

SLUG_FILE = "english_standard.json"

JOINED = """
SELECT v.concept_id, sum(f.offer_count), sum(f.pick_count),
       sum(f.correct_guess_count), sum(f.total_guesser_count)
FROM prompt_versions v
JOIN prompt_usage_facts f ON f.prompt_version_id = v.id
WHERE f.prompt_list_id = :list_id {window}
GROUP BY v.concept_id
"""

BY_VERSION = """
SELECT v.concept_id, sum(t.offers), sum(t.picks), sum(t.correct), sum(t.guessers)
FROM (
  SELECT f.prompt_version_id, sum(f.offer_count) AS offers, sum(f.pick_count) AS picks,
         sum(f.correct_guess_count) AS correct, sum(f.total_guesser_count) AS guessers
  FROM prompt_usage_facts f
  WHERE f.prompt_list_id = :list_id {window}
  GROUP BY f.prompt_version_id
) t
JOIN prompt_versions v ON v.id = t.prompt_version_id
GROUP BY v.concept_id
"""


async def _seed(factory, repo, facts: int) -> tuple[str, str]:
    with tempfile.TemporaryDirectory() as directory:
        shutil.copy(DEFAULT_PROMPT_LISTS_DIR / SLUG_FILE, Path(directory) / SLUG_FILE)
        [summary] = await seed_prompt_lists(repo, Path(directory))
    async with factory() as session, session.begin():
        list_id = await session.scalar(text("SELECT id FROM prompt_lists WHERE slug = :slug"), {"slug": summary.slug})
        versions = await session.scalar(
            text("SELECT count(*) FROM prompts p JOIN prompt_versions v ON v.concept_id = p.concept_id WHERE p.prompt_list_id = :id"),
            {"id": list_id},
        )
        per_version = max(1, facts // max(1, versions))
        await session.execute(
            text("""
                INSERT INTO prompt_usage_facts (id, batch_id, prompt_list_id, prompt_version_id, occurred_at,
                    scoring_mode, hint_mode, offer_count, pick_count, correct_guess_count,
                    total_guesser_count, created_at)
                SELECT gen_random_uuid(), gen_random_uuid(), :list_id, v.id,
                       now() - random() * interval '730 days',
                       (CAST(:scoring AS text[]))[1 + floor(random() * cardinality(CAST(:scoring AS text[])))::int],
                       (CAST(:hints AS text[]))[1 + floor(random() * cardinality(CAST(:hints AS text[])))::int],
                       1, (random() < 0.33)::int, floor(random() * 5)::int, 4, now()
                FROM prompts p
                JOIN prompt_versions v ON v.concept_id = p.concept_id
                CROSS JOIN generate_series(1, :per_version)
                WHERE p.prompt_list_id = :list_id
            """),
            {"list_id": list_id, "per_version": per_version, "scoring": list(SCORING_MODES), "hints": list(HINT_MODES)},
        )
    async with factory() as session:
        await session.execute(text("ANALYZE prompt_usage_facts"))
        await session.commit()
    return str(list_id), summary.slug


async def _timed(factory, sql: str, list_id: str, window: str, samples: int, work_mem: str) -> dict:
    statement = text(sql.format(window=window))
    times = []
    async with factory() as session:
        await session.execute(text(f"SET work_mem = '{work_mem}'"))
        for _ in range(samples):
            started = perf_counter()
            await session.execute(statement, {"list_id": list_id})
            times.append((perf_counter() - started) * 1000)
        plan = (await session.execute(text("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + sql.format(window=window)), {"list_id": list_id})).scalar()
    plan = plan[0] if isinstance(plan, list) else json.loads(plan)[0]
    root = plan["Plan"]
    return {
        "median_ms": round(statistics.median(times), 1),
        "temp_written_blocks": root.get("Temp Written Blocks", 0) + _temp(root),
        "shared_read_blocks": root.get("Shared Read Blocks", 0),
    }


def _temp(node: dict) -> int:
    return sum(child.get("Temp Written Blocks", 0) + _temp(child) for child in node.get("Plans", []))


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--facts", type=int, default=200_000)
    parser.add_argument("--samples", type=int, default=5)
    parser.add_argument("--work-mem", default="8MB")
    args = parser.parse_args()
    url = os.environ.get("TEST_DATABASE_URL", "")
    if not url.startswith("postgresql"):
        print("prompt_stats_query measures PostgreSQL; set TEST_DATABASE_URL")
        return
    factory, engine = await create_test_db()
    try:
        repo = SqlAlchemyPromptListRepository(factory)
        list_id, slug = await _seed(factory, repo, args.facts)
        async with factory() as session:
            total = await session.scalar(text("SELECT count(*) FROM prompt_usage_facts"))
        results = {"facts": total, "work_mem": args.work_mem}
        for label, window in (("all", ""), ("30d", "AND f.occurred_at >= now() - interval '30 days'")):
            for name, sql in (("joined", JOINED), ("by_version", BY_VERSION)):
                results[f"{label} {name}"] = await _timed(factory, sql, list_id, window, args.samples, args.work_mem)
        # The repository's read: one aggregate, then served from the cache
        # within its TTL (the application's PROMPT_STATS_TTL_SECONDS).
        cached = SqlAlchemyPromptListRepository(factory, prompt_stats_ttl_seconds=300)
        started = perf_counter()
        await cached.get_prompt_stats(slug)
        results["all repository, first read"] = {"ms": round((perf_counter() - started) * 1000, 1)}
        times = []
        for _ in range(args.samples):
            started = perf_counter()
            await cached.get_prompt_stats(slug)
            times.append((perf_counter() - started) * 1000)
        results["all repository, within the TTL"] = {"median_ms": round(statistics.median(times), 3)}
        print(json.dumps(results, indent=2))
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
