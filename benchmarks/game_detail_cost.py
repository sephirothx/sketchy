#!/usr/bin/env python3
"""What one game-detail request costs the event loop (#1254).

`GET /api/games/{id}` is the profile page's round-by-round view, open to every
participant at 120 requests a minute. This records one scored game of
``--seats`` seats and ``--rounds`` rounds - every guesser right every turn,
three prompts offered per turn - and fetches its detail ``--requests`` times
through the real router, reporting the median CPU time and wall time per
request (one worker, one thread: CPU time is the loop's) and the size of the
response.

    TEST_DATABASE_URL=postgresql+asyncpg://sketchy:sketchy@127.0.0.1:5433/sketchy_test \\
        backend/.venv/bin/python benchmarks/game_detail_cost.py --seats 16 --rounds 10
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import sys
from dataclasses import replace
from time import perf_counter, process_time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))
sys.path.insert(0, os.path.join(ROOT, "benchmarks"))

from fastapi import FastAPI, Request  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

from app.api.profiles import create_profile_router  # noqa: E402
from app.repositories.interfaces import PromptOfferInput  # noqa: E402
from app.repositories.sqlalchemy import (  # noqa: E402
    SqlAlchemyGameHistoryRepository,
    SqlAlchemyUserRepository,
)
from integrity_audit_stall import scored_game  # noqa: E402
from tests.dbfixtures import create_test_db  # noqa: E402


async def run(args) -> dict:
    factory, engine = await create_test_db()
    try:
        users = SqlAlchemyUserRepository(factory)
        history = SqlAlchemyGameHistoryRepository(factory)
        players = [str((await users.create_anonymous(display_name=f"P{i}")).id) for i in range(args.seats)]
        game = scored_game(players, args.rounds)
        game["turns"] = [
            replace(turn, prompt_offers=tuple(
                PromptOfferInput(position=position, prompt=prompt, selected=prompt == "cat", source_kind="custom")
                for position, prompt in enumerate(("cat", "lantern", "harbour"))
            ))
            for turn in game["turns"]
        ]
        game_id = await history.save_game(**game)

        app = FastAPI()

        @app.middleware("http")
        async def signed_in(request: Request, call_next):
            request.state.user_id = players[0]
            return await call_next(request)

        app.include_router(create_profile_router(users, history))
        cpu, wall, size = [], [], 0
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://bench") as http:
            for _ in range(args.requests):
                started_cpu, started = process_time(), perf_counter()
                response = await http.get(f"/api/games/{game_id}")
                cpu.append((process_time() - started_cpu) * 1000)
                wall.append((perf_counter() - started) * 1000)
                assert response.status_code == 200, response.text
                size = len(response.content)
        return {
            "game": f"{args.seats} seats x {args.rounds} rounds, {len(game['turns'])} turns",
            "response_kb": round(size / 1024, 1),
            "cpu_ms_median": round(statistics.median(cpu), 1),
            "wall_ms_median": round(statistics.median(wall), 1),
        }
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--seats", type=int, default=16)
    parser.add_argument("--rounds", type=int, default=10)
    parser.add_argument("--requests", type=int, default=15)
    args = parser.parse_args()
    print(json.dumps(asyncio.run(run(args)), indent=2))


if __name__ == "__main__":
    main()
