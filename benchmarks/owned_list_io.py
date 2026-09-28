"""What reading and saving one of a player's own prompt lists costs the event loop (#1236).

Seeds one registered account with a list at the ceiling - ``--prompts`` prompts
of ``--aliases`` aliases each - and measures, through the repository the REST
routes call:

- ``get``: `get_owned`, the editor opening the list;
- ``put``: `update_owned` with one entry changed, the editor's Save;
- ``create``: `create_owned` of a list that size;
- ``burst``: ``--burst`` saves of the list at once from the same account, with a
  pooled ``SELECT 1`` issued in the middle - how long an unrelated request
  waits for a connection while they run.

For each: the SQL statements issued, the process CPU time (one worker, one
thread: the loop's), the wall time, and the worst wait a 1 ms ticker saw on the
loop meanwhile.

Runs on the disposable PostgreSQL database in ``TEST_DATABASE_URL`` (its tables
are emptied first), or in-memory SQLite without one:

    TEST_DATABASE_URL=postgresql+asyncpg://sketchy:sketchy@127.0.0.1:5433/sketchy_test \\
      backend/.venv/bin/python benchmarks/owned_list_io.py
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time

BACKEND = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend")
sys.path.insert(0, BACKEND)

from sqlalchemy import event, insert, text  # noqa: E402

from app.db.models import User, generate_uuid  # noqa: E402
from app.repositories.interfaces import PromptListEntryInput  # noqa: E402
from app.repositories.sqlalchemy import SqlAlchemyPromptListRepository  # noqa: E402
from tests.dbfixtures import create_test_db  # noqa: E402


class Probe:
    """Statements issued and the loop's worst wait, over one `with` block."""

    def __init__(self, engine) -> None:
        self.statements = 0
        event.listen(engine.sync_engine, "before_cursor_execute", self._count)

    def _count(self, *_args, **_kwargs) -> None:
        self.statements += 1

    async def measure(self, coroutine) -> tuple[object, dict]:
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
        statements = self.statements
        cpu, wall = time.process_time(), time.perf_counter()
        result = await coroutine
        cpu, wall = time.process_time() - cpu, time.perf_counter() - wall
        stop.set()
        await tick
        return result, {
            "statements": self.statements - statements,
            "cpu_ms": round(cpu * 1000, 1),
            "wall_ms": round(wall * 1000, 1),
            "worst_loop_wait_ms": round(worst * 1000, 1),
        }


def entries(prompts: int, aliases: int, salt: str = "") -> list[PromptListEntryInput]:
    return [
        PromptListEntryInput(
            answer=f"prompt{salt}{index}",
            aliases=tuple(f"prompt{salt}{index}alias{alias}" for alias in range(aliases)),
        )
        for index in range(prompts)
    ]


async def run(args) -> dict:
    factory, engine = await create_test_db()
    probe = Probe(engine)
    try:
        repo = SqlAlchemyPromptListRepository(factory)
        user_id = generate_uuid()
        async with factory() as session, session.begin():
            await session.execute(insert(User), [{
                "id": user_id, "display_name": "Lister", "username": "Lister",
                "password_hash": "hash", "state": "registered",
            }])
        owner = str(user_id)
        created, create_cost = await probe.measure(repo.create_owned(
            owner, name="Big list", description="", language=args.language,
            prompts=entries(args.prompts, args.aliases),
        ))
        _, get_cost = await probe.measure(repo.get_owned(owner, created.id))

        def edited(current, salt):
            changed = list(current.prompts)
            first = changed[0]
            rows = [
                PromptListEntryInput(concept_id=entry.concept_id, answer=entry.answer, aliases=entry.aliases)
                for entry in changed
            ]
            rows[0] = PromptListEntryInput(concept_id=first.concept_id, answer=f"changed{salt}", aliases=first.aliases)
            return rows

        current = await repo.get_owned(owner, created.id)
        updated, put_cost = await probe.measure(repo.update_owned(
            owner, created.id, expected_version=current.version, name=current.name,
            description=current.description, prompts=edited(current, "a"),
        ))

        # The burst: every save racing for the list's row lock, and a request
        # that needs nothing but a connection, sent a moment in.
        current = await repo.get_owned(owner, created.id)

        async def save(index):
            try:
                await repo.update_owned(
                    owner, created.id, expected_version=current.version, name=current.name,
                    description=current.description, prompts=edited(current, f"b{index}"),
                )
                return "saved"
            except Exception as error:  # a version conflict, for all but one
                return type(error).__name__

        async def pooled_read():
            await asyncio.sleep(0.05)
            started = time.perf_counter()
            async with factory() as session:
                await session.execute(text("SELECT 1"))
            return round((time.perf_counter() - started) * 1000, 1)

        async def burst():
            return await asyncio.gather(pooled_read(), *(save(index) for index in range(args.burst)))

        results, burst_cost = await probe.measure(burst())
        outcomes = {}
        for outcome in results[1:]:
            outcomes[outcome] = outcomes.get(outcome, 0) + 1
        return {
            "list": f"{args.prompts} x {args.aliases} aliases, {args.language}",
            "create": create_cost,
            "get": get_cost,
            "put_one_entry": put_cost,
            "burst": {**burst_cost, "saves": args.burst, "outcomes": outcomes, "pooled_select_wait_ms": results[0]},
        }
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--prompts", type=int, default=500)
    parser.add_argument("--aliases", type=int, default=20)
    parser.add_argument("--language", default="en")
    parser.add_argument("--burst", type=int, default=10)
    args = parser.parse_args()
    print(json.dumps(asyncio.run(run(args)), indent=2))


if __name__ == "__main__":
    main()
