"""An entry answers inside the client's patience or creates nothing, and a repeat
of a creation is the same room (#879).

Every database step on the way into a room was bounded on its own, and creating
one takes four in a row - forty seconds against a client that gives up after
eight. Under a slow database the player was told it failed while the room was
made anyway. Deadlines here are scaled down; the ratios are the real ones.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.handlers.rooms import (
    CREATE_REQUEST_MEMORY_SECONDS,
    ENTRY_DEADLINE_SECONDS,
)
from app.rooms import RoomManager
from tests.test_entry_timeouts import build_stack

CLIENT_ACK_TIMEOUT_SECONDS = 8  # frontend/src/lib/socket.ts DEFAULT_ACK_TIMEOUT_MS


def stalls(seconds: float, answer=None):
    async def slow(*_args, **_kwargs):
        await asyncio.sleep(seconds)
        return answer

    return AsyncMock(side_effect=slow)


def codes(allocate):
    return SimpleNamespace(
        allocate=allocate,
        release_unpublished=AsyncMock(),
        retire_ephemeral=AsyncMock(),
        is_retired=AsyncMock(return_value=False),
    )


@pytest.fixture
def scaled(monkeypatch):
    """Six seconds against eight, as a tenth of a second against more."""
    monkeypatch.setattr("app.handlers.rooms.ENTRY_DEADLINE_SECONDS", 0.3)


def test_the_deadline_leaves_the_answer_time_to_arrive():
    assert ENTRY_DEADLINE_SECONDS <= CLIENT_ACK_TIMEOUT_SECONDS - 2


async def test_one_step_past_the_deadline_is_a_refusal_and_no_room(scaled):
    """The issue's 'database stalled 9 s': one call that outlasts the deadline."""
    room_manager = RoomManager()
    ctx, sio, sessions = build_stack(room_manager)
    ctx.room_codes = codes(stalls(0.9, "ABCDEF"))
    await sessions.save("host", {"user_id": "user-1"})

    started = asyncio.get_running_loop().time()
    answer = await sio.handlers["/"]["create_room"]("host", {"nickname": "Host"})

    assert answer["ok"] is False and answer["errorCode"] == "database_busy"
    assert asyncio.get_running_loop().time() - started < 0.6
    assert room_manager.rooms == {}


async def test_steps_each_inside_their_own_bound_are_refused_whole_past_the_deadline(scaled):
    """The issue's 'stalled 3 s x3': every call alone is fine, together they are
    not - and the refusal gives back what the attempt spent."""
    room_manager = RoomManager()
    ctx, sio, sessions = build_stack(room_manager)
    ctx.room_quotas.check_creation_rate = stalls(0.12)
    ctx.room_quotas.refund_creation = AsyncMock()
    ctx.room_codes = codes(stalls(0.12, "ABCDEF"))
    real_settings = ctx.game_flow.room_settings_from_payload

    async def slow_settings(*args, **kwargs):
        await asyncio.sleep(0.12)
        return await real_settings(*args, **kwargs)

    ctx.game_flow.room_settings_from_payload = slow_settings
    await sessions.save("host", {"user_id": "user-1"})

    answer = await sio.handlers["/"]["create_room"]("host", {"nickname": "Host"})

    assert answer["ok"] is False and answer["errorCode"] == "database_busy"
    assert room_manager.rooms == {}
    ctx.room_quotas.refund_creation.assert_awaited_once_with("user-1")


async def test_a_join_past_the_deadline_takes_no_seat(scaled, monkeypatch):
    room_manager = RoomManager()
    ctx, sio, sessions = build_stack(room_manager)
    room = room_manager.create_room(name="Open", is_public=True)
    await sessions.save("guest", {"user_id": "user-2"})
    # A stall on the database step a join makes before seating.
    monkeypatch.setattr("app.handlers.rooms.resolve_identity", stalls(0.5))

    answer = await sio.handlers["/"]["join_room"]("guest", {"code": room.code, "nickname": "Guest"})

    assert answer["ok"] is False and answer["errorCode"] == "database_busy"
    assert room.players == {}


