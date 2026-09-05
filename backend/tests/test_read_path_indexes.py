"""The application's own queries use the partial indexes they were given (#554).

A partial index only matches a plan whose predicate names the literal its
predicate names; a value bound as a parameter, which is what SQLAlchemy does
by default and what asyncpg prepares, does not. These explain the real
statements, with their real binding, and read the plan back.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os

import pytest

from app.db.models import Base

from tests.dbfixtures import create_test_db

pytestmark = pytest.mark.asyncio

ON_POSTGRESQL = os.environ.get("TEST_DATABASE_URL", "").startswith("postgresql")


def test_the_indexes_named_here_exist_in_the_metadata():
    names = {index.name for table in Base.metadata.sorted_tables for index in table.indexes}
    assert {
        "ix_room_messages_lobby_newest",
        "ix_user_bans_active_newest",
        "ix_email_outbox_sent_at_sent",
        "ix_audit_events_type_created_at",
    } <= names
    assert "ix_audit_events_event_type" not in names, "replaced by the composite that leads with it"


async def _plan_of(session, statement) -> str:
    """Run the statement the way the application does, then explain exactly
    what reached the driver: the same text, the same bound parameters."""
    from sqlalchemy import event

    captured: list[tuple[str, tuple]] = []
    connection = await session.connection()
    sync_connection = await connection.get_raw_connection()
    assert sync_connection is not None

    def before(conn, cursor, statement_text, parameters, context, executemany):
        captured.append((statement_text, parameters))

    engine = session.get_bind()
    event.listen(engine, "before_cursor_execute", before)
    try:
        await session.execute(statement)
    finally:
        event.remove(engine, "before_cursor_execute", before)
    statement_text, parameters = captured[-1]
    raw = (
        await connection.exec_driver_sql("EXPLAIN (FORMAT TEXT) " + statement_text, parameters)
    ).scalars().all()
    return "\n".join(raw)


async def _seed(factory, now: datetime) -> None:
    """Enough rows, skewed the way production is, for the planner to have a
    choice: an empty table is a trivial sort whatever the indexes say."""
    from sqlalchemy import insert, text

    from app.db.models import EmailOutboxEntry, RoomMessage, User, UserBan, generate_uuid

    async with factory() as session:
        async with session.begin():
            speaker = generate_uuid()
            session.add(User(id=speaker, display_name="Speaker"))
            await session.flush()
            await session.execute(
                insert(RoomMessage),
                [
                    {
                        "id": generate_uuid(),
                        "room_instance_id": None if i % 40 == 0 else generate_uuid(),
                        "sender_user_id": speaker,
                        "sender_player_id": None if i % 40 == 0 else generate_uuid(),
                        "sender_display_name_snapshot": "S",
                        "sender_is_anonymous_snapshot": True,
                        "is_spectator": False,
                        "message_kind": "chat",
                        "audience": "lobby" if i % 40 == 0 else "room",
                        "audience_user_ids": [],
                        "text": f"line {i}",
                        "created_at": now - timedelta(seconds=i),
                        "expires_at": now + timedelta(days=29),
                    }
                    for i in range(4_000)
                ],
            )
            await session.execute(
                insert(EmailOutboxEntry),
                [
                    {
                        "id": generate_uuid(),
                        "user_id": speaker,
                        "to_address": "a@b.c",
                        "template": "verify_email",
                        "payload": {},
                        "state": "pending" if i % 100 == 0 else "sent",
                        "attempts": 1,
                        "next_attempt_at": now,
                        "sent_at": None if i % 100 == 0 else now - timedelta(days=i % 60),
                        "created_at": now - timedelta(days=i % 60),
                    }
                    for i in range(4_000)
                ],
            )
            await session.execute(
                insert(UserBan),
                [
                    {
                        "id": generate_uuid(),
                        "user_id": speaker,
                        "banned_by_user_id": speaker,
                        "reason": "spam",
                        "is_active": i % 20 == 0,
                        "expires_at": None,
                        "created_at": now - timedelta(minutes=i),
                    }
                    for i in range(4_000)
                ],
            )
        await session.execute(text("ANALYZE room_messages"))
        await session.execute(text("ANALYZE email_outbox"))
        await session.execute(text("ANALYZE user_bans"))
        await session.commit()


@pytest.mark.skipif(not ON_POSTGRESQL, reason="plans are PostgreSQL's")
async def test_the_lobby_restore_and_the_sent_purge_use_their_partial_indexes():
    from sqlalchemy import func, literal, select

    from app.db.models import EmailOutboxEntry, RoomMessage, UserBan
    from app.auth.bans import active_ban_filter
    from app.domain_values import EmailOutboxState

    factory, engine = await create_test_db()
    try:
        now = datetime.now(timezone.utc)
        await _seed(factory, now)
        async with factory() as session:
            lobby = (
                select(RoomMessage.id)
                .where(
                    RoomMessage.audience == literal("lobby", literal_execute=True),
                    RoomMessage.expires_at > now,
                )
                .order_by(RoomMessage.created_at.desc(), RoomMessage.id.desc())
                .limit(50)
            )
            assert "ix_room_messages_lobby_newest" in await _plan_of(session, lobby)

            # A bound value matches too while PostgreSQL plans each execution
            # with the value in hand; a generic plan for a prepared statement
            # cannot prove `audience = $1` implies the predicate, which is why
            # the application inlines the literal rather than relying on it.
            sent = (
                select(EmailOutboxEntry.id)
                .where(
                    EmailOutboxEntry.state
                    == literal(EmailOutboxState.SENT.value, literal_execute=True),
                    EmailOutboxEntry.sent_at <= now - timedelta(days=30),
                )
                .order_by(EmailOutboxEntry.sent_at, EmailOutboxEntry.id)
                .limit(500)
            )
            assert "ix_email_outbox_sent_at_sent" in await _plan_of(session, sent)

            bans = (
                select(UserBan.id)
                .where(*active_ban_filter(now))
                .order_by(UserBan.created_at.desc())
                .limit(50)
            )
            assert "ix_user_bans_active_newest" in await _plan_of(session, bans)
            assert func is not None
    finally:
        await engine.dispose()
