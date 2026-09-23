#!/usr/bin/env python3
"""How long finishing a game holds the event loop (#976).

A finished game is staged as one envelope and replayed into history by the
handoff worker (#541). Both ends encode drawings: the envelope deflates every
turn's wire frame, and the replay turns each frame into its stored form before
writing it. On the loop, that work stalls every room's strokes and timers for
as long as it runs. This stages and replays games of eight drawn turns through
the real worker and repositories, with a 1 ms ticker on the loop, and reports
the longest the ticker was kept waiting - for an ordinary drawing and for a
stroke-heavy one, the two shapes the issue measured.

    TEST_DATABASE_URL=postgresql+asyncpg://sketchy:sketchy@127.0.0.1:5433/sketchy_test \\
        backend/.venv/bin/python benchmarks/finish_game_stall.py --games 4
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import sys
from datetime import datetime, timedelta, timezone
from time import perf_counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))
sys.path.insert(0, os.path.join(ROOT, "benchmarks"))

import canvas_history as bench  # noqa: E402
from app.db.models import generate_uuid  # noqa: E402
from app.repositories.interfaces import (  # noqa: E402
    GameParticipantInput,
    GameRecordInput,
    TurnDrawingInput,
    TurnParticipantOutcomeInput,
    TurnRecordInput,
)
from app.repositories.sqlalchemy import (  # noqa: E402
    SqlAlchemyGameHistoryRepository,
    SqlAlchemyUserRepository,
)
from app.services.game_handoff import (  # noqa: E402
    FinishedGameEnvelope,
    FinishedGameHandoffWorker,
    SqlEnvelopeStore,
)
from app.services.game_history import GameHistoryWrite  # noqa: E402
from tests.dbfixtures import create_test_db  # noqa: E402

TURNS = 8
SEATS = 4


def _game(players: list[str], frame: bytes) -> GameHistoryWrite:
    now = datetime.now(timezone.utc)
    seats = [str(generate_uuid()) for _ in players]
    turns, drawings = [], []
    for index in range(TURNS):
        drawer = index % len(players)
        turn_id = str(generate_uuid())
        turns.append(
            TurnRecordInput(
                id=turn_id, round_number=index // SEATS + 1, turn_number=index + 1,
                drawer_user_id=players[drawer], drawer_seat_id=seats[drawer], prompt="cat",
                duration_seconds=40.0, guesser_count=len(players) - 1,
                participant_outcomes=tuple(
                    TurnParticipantOutcomeInput(
                        seat_id=seats[seat], user_id=players[seat], eligible=True,
                        eligibility_reason="eligible", outcome="correct", terminal_state="active",
                        correct_guess_time_seconds=5.0, points_awarded=0,
                    )
                    for seat in range(len(players))
                    if seat != drawer
                ),
            )
        )
        drawings.append(TurnDrawingInput(turn_id=turn_id, payload=frame))
    return GameHistoryWrite(
        record=GameRecordInput(
            id=str(generate_uuid()), room_name="Bench", scoring_mode="default", scoring_version=1,
            score_ledger_version=1, rule_snapshot_version=1, rule_snapshot={"schemaVersion": 1},
            hint_mode="checkpoints", drawing_seconds=90, total_rounds=TURNS // SEATS,
            player_count=len(players), started_at=now, finished_at=now + timedelta(minutes=10),
            visibility="public",
        ),
        participants=[
            GameParticipantInput(user_id=player, final_score=0, final_rank=index + 1,
                                 seat_id=seats[index], display_name=f"P{index}")
            for index, player in enumerate(players)
        ],
        turns=turns, score_events=[], drawings=drawings, reactions=[],
    )


async def _finish(worker, players, frame) -> tuple[float, float]:
    """Stage and replay one game; the loop's longest wait, and the wall time."""
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
    await worker.stage(FinishedGameEnvelope(_game(players, frame)))
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
        players = [(await users.create_anonymous(display_name=f"P{i}")).id for i in range(SEATS)]
        worker = FinishedGameHandoffWorker(
            SqlEnvelopeStore(factory),
            game_history_repo=SqlAlchemyGameHistoryRepository(factory),
            prompt_list_repo=None,
        )
        result = {}
        for name, history in (("realistic", bench.realistic_history), ("stroke_heavy", bench.mixed_history)):
            frame = history().binary_payload()
            samples = [await _finish(worker, players, frame) for _ in range(games)]
            result[name] = {
                "frameBytes": len(frame),
                "worstLoopStallMsMedian": round(statistics.median(s[0] for s in samples), 1),
                "stageAndReplayMsMedian": round(statistics.median(s[1] for s in samples), 1),
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
