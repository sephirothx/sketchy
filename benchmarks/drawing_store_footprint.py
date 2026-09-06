"""What the stored drawing format saves in PostgreSQL, per game (#547).

Seeds finished games whose every turn carries the benchmark's realistic
drawing through the real history writer into a disposable PostgreSQL
database, then reports turn_drawings heap, TOAST and index bytes per game,
the WAL the writes produced per game, and the p95 of reading one drawing
back to wire bytes. Runs unchanged before and after #547, so the two can be
compared; the frame-level ratios are `drawing_compression.py`'s business.

    TEST_DATABASE_URL=postgresql+asyncpg://... backend/.venv/bin/python benchmarks/drawing_store_footprint.py --games 50
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))
sys.path.insert(0, os.path.join(ROOT, "benchmarks"))

import canvas_history as bench
from app.canvas_storage import stored_drawing_wire_payload
from app.db.models import Base, TurnDrawing, generate_uuid
from app.repositories.interfaces import (
    GameParticipantInput,
    GameRecordInput,
    TurnDrawingInput,
    TurnGuessInput,
    TurnParticipantOutcomeInput,
    TurnRecordInput,
)
from app.repositories.sqlalchemy import (
    SqlAlchemyGameHistoryRepository,
    SqlAlchemyUserRepository,
)
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import undefer

SEATS, TURNS = 4, 8


def _seed_inputs(players, started, frame):
    seats = [str(generate_uuid()) for _ in players]
    turns, guesses, drawings = [], [], []
    for index in range(TURNS):
        drawer = index % SEATS
        turn_id = str(generate_uuid())
        outcomes = []
        for seat_index, seat in enumerate(seats):
            if seat_index == drawer:
                continue
            guesses.append(TurnGuessInput(turn_id=turn_id, user_id=players[seat_index], seat_id=seat,
                                          points_awarded=10, guess_time_seconds=5.0))
            outcomes.append(TurnParticipantOutcomeInput(
                seat_id=seat, user_id=players[seat_index], eligible=True, eligibility_reason="eligible",
                outcome="correct", terminal_state="active", correct_guess_time_seconds=5.0))
        turns.append(TurnRecordInput(id=turn_id, round_number=index // SEATS + 1, turn_number=index + 1,
                                     drawer_user_id=players[drawer], drawer_seat_id=seats[drawer],
                                     prompt=f"prompt {index}", duration_seconds=60, prompt_source_kind="custom",
                                     guesser_count=SEATS - 1, participant_outcomes=tuple(outcomes)))
        drawings.append(TurnDrawingInput(turn_id=turn_id, payload=frame))
    participants = [GameParticipantInput(user_id=p, final_score=100, final_rank=i + 1, seat_id=s,
                                         display_name=f"P{i}", is_anonymous=False)
                    for i, (p, s) in enumerate(zip(players, seats, strict=True))]
    record = GameRecordInput(room_name="Drawings", scoring_mode="default", hint_mode="none", drawing_seconds=60,
                             total_rounds=2, player_count=SEATS, started_at=started,
                             finished_at=started + timedelta(minutes=10), prompt_source_mode="custom")
    return record, participants, turns, guesses, drawings


async def run(games: int) -> dict:
    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    factory = async_sessionmaker(engine, expire_on_commit=False)
    frame = bench.realistic_history().binary_payload()
    async with engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            await conn.execute(table.delete())
    users, history = SqlAlchemyUserRepository(factory), SqlAlchemyGameHistoryRepository(factory)
    players = []
    for i in range(SEATS):
        u = await users.create_anonymous(f"P{i}")
        players.append(u.id)
    started = datetime(2026, 8, 1, tzinfo=timezone.utc)
    async with engine.connect() as conn:
        await conn.execution_options(isolation_level="AUTOCOMMIT")
        wal_start = await conn.scalar(text("SELECT pg_current_wal_lsn()::text"))
    write_seconds = 0.0
    for g in range(games):
        began = time.perf_counter()
        record, participants, turns, guesses, drawings = _seed_inputs(players, started + timedelta(hours=g), frame)
        await history.save_game(record, participants, turns, guesses, drawings=drawings)
        write_seconds += time.perf_counter() - began
    async with engine.connect() as conn:
        await conn.execution_options(isolation_level="AUTOCOMMIT")
        wal_bytes = await conn.scalar(text(f"SELECT pg_wal_lsn_diff(pg_current_wal_lsn(), '{wal_start}'::pg_lsn)"))
        await conn.execute(text("VACUUM FULL ANALYZE turn_drawings"))
    async with engine.connect() as conn:
        rows = await conn.scalar(text("SELECT count(*) FROM turn_drawings"))
        heap = await conn.scalar(text("SELECT pg_relation_size('turn_drawings')"))
        toast = await conn.scalar(text(
            "SELECT coalesce(pg_total_relation_size(reltoastrelid), 0) FROM pg_class WHERE relname = 'turn_drawings'"))
        idx = await conn.scalar(text("SELECT pg_indexes_size('turn_drawings')"))
        stored_size = await conn.scalar(text("SELECT avg(byte_size) FROM turn_drawings"))
        fmt = (await conn.execute(text("SELECT format_magic, count(*) FROM turn_drawings GROUP BY 1"))).all()
        storage = await conn.scalar(text(
            "SELECT attstorage FROM pg_attribute WHERE attrelid = 'turn_drawings'::regclass AND attname = 'payload'"))
    decode_samples = []
    async with factory() as session:
        ids = (await session.scalars(select(TurnDrawing.turn_id).limit(40))).all()
        for turn_id in ids:
            began = time.perf_counter()
            row = await session.scalar(select(TurnDrawing).options(undefer(TurnDrawing.payload)).where(TurnDrawing.turn_id == turn_id))
            wire = stored_drawing_wire_payload(row.payload, checksum=row.checksum_sha256)
            decode_samples.append((time.perf_counter() - began) * 1000)
            assert wire == frame
    await engine.dispose()
    decode_samples.sort()
    return {
        "games": games, "shape": {"seats": SEATS, "turns": TURNS, "wire_frame_bytes": len(frame)},
        "formats": {magic: count for magic, count in fmt}, "payload_storage": str(storage),
        "stored_bytes_per_drawing": float(stored_size),
        "rows_per_game": rows / games,
        "heap_bytes_per_game": heap / games, "toast_bytes_per_game": toast / games,
        "index_bytes_per_game": idx / games, "total_bytes_per_game": (heap + toast + idx) / games,
        "wal_bytes_per_game": int(wal_bytes) / games,
        "save_game_ms_per_game": write_seconds / games * 1000,
        "read_one_drawing_p95_ms": decode_samples[max(0, int(len(decode_samples) * 0.95) - 1)],
    }


def main() -> None:
    parser = argparse.ArgumentParser(); parser.add_argument("--games", type=int, default=50)
    args = parser.parse_args()
    if not os.environ.get("TEST_DATABASE_URL", "").startswith("postgresql"):
        parser.error("TEST_DATABASE_URL must point at a disposable PostgreSQL database")
    print(json.dumps(asyncio.run(run(args.games)), indent=2))


if __name__ == "__main__":
    main()
