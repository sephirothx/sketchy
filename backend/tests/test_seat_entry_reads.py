"""Taking a seat reads the account once and writes activity once (#980)."""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import event

from app.db.models import IdentityAlias, UserSettings
from app.repositories.sqlalchemy import SqlAlchemyUserRepository

from tests.dbfixtures import create_test_db


def _count_statements(engine) -> list[str]:
    statements: list[str] = []

    def count(_conn, _cursor, statement, *_args):
        statements.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", count)
    return statements


async def test_the_seat_account_and_its_colour_preference_are_one_statement():
    factory, engine = await create_test_db()
    try:
        users = SqlAlchemyUserRepository(factory)
        plain = await users.create_anonymous("Plain")
        careful = await users.create_anonymous("Careful")
        async with factory() as session:
            async with session.begin():
                session.add(UserSettings(user_id=UUID(careful.id), colorblind_safe_colors=True))
        statements = _count_statements(engine)

        account, colorblind = await users.get_seat_account(careful.id)
        assert (account.id, colorblind) == (careful.id, True)
        assert len(statements) == 1

        # No settings row reads as the default, not as "unknown".
        assert (await users.get_seat_account(plain.id))[1] is False
        assert await users.get_seat_account("not-a-uuid") == (None, None)
    finally:
        await engine.dispose()


async def test_a_merged_guest_is_seated_as_the_account_it_became():
    factory, engine = await create_test_db()
    try:
        users = SqlAlchemyUserRepository(factory)
        guest = await users.create_anonymous("Guest")
        account = await users.create_anonymous("Account")
        async with factory() as session:
            async with session.begin():
                session.add(IdentityAlias(source_user_id=UUID(guest.id), target_user_id=UUID(account.id)))
        seated, _ = await users.get_seat_account(guest.id)
        assert seated.id == account.id == (await users.get_by_id(guest.id)).id
    finally:
        await engine.dispose()


async def test_recording_activity_is_one_statement():
    """It was a SELECT and then an UPDATE through the ORM, on every seat."""
    factory, engine = await create_test_db()
    try:
        users = SqlAlchemyUserRepository(factory)
        guest = await users.create_anonymous("Player")
        statements = _count_statements(engine)
        touched = await users.touch_last_active(guest.id)
        assert touched is not None and touched.id == guest.id and touched.last_active_at is not None
        assert len(statements) == 1 and statements[0].lstrip().upper().startswith("UPDATE")
        assert await users.touch_last_active("01920000-0000-7000-8000-000000000000") is None
    finally:
        await engine.dispose()


USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 Version/17.5 Safari/605.1.15"


async def _entry_env():
    """Handlers over a real database: the account, its session, its settings."""
    from unittest.mock import AsyncMock

    import socketio

    from app.auth.blocks import BlockService
    from app.auth.sessions import create_session
    from app.handlers import register_all_handlers
    from app.rooms import RoomManager

    factory, engine = await create_test_db()
    users = SqlAlchemyUserRepository(factory)
    account = await users.create_anonymous("Careful")
    async with factory() as session:
        async with session.begin():
            from app.db.models import User

            row = await session.get(User, UUID(account.id))
            row.username = "CarefulPlayer"
            row.password_hash = "x"
            row.state = "registered"
            session.add(UserSettings(user_id=UUID(account.id), colorblind_safe_colors=True))
    from app.auth.sessions import device_label_from_user_agent

    issued = await create_session(
        factory, user_id=account.id, device_label=device_label_from_user_agent(USER_AGENT)
    )
    room_manager = RoomManager()
    sio = socketio.AsyncServer(async_mode="asgi")
    ctx = register_all_handlers(
        sio, room_manager, user_repo=users, session_factory=factory,
        block_service=BlockService(factory),
    )
    sio.emit = AsyncMock()
    sio.enter_room = AsyncMock()
    sio.leave_room = AsyncMock()
    sessions: dict[str, dict] = {}

    async def save_session(sid, data, namespace=None):
        sessions[sid] = dict(data)

    async def get_session(sid, namespace=None):
        return sessions.setdefault(sid, {})

    sio.save_session = save_session
    sio.get_session = get_session
    return factory, engine, users, account, issued.token, sio, ctx, room_manager


async def test_a_signed_in_handshake_and_a_registered_seat_cost_what_they_should():
    """Statement counts over the whole path, as #980 asks - not per function.

    The handshake: the session resolve, the lobby identity and the block list
    (the last two at once); the last-seen stamp is written on its own. Taking
    the seat: one read of the account with its colour preference, the block
    list already warm, and the activity stamp after the acknowledgement."""
    import asyncio

    from app.auth.sessions import cookie_name
    from app.handlers import rooms as rooms_handlers
    from app.handlers.connection import _last_seen_writes
    from app.protocol import PROTOCOL_VERSION

    factory, engine, users, account, token, sio, ctx, room_manager = await _entry_env()
    try:
        before = (await users.get_by_id(account.id)).last_active_at
        statements = _count_statements(engine)
        await sio.handlers["/"]["connect"](
            "sid-1",
            {"HTTP_COOKIE": f"{cookie_name()}={token}", "HTTP_USER_AGENT": USER_AGENT},
            {"protocol": PROTOCOL_VERSION},
        )
        await asyncio.gather(*_last_seen_writes)
        handshake = [s for s in statements if not s.lstrip().upper().startswith(("BEGIN", "COMMIT", "ROLLBACK"))]
        statements.clear()

        answer = await sio.handlers["/"]["create_room"]("sid-1", {"nickname": "ignored", "name": "Room"})
        assert answer["ok"] is True
        seat_before_stamp = list(statements)
        await asyncio.gather(*rooms_handlers._activity_writes)
        stamp = statements[len(seat_before_stamp):]

        player = room_manager.get_room(answer["roomId"]).players[answer["playerId"]]
        assert player.nickname == "CarefulPlayer"
        assert player.colorblind_safe_colors is True, "read from the stored preference"
        assert [s for s in stamp if s.lstrip().upper().startswith("UPDATE USERS")], "the activity stamp lands"
        assert (await users.get_by_id(account.id)).last_active_at > before
        # The handshake, whole: the session, the account's lobby identity and
        # its block list (read together), and the last-seen stamp.
        def kinds(group):
            return sorted(" ".join(statement.split())[:40] for statement in group)

        assert len(handshake) == 4, kinds(handshake)
        assert sum("FROM auth_sessions" in s for s in handshake) == 1
        assert sum("FROM user_blocks" in s for s in handshake) == 1
        assert sum(s.lstrip().startswith("SELECT users.") for s in handshake) == 1
        # The seat, as far as the account goes: one read of it with its
        # preference, no read of the settings alone, and no second read of
        # the block list the handshake already warmed. (The rest of a
        # `create_room` - its rate limit and its invite code - is the room's.)
        account_reads = [s for s in seat_before_stamp if s.lstrip().startswith("SELECT users.")]
        assert len(account_reads) == 1 and "user_settings" in account_reads[0]
        assert not any(s.lstrip().startswith("SELECT user_settings.") for s in seat_before_stamp)
        assert not any("FROM user_blocks" in s for s in seat_before_stamp)
    finally:
        await ctx.timers.close()
        await engine.dispose()
