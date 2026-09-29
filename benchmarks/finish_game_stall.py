#!/usr/bin/env python3
"""How long finishing a game holds the event loop (#976).

A finished game is staged as one envelope and replayed into history by the
handoff worker (#541). Both ends encode drawings: the envelope deflates every
turn's wire frame, and the replay turns each frame into its stored form before
writing it. On the loop, that work stalls every room's strokes and timers for
as long as it runs. This stages and replays scored games - a guess award for
every guesser and a drawer bonus every turn, as the scorer writes them -
through the real worker and repositories, with a 1 ms ticker on the loop, and
reports the longest the ticker was kept waiting. Three shapes: four seats and
two rounds with an ordinary drawing and with a stroke-heavy one, the two the
issue measured, and the largest room there is, sixteen seats and ten rounds:
160 turns, 2,400 guesser outcomes and 2,560 score events, which is where the
rows the replay writes cost more than its drawings (#1260). Per shape it also
reports the envelope as staged, the envelope encode's time, and on PostgreSQL
the WAL a whole finished game writes - staging, replay and the envelope's
deletion - which is what WAL archiving and backups have to be sized on (#1259).

    TEST_DATABASE_URL=postgresql+asyncpg://sketchy:sketchy@127.0.0.1:5433/sketchy_test \\
        backend/.venv/bin/python benchmarks/finish_game_stall.py --games 4
"""
from __future__ import annotations

import argparse
import asyncio
import functools
import json
import os
import statistics
import sys
from datetime import datetime, timedelta, timezone
from time import perf_counter
from uuid import UUID

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))
sys.path.insert(0, os.path.join(ROOT, "benchmarks"))

import canvas_history as bench  # noqa: E402
from app.db.models import generate_uuid  # noqa: E402
from app.repositories.interfaces import TurnDrawingInput  # noqa: E402
from app.repositories.sqlalchemy import (  # noqa: E402
    SqlAlchemyGameHistoryRepository,
    SqlAlchemyUserRepository,
)
from sqlalchemy import select, text  # noqa: E402

from app.db.models import FinishedGameEnvelope as EnvelopeRow  # noqa: E402
from app.services.game_handoff import (  # noqa: E402
    FinishedGameEnvelope,
    FinishedGameHandoffWorker,
    SqlEnvelopeStore,
    encode_envelope,
)
from app.services.game_history import GameHistoryWrite  # noqa: E402
from integrity_audit_stall import scored_game  # noqa: E402
from tests.dbfixtures import create_test_db  # noqa: E402

MAX_SEATS = 16

# name, seats, rounds, and the frame every turn draws (None: each its own
# realistic drawing).
SHAPES = (
    ("realistic", 4, 2, None),
    ("stroke_heavy", 4, 2, "stroke_heavy"),
    ("max_room", MAX_SEATS, 10, None),
)


