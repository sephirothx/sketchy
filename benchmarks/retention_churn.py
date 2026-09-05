"""PostgreSQL churn under the bounded retention sweep (#550).

Inserts a backlog of expired room messages, then runs the bounded purge
until the table is clean, sampling after every run what a DBA would watch:
dead tuples and live tuples in `pg_stat_user_tables`, the relation's total
size, and the WAL bytes the run generated. The point is to see the shape -
a bounded run deletes a fixed slice and leaves dead tuples for autovacuum
to reclaim, so relation size does not fall until vacuum has run - before
anybody chooses table storage parameters or reopens partitioning (#546).

Requires ``TEST_DATABASE_URL`` pointing at a disposable PostgreSQL database
at Alembic head; the messages table is emptied first.

    TEST_DATABASE_URL=postgresql+asyncpg://sketchy:sketchy@127.0.0.1:5433/sketchy_test \\
      backend/.venv/bin/python benchmarks/retention_churn.py --rows 100000 --row-budget 5000
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timedelta, timezone
import json
import os
import sys
from time import perf_counter

BACKEND = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend")
sys.path.insert(0, BACKEND)

from sqlalchemy import delete, insert, text  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from app.db.models import RoomMessage, User, generate_uuid  # noqa: E402
from app.services.message_retention import purge_expired_room_messages  # noqa: E402
from app.services.sweeps import SweepBudget  # noqa: E402


async def _sample(session) -> dict:
    row = (
        await session.execute(
            text(
                "SELECT n_live_tup, n_dead_tup, pg_total_relation_size('room_messages'), "
                "pg_current_wal_lsn()::text FROM pg_stat_user_tables "
                "WHERE relname = 'room_messages'"
            )
        )
    ).one()
    return {"live": int(row[0]), "dead": int(row[1]), "bytes": int(row[2]), "lsn": row[3]}


async def _wal_between(session, start: str, end: str) -> int:
    # Literals rather than binds: asyncpg types a pg_lsn parameter as an
    # integer, and both values came from the server a moment ago.
    return int(
        await session.scalar(
            text(f"SELECT pg_wal_lsn_diff('{end}'::pg_lsn, '{start}'::pg_lsn)")
        )
    )


async def run(rows: int, row_budget: int, batch: int, insert_batch: int) -> dict:
    url = os.environ["TEST_DATABASE_URL"]
    engine = create_async_engine(url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    now = datetime.now(timezone.utc)
    speaker = generate_uuid()
    async with factory() as session:
        async with session.begin():
            await session.execute(delete(RoomMessage))
            await session.execute(delete(User).where(User.display_name == "Churn"))
            session.add(User(id=speaker, display_name="Churn"))
        async with session.begin():
            for start in range(0, rows, insert_batch):
                await session.execute(
                    insert(RoomMessage),
                    [
                        {
                            "id": generate_uuid(),
                            "room_instance_id": None,
                            "sender_user_id": speaker,
                            "sender_player_id": None,
                            "sender_display_name_snapshot": "Churn",
                            "sender_is_anonymous_snapshot": True,
                            "is_spectator": False,
                            "message_kind": "chat",
                            "audience": "lobby",
                            "audience_user_ids": [],
                            "text": f"line {index}",
                            "created_at": now - timedelta(days=31, seconds=index),
                            "expires_at": now - timedelta(days=1, seconds=index),
                        }
                        for index in range(start, min(start + insert_batch, rows))
                    ],
                )
        await session.execute(text("ANALYZE room_messages"))
        await session.commit()
        before = await _sample(session)

    samples = []
    budget = SweepBudget(rows=row_budget, batch=batch, seconds=600)
    while True:
        async with factory() as session:
            start_lsn = (await _sample(session))["lsn"]
        started = perf_counter()
        report = await purge_expired_room_messages(factory, now=now, budget=budget)
        elapsed = perf_counter() - started
        async with factory() as session:
            after = await _sample(session)
            wal = await _wal_between(session, start_lsn, after["lsn"])
        samples.append(
            {
                "rows": int(report),
                "batches": report.batches,
                "seconds": round(elapsed, 3),
                "wal_bytes": wal,
                "dead_tuples": after["dead"],
                "live_tuples": after["live"],
                "relation_bytes": after["bytes"],
                "exhausted": report.exhausted,
                "oldest_overdue_seconds": report.oldest_overdue_seconds,
            }
        )
        if not report.exhausted:
            break
    # VACUUM refuses a transaction block, so it gets an autocommit connection.
    async with engine.connect() as connection:
        await connection.execution_options(isolation_level="AUTOCOMMIT")
        await connection.execute(text("VACUUM room_messages"))
    async with factory() as session:
        vacuumed = await _sample(session)
    await engine.dispose()
    return {
        "rows": rows,
        "row_budget": row_budget,
        "batch": batch,
        "before": {k: v for k, v in before.items() if k != "lsn"},
        "runs": samples,
        "after_vacuum": {k: v for k, v in vacuumed.items() if k != "lsn"},
        "total_seconds": round(sum(s["seconds"] for s in samples), 3),
        "total_wal_bytes": sum(s["wal_bytes"] for s in samples),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rows", type=int, default=100_000)
    parser.add_argument("--row-budget", type=int, default=5_000)
    parser.add_argument("--batch", type=int, default=500)
    parser.add_argument("--insert-batch", type=int, default=5_000)
    parser.add_argument("--json-output")
    args = parser.parse_args()
    if not os.environ.get("TEST_DATABASE_URL", "").startswith("postgresql"):
        parser.error("TEST_DATABASE_URL must point at a disposable PostgreSQL database")
    result = asyncio.run(run(args.rows, args.row_budget, args.batch, args.insert_batch))
    encoded = json.dumps(result, indent=2)
    print(encoded)
    if args.json_output:
        with open(args.json_output, "w", encoding="utf-8") as output:
            output.write(encoded)


if __name__ == "__main__":
    main()
