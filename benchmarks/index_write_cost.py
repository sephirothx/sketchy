"""What the indexes and page fill of the hottest update and insert paths cost (#890).

Two measurements against the schema the database is migrated to, so running
it before and after a revision shows what the revision changed:

- **Session touch.** Seeds ``--sessions`` sessions, then runs three rounds,
  each touching 12.5% of them the way ``resolve_session``'s throttled write
  does (``last_used_at``, ``idle_expires_at``, ``last_ip_hash``). Reports WAL
  per touch, how many updates were heap-only (HOT), and the table plus
  indexes before and after. An update that changes an indexed column, or
  finds no room on its page, cannot be HOT and writes an entry into every
  index of the table.
- **Chat insert.** Inserts ``--messages`` room messages with six recipients
  each, in batches of 1,000, and reports the insert time, WAL, and heap,
  TOAST and per-index bytes per row.

Requires ``TEST_DATABASE_URL`` pointing at a disposable PostgreSQL database at
Alembic head; ``auth_sessions`` and ``room_messages`` are truncated first.

    TEST_DATABASE_URL=postgresql+asyncpg://sketchy:sketchy@127.0.0.1:5433/sketchy_test \\
      backend/.venv/bin/python benchmarks/index_write_cost.py --sessions 20000 --messages 100000
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
import random
import sys
from time import perf_counter

BACKEND = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend")
sys.path.insert(0, BACKEND)

from sqlalchemy import insert, text, update  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from app.db.models import AuthSession, RoomMessage, User, generate_uuid  # noqa: E402


async def _lsn(session) -> str:
    return str(await session.scalar(text("SELECT pg_current_wal_lsn()::text")))


async def _wal_between(session, start: str, end: str) -> int:
    # Literals: asyncpg types a pg_lsn parameter as an integer.
    return int(await session.scalar(text(f"SELECT pg_wal_lsn_diff('{end}'::pg_lsn, '{start}'::pg_lsn)")))


async def _table_stats(session, table: str) -> dict:
    # Statistics are flushed asynchronously and cached per transaction.
    await session.execute(text("SELECT pg_stat_force_next_flush()"))
    await session.commit()
    await session.execute(text("SELECT pg_stat_clear_snapshot()"))
    row = (
        await session.execute(
            text(
                "SELECT n_tup_upd, n_tup_hot_upd, pg_total_relation_size(relid) "
                "FROM pg_stat_user_tables WHERE relname = :table"
            ),
            {"table": table},
        )
    ).one()
    return {"updates": int(row[0]), "hot": int(row[1]), "total_bytes": int(row[2])}


async def _footprint(session, table: str, rows: int) -> dict:
    heap = int(await session.scalar(text(f"SELECT pg_table_size('{table}')")))
    indexes = (
        await session.execute(
            text(
                "SELECT indexrelname, pg_relation_size(indexrelid) FROM pg_stat_user_indexes "
                "WHERE relname = :table ORDER BY 2 DESC"
            ),
            {"table": table},
        )
    ).all()
    return {
        "heap_and_toast_bytes": heap,
        "heap_bytes_per_row": round(heap / rows, 1),
        "indexes": {name: {"bytes": int(size), "per_row": round(int(size) / rows, 1)} for name, size in indexes},
        "all_indexes_per_row": round(sum(int(size) for _, size in indexes) / rows, 1),
    }


async def _truncate(engine, *tables: str) -> None:
    async with engine.begin() as connection:
        await connection.execute(text(f"TRUNCATE {', '.join(tables)} CASCADE"))


async def session_touch(factory, engine, sessions: int, rounds: int, share: float) -> dict:
    await _truncate(engine, "auth_sessions")
    now = datetime.now(timezone.utc)
    users = [generate_uuid() for _ in range(max(1, sessions // 4))]
    ids = [generate_uuid() for _ in range(sessions)]
    async with factory() as session:
        async with session.begin():
            await session.execute(
                insert(User), [{"id": user, "display_name": f"Bench{i % 1000}"} for i, user in enumerate(users)]
            )
            for start in range(0, sessions, 2000):
                await session.execute(
                    insert(AuthSession),
                    [
                        {
                            "id": ids[index],
                            "user_id": users[index % len(users)],
                            "token_hash": hashlib.sha256(str(ids[index]).encode()).hexdigest(),
                            "device_label": "Firefox on Linux",
                            "created_at": now,
                            "last_used_at": now,
                            "expires_at": now + timedelta(days=365),
                            "idle_expires_at": now + timedelta(days=90),
                            "ip_hash": "a" * 64,
                        }
                        for index in range(start, min(start + 2000, sessions))
                    ],
                )
        await session.execute(text("ANALYZE auth_sessions"))
        await session.commit()
        before = await _table_stats(session, "auth_sessions")
        start_lsn = await _lsn(session)
    chooser = random.Random(890)
    touched = 0
    started = perf_counter()
    for round_number in range(1, rounds + 1):
        at = now + timedelta(minutes=6 * round_number)
        picked = chooser.sample(ids, int(sessions * share))
        async with factory() as session:
            # One statement per session, as the request path issues it.
            for session_id in picked:
                async with session.begin():
                    await session.execute(
                        update(AuthSession)
                        .where(AuthSession.id == session_id)
                        .values(
                            last_used_at=at,
                            idle_expires_at=at + timedelta(days=90),
                            last_ip_hash="b" * 64,
                        )
                    )
        touched += len(picked)
    elapsed = perf_counter() - started
    async with factory() as session:
        end_lsn = await _lsn(session)
        wal = await _wal_between(session, start_lsn, end_lsn)
        after = await _table_stats(session, "auth_sessions")
    return {
        "sessions": sessions,
        "touches": touched,
        "wal_bytes_per_touch": round(wal / touched),
        "hot_updates": after["hot"] - before["hot"],
        "updates": after["updates"] - before["updates"],
        "table_and_indexes_kb_before": before["total_bytes"] // 1024,
        "table_and_indexes_kb_after": after["total_bytes"] // 1024,
        "ms_per_touch": round(elapsed / touched * 1000, 3),
    }


async def chat_insert(factory, engine, messages: int) -> dict:
    await _truncate(engine, "room_messages")
    now = datetime.now(timezone.utc)
    speaker = generate_uuid()
    recipients = [str(generate_uuid()) for _ in range(6)]
    room, player, game = generate_uuid(), generate_uuid(), generate_uuid()
    turns = [generate_uuid() for _ in range(24)]
    async with factory() as session:
        async with session.begin():
            session.add(User(id=speaker, display_name="Chatter"))
        start_lsn = await _lsn(session)
    started = perf_counter()
    async with factory() as session:
        for start in range(0, messages, 1000):
            async with session.begin():
                await session.execute(
                    insert(RoomMessage),
                    [
                        {
                            "id": generate_uuid(),
                            "room_instance_id": room,
                            "game_id": game,
                            "turn_id": turns[index % len(turns)],
                            "sender_user_id": speaker,
                            "sender_player_id": player,
                            "sender_display_name_snapshot": "Chatter",
                            "sender_is_anonymous_snapshot": False,
                            "is_spectator": False,
                            "message_kind": "chat",
                            "audience": "room",
                            "audience_user_ids": recipients,
                            "text": f"is it a lighthouse? {index}",
                            "created_at": now + timedelta(milliseconds=index),
                            "expires_at": now + timedelta(days=30, milliseconds=index),
                        }
                        for index in range(start, min(start + 1000, messages))
                    ],
                )
    elapsed = perf_counter() - started
    async with factory() as session:
        wal = await _wal_between(session, start_lsn, await _lsn(session))
        await session.execute(text("ANALYZE room_messages"))
        footprint = await _footprint(session, "room_messages", messages)
    return {
        "messages": messages,
        "insert_seconds": round(elapsed, 2),
        "wal_bytes_per_row": round(wal / messages),
        **footprint,
    }


async def run(sessions: int, messages: int) -> dict:
    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        head = await session.scalar(text("SELECT version_num FROM alembic_version"))
        fillfactor = (
            await session.execute(
                text(
                    "SELECT relname, reloptions FROM pg_class WHERE relname IN "
                    "('auth_sessions', 'room_messages') ORDER BY relname"
                )
            )
        ).all()
    result = {
        "revision": head,
        "reloptions": {name: options for name, options in fillfactor},
        "session_touch": await session_touch(factory, engine, sessions, rounds=3, share=0.125),
        "chat_insert": await chat_insert(factory, engine, messages),
    }
    await _truncate(engine, "auth_sessions", "room_messages")
    await engine.dispose()
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sessions", type=int, default=20000)
    parser.add_argument("--messages", type=int, default=100000)
    args = parser.parse_args()
    if not os.environ.get("TEST_DATABASE_URL", "").startswith("postgresql"):
        parser.error("TEST_DATABASE_URL must point at a disposable PostgreSQL database")
    print(json.dumps(asyncio.run(run(args.sessions, args.messages)), indent=2))


if __name__ == "__main__":
    main()