@functools.cache
def _realistic(turn: int) -> bytes:
    """`canvas_history.realistic_history`, drawn differently for each turn.

    A game repeating one drawing would flatter the envelope: identical stored
    drawings deduplicate inside its deflate window, which no real game gets
    to do (#1259). The same strokes, shapes and fills, at other places and in
    other colours.
    """
    from app.canvas_history import PackedCanvasHistory

    history = PackedCanvasHistory()
    bench._append_grid(history, 200)
    for index in range(600):
        x = ((index * 37 + turn * 211) % 780) / 800
        y = ((index * 53 + turn * 97) % 580) / 600
        points = [(x, y)]
        for step in range(1, 12):
            points.append((
                min(0.99, x + ((index + step * 7 + turn) % 13) / 800),
                min(0.99, y + ((index + step * 5 + turn) % 11) / 600),
            ))
        history.append_path(points, color=(index * 977 + turn * 7919) & 0xFFFFFF, width=(index + turn) % 8 + 2)
    for index in range(12):
        history.append_fill(
            x=(index % 4) * 200 + 100, y=(index // 4) * 200 + 100, color=(index * 654_319 + turn) & 0xFFFFFF,
        )
    return history.binary_payload()


def _game(players: list[str], rounds: int, frame: bytes | None) -> GameHistoryWrite:
    """A scored game of `rounds` rounds; `frame` for every turn's drawing, or
    None for a realistic drawing of each turn's own."""
    game = scored_game(players, rounds)
    return GameHistoryWrite(
        record=game["game_record"],
        participants=game["participants"],
        turns=game["turns"],
        score_events=game["score_events"],
        drawings=[
            TurnDrawingInput(turn_id=turn.id, payload=frame if frame is not None else _realistic(index))
            for index, turn in enumerate(game["turns"])
        ],
        reactions=[],
    )


def _lsn_bytes(lsn: str) -> int:
    high, low = lsn.split("/")
    return (int(high, 16) << 32) + int(low, 16)


async def _wal_lsn(factory) -> int | None:
    async with factory() as session:
        if session.bind.dialect.name != "postgresql":
            return None
        return _lsn_bytes(await session.scalar(text("SELECT pg_current_wal_insert_lsn()::text")))


async def _wal_since(factory, lsn: int | None) -> int | None:
    if lsn is None:
        return None
    return (await _wal_lsn(factory)) - lsn


async def _finish(worker, game: GameHistoryWrite) -> tuple[float, float]:
    """Stage and replay one game; the loop's longest wait, and the wall time.

    The game is built before the ticker starts: drawing its turns is the
    benchmark's work, not the server's."""
    waits: list[float] = []
    done = False

    async def ticker() -> None:
        while not done:
            started = perf_counter()
            await asyncio.sleep(0.001)
            waits.append((perf_counter() - started - 0.001) * 1000)

    tick = asyncio.create_task(ticker())
    await asyncio.sleep(0.01)
    started = perf_counter()
    await worker.stage(FinishedGameEnvelope(game))
    report = await worker.drain()
    elapsed = (perf_counter() - started) * 1000
    done = True
    await tick
    if report.recorded != 1:
        raise SystemExit(f"the game was not recorded: {report}")
    return max(waits), elapsed


async def run(games: int) -> dict:
    factory, engine = await create_test_db()
    try:
        users = SqlAlchemyUserRepository(factory)
        players = [(await users.create_anonymous(display_name=f"P{i}")).id for i in range(MAX_SEATS)]
        worker = FinishedGameHandoffWorker(
            SqlEnvelopeStore(factory),
            game_history_repo=SqlAlchemyGameHistoryRepository(factory),
            prompt_list_repo=None,
        )
        result = {}
        # Realistic drawings differ turn to turn; the stroke-heavy frame is
        # far past the deflate window, so repeating it flatters nothing.
        stroke_heavy = bench.mixed_history().binary_payload()
        for name, seats, rounds, drawn in SHAPES:
            frame = stroke_heavy if drawn == "stroke_heavy" else None
            samples = [await _finish(worker, _game(players[:seats], rounds, frame)) for _ in range(games)]
            # One more, staged alone first to read its envelope, then replayed.
            game = _game(players[:seats], rounds, frame)
            encode_started = perf_counter()
            encode_envelope(FinishedGameEnvelope(game))
            encode_ms = (perf_counter() - encode_started) * 1000
            lsn = await _wal_lsn(factory)
            await worker.stage(FinishedGameEnvelope(game))
            async with factory() as session:
                envelope_bytes = await session.scalar(
                    select(EnvelopeRow.byte_size).where(EnvelopeRow.game_id == UUID(game.record.id))
                )
            await worker.drain()
            wal = await _wal_since(factory, lsn)
            result[name] = {
                "turns": len(game.turns),
                "outcomes": sum(len(turn.participant_outcomes) for turn in game.turns),
                "scoreEvents": len(game.score_events),
                "frameBytes": len(frame if frame is not None else _realistic(0)),
                "worstLoopStallMsMedian": round(statistics.median(s[0] for s in samples), 1),
                "stageAndReplayMsMedian": round(statistics.median(s[1] for s in samples), 1),
                "envelopeKB": round((envelope_bytes or 0) / 1024, 1),
                "envelopeEncodeMs": round(encode_ms, 1),
                "walKBPerGame": None if wal is None else round(wal / 1024, 1),
            }
        return result
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--games", type=int, default=4, help="games finished per drawing shape")
    args = parser.parse_args()
    print(json.dumps(asyncio.run(run(args.games)), indent=2))


if __name__ == "__main__":
    main()
