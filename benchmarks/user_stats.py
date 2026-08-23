#!/usr/bin/env python3
"""Compare full-history profile aggregates with the daily projection read.

Usage:
  backend/.venv/bin/python benchmarks/user_stats.py --games 10000 --reads 100
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timedelta, timezone
import json
import os
import statistics
import sys
import time

from sqlalchemy import and_, case, distinct, func, insert, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND_DIR = os.path.join(ROOT_DIR, "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from app.db.models import (  # noqa: E402
    Base,
    GameParticipant,
    GameRecord,
    TurnGuess,
    TurnRecord,
    User,
    generate_uuid,
)
from app.repositories.sqlalchemy import SqlAlchemyUserRepository  # noqa: E402
from app.services.user_stats_projection import (  # noqa: E402
    rebuild_user_stats_projection,
)


async def legacy_read(factory, user_id) -> None:
    """The pre-#370 four full-history aggregate queries."""
    async with factory() as session:
        await session.execute(
            select(
                func.count(distinct(GameParticipant.game_id)),
                func.count(
                    distinct(
                        case(
                            (GameParticipant.final_rank == 1, GameParticipant.game_id),
                            else_=None,
                        )
                    )
                ),
                func.coalesce(func.sum(GameParticipant.final_score), 0),
            ).where(GameParticipant.user_id == user_id)
        )
        await session.execute(
            select(func.count(distinct(TurnRecord.id)))
            .select_from(TurnRecord)
            .join(
                GameParticipant,
                and_(
                    GameParticipant.game_id == TurnRecord.game_id,
                    GameParticipant.user_id == user_id,
                ),
            )
        )
        await session.execute(
            select(func.count(TurnGuess.id)).where(TurnGuess.user_id == user_id)
        )
        await session.execute(
            select(func.count(TurnRecord.id)).where(
                TurnRecord.drawer_user_id == user_id
            )
        )


async def timed(operation, reads: int) -> list[float]:
    samples = []
    for _ in range(reads):
        started = time.perf_counter()
        await operation()
        samples.append((time.perf_counter() - started) * 1000)
    return samples


async def run(games: int, reads: int) -> dict:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    user_id = generate_uuid()
    start = datetime(2020, 1, 1, tzinfo=timezone.utc)
    game_rows = []
    participant_rows = []
    turn_rows = []
    for index in range(games):
        game_id = generate_uuid()
        turn_id = generate_uuid()
        finished_at = start + timedelta(days=index % 365, minutes=index)
        game_rows.append(
            {
                "id": game_id,
                "payload_hash": f"benchmark-{index}",
                "room_name": "Benchmark",
                "scoring_mode": "default",
                "hint_mode": "none",
                "drawing_seconds": 90,
                "total_rounds": 1,
                "player_count": 1,
                "started_at": finished_at - timedelta(minutes=1),
                "finished_at": finished_at,
            }
        )
        participant_rows.append(
            {
                "id": generate_uuid(),
                "game_id": game_id,
                "user_id": user_id,
                "display_name_snapshot": "Benchmark player",
                "is_anonymous_snapshot": True,
                "final_score": index % 301,
                "final_rank": 1 if index % 4 == 0 else 2,
            }
        )
        turn_rows.append(
            {
                "id": turn_id,
                "game_id": game_id,
                "round_number": 1,
                "turn_number": 1,
                "drawer_user_id": user_id,
                "drawer_participant_id": participant_rows[-1]["id"],
                "drawer_display_name_snapshot": "Benchmark player",
                "drawer_is_anonymous_snapshot": True,
                "prompt": "anchor",
                "duration_seconds": 30,
            }
        )

    async with factory() as session:
        async with session.begin():
            session.add(User(id=user_id, display_name="Benchmark player"))
            await session.execute(insert(GameRecord), game_rows)
            await session.execute(insert(GameParticipant), participant_rows)
            await session.execute(insert(TurnRecord), turn_rows)
    projection_rows = await rebuild_user_stats_projection(factory)
    users = SqlAlchemyUserRepository(factory)

    await legacy_read(factory, user_id)
    await users.get_stats(str(user_id))
    legacy_samples = await timed(lambda: legacy_read(factory, user_id), reads)
    projection_samples = await timed(
        lambda: users.get_stats(str(user_id)), reads
    )
    result = {
        "games": games,
        "turns": games,
        "projectionRows": projection_rows,
        "reads": reads,
        "legacyMedianMs": round(statistics.median(legacy_samples), 3),
        "projectionMedianMs": round(statistics.median(projection_samples), 3),
    }
    result["medianSpeedup"] = round(
        result["legacyMedianMs"] / max(result["projectionMedianMs"], 0.001), 2
    )
    await engine.dispose()
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--games", type=int, default=10_000)
    parser.add_argument("--reads", type=int, default=100)
    parser.add_argument("--json-output")
    args = parser.parse_args()
    if args.games < 1 or args.reads < 1:
        parser.error("--games and --reads must be positive")
    result = asyncio.run(run(args.games, args.reads))
    encoded = json.dumps(result, indent=2, sort_keys=True)
    print(encoded)
    if args.json_output:
        with open(args.json_output, "w", encoding="utf-8") as output:
            output.write(encoded + "\n")


if __name__ == "__main__":
    main()
