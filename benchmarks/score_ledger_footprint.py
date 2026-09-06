"""Physical size, write time and read cost of the score-event ledger (#552).

Seeds finished, fully scored games of one shape (8 seats, 24 turns, every
guesser correct: 7 awards and 1 drawer bonus per turn, 192 events per game)
through the real history writer into a disposable PostgreSQL database, then
reports score_events heap and index bytes per game, the writer's wall time
per game, and the detail read's ledger fetch explained. Runs unchanged on
the UUID-keyed and the order-keyed ledger, so the two can be compared.

    TEST_DATABASE_URL=postgresql+asyncpg://... backend/.venv/bin/python benchmarks/score_ledger_footprint.py --games 200
"""
from __future__ import annotations

import argparse
import asyncio
import dataclasses
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend"))

from app.db.models import Base, generate_uuid
from app.repositories.interfaces import (
    GameParticipantInput,
    GameRecordInput,
    ScoreEventInput,
    TurnParticipantOutcomeInput,
    TurnRecordInput,
)
from app.repositories.sqlalchemy import (
    SqlAlchemyGameHistoryRepository,
    SqlAlchemyUserRepository,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

SEATS, TURNS, AWARD = 8, 24, 100
EVENT_FIELDS = {f.name for f in dataclasses.fields(ScoreEventInput)}


def _event(**kwargs) -> ScoreEventInput:
    """Build an input for whichever ledger identity the checkout has."""
    if "id" in EVENT_FIELDS:
        kwargs.setdefault("id", str(generate_uuid()))
        kwargs.setdefault("scoring_version", 1)
        kwargs.setdefault("rule_snapshot_version", 1)
    return ScoreEventInput(**{k: v for k, v in kwargs.items() if k in EVENT_FIELDS})


def _seed_inputs(players, started):
    seats = [str(generate_uuid()) for _ in players]
    turns, events = [], []
    totals = [0] * SEATS
    for index in range(TURNS):
        drawer = index % SEATS
        turn_id = str(generate_uuid())
        outcomes = []
        for seat_index, seat in enumerate(seats):
            if seat_index == drawer:
                continue
            outcomes.append(TurnParticipantOutcomeInput(
                seat_id=seat, user_id=players[seat_index], eligible=True, eligibility_reason="eligible",
                outcome="correct", terminal_state="active", correct_guess_time_seconds=5.0, points_awarded=AWARD))
            events.append(_event(participant_seat_id=seat, participant_user_id=players[seat_index], turn_id=turn_id,
                                 event_order=len(events) + 1, event_type="guess_award", points_delta=AWARD))
            totals[seat_index] += AWARD
        events.append(_event(participant_seat_id=seats[drawer], participant_user_id=players[drawer], turn_id=turn_id,
                             event_order=len(events) + 1, event_type="drawer_bonus", points_delta=AWARD * (SEATS - 1)))
        totals[drawer] += AWARD * (SEATS - 1)
        turns.append(TurnRecordInput(id=turn_id, round_number=index // SEATS + 1, turn_number=index + 1,
                                     drawer_user_id=players[drawer], drawer_seat_id=seats[drawer],
                                     prompt=f"prompt {index}", duration_seconds=60, prompt_source_kind="custom",
                                     guesser_count=SEATS - 1, participant_outcomes=tuple(outcomes)))
    participants = [GameParticipantInput(user_id=p, final_score=totals[i], final_rank=i + 1, seat_id=s,
                                         display_name=f"P{i}", is_anonymous=False)
                    for i, (p, s) in enumerate(zip(players, seats, strict=True))]
    record = GameRecordInput(room_name="Ledger", scoring_mode="default", hint_mode="none", drawing_seconds=60,
                             total_rounds=3, player_count=SEATS, started_at=started,
                             finished_at=started + timedelta(minutes=20), scoring_version=1,
                             score_ledger_version=1, rule_snapshot_version=1, prompt_source_mode="custom")
    return record, participants, turns, events


async def run(games: int) -> dict:
    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            await conn.execute(table.delete())
    users, history = SqlAlchemyUserRepository(factory), SqlAlchemyGameHistoryRepository(factory)
    players = []
    for i in range(SEATS):
        u = await users.create_anonymous(f"P{i}")
        await users.claim_account(u.id, f"ledger{i}", "hash")
        players.append(u.id)
    started = datetime(2026, 8, 1, tzinfo=timezone.utc)
    write_seconds = 0.0
    game_ids = []
    for g in range(games):
        inputs = _seed_inputs(players, started + timedelta(hours=g))
        began = time.perf_counter()
        game_ids.append(await history.save_game(*inputs))
        write_seconds += time.perf_counter() - began
    read_began = time.perf_counter()
    for game_id in game_ids[:50]:
        detail = await history.get_game_detail(game_id, players[0])
        assert detail is not None and len(detail.score_events) == TURNS * SEATS
    read_seconds = time.perf_counter() - read_began
    async with engine.connect() as conn:
        await conn.execution_options(isolation_level="AUTOCOMMIT")
        for table in ("score_events", "game_records", "game_participants", "turn_records"):
            await conn.execute(text(f"VACUUM FULL ANALYZE {table}"))
    async with engine.connect() as conn:
        rows = await conn.scalar(text("SELECT count(*) FROM score_events"))
        heap = await conn.scalar(text("SELECT pg_relation_size('score_events')"))
        idx = await conn.scalar(text("SELECT pg_indexes_size('score_events')"))
        indexes = (await conn.execute(text(
            "SELECT indexrelname, pg_relation_size(indexrelid) FROM pg_stat_user_indexes "
            "WHERE relname = 'score_events' ORDER BY indexrelname"))).all()
        columns = [r[0] for r in (await conn.execute(text(
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'score_events' "
            "ORDER BY ordinal_position"))).all()]
        plan = (await conn.execute(text(
            "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) SELECT * FROM score_events "
            "WHERE game_id = (SELECT id FROM game_records LIMIT 1) ORDER BY event_order"))).scalar_one()
    await engine.dispose()
    node = (plan[0] if isinstance(plan, list) else json.loads(plan)[0])
    return {
        "games": games, "shape": {"seats": SEATS, "turns": TURNS, "events_per_game": TURNS * SEATS},
        "columns": columns,
        "rows_per_game": rows / games, "heap_bytes_per_game": heap / games, "index_bytes_per_game": idx / games,
        "total_bytes_per_game": (heap + idx) / games,
        "indexes_bytes_per_game": {name: size / games for name, size in indexes},
        "save_game_ms_per_game": write_seconds / games * 1000,
        "get_game_detail_ms": read_seconds / min(games, 50) * 1000,
        "ledger_fetch_plan": {"node": node["Plan"]["Node Type"], "execution_ms": node.get("Execution Time"),
                              "buffers": node["Plan"].get("Shared Hit Blocks")},
    }


def main() -> None:
    parser = argparse.ArgumentParser(); parser.add_argument("--games", type=int, default=50)
    args = parser.parse_args()
    if not os.environ.get("TEST_DATABASE_URL", "").startswith("postgresql"):
        parser.error("TEST_DATABASE_URL must point at a disposable PostgreSQL database")
    print(json.dumps(asyncio.run(run(args.games)), indent=2))


if __name__ == "__main__":
    main()
