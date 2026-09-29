"""What an account export costs the event loop when the owner saved a list many times (#1250).

Every content save of an owned list writes the whole list again as a new
revision, and the export writes every revision's prompts. This seeds one
registered account with a ``--prompts``-prompt list saved ``--saves`` times
through the repository the editor's Save calls (one entry changed each time),
then builds the account's export document the way the worker does and reports:

- the longest wait a 1 ms ticker saw on the loop while the build ran;
- the build's wall and CPU time, and the JSON it wrote (or ``too_large``);
- the peak of Python's own allocations during a second build, under
  ``tracemalloc`` (kept out of the timed build, which it would slow).

Runs on the disposable PostgreSQL database in ``TEST_DATABASE_URL`` (its tables
are emptied first), or in-memory SQLite without one:

    TEST_DATABASE_URL=postgresql+asyncpg://sketchy:sketchy@127.0.0.1:5433/sketchy_test \\
      backend/.venv/bin/python benchmarks/export_list_revisions.py --saves 300
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
import tracemalloc
from datetime import datetime, timezone
from uuid import UUID

BACKEND = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend")
sys.path.insert(0, BACKEND)

from sqlalchemy import insert  # noqa: E402

from app.auth.account_data import (  # noqa: E402
    ExportTooLarge,
    _ExportWriter,
    _write_export_artifact,
    export_max_bytes,
)
from app.db.models import User, generate_uuid  # noqa: E402
from app.repositories.interfaces import PromptListEntryInput  # noqa: E402
from app.repositories.sqlalchemy import SqlAlchemyPromptListRepository  # noqa: E402
from tests.dbfixtures import create_test_db  # noqa: E402


async def seed(factory, args) -> str:
    repo = SqlAlchemyPromptListRepository(factory)
    user_id = generate_uuid()
    async with factory() as session, session.begin():
        await session.execute(insert(User), [{
            "id": user_id, "display_name": "Saver", "username": "Saver",
            "password_hash": "hash", "state": "registered",
        }])
    owner = str(user_id)
    created = await repo.create_owned(
        owner, name="Saved often", description="", language="en",
        prompts=[
            PromptListEntryInput(
                answer=f"prompt{index}",
                aliases=tuple(f"prompt{index}alias{alias}" for alias in range(args.aliases)),
            )
            for index in range(args.prompts)
        ],
    )
    current = await repo.get_owned(owner, created.id)
    for save in range(args.saves - 1):
        rows = [
            PromptListEntryInput(concept_id=entry.concept_id, answer=entry.answer, aliases=entry.aliases)
            for entry in current.prompts
        ]
        rows[save % len(rows)] = PromptListEntryInput(answer=f"changed{save}", aliases=())
        current = await repo.update_owned(
            owner, created.id, expected_version=current.version, name=current.name,
            description=current.description, prompts=rows,
        )
    return owner


async def build(factory, owner: str) -> tuple[str, int]:
    writer = _ExportWriter(max_bytes=export_max_bytes(os.environ))
    try:
        async with factory() as session:
            await _write_export_artifact(
                session, writer, user_id=UUID(owner), generated_at=datetime.now(timezone.utc)
            )
        writer.finish()
        return "ready", writer.written
    except ExportTooLarge:
        return "too_large", writer.written


async def timed(coroutine) -> tuple[object, dict]:
    worst = 0.0
    stop = asyncio.Event()

    async def ticker():
        nonlocal worst
        while not stop.is_set():
            before = time.perf_counter()
            await asyncio.sleep(0.001)
            worst = max(worst, time.perf_counter() - before - 0.001)

    tick = asyncio.create_task(ticker())
    await asyncio.sleep(0.01)
    cpu, wall = time.process_time(), time.perf_counter()
    result = await coroutine
    cpu, wall = time.process_time() - cpu, time.perf_counter() - wall
    stop.set()
    await tick
    return result, {
        "wall_ms": round(wall * 1000, 1),
        "cpu_ms": round(cpu * 1000, 1),
        "worst_loop_wait_ms": round(worst * 1000, 1),
    }


async def run(args) -> dict:
    factory, engine = await create_test_db()
    try:
        started = time.perf_counter()
        owner = await seed(factory, args)
        seeded = time.perf_counter() - started
        (outcome, written), cost = await timed(build(factory, owner))
        tracemalloc.start()
        await build(factory, owner)
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        return {
            "list": f"{args.prompts} prompts x {args.aliases} aliases, saved {args.saves} times",
            "seed_seconds": round(seeded, 1),
            "outcome": outcome,
            "json_mb": round(written / 1e6, 1),
            **cost,
            "python_peak_mb": round(peak / 1e6, 1),
        }
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--prompts", type=int, default=500)
    parser.add_argument("--aliases", type=int, default=0)
    parser.add_argument("--saves", type=int, default=300, help="revisions the list ends with")
    args = parser.parse_args()
    print(json.dumps(asyncio.run(run(args)), indent=2))


if __name__ == "__main__":
    main()
