"""EXPLAIN (ANALYZE, BUFFERS) for the admin, moderation and queue reads (#554).

Seeds a representative, deliberately skewed population into a disposable
PostgreSQL database - many room messages and few lobby lines, a long audit
ledger with a handful of event types, mostly-revoked bans, a mostly-delivered
outbox, a few pending exports, many registered players - then explains the
real queries the application runs against them, reporting the plan's node
types, rows, shared buffers and time. Run it at the revision before the
#554 indexes and at head; the decision to keep or drop an index is the
difference between the two.

    TEST_DATABASE_URL=postgresql+asyncpg://... backend/.venv/bin/python benchmarks/index_plans.py --scale 1
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timedelta, timezone
import json
import os
import sys

BACKEND = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend")
sys.path.insert(0, BACKEND)

from sqlalchemy import insert, text  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from app.db.models import (  # noqa: E402
    AuditEvent,
    DataExport,
    EmailOutboxEntry,
    RoomMessage,
    User,
    UserBan,
    generate_uuid,
)

NOW = datetime(2026, 9, 6, 12, tzinfo=timezone.utc)


def _chunks(rows: list, size: int = 5000):
    for start in range(0, len(rows), size):
        yield rows[start : start + size]


async def _seed(session, scale: int) -> dict:
    users = [generate_uuid() for _ in range(20_000 * scale)]
    await session.execute(
        insert(User),
        [
            {
                "id": uid, "display_name": f"Player {i} {'otter' if i % 97 == 0 else 'heron'}",
                "username": f"player{i}", "password_hash": "x", "state": "registered",
                "last_active_at": NOW - timedelta(minutes=i),
            }
            for i, uid in enumerate(users)
        ],
    )
    room = generate_uuid()
    reported = users[0]
    messages = []
    for i in range(200_000 * scale):
        lobby = i % 40 == 0
        messages.append(
            {
                "id": generate_uuid(),
                "room_instance_id": None if lobby else (room if i % 3 == 0 else generate_uuid()),
                "sender_user_id": reported if i % 50 == 0 else users[i % len(users)],
                "sender_player_id": None if lobby else generate_uuid(),
                "sender_display_name_snapshot": "S", "sender_is_anonymous_snapshot": False,
                "is_spectator": False, "message_kind": "chat",
                "audience": "lobby" if lobby else "room", "audience_user_ids": [],
                "text": f"line {i}",
                "created_at": NOW - timedelta(seconds=i * 3),
                "expires_at": NOW + timedelta(days=29) - timedelta(seconds=i * 3),
            }
        )
    for chunk in _chunks(messages):
        await session.execute(insert(RoomMessage), chunk)
    events = [
        {
            "id": generate_uuid(),
            "event_type": ("account.login", "account.password_reset", "moderation.ban")[i % 3] if i % 500 else "retention.anonymous_purge",
            "actor_user_id": users[i % len(users)], "target_user_id": None,
            "target_type": "user", "target_id": str(users[i % len(users)]),
            "details": {}, "created_at": NOW - timedelta(seconds=i * 7),
        }
        for i in range(100_000 * scale)
    ]
    for chunk in _chunks(events):
        await session.execute(insert(AuditEvent), chunk)
    bans = [
        {
            "id": generate_uuid(), "user_id": users[i % len(users)], "banned_by_user_id": users[1],
            "reason": "spam", "is_active": i % 20 == 0,
            "expires_at": None if i % 2 else NOW + timedelta(days=1),
            "created_at": NOW - timedelta(minutes=i),
        }
        for i in range(20_000 * scale)
    ]
    for chunk in _chunks(bans):
        await session.execute(insert(UserBan), chunk)
    outbox = [
        {
            "id": generate_uuid(), "user_id": users[i % len(users)], "to_address": "a@b.c",
            "template": "verify_email", "payload": {}, "state": "pending" if i % 200 == 0 else "sent",
            "attempts": 1, "next_attempt_at": NOW - timedelta(minutes=1) if i % 200 == 0 else NOW,
            "sent_at": None if i % 200 == 0 else NOW - timedelta(days=i % 60),
            "created_at": NOW - timedelta(days=i % 60, minutes=i % 100),
        }
        for i in range(50_000 * scale)
    ]
    for chunk in _chunks(outbox):
        await session.execute(insert(EmailOutboxEntry), chunk)
    exports = [
        {
            "id": generate_uuid(), "user_id": users[i], "status": "pending" if i < 5 else "ready",
            "schema_version": 1, "artifact": None if i < 5 else b"x", "artifact_encoding": None if i < 5 else "gzip+json",
            "created_at": NOW - timedelta(hours=i), "expires_at": NOW + timedelta(days=7),
            "completed_at": None if i < 5 else NOW,
        }
        for i in range(2_000 * scale)
    ]
    for chunk in _chunks(exports):
        await session.execute(insert(DataExport), chunk)
    return {"room": room, "reported": reported}


QUERIES = {
    "lobby_restore": (
        "SELECT id FROM room_messages WHERE audience = 'lobby' AND expires_at > :now "
        "ORDER BY created_at DESC, id DESC LIMIT 50"
    ),
    "audit_newest_of_type": (
        "SELECT id FROM audit_events WHERE event_type = 'moderation.ban' "
        "ORDER BY created_at DESC LIMIT 100"
    ),
    "audit_newest_any": "SELECT id FROM audit_events ORDER BY created_at DESC LIMIT 100",
    "audit_newest_of_rare_type": (
        "SELECT id FROM audit_events WHERE event_type = 'retention.anonymous_purge' "
        "ORDER BY created_at DESC LIMIT 100"
    ),
    "outbox_terminal_purge_failed": (
        "SELECT id FROM email_outbox WHERE state = 'failed' AND created_at <= :cutoff "
        "ORDER BY created_at, id LIMIT 500"
    ),
    "ban_queue_active_newest": (
        "SELECT id FROM user_bans WHERE is_active AND (expires_at IS NULL OR expires_at > :now) "
        "ORDER BY created_at DESC LIMIT 50"
    ),
    "outbox_due": (
        "SELECT id FROM email_outbox WHERE state = 'pending' AND next_attempt_at <= :now "
        "ORDER BY next_attempt_at LIMIT 100"
    ),
    "outbox_terminal_purge_sent": (
        "SELECT id FROM email_outbox WHERE state = 'sent' AND sent_at <= :cutoff "
        "ORDER BY sent_at, id LIMIT 500"
    ),
    "room_evidence": (
        "SELECT id FROM room_messages WHERE room_instance_id = :room AND sender_user_id = :reported "
        "AND expires_at > :now ORDER BY created_at DESC LIMIT 20"
    ),
    "export_queue": (
        "SELECT id FROM data_exports WHERE status = 'pending' ORDER BY created_at LIMIT 10"
    ),
    "export_depth": "SELECT count(*), min(created_at) FROM data_exports WHERE status IN ('pending', 'processing')",
    "player_search_ilike": (
        "SELECT id FROM users WHERE state = 'registered' AND display_name ILIKE '%otter%' "
        "ORDER BY last_active_at DESC LIMIT 20"
    ),
}


def _summarise(plan: dict) -> dict:
    nodes: list[str] = []

    def walk(node: dict) -> None:
        label = node.get("Node Type", "?")
        if node.get("Index Name"):
            label += f"[{node['Index Name']}]"
        if node.get("Relation Name") and not node.get("Index Name"):
            label += f"({node['Relation Name']})"
        nodes.append(label)
        for child in node.get("Plans", []):
            walk(child)

    walk(plan["Plan"])
    return {
        "nodes": nodes,
        "execution_ms": plan.get("Execution Time"),
        "shared_hit": plan["Plan"].get("Shared Hit Blocks"),
        "shared_read": plan["Plan"].get("Shared Read Blocks"),
        "rows": plan["Plan"].get("Actual Rows"),
    }


async def run(scale: int, reseed: bool) -> dict:
    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        if reseed:
            async with session.begin():
                for table in ("email_outbox", "data_exports", "user_bans", "audit_events", "room_messages", "users"):
                    await session.execute(text(f"DELETE FROM {table}"))
                params = await _seed(session, scale)
            async with session.begin():
                await session.execute(text("INSERT INTO app_config (key, value) VALUES ('bench.index_plans', :v) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value"), {"v": json.dumps({k: str(v) for k, v in params.items()})})
            await session.execute(text("ANALYZE"))
            await session.commit()
        stored = json.loads(await session.scalar(text("SELECT value FROM app_config WHERE key = 'bench.index_plans'")))
        params = {
            "now": NOW,
            "cutoff": NOW - timedelta(days=30),
            "room": stored["room"],
            "reported": stored["reported"],
        }
        results = {}
        for name, sql in QUERIES.items():
            await session.execute(text(sql), params)  # warm
            raw = (await session.execute(text("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + sql), params)).scalar_one()
            plan = raw[0] if isinstance(raw, list) else json.loads(raw)[0]
            results[name] = _summarise(plan)
    await engine.dispose()
    return results


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scale", type=int, default=1)
    parser.add_argument("--no-reseed", action="store_true", help="Explain against what is already seeded.")
    parser.add_argument("--json-output")
    args = parser.parse_args()
    if not os.environ.get("TEST_DATABASE_URL", "").startswith("postgresql"):
        parser.error("TEST_DATABASE_URL must point at a disposable PostgreSQL database")
    result = asyncio.run(run(args.scale, not args.no_reseed))
    encoded = json.dumps(result, indent=2, default=str)
    print(encoded)
    if args.json_output:
        with open(args.json_output, "w", encoding="utf-8") as output:
            output.write(encoded)


if __name__ == "__main__":
    main()
