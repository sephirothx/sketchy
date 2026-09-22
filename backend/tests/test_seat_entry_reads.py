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
            # A stored colour, so an assertion about the colour the rebind
            # returns is about something (#980 third review).
            row.name_color = "#4f7cff"
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
        before_tasks = {"seen": set(_last_seen_writes), "activity": set(rooms_handlers._activity_writes)}
        statements = _count_statements(engine)
        await sio.handlers["/"]["connect"](
            "sid-1",
            {"HTTP_COOKIE": f"{cookie_name()}={token}", "HTTP_USER_AGENT": USER_AGENT},
            {"protocol": PROTOCOL_VERSION},
        )
        await asyncio.gather(*list(_last_seen_writes - before_tasks["seen"]))
        handshake = [s for s in statements if not s.lstrip().upper().startswith(("BEGIN", "COMMIT", "ROLLBACK"))]
        statements.clear()

        # The stamp is held until the acknowledgement is in hand, so "after
        # the answer" is a fact about this run rather than about which awaits
        # happened not to yield (#980 third review): with a 50 ms warm-up in
        # the handler the write used to land in the middle of it.
        release = asyncio.Event()
        real_stamp = users.touch_last_active

        async def stalled_stamp(user_id):
            await release.wait()
            return await real_stamp(user_id)

        users.touch_last_active = stalled_stamp
        answer = await sio.handlers["/"]["create_room"]("sid-1", {"nickname": "ignored", "name": "Room"})
        assert answer["ok"] is True
        seat_before_stamp = list(statements)
        assert not [s for s in seat_before_stamp if s.lstrip().upper().startswith("UPDATE USERS")]
        release.set()
        users.touch_last_active = real_stamp
        await asyncio.gather(*list(set(rooms_handlers._activity_writes) - before_tasks["activity"]))
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


async def test_the_activity_stamp_lands_even_when_the_entry_ran_out_of_time():
    """The task is created with the entry's context, so the entry's six-second
    deadline followed it: under exactly the load this runs after, the stamp
    was dropped before reaching the database (#980 review)."""
    import asyncio

    from app.handlers import rooms as rooms_handlers

    factory, engine, users, account, token, sio, ctx, room_manager = await _entry_env()
    try:
        before = (await users.get_by_id(account.id)).last_active_at
        started_with = set(rooms_handlers._activity_writes)
        room = room_manager.create_room(name="Late")
        player = room_manager.add_player(room, "CarefulPlayer", user_id=account.id)
        # As if the entry had spent its whole deadline before seating.
        token_ = rooms_handlers._entry_deadline.set(asyncio.get_running_loop().time() - 1)
        try:
            await rooms_handlers._after_seating(ctx, [player])
        finally:
            rooms_handlers._entry_deadline.reset(token_)
        await asyncio.gather(*list(set(rooms_handlers._activity_writes) - started_with))
        assert (await users.get_by_id(account.id)).last_active_at > before
    finally:
        await ctx.timers.close()
        await engine.dispose()


async def test_a_guest_seat_keeps_the_preference_it_asked_for():
    """A guest has no settings row, so the stored answer must not overrule the
    payload: making the guest branch prefer the column passed every test
    before (#980 review)."""
    from app.handlers.identity import resolve_identity

    factory, engine, users, account, token, sio, ctx, room_manager = await _entry_env()
    try:
        guest = await users.create_anonymous("GuestSeat")
        await sio.save_session("sid-guest", {"user_id": guest.id})
        identity = await resolve_identity(
            ctx, "sid-guest", "ignored", requested_colorblind_safe_colors=True
        )
        assert identity.is_anonymous and identity.nickname == "GuestSeat"
        assert identity.colorblind_safe_colors is True
        plain = await resolve_identity(
            ctx, "sid-guest", "ignored", requested_colorblind_safe_colors=False
        )
        assert plain.colorblind_safe_colors is False
    finally:
        await ctx.timers.close()
        await engine.dispose()


async def test_a_returning_registered_seat_reads_its_account_once():
    """The rebind path asked for the settings row and the account one after
    the other - the pair the entry path merged, on the path a reconnect herd
    walks (#980 review).

    Driven through `join_room`, not through the helper: calling the helper
    directly proves the helper, and the call site can be put back to two
    serial reads with every test still passing (#980 third review).
    """
    factory, engine, users, account, token, sio, ctx, room_manager = await _entry_env()
    try:
        room = room_manager.create_room(name="Back")
        player = room_manager.add_player(room, "CarefulPlayer", user_id=account.id)
        player.is_anonymous = False
        player.name_color = "#111111"
        player.colorblind_safe_colors = False
        player.connected = False
        player.sid = "sid-gone"
        await sio.save_session("sid-back", {"user_id": account.id})

        statements = _count_statements(engine)
        answer = await sio.handlers["/"]["join_room"](
            "sid-back",
            {"roomId": room.id, "nickname": "ignored", "colorblindSafeColors": True},
        )

        assert answer["ok"] is True
        assert player.colorblind_safe_colors is True, "the stored preference, not the payload"
        assert player.name_color == "#4f7cff", "the colour stored on the account"
        reads = [s for s in statements if s.lstrip().startswith("SELECT users.")]
        assert len(reads) == 1 and "user_settings" in reads[0], reads
        assert not any(s.lstrip().startswith("SELECT user_settings.") for s in statements)
    finally:
        await ctx.timers.close()
        await engine.dispose()


