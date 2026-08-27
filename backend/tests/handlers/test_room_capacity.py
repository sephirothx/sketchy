"""Ceilings on watchers, sockets, and how fast one may re-enter.

`max_players` only ever counted players, so a room could hold any number of
spectators, and every one of them was another recipient of every broadcast.
"""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
import socketio

from app.handlers import register_all_handlers as register_handlers
from app.rooms import RoomManager
from app.services.room_quotas import RoomCapacityService
from tests.handlers.helpers import SessionStore


def build_stack(room_manager: RoomManager, **kwargs):
    sio = socketio.AsyncServer(async_mode="asgi")
    ctx = register_handlers(sio, room_manager, **kwargs)
    sessions = SessionStore()
    sio.get_session = AsyncMock(side_effect=sessions.get)
    sio.save_session = AsyncMock(side_effect=sessions.save)
    sio.enter_room = AsyncMock()
    sio.leave_room = AsyncMock()
    sio.disconnect = AsyncMock()
    sio.emit = AsyncMock()
    return ctx, sio, sessions


async def open_room(sio, sessions, sid="host-sid"):
    await sessions.save(sid, {"user_id": f"user-{sid}"})
    return await sio.handlers["/"]["create_room"](sid, {"nickname": "Host"})


@pytest.mark.asyncio
async def test_a_room_takes_only_so_many_spectators():
    room_manager = RoomManager()
    ctx, sio, sessions = build_stack(room_manager)
    ctx.room_capacity = RoomCapacityService(environ={"ROOM_SPECTATOR_LIMIT": "2"})
    created = await open_room(sio, sessions)
    room = room_manager.get_room(created["roomId"])

    joins = []
    for index in range(3):
        sid = f"watcher-{index}"
        await sessions.save(sid, {"user_id": f"watcher-user-{index}"})
        joins.append(
            await sio.handlers["/"]["join_room"](
                sid,
                {"roomId": room.id, "nickname": f"Watcher{index}", "asSpectator": True},
            )
        )

    assert [join["ok"] for join in joins] == [True, True, False]
    assert "spectators" in joins[2]["error"]
    # `roomFull` is what makes the client offer spectating; offering it to
    # somebody refused as a spectator would be a loop.
    assert "roomFull" not in joins[2]
    assert len([p for p in room.player_list() if p.is_spectator]) == 2
    # Watching being full must not close the room to players.
    await sessions.save("player-sid", {"user_id": "player-user"})
    seated = await sio.handlers["/"]["join_room"](
        "player-sid", {"roomId": room.id, "nickname": "Player"}
    )
    assert seated["ok"] is True


@pytest.mark.asyncio
async def test_a_spectator_leaving_makes_room_for_another():
    room_manager = RoomManager()
    ctx, sio, sessions = build_stack(room_manager)
    ctx.room_capacity = RoomCapacityService(environ={"ROOM_SPECTATOR_LIMIT": "1"})
    created = await open_room(sio, sessions)
    room = room_manager.get_room(created["roomId"])

    await sessions.save("watcher-1", {"user_id": "watcher-user-1"})
    await sessions.save("watcher-2", {"user_id": "watcher-user-2"})
    first = await sio.handlers["/"]["join_room"](
        "watcher-1", {"roomId": room.id, "nickname": "One", "asSpectator": True}
    )
    assert first["ok"] is True
    refused = await sio.handlers["/"]["join_room"](
        "watcher-2", {"roomId": room.id, "nickname": "Two", "asSpectator": True}
    )
    assert refused["ok"] is False

    await sio.handlers["/"]["leave_room"]("watcher-1")
    allowed = await sio.handlers["/"]["join_room"](
        "watcher-2", {"roomId": room.id, "nickname": "Two", "asSpectator": True}
    )
    assert allowed["ok"] is True


@pytest.mark.asyncio
async def test_the_server_stops_accepting_sockets_past_its_ceiling():
    """Told rather than refused: a refusal carries no diagnosable signal, and
    ConnectionRefusedError is reserved for suspensions."""
    room_manager = RoomManager()
    ctx, sio, _ = build_stack(room_manager)
    ctx.room_capacity = RoomCapacityService(environ={"SOCKET_LIMIT": "2"})

    async def close_socket(target, *_args, **_kwargs):
        # What Socket.IO does: the handler runs inline from the close.
        await sio.handlers["/"]["disconnect"](target)

    sio.disconnect = AsyncMock(side_effect=close_socket)

    for sid in ("first", "second"):
        await sio.handlers["/"]["connect"](sid, {}, None)
    await sio.handlers["/"]["connect"]("third", {}, None)

    refusals = [
        call.args
        for call in sio.emit.await_args_list
        if call.args and call.args[0] == "server_full"
    ]
    assert len(refusals) == 1
    assert sio.disconnect.await_args_list[-1].args[0] == "third"

    # A socket that leaves gives its place back.
    await sio.handlers["/"]["disconnect"]("first")
    await sio.handlers["/"]["connect"]("fourth", {}, None)
    assert len([
        call for call in sio.emit.await_args_list
        if call.args and call.args[0] == "server_full"
    ]) == 1


@pytest.mark.asyncio
async def test_one_socket_cannot_hammer_the_join_path():
    room_manager = RoomManager()
    ctx, sio, sessions = build_stack(room_manager)
    ctx.room_capacity = RoomCapacityService(environ={"ROOM_JOIN_LIMIT": "2"})
    rooms = [
        room_manager.get_room(
            (await open_room(sio, sessions, f"host-{index}"))["roomId"]
        )
        for index in range(3)
    ]
    await sessions.save("joiner", {"user_id": "joiner-user"})

    results = [
        await sio.handlers["/"]["join_room"](
            "joiner", {"roomId": room.id, "nickname": "Joiner"}
        )
        for room in rooms
    ]

    assert [result["ok"] for result in results] == [True, True, False]
    assert "too quickly" in results[2]["error"]


@pytest.mark.asyncio
async def test_confirming_a_seat_never_spends_the_join_allowance():
    """A client heartbeats through the same-room confirmation, and a liveness
    check must not be able to lock a player out of their own room."""
    room_manager = RoomManager()
    ctx, sio, sessions = build_stack(room_manager)
    ctx.room_capacity = RoomCapacityService(environ={"ROOM_JOIN_LIMIT": "2"})
    created = await open_room(sio, sessions)
    room = room_manager.get_room(created["roomId"])
    await sessions.save("joiner", {"user_id": "joiner-user"})

    seated = await sio.handlers["/"]["join_room"](
        "joiner", {"roomId": room.id, "nickname": "Joiner"}
    )
    assert seated["ok"] is True
    for _ in range(10):
        beat = await sio.handlers["/"]["join_room"](
            "joiner", {"roomId": room.id, "nickname": "Joiner", "soft": True}
        )
        assert beat["ok"] is True

    # One seating join was spent, so exactly one remains.
    other = room_manager.get_room((await open_room(sio, sessions, "host-2"))["roomId"])
    assert (
        await sio.handlers["/"]["join_room"](
            "joiner", {"roomId": other.id, "nickname": "Joiner"}
        )
    )["ok"] is True