async def test_the_same_request_twice_is_one_room_and_the_same_answer():
    room_manager = RoomManager()
    ctx, sio, sessions = build_stack(room_manager)
    await sessions.save("first-socket", {"user_id": "user-1"})
    await sessions.save("second-socket", {"user_id": "user-1"})
    create = sio.handlers["/"]["create_room"]
    request = {"nickname": "Host", "requestId": "press-1"}

    first = await create("first-socket", request)
    # The answer was lost with the connection; the retry comes on a new socket.
    again = await create("second-socket", request)

    assert first["ok"] is True and again["ok"] is True
    assert len(room_manager.rooms) == 1
    assert again["roomId"] == first["roomId"] and again["playerId"] == first["playerId"]
    room = room_manager.get_room(first["roomId"])
    assert room.players[first["playerId"]].sid == "second-socket"


async def test_a_new_press_or_a_room_the_creator_left_is_a_new_room(monkeypatch):
    room_manager = RoomManager()
    ctx, sio, sessions = build_stack(room_manager)
    await sessions.save("host", {"user_id": "user-1"})
    create = sio.handlers["/"]["create_room"]

    first = await create("host", {"nickname": "Host", "requestId": "press-1"})
    other = await create("host", {"nickname": "Host", "requestId": "press-2"})
    assert other["roomId"] != first["roomId"]

    # Left, then the old press repeated: not theirs to be handed back.
    room = room_manager.get_room(other["roomId"])
    await sio.handlers["/"]["leave_room"]("host", None)
    assert room_manager.get_player_by_user_id(room, "user-1") is None
    third = await create("host", {"nickname": "Host", "requestId": "press-2"})
    assert third["roomId"] != other["roomId"]

    # And a remembered request is forgotten after a minute.
    import time as clock

    real_monotonic = clock.monotonic
    fourth = await create("host", {"nickname": "Host", "requestId": "press-3"})
    monkeypatch.setattr(
        "app.handlers.rooms.time.monotonic",
        lambda: real_monotonic() + CREATE_REQUEST_MEMORY_SECONDS + 1,
    )
    fifth = await create("host", {"nickname": "Host", "requestId": "press-3"})
    assert fifth["roomId"] != fourth["roomId"]


async def test_leaving_a_named_room_never_leaves_another():
    """A late 'you got in' is given back by name, so the room the player has
    entered since is not the one left."""
    room_manager = RoomManager()
    ctx, sio, sessions = build_stack(room_manager)
    await sessions.save("host", {"user_id": "user-1"})
    create = sio.handlers["/"]["create_room"]
    leave = sio.handlers["/"]["leave_room"]
    late = await create("host", {"nickname": "Host", "requestId": "late"})
    now = await create("host", {"nickname": "Host", "requestId": "now"})

    await leave("host", {"roomId": late["roomId"]})
    here = room_manager.get_room(now["roomId"])
    assert room_manager.get_player_by_user_id(here, "user-1") is not None

    await leave("host", {"roomId": now["roomId"]})
    assert room_manager.get_room(now["roomId"]) is None or room_manager.get_player_by_user_id(
        room_manager.get_room(now["roomId"]), "user-1"
    ) is None


async def test_two_copies_of_one_press_at_once_make_one_room():
    """A retry from the replacement socket while the first is still being
    made: different sockets, different seating gates, one room."""
    room_manager = RoomManager()
    ctx, sio, sessions = build_stack(room_manager)
    ctx.room_codes = codes(stalls(0.1, "ABCDEF"))
    await sessions.save("old-socket", {"user_id": "user-1"})
    await sessions.save("new-socket", {"user_id": "user-1"})
    create = sio.handlers["/"]["create_room"]
    request = {"nickname": "Host", "requestId": "press-1"}

    first, second = await asyncio.gather(
        create("old-socket", request), create("new-socket", request)
    )

    assert first["ok"] is True and second["ok"] is True
    assert len(room_manager.rooms) == 1
    assert first["roomId"] == second["roomId"]
    assert ctx.room_creations_in_flight == {}


