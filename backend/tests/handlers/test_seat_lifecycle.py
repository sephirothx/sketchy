"""One socket, one seat.

A connection that enters a second room must give up the first, and a
disconnect must reconcile against every seat the socket actually holds -
otherwise a re-entry strands a `Room`, a `Player` and a claimed room code for
the life of the process.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import socketio

from app.handlers import register_all_handlers as register_handlers
from app.repositories.interfaces import ResolvedPromptSelection
from app.rooms import RoomManager
from tests.handlers.helpers import SessionStore


def build_stack(room_manager: RoomManager, **kwargs):
    """A handler stack whose socket sessions actually persist."""
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


def emitted(sio, event: str) -> list[tuple]:
    return [
        call.args
        for call in sio.emit.await_args_list
        if call.args and call.args[0] == event
    ]


@pytest.mark.asyncio
async def test_creating_a_second_room_releases_the_seat_in_the_first():
    room_manager = RoomManager()
    ctx, sio, _ = build_stack(room_manager)
    ctx.room_codes = SimpleNamespace(
        allocate=AsyncMock(side_effect=["FIRST1", "SECOND"]),
        release_unpublished=AsyncMock(),
        retire_ephemeral=AsyncMock(),
        is_retired=AsyncMock(return_value=False),
    )
    create_room = sio.handlers["/"]["create_room"]

    first = await create_room("sid-A", {"nickname": "Host", "name": "First"})
    second = await create_room("sid-A", {"nickname": "Host", "name": "Second"})

    assert first["roomId"] != second["roomId"]
    assert room_manager.get_room(first["roomId"]) is None, "the first room leaked"
    assert list(room_manager.rooms) == [second["roomId"]]
    # The abandoned room's code has to go back, or the reservation outlives it.
    ctx.room_codes.retire_ephemeral.assert_awaited_once_with("FIRST1")


@pytest.mark.asyncio
async def test_joining_another_room_leaves_the_previous_one_running():
    """The room the socket walked out of keeps playing, minus that seat."""
    room_manager = RoomManager()
    ctx, sio, _ = build_stack(room_manager)
    create_room = sio.handlers["/"]["create_room"]
    join_room = sio.handlers["/"]["join_room"]

    first = await create_room("sid-A", {"nickname": "Ann", "name": "First"})
    await join_room("sid-B", {"roomId": first["roomId"], "nickname": "Bob"})
    second = await create_room("sid-C", {"nickname": "Cal", "name": "Second"})

    moved = await join_room("sid-A", {"roomId": second["roomId"], "nickname": "Ann"})

    old = room_manager.get_room(first["roomId"])
    assert old is not None, "the room still holding Bob was torn down"
    assert [p.nickname for p in old.player_list()] == ["Bob"]
    assert next(iter(old.player_list())).is_host is True
    assert ("player_left", {"playerId": first["playerId"]}) in [
        (args[0], args[1]) for args in emitted(sio, "player_left")
    ]
    new = room_manager.get_room(second["roomId"])
    assert new is not None
    assert sorted(p.nickname for p in new.player_list()) == ["Ann", "Cal"]
    assert new.players[moved["playerId"]].sid == "sid-A"


@pytest.mark.asyncio
async def test_a_refused_create_keeps_the_seat_the_socket_already_had():
    """The old seat is only given up once the new one is certain."""

    class HalfReachablePromptListRepo:
        """Answers for the default list, unreachable for the one the host asks for."""

        async def resolve_selection(
            self, slugs, *, requesting_user_id=None, share_codes=()
        ):
            if "safari" in slugs:
                raise RuntimeError("prompt store is unreachable")
            return ResolvedPromptSelection(
                slugs=tuple(slugs), language="en", prompts=("apple", "boat")
            )

        async def record_prompt_usage(self, slugs, usage):
            return None

    room_manager = RoomManager()
    ctx, sio, _ = build_stack(
        room_manager, prompt_list_repo=HalfReachablePromptListRepo()
    )
    create_room = sio.handlers["/"]["create_room"]

    first = await create_room("sid-A", {"nickname": "Host", "name": "First"})
    refused = await create_room(
        "sid-A", {"nickname": "Host", "promptListSlugs": ["safari"]}
    )

    assert refused["ok"] is False
    room = room_manager.get_room(first["roomId"])
    assert room is not None
    seat = room.players[first["playerId"]]
    assert seat.connected is True and seat.sid == "sid-A"


@pytest.mark.asyncio
async def test_disconnect_reconciles_every_room_the_socket_sits_in():
    """Even a seat the session no longer names has to become disconnected."""
    room_manager = RoomManager()
    ctx, sio, sessions = build_stack(room_manager)

    stranded = room_manager.create_room(name="Stranded")
    ghost = room_manager.add_player(stranded, "Ghost")
    ghost.sid = "sid-A"

    current = room_manager.create_room(name="Current")
    seat = room_manager.add_player(current, "Seated")
    seat.sid = "sid-A"
    await sessions.save(
        "sid-A", {"room_id": current.id, "player_id": seat.id, "user_id": None}
    )

    await sio.handlers["/"]["disconnect"]("sid-A")

    assert ghost.connected is False and ghost.sid is None
    assert seat.connected is False and seat.sid is None
    assert stranded.connected_players() == []
    assert await ctx.remove_room_if_empty(stranded.id) is True
    await ctx.timers.close()


@pytest.mark.asyncio
async def test_racing_creates_on_one_socket_still_leave_a_single_seat():
    room_manager = RoomManager()
    ctx, sio, _ = build_stack(room_manager)

    async def slow_allocate(kind):
        # A real allocation reaches the database, which is exactly the gap a
        # second create_room from the same socket slips into.
        await asyncio.sleep(0.01)
        return f"CODE{len(room_manager.rooms)}{kind[0].upper()}"

    ctx.room_codes = SimpleNamespace(
        allocate=AsyncMock(side_effect=slow_allocate),
        release_unpublished=AsyncMock(),
        retire_ephemeral=AsyncMock(),
        is_retired=AsyncMock(return_value=False),
    )
    create_room = sio.handlers["/"]["create_room"]

    await asyncio.gather(
        create_room("sid-A", {"nickname": "Host", "name": "One"}),
        create_room("sid-A", {"nickname": "Host", "name": "Two"}),
    )

    assert len(room_manager.rooms) == 1
    seats = [p for room in room_manager.rooms.values() for p in room.player_list()]
    assert len(seats) == 1


@pytest.mark.asyncio
async def test_a_socket_that_drops_while_creating_leaves_no_connected_seat():
    """The disconnect can win the race with the join it interrupts."""
    room_manager = RoomManager()
    ctx, sio, _ = build_stack(room_manager)
    disconnect = sio.handlers["/"]["disconnect"]
    dropped: list[asyncio.Task] = []

    async def allocate_then_drop(kind):
        dropped.append(asyncio.create_task(disconnect("sid-A")))
        # Let the disconnect run as far as it can while this is in flight.
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        return "CODE01"

    ctx.room_codes = SimpleNamespace(
        allocate=AsyncMock(side_effect=allocate_then_drop),
        release_unpublished=AsyncMock(),
        retire_ephemeral=AsyncMock(),
        is_retired=AsyncMock(return_value=False),
    )

    response = await sio.handlers["/"]["create_room"](
        "sid-A", {"nickname": "Host", "name": "Room"}
    )
    await asyncio.gather(*dropped)

    room = room_manager.get_room(response["roomId"])
    assert room is not None
    assert room.connected_players() == [], "a dead socket kept a connected seat"
    await ctx.timers.close()


@pytest.mark.asyncio
async def test_two_sockets_superseding_each_other_do_not_wait_for_each_other():
    """Cutting off a displaced tab runs its disconnect handler inline.

    Two tabs of one account reaching the same seat at the same moment each
    close the other, so a disconnect that queued at the closing socket's
    seating gate would leave both waiting for a gate the other holds.
    """
    room_manager = RoomManager()
    ctx, sio, sessions = build_stack(room_manager)
    room = room_manager.create_room(name="Studio")
    seat = room_manager.add_player(room, "Ann", user_id="user-1")
    seat.sid = "sid-B"

    async def close_socket(target, *_args, **_kwargs):
        # What Socket.IO does: the displaced socket's disconnect handler runs
        # inline, from inside the join that displaced it.
        await sio.handlers["/"]["disconnect"](target)

    sio.disconnect = AsyncMock(side_effect=close_socket)
    async def yield_control(*_args, **_kwargs):
        # The one await in the join that really does hand the loop back, which
        # is what lets the two joins interleave at all.
        await asyncio.sleep(0)

    sio.enter_room = AsyncMock(side_effect=yield_control)
    for sid in ("sid-A", "sid-B"):
        await sessions.save(sid, {"user_id": "user-1"})

    join_room = sio.handlers["/"]["join_room"]
    try:
        await asyncio.wait_for(
            asyncio.gather(
                join_room("sid-A", {"roomId": room.id, "nickname": "Ann"}),
                join_room("sid-B", {"roomId": room.id, "nickname": "Ann"}),
            ),
            timeout=2,
        )
    except asyncio.TimeoutError:  # pragma: no cover - the regression itself
        pytest.fail("two sockets superseding each other deadlocked")

    assert len(room.players) == 1
    # Whichever socket lost the race left nothing of itself behind on the seat.
    assert room_manager.seats_for_sid("sid-A") + room_manager.seats_for_sid(
        "sid-B"
    ) in ([], [(room, seat)])
    await ctx.timers.close()


@pytest.mark.asyncio
async def test_reclaiming_a_stranded_seat_keeps_the_binding_to_the_room_sat_in():
    """Giving up a seat somewhere else must not unseat the socket here.

    A client heartbeats through the same-room confirmation, and that entry
    never re-saves the session afterwards - so clearing the binding there
    leaves a player everybody can see but who can no longer act.
    """
    room_manager = RoomManager()
    ctx, sio, sessions = build_stack(room_manager)

    home = await sio.handlers["/"]["create_room"]("sid-A", {"nickname": "Ann"})
    stranded = room_manager.create_room(name="Stranded")
    room_manager.add_player(stranded, "Ann").sid = "sid-A"

    await sio.handlers["/"]["join_room"](
        "sid-A", {"roomId": home["roomId"], "nickname": "Ann", "soft": True}
    )

    assert room_manager.get_room(stranded.id) is None, "the stranded room survived"
    assert sessions.sessions["sid-A"]["room_id"] == home["roomId"]
    assert await ctx.game_flow.require_current_player("sid-A") is not None


@pytest.mark.asyncio
async def test_leaving_the_room_the_session_names_drops_its_binding():
    """The other half of the same rule, which the leave path relies on."""
    room_manager = RoomManager()
    ctx, sio, sessions = build_stack(room_manager)

    await sio.handlers["/"]["create_room"]("sid-A", {"nickname": "Ann"})
    await sio.handlers["/"]["leave_room"]("sid-A")

    assert sessions.sessions["sid-A"] == {"user_id": sessions.account_for("sid-A")}
    assert await ctx.game_flow.require_current_player("sid-A") is None
