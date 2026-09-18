"""What one reaction costs a popular drawing while its row is locked (#897).

Seeds a public game whose drawing already carries ``--reactions`` reactions
from as many registered accounts, then has ``--samples`` new accounts react
from the Gallery through the repository, one at a time. For each write it
records the time from the drawing's ``FOR UPDATE`` to the commit - how long
every other reaction to that drawing waits behind this one - and the number
of statements and rows fetched inside the transaction.

Runs on SQLite by default (a throwaway in-memory database) or on the
disposable PostgreSQL database in ``TEST_DATABASE_URL``, whose tables are
emptied first.

    backend/.venv/bin/python benchmarks/reaction_write.py --reactions 300 5000
    TEST_DATABASE_URL=postgresql+asyncpg://sketchy:sketchy@127.0.0.1:5433/sketchy_test \\
      backend/.venv/bin/python benchmarks/reaction_write.py --reactions 300 5000
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import sys
from time import perf_counter
from uuid import UUID

BACKEND = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend")
sys.path.insert(0, BACKEND)

from sqlalchemy import event, insert, update  # noqa: E402

from app.db.models import TurnDrawing, TurnDrawingReaction, User, generate_uuid  # noqa: E402
from app.domain_values import OFFERED_REACTION_EMOJI_CODES, REACTION_SET_VERSION  # noqa: E402
from app.repositories.sqlalchemy import (  # noqa: E402
    SqlAlchemyGameHistoryRepository,
    SqlAlchemyUserRepository,
)
from tests.dbfixtures import create_test_db  # noqa: E402
from tests.test_drawing_reactions import record_game, registered  # noqa: E402


async def _seed(factory, turn_id: UUID, game_id: UUID, count: int) -> None:
    emoji = list(OFFERED_REACTION_EMOJI_CODES)
    async with factory() as session, session.begin():
        for start in range(0, count, 1000):
            ids = [generate_uuid() for _ in range(start, min(start + 1000, count))]
            await session.execute(
                insert(User),
                [
                    {
                        "id": user_id,
                        "display_name": f"Fan{start + index}",
                        "username": f"fan{start + index}",
                        "password_hash": "hash",
                        "state": "registered",
                    }
                    for index, user_id in enumerate(ids)
                ],
            )
            await session.execute(
                insert(TurnDrawingReaction),
                [
                    {
                        "id": generate_uuid(),
                        "game_id": game_id,
                        "turn_id": turn_id,
                        "user_id": user_id,
                        "participant_id": None,
                        "emoji": emoji[(start + index) % len(emoji)],
                        "set_version": REACTION_SET_VERSION,
                    }
                    for index, user_id in enumerate(ids)
                ],
            )
        await session.execute(
            update(TurnDrawing).where(TurnDrawing.turn_id == turn_id).values(reaction_count=count)
        )


async def measure(reactions: int, samples: int) -> dict:
    factory, engine = await create_test_db()
    try:
        users = SqlAlchemyUserRepository(factory)
        history = SqlAlchemyGameHistoryRepository(factory)
        drawer = await registered(users, "Drawer")
        sitter = await registered(users, "Sitter")
        recorded = await record_game(history, drawer=drawer.id, reactor=sitter.id, visibility="public")
        turn_id = UUID(recorded.turn_id)
        await _seed(factory, turn_id, UUID(recorded.game_id), reactions)
        reactors = [await registered(users, f"New{index}") for index in range(samples)]

        state: dict = {}

        def before(conn, cursor, statement, parameters, context, executemany):
            if "FOR UPDATE" in statement and "turn_drawings" in statement:
                state["locked"] = perf_counter()
            if "locked" in state:
                state["statements"] = state.get("statements", 0) + 1

        def after(conn, cursor, statement, parameters, context, executemany):
            if "locked" in state and cursor.description is not None:
                state["rows"] = state.get("rows", 0) + max(cursor.rowcount, 0)

        def commit(conn):
            if "locked" in state:
                state["held"] = perf_counter() - state.pop("locked")

        event.listen(engine.sync_engine, "before_cursor_execute", before)
        event.listen(engine.sync_engine, "after_cursor_execute", after)
        event.listen(engine.sync_engine, "commit", commit)
        held, statements, rows = [], [], []
        for index, reactor in enumerate(reactors):
            state.clear()
            result = await history.set_drawing_reaction(
                None, str(turn_id), requesting_user_id=reactor.id,
                emoji=OFFERED_REACTION_EMOJI_CODES[index % len(OFFERED_REACTION_EMOJI_CODES)],
                from_gallery=True,
            )
            assert result is not None
            held.append(state["held"] * 1000)
            statements.append(state.get("statements", 0))
            rows.append(state.get("rows", 0))
        async with factory() as session:
            drawing = await session.get(TurnDrawing, turn_id)
            count = drawing.reaction_count if drawing else None
        held.sort()
        return {
            "existing_reactions": reactions,
            "samples": samples,
            "lock_held_ms_median": round(statistics.median(held), 2),
            "lock_held_ms_p95": round(held[max(0, int(len(held) * 0.95) - 1)], 2),
            "statements_under_lock": max(statements),
            "rows_fetched_under_lock": max(rows),
            "reaction_count_after": count,
            "expected_count": reactions + samples + 0,
        }
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reactions", type=int, nargs="+", default=[300, 5000])
    parser.add_argument("--samples", type=int, default=40)
    args = parser.parse_args()
    results = [asyncio.run(measure(count, args.samples)) for count in args.reactions]
    engine = "postgresql" if os.environ.get("TEST_DATABASE_URL", "").startswith("postgresql") else "sqlite"
    print(json.dumps({"engine": engine, "results": results}, indent=2))


if __name__ == "__main__":
    main()
