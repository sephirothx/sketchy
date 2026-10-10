"""The inbox from the socket's side (#1436): a warning not yet acknowledged
holds every new seat back, and an invitation leaves an entry behind it.

The gate is on the server so another tab, or a client that never shows the
dialog, cannot skip it (R-INBOX-04); a seat the account already holds is taken
back whatever arrived meanwhile, so a warning issued mid-game never strands a
player who dropped and reconnected.
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
import socketio
from sqlalchemy import select

from app.auth.warnings import has_unacknowledged_warning
from app.db.models import InboxEntry, User, UserWarning, generate_uuid
from app.handlers import register_all_handlers as register_handlers
from app.handlers import rooms as room_handlers
from app.rooms import RoomManager
from tests.dbfixtures import create_test_db
from tests.handlers.helpers import SessionStore
from tests.handlers.test_friends import ADA, BOB, StubFriendService, seat_host


def server(room_manager, **kwargs):
    sio = socketio.AsyncServer(async_mode="asgi")
    ctx = register_handlers(sio, room_manager, **kwargs)
    sessions = SessionStore()
    sio.get_session = AsyncMock(side_effect=sessions.get)
    sio.save_session = AsyncMock(side_effect=sessions.save)
    sio.enter_room = AsyncMock()
    sio.leave_room = AsyncMock()
    sio.disconnect = AsyncMock()
    sio.emit = AsyncMock()
    return sio, ctx, sessions


@pytest.fixture
def warned(monkeypatch):
    """The accounts holding a warning they have not acknowledged."""
    accounts: set[str] = set()

    async def holds(_factory, user_id):
        return user_id in accounts

    monkeypatch.setattr(room_handlers, "has_unacknowledged_warning", holds)
    return accounts


REFUSED = {
    "ok": False,
    "errorCode": "warning_unread",
    "error": "Read your moderator warning first.",
    "params": {"action": "play"},
}


def seated(room) -> int:
    return len([p for p in room.players.values() if not p.is_spectator])


async def test_a_warning_holds_back_every_new_seat(warned):
    room_manager = RoomManager()
    room = room_manager.create_room(name="Room", is_public=True, max_players=8)
    host = room_manager.add_player(room, "Host")
    host.sid = "host-sid"
    sio, ctx, _ = server(room_manager)
    ctx.session_factory = object()  # what the gate checks for; the read is stubbed
    warned.add("user-warned-sid")

    handlers = sio.handlers["/"]
    assert await handlers["quick_play"]("warned-sid", {"nickname": "Wren"}) == REFUSED
    assert await handlers["join_room"]("warned-sid", {"code": room.code, "nickname": "Wren"}) == REFUSED
    assert await handlers["join_room"](
        "warned-sid", {"code": room.code, "nickname": "Wren", "asSpectator": True}
    ) == REFUSED
    assert await handlers["create_room"]("warned-sid", {"nickname": "Wren", "name": "Mine"}) == REFUSED
    assert seated(room) == 1 and len(room_manager.rooms) == 1

    # Anybody else walks straight in.
    joined = await handlers["join_room"]("other-sid", {"code": room.code, "nickname": "Otto"})
    assert joined["ok"] is True and seated(room) == 2


async def test_a_seat_the_account_already_holds_is_taken_back_whatever_arrived(warned):
    """Warned mid-game, then the connection dropped: the reconnect takes the
    seat back, and the dialog waits for the game to end (R-INBOX-02)."""
    room_manager = RoomManager()
    room = room_manager.create_room(name="Room", is_public=True, max_players=8)
    sio, ctx, sessions = server(room_manager)
    ctx.session_factory = object()

    first = await sio.handlers["/"]["join_room"]("phone-sid", {"code": room.code, "nickname": "Pia"})
    assert first["ok"] is True
    warned.add("user-phone-sid")
    # The same account, back on a new socket.
    sessions.sessions["phone-sid-2"] = {"user_id": "user-phone-sid"}
    again = await sio.handlers["/"]["join_room"]("phone-sid-2", {"code": room.code, "nickname": "Pia"})
    assert again["ok"] is True and again["playerId"] == first["playerId"]


async def test_the_gate_reads_only_warnings_not_yet_acknowledged():
    factory, engine = await create_test_db()
    try:
        user_id = generate_uuid()
        async with factory() as session:
            async with session.begin():
                session.add(User(id=user_id, display_name="Wren", state="anonymous"))
                await session.flush()
                warning = UserWarning(id=generate_uuid(), user_id=user_id, reason="Tone.")
                session.add(warning)
        assert await has_unacknowledged_warning(factory, str(user_id))
        async with factory() as session:
            async with session.begin():
                row = await session.get(UserWarning, warning.id)
                row.acknowledged_at = datetime.now(timezone.utc)
        assert not await has_unacknowledged_warning(factory, str(user_id))
        assert not await has_unacknowledged_warning(factory, None)
        assert not await has_unacknowledged_warning(factory, "not-an-id")
    finally:
        await engine.dispose()


async def test_an_invitation_is_in_the_friends_inbox_too():
    """Sent while they were away, it is still there to read; the token stays
    with the live card, and the entry says only who asked and until when."""
    factory, engine = await create_test_db()
    try:
        async with factory() as session:
            async with session.begin():
                for user_id, name in ((ADA, "Ada"), (BOB, "Bob")):
                    session.add(
                        User(id=UUID(user_id), display_name=name, state="anonymous")
                    )
        room_manager = RoomManager()
        sio, ctx, sessions = server(room_manager, friend_service=StubFriendService(friends=[(ADA, BOB)]))
        ctx.session_factory = factory
        ctx.on_inbox_changed = AsyncMock()
        room = room_manager.create_room(name="Studio", is_public=False)
        me = await seat_host(room_manager, room, ADA, "Ada")
        me.sid = "sid-ada"
        await sessions.save("sid-ada", {"room_id": room.id, "player_id": me.id})

        for _ in range(2):
            answer = await sio.handlers["/"]["invite_friend"]("sid-ada", {"friendUserId": BOB})
            assert answer == {"ok": True}

        async with factory() as session:
            [entry] = (await session.scalars(select(InboxEntry))).all()
        assert (str(entry.user_id), entry.kind, str(entry.subject_id)) == (BOB, "game_invite", ADA)
        assert set(entry.params) == {"expiresAt"}, "no token, no room in the record"
        ctx.on_inbox_changed.assert_awaited_with(BOB)
    finally:
        await engine.dispose()
