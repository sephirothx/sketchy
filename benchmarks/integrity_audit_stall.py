#!/usr/bin/env python3
"""How long the scheduled integrity audit holds the event loop (#1251).

The audit (#894) runs every five minutes in the one process every room shares.
Two of its checks scale with what they read: the drawings walk hashes and
decodes every stored drawing it visits, and the games slice compares a
hundred games' score ledgers and guesser counts. This seeds both - ``--games``
scored games of ``--seats`` seats and ``--rounds`` rounds (a guess award for
every guesser and a drawer bonus every turn, as the scorer writes them), and
``--drawings`` realistic drawings - and reports, each with a 1 ms ticker on the
loop:

- one games slice (`GAME_SLICE_ROWS` games, the first of the walk);
- a whole drawings walk, a slice of `DRAWING_SLICE_ROWS` rows at a time under
  the audit's default byte budget, as the pass runs it.

    TEST_DATABASE_URL=postgresql+asyncpg://sketchy:sketchy@127.0.0.1:5433/sketchy_test \\
        backend/.venv/bin/python benchmarks/integrity_audit_stall.py --games 100 --drawings 1000
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from time import perf_counter, process_time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))
sys.path.insert(0, os.path.join(ROOT, "benchmarks"))

import canvas_history as bench  # noqa: E402
from app.db.models import generate_uuid  # noqa: E402
from app.repositories.interfaces import (  # noqa: E402
    GameParticipantInput,
    GameRecordInput,
    ScoreEventInput,
    TurnDrawingInput,
    TurnParticipantOutcomeInput,
    TurnRecordInput,
)
from app.repositories.sqlalchemy import (  # noqa: E402
    SqlAlchemyGameHistoryRepository,
    SqlAlchemyUserRepository,
)
from app.services import integrity_audit  # noqa: E402
from app.services.drawing_storage import verify_stored_drawings  # noqa: E402
from tests.dbfixtures import create_test_db  # noqa: E402

AWARD = 10


def scored_game(players: list[str], rounds: int, frame: bytes | None = None) -> dict:
    """One finished game every seat draws in once a round, every guesser
    right: `save_game`'s arguments, ledger reconciled, drawings optional."""
    now = datetime.now(timezone.utc)
    seats = [str(generate_uuid()) for _ in players]
    totals = [0] * len(players)
    turns, events, drawings = [], [], []
    for index in range(rounds * len(players)):
        drawer = index % len(players)
        turn_id = str(generate_uuid())
        guessers = [seat for seat in range(len(players)) if seat != drawer]
        turns.append(TurnRecordInput(
            id=turn_id, round_number=index // len(players) + 1, turn_number=index + 1,
            drawer_user_id=players[drawer], drawer_seat_id=seats[drawer], prompt="cat",
            duration_seconds=40.0, guesser_count=len(guessers),
            participant_outcomes=tuple(
                TurnParticipantOutcomeInput(
                    seat_id=seats[seat], user_id=players[seat], eligible=True,
                    eligibility_reason="eligible", outcome="correct", terminal_state="active",
                    correct_guess_time_seconds=5.0, points_awarded=AWARD,
                )
                for seat in guessers
            ),
        ))
        for seat in guessers:
            events.append(ScoreEventInput(
                participant_seat_id=seats[seat], participant_user_id=players[seat],
                event_order=len(events) + 1, event_type="guess_award", points_delta=AWARD, turn_id=turn_id,
            ))
            totals[seat] += AWARD
        events.append(ScoreEventInput(
            participant_seat_id=seats[drawer], participant_user_id=players[drawer],
            event_order=len(events) + 1, event_type="drawer_bonus",
            points_delta=AWARD * len(guessers), turn_id=turn_id,
        ))
        totals[drawer] += AWARD * len(guessers)
        if frame is not None:
            drawings.append(TurnDrawingInput(turn_id=turn_id, payload=frame))
    ranked = sorted(range(len(players)), key=lambda seat: -totals[seat])
    return {
        "game_record": GameRecordInput(
            id=str(generate_uuid()), room_name="Bench", scoring_mode="default", scoring_version=1,
            score_ledger_version=1, rule_snapshot_version=1, rule_snapshot={"schemaVersion": 1},
            hint_mode="none", drawing_seconds=90, total_rounds=rounds,
            player_count=len(players), started_at=now - timedelta(minutes=30), finished_at=now,
            visibility="public",
        ),
        "participants": [
            GameParticipantInput(user_id=players[seat], final_score=totals[seat],
                                 final_rank=ranked.index(seat) + 1, seat_id=seats[seat], display_name=f"P{seat}")
            for seat in range(len(players))
        ],
        "turns": turns,
        "score_events": events,
        "drawings": drawings,
    }


async def ticked(coroutine) -> tuple[object, dict]:
    worst = 0.0
    done = False

    async def ticker() -> None:
        nonlocal worst
        while not done:
            started = perf_counter()
            await asyncio.sleep(0.001)
            worst = max(worst, perf_counter() - started - 0.001)

    tick = asyncio.create_task(ticker())
    await asyncio.sleep(0.01)
    cpu, wall = process_time(), perf_counter()
    result = await coroutine
    cpu, wall = process_time() - cpu, perf_counter() - wall
    done = True
    await tick
    return result, {
        "wall_ms": round(wall * 1000, 1),
        "cpu_ms": round(cpu * 1000, 1),
        "worst_loop_wait_ms": round(worst * 1000, 1),
    }


async def games_slice(factory):
    async with factory() as session, session.begin():
        return await integrity_audit._games_slice(session, None)


async def run(args) -> dict:
    factory, engine = await create_test_db()
    try:
        users = SqlAlchemyUserRepository(factory)
        history = SqlAlchemyGameHistoryRepository(factory)
        players = [str((await users.create_anonymous(display_name=f"P{i}")).id) for i in range(args.seats)]
        seeded = perf_counter()
        # The scored games first: the games walk is by id, and these are the
        # slice it takes first.
        for _ in range(args.games):
            await history.save_game(**scored_game(players, args.rounds))
        frame = bench.realistic_history().binary_payload()
        per_game = 8
        drawers = players[:per_game] if len(players) >= per_game else (players * per_game)[:per_game]
        for _ in range(-(-args.drawings // per_game)):
            game = scored_game(drawers[:2], per_game // 2, frame)
            await history.save_game(**game)
        seeded = perf_counter() - seeded

        sliced, slice_cost = await ticked(games_slice(factory))
        walked, walk_cost = await ticked(verify_stored_drawings(
            factory,
            batch_size=integrity_audit.DRAWING_SLICE_ROWS,
            byte_budget=integrity_audit.DEFAULT_BYTE_BUDGET_MIB * 1024 * 1024,
        ))
        return {
            "seed_seconds": round(seeded, 1),
            "games_slice": {
                "games": sliced.rows, "shape": f"{args.seats} seats x {args.rounds} rounds",
                "mismatches": len(sliced.mismatches), **slice_cost,
            },
            "drawings_walk": {
                "drawings": walked.checked, "frame_bytes": len(frame),
                "failures": walked.failed,
                **walk_cost,
            },
        }
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--games", type=int, default=100, help="scored games for the games slice")
    parser.add_argument("--seats", type=int, default=16)
    parser.add_argument("--rounds", type=int, default=10)
    parser.add_argument("--drawings", type=int, default=1000, help="realistic drawings for the drawings walk")
    args = parser.parse_args()
    print(json.dumps(asyncio.run(run(args)), indent=2))


if __name__ == "__main__":
    main()
