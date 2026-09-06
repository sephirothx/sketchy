"""What a native uuid[] would save on room_messages recipients (#545).

Creates two throwaway tables in a disposable PostgreSQL database holding
the same recipient lists as jsonb (the storage today) and as uuid[], for
0, 1, 8 and 16 recipients, and reports pg_column_size per value plus heap
size per 100,000 rows of each. Measurement only; nothing changes.

    TEST_DATABASE_URL=postgresql+asyncpg://... backend/.venv/bin/python benchmarks/recipient_array_sizes.py
"""
from __future__ import annotations

import asyncio
import json
import os
import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine


async def run() -> dict:
    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    result: dict = {"per_value_bytes": {}, "per_100k_rows_bytes": {}}
    async with engine.begin() as conn:
        await conn.execute(text("DROP TABLE IF EXISTS bench_recipients_jsonb, bench_recipients_uuid"))
        await conn.execute(text("CREATE TABLE bench_recipients_jsonb (id uuid primary key, recipients jsonb not null)"))
        await conn.execute(text("CREATE TABLE bench_recipients_uuid (id uuid primary key, recipients uuid[] not null)"))
        for count in (0, 1, 8, 16):
            ids = [uuid.uuid4() for _ in range(count)]
            js = await conn.scalar(
                text("SELECT pg_column_size(CAST(:v AS jsonb))"), {"v": json.dumps([str(i) for i in ids])}
            )
            # asyncpg types a uuid[] parameter as a list of UUIDs.
            arr = await conn.scalar(text("SELECT pg_column_size(CAST(:v AS uuid[]))"), {"v": ids})
            result["per_value_bytes"][count] = {"jsonb": js, "uuid_array": arr, "saving": js - arr}
        for count in (1, 8):
            for table, cast in (("bench_recipients_jsonb", "jsonb"), ("bench_recipients_uuid", "uuid[]")):
                await conn.execute(text(f"TRUNCATE {table}"))
                await conn.execute(
                    text(
                        f"INSERT INTO {table} SELECT gen_random_uuid(), "
                        + ("CAST(to_jsonb(ARRAY(SELECT gen_random_uuid()::text FROM generate_series(1, :n))) AS jsonb)" if cast == "jsonb" else "ARRAY(SELECT gen_random_uuid() FROM generate_series(1, :n))")
                        + " FROM generate_series(1, 100000)"
                    ),
                    {"n": count},
                )
                await conn.execute(text(f"VACUUM ANALYZE {table}")) if False else None
            sizes = {}
            for table in ("bench_recipients_jsonb", "bench_recipients_uuid"):
                sizes[table] = {
                    "heap": await conn.scalar(text(f"SELECT pg_relation_size('{table}')")),
                    "toast": await conn.scalar(text(f"SELECT pg_total_relation_size('{table}') - pg_relation_size('{table}') - pg_indexes_size('{table}')")),
                    "total": await conn.scalar(text(f"SELECT pg_total_relation_size('{table}')")),
                }
            result["per_100k_rows_bytes"][count] = sizes
        await conn.execute(text("DROP TABLE bench_recipients_jsonb, bench_recipients_uuid"))
    await engine.dispose()
    return result


def main() -> None:
    if not os.environ.get("TEST_DATABASE_URL", "").startswith("postgresql"):
        raise SystemExit("TEST_DATABASE_URL must point at a disposable PostgreSQL database")
    print(json.dumps(asyncio.run(run()), indent=2))


if __name__ == "__main__":
    main()