async def test_a_seat_confirming_itself_reads_the_account_once_too():
    """The `already_joined` branch every soft rebind walks - a heartbeat, a
    tab coming back to the foreground - read the settings row on its own
    (#980 third review)."""
    factory, engine, users, account, token, sio, ctx, room_manager = await _entry_env()
    try:
        room = room_manager.create_room(name="Still here")
        player = room_manager.add_player(room, "CarefulPlayer", user_id=account.id)
        player.is_anonymous = False
        player.name_color = "#101010"
        player.sid = "sid-here"
        await sio.save_session(
            "sid-here",
            {"user_id": account.id, "room_id": room.id, "player_id": player.id},
        )

        statements = _count_statements(engine)
        answer = await sio.handlers["/"]["join_room"](
            "sid-here",
            {"roomId": room.id, "nickname": "ignored", "colorblindSafeColors": False, "soft": True},
        )

        assert answer["ok"] is True
        assert player.colorblind_safe_colors is True, "the stored preference, not the payload"
        # A heartbeat confirms a seat; it does not re-identify it.
        assert player.name_color == "#101010", "the confirm branch leaves the colour alone"
        assert not any(s.lstrip().startswith("SELECT user_settings.") for s in statements)
        reads = [s for s in statements if s.lstrip().startswith("SELECT users.")]
        assert len(reads) <= 1 and all("user_settings" in read for read in reads), reads
    finally:
        await ctx.timers.close()
        await engine.dispose()


async def test_a_seat_whose_account_is_gone_keeps_what_it_carries():
    """`(None, None)` means two different things - a repository that does not
    read the preference with the account, and an account that is not there.
    Conflated, a rebind for an erased account opened a second session to read
    settings that do not exist (#980 third review)."""
    from app.handlers.rooms import _rebound_account

    factory, engine, users, account, token, sio, ctx, room_manager = await _entry_env()
    try:
        room = room_manager.create_room(name="Gone")
        player = room_manager.add_player(room, "Vanished", user_id=account.id)
        player.is_anonymous = False
        player.colorblind_safe_colors = True

        async def no_such_account(_user_id):
            return None, None

        ctx.user_repo.get_seat_account = no_such_account
        statements = _count_statements(engine)
        colour, colorblind = await _rebound_account(ctx, player, requested=False)

        assert (colour, colorblind) == (None, True), "what the seat carries"
        assert statements == [], "and no second read for settings that are not there"
    finally:
        await ctx.timers.close()
        await engine.dispose()


async def test_a_repository_that_does_not_read_the_preference_falls_back(monkeypatch):
    """The default `get_seat_account` answers `(account, None)` - "I did not
    read the preference" - and the seat then reads it on its own rather than
    trusting the payload. Changing that fallback to the payload's value passed
    every test (#980 fourth review, R-SET-01)."""
    from app.handlers.rooms import _rebound_account

    factory, engine, users, account, token, sio, ctx, room_manager = await _entry_env()
    try:
        room = room_manager.create_room(name="Old repository")
        player = room_manager.add_player(room, "CarefulPlayer", user_id=account.id)
        player.is_anonymous = False
        player.colorblind_safe_colors = False

        async def without_the_preference(user_id):
            return await users.get_by_id(user_id), None

        ctx.user_repo.get_seat_account = without_the_preference

        colour, colorblind = await _rebound_account(ctx, player, requested=False)

        assert colour == "#4f7cff"
        assert colorblind is True, "read from the stored preference, not the payload"
    finally:
        await ctx.timers.close()
        await engine.dispose()


async def test_a_merged_read_that_stalls_leaves_the_seat_as_it_was():
    """A slow database must not hand a registered seat the payload's value -
    the spoof the resolution exists to prevent - and the merged read had no
    test for its own stall (#980 fourth review)."""
    import asyncio

    from app.handlers.rooms import _rebound_account

    factory, engine, users, account, token, sio, ctx, room_manager = await _entry_env()
    try:
        room = room_manager.create_room(name="Stalled")
        player = room_manager.add_player(room, "CarefulPlayer", user_id=account.id)
        player.is_anonymous = False
        player.name_color = "#111111"
        player.colorblind_safe_colors = True

        async def never(user_id):
            await asyncio.sleep(3600)

        ctx.user_repo.get_seat_account = never
        import app.handlers.rooms as rooms_handlers

        token_ = rooms_handlers._entry_deadline.set(asyncio.get_running_loop().time() - 1)
        try:
            colour, colorblind = await _rebound_account(ctx, player, requested=False)
        finally:
            rooms_handlers._entry_deadline.reset(token_)

        assert (colour, colorblind) == (None, True), "the seat keeps what it carries"
        assert player.name_color == "#111111"
    finally:
        await ctx.timers.close()
        await engine.dispose()