async def test_a_copy_takes_its_own_leaders_room_whatever_the_memo_says(monkeypatch):
    """Another tab's creation can move the account's memo on before a waiting
    copy resumes; the copy reads its leader's room from the leader itself."""
    room_manager = RoomManager()
    ctx, sio, sessions = build_stack(room_manager)
    ctx.room_codes = codes(stalls(0.1, "ABCDEF"))
    await sessions.save("old-socket", {"user_id": "user-1"})
    await sessions.save("new-socket", {"user_id": "user-1"})
    # Every creation is remembered as some other press - as if another tab's
    # had landed in between.
    real_remember = __import__("app.handlers.rooms", fromlist=["x"])._remember_creation
    monkeypatch.setattr(
        "app.handlers.rooms._remember_creation",
        lambda ctx, user_id, request_id, room_id: real_remember(ctx, user_id, "other-tab", room_id),
    )
    create = sio.handlers["/"]["create_room"]
    request = {"nickname": "Host", "requestId": "press-1"}

    first, second = await asyncio.gather(
        create("old-socket", request), create("new-socket", request)
    )

    assert first["ok"] is True and second["ok"] is True
    assert len(room_manager.rooms) == 1 and first["roomId"] == second["roomId"]


async def test_a_hung_teardown_of_the_room_left_behind_neither_blocks_nor_refuses_the_entry(
    scaled, monkeypatch
):
    """Moving to a new room tears the old one down, and its durable half - the
    abandoned game, the code retirement - can wait on the database. It runs on
    its own now: the entry answers inside its deadline, and the gate is free."""
    monkeypatch.setattr("app.handlers.context.ROOM_CODE_RETIRE_TIMEOUT_SECONDS", 0.5)
    room_manager = RoomManager()
    ctx, sio, sessions = build_stack(room_manager)
    await sessions.save("host", {"user_id": "user-1"})
    create = sio.handlers["/"]["create_room"]
    old = await create("host", {"nickname": "Host", "requestId": "first"})
    assert old["ok"] is True
    ctx.room_codes = codes(AsyncMock(return_value="NEWONE"))
    ctx.room_codes.retire_ephemeral = stalls(3600)

    started = asyncio.get_running_loop().time()
    answer = await create("host", {"nickname": "Host", "requestId": "second"})

    assert answer["ok"] is True
    assert asyncio.get_running_loop().time() - started < 0.3
    assert [room.code for room in room_manager.rooms.values()] == ["NEWONE"]
    assert len(ctx.room_cleanups) == 1, "the old room's retirement runs on its own"
    # And it is bounded: it gives up, leaving the code claimed for the
    # startup sweep, rather than living for ever.
    await ctx.drain_room_cleanups(2)
    assert ctx.room_cleanups == set()
    ctx.room_codes.retire_ephemeral.assert_awaited_once_with(old["code"])


async def test_a_hung_history_staging_for_the_game_left_behind_does_not_hold_the_entry(
    scaled, monkeypatch
):
    """The old room is not empty - a spectator stays - so it is not torn down,
    but the game the leaver was the last player of is abandoned, and that
    stages history. Entry-driven, the staging runs on its own (#879)."""
    from app.game import Game
    from tests.fake_game_history_repo import FakeGameHistoryRepository

    room_manager = RoomManager()
    worker = SimpleNamespace(stage=stalls(3600), bind_outcome=lambda *_: None)
    ctx, sio, sessions = build_stack(
        room_manager, game_history_repo=FakeGameHistoryRepository(), finished_games=worker
    )
    await sessions.save("host", {"user_id": "user-1"})
    await sessions.save("watcher", {"user_id": "user-2"})
    create = sio.handlers["/"]["create_room"]
    old = await create("host", {"nickname": "Host"})
    await sio.handlers["/"]["join_room"](
        "watcher", {"roomId": old["roomId"], "nickname": "Watcher", "asSpectator": True}
    )
    room = room_manager.get_room(old["roomId"])
    room.state = "playing"
    room.game = Game(turn_order=[old["playerId"]])
    room.game.start_next_turn(canvas_generation=room.allocate_canvas_generation())

    started = asyncio.get_running_loop().time()
    answer = await create("host", {"nickname": "Host"})

    assert answer["ok"] is True
    assert asyncio.get_running_loop().time() - started < 0.3
    assert room.game is None and room.players, "the game went, the spectator stayed"
    assert len(ctx.room_cleanups) == 1, "its history is staged on its own"
