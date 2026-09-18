"""Quick play joins (#589, R-UX-14): only a room still public and waiting."""

from unittest.mock import AsyncMock

import socketio

from app.handlers import register_all_handlers as register_handlers
from app.handlers import rooms as room_handlers
from app.rooms import RoomManager


def server(room_manager):
    sio = socketio.AsyncServer(async_mode="asgi")
    ctx = register_handlers(sio, room_manager)
    sio.get_session = AsyncMock(return_value={})
    sio.save_session = AsyncMock()
    sio.enter_room = AsyncMock()
    sio.emit = AsyncMock()
    return sio, ctx


def waiting_room(room_manager, *, is_public=True):
    room = room_manager.create_room(name="Room", is_public=is_public)
    host = room_manager.add_player(room, "Host")
    host.sid = "host-sid"
    return room


def join(sio, room, **extra):
    return sio.handlers["/"]["join_room"](
        "guest-sid", {"roomId": room.id, "nickname": "Marta", "quickPlay": True, **extra}
    )


async def test_a_public_waiting_room_takes_a_quick_play_seat():
    room_manager = RoomManager()
    room = waiting_room(room_manager)
    sio, _ = server(room_manager)

    response = await join(sio, room)

    assert response["ok"] is True
    assert len([p for p in room.players.values() if not p.is_spectator]) == 2


async def test_a_game_under_way_is_refused_to_quick_play_but_not_to_an_ordinary_join():
    room_manager = RoomManager()
    room = waiting_room(room_manager)
    room.state = "playing"
    sio, _ = server(room_manager)

    refused = await join(sio, room)
    assert refused["ok"] is False
    assert refused["errorCode"] == "room_not_open"
    assert len(room.players) == 1

    # The ordinary join still admits a game in progress, as it always has.
    admitted = await sio.handlers["/"]["join_room"](
        "guest-sid", {"roomId": room.id, "nickname": "Marta"}
    )
    assert admitted["ok"] is True


async def test_a_private_room_is_refused_to_quick_play():
    room_manager = RoomManager()
    room = waiting_room(room_manager, is_public=False)
    sio, _ = server(room_manager)

    refused = await join(sio, room)

    assert refused["errorCode"] == "room_not_open"
    assert len(room.players) == 1


async def test_a_room_that_starts_while_the_joiner_is_being_named_is_refused_and_the_join_refunded(
    monkeypatch,
):
    """The host can start between the room being resolved and the seat being
    added - resolving the identity awaits - so the check that counts is the one
    with nothing awaited between it and the seat."""
    room_manager = RoomManager()
    room = waiting_room(room_manager)
    sio, ctx = server(room_manager)
    real_resolve = room_handlers.resolve_identity

    async def host_starts_meanwhile(*args, **kwargs):
        identity = await real_resolve(*args, **kwargs)
        room.state = "playing"
        return identity

    monkeypatch.setattr(room_handlers, "resolve_identity", host_starts_meanwhile)
    refunded = []
    real_refund = ctx.room_capacity.refund_join
    monkeypatch.setattr(
        ctx.room_capacity, "refund_join", lambda sid: (refunded.append(sid), real_refund(sid))
    )

    refused = await join(sio, room)

    assert refused["errorCode"] == "room_not_open"
    assert len(room.players) == 1
    assert refunded == ["guest-sid"], "a refused seat does not spend the join allowance"


async def test_quick_play_is_a_player_seat_by_room_id_only():
    room_manager = RoomManager()
    room = waiting_room(room_manager)
    sio, _ = server(room_manager)

    by_code = await sio.handlers["/"]["join_room"](
        "guest-sid", {"code": room.code, "nickname": "Marta", "quickPlay": True}
    )
    as_spectator = await join(sio, room, asSpectator=True)

    assert by_code["errorCode"] == "invalid_payload"
    assert as_spectator["errorCode"] == "invalid_payload"
    assert len(room.players) == 1
