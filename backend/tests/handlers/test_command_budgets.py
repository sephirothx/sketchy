"""What one caller may ask of a room, and how often.

The authentication surface has been limited since it shipped; no in-room
command was limited at all, and every one of them does real work per call.
"""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
import socketio

from app.handlers import register_all_handlers as register_handlers
from app.handlers.budgets import (
    COMMAND_CLASSES,
    CommandBudgetPolicy,
    CommandBudgets,
)
from app.rooms import RoomManager
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


async def seated(sio, sessions, sid="host-sid"):
    await sessions.save(sid, {"user_id": f"user-{sid}"})
    created = await sio.handlers["/"]["create_room"](sid, {"nickname": "Host"})
    assert created["ok"] is True
    return created


def test_every_registered_command_answers_to_a_budget():
    """The table and the handlers must not drift: a command registered without
    one would be exactly the unbounded surface this closes."""
    room_manager = RoomManager()
    sio = socketio.AsyncServer(async_mode="asgi")
    register_handlers(sio, room_manager)

    policy = CommandBudgetPolicy()
    commands = set(sio.handlers["/"]) - {"connect", "disconnect"}
    assert commands, "found no registered commands - has registration moved?"
    for command in commands:
        assert policy.for_command(command) is not None
    # And the table names nothing that is not registered.
    assert set(COMMAND_CLASSES) <= commands


@pytest.mark.asyncio
async def test_a_flood_of_guesses_is_refused_without_doing_the_work():
    room_manager = RoomManager()
    ctx, sio, sessions = build_stack(room_manager)
    await seated(sio, sessions)
    budget = CommandBudgetPolicy().for_command("guess")

    answers = [
        await sio.handlers["/"]["guess"]("host-sid", {"text": f"apple {index}"})
        for index in range(budget.limit + 5)
    ]

    refused = [answer for answer in answers if answer and answer.get("ok") is False]
    assert len(refused) == 5
    assert all("too quickly" in answer["error"] for answer in refused)


@pytest.mark.asyncio
async def test_a_drawer_at_full_speed_is_never_refused():
    """The flush timer fires every 40ms, so a second of drawing is 25 frames."""
    budgets = CommandBudgets()
    budget = CommandBudgetPolicy().for_command("draw")

    allowed = [budgets.check("sid:draw", budget) for _ in range(25)]

    assert all(allowed), "a legitimate drawer was refused"


@pytest.mark.asyncio
async def test_canvas_replays_have_a_floor_between_them():
    """The cheap request with the expensive answer."""
    budgets = CommandBudgets()
    budget = CommandBudgetPolicy().for_command("request_sync_strokes")
    assert budget.limit <= 3, "a resync floor this loose is not a floor"

    verdicts = [budgets.check("sid:request_sync_strokes", budget) for _ in range(5)]

    assert verdicts.count(True) == budget.limit


@pytest.mark.asyncio
async def test_a_window_that_has_passed_is_forgotten():
    now = [1000.0]
    budgets = CommandBudgets(clock=lambda: now[0])
    budget = CommandBudgetPolicy().for_command("guess")

    for _ in range(budget.limit):
        assert budgets.check("sid:guess", budget) is True
    assert budgets.check("sid:guess", budget) is False

    now[0] += budget.window_seconds + 0.1
    assert budgets.check("sid:guess", budget) is True


@pytest.mark.asyncio
async def test_a_socket_that_leaves_takes_its_windows_with_it():
    """Keyed by socket and command, so the map would otherwise keep a deque per
    command per connection for the life of a process that also holds every
    live game."""
    room_manager = RoomManager()
    ctx, sio, sessions = build_stack(room_manager)
    await seated(sio, sessions)
    await sio.handlers["/"]["guess"]("host-sid", {"text": "apple"})
    assert ctx._command_windows.tracked_keys() > 0

    await sio.handlers["/"]["disconnect"]("host-sid")

    assert ctx._command_windows.tracked_keys() == 0
    await ctx.timers.close()


@pytest.mark.asyncio
async def test_being_throttled_is_recorded_once_a_window_not_once_a_refusal():
    """A caller being refused is being refused repeatedly, so an observation
    per refusal would be the write amplification these budgets exist to stop -
    but only ever recording the first would make a two-second mistake and a
    twenty-minute flood look identical afterwards."""
    now = [1000.0]
    windows = CommandBudgets(clock=lambda: now[0])
    budget = CommandBudgetPolicy().for_command("guess")

    for _ in range(budget.limit):
        assert windows.check("sid:guess", budget) is True

    reports = 0
    for _ in range(50):
        assert windows.check("sid:guess", budget) is False
        if windows.should_report("sid:guess", budget):
            reports += 1
    assert reports == 1, "fifty refusals in one window recorded more than once"

    # A flood that outlives its window says so again, so duration is visible.
    now[0] += budget.window_seconds + 0.1
    for _ in range(budget.limit):
        windows.check("sid:guess", budget)
    assert windows.check("sid:guess", budget) is False
    assert windows.should_report("sid:guess", budget) is True


@pytest.mark.asyncio
async def test_a_refused_frame_answers_nothing_and_a_refused_action_explains():
    """Nobody is waiting on an answer to a drawing frame at twenty-five a
    second, and an error surfacing mid-stroke is worse than the dropped frame
    it describes. A control somebody pressed is the opposite: silence there
    reads as the app being broken."""
    room_manager = RoomManager()
    ctx, sio, sessions = build_stack(room_manager)
    created = await seated(sio, sessions)
    room = room_manager.get_room(created["roomId"])
    room.players[created["playerId"]].sid = "host-sid"

    draw = sio.handlers["/"]["draw"]
    frame_budget = ctx.command_budgets.for_command("draw")
    for _ in range(frame_budget.limit):
        await draw("host-sid", b"", [1, 1])
    assert await draw("host-sid", b"", [1, 1]) is None, "a refused frame answered"

    toggle = sio.handlers["/"]["toggle_afk"]
    action_budget = ctx.command_budgets.for_command("toggle_afk")
    for _ in range(action_budget.limit):
        await toggle("host-sid", {})
    refused = await toggle("host-sid", {})
    assert refused["ok"] is False and "too quickly" in refused["error"]


def test_a_budget_cannot_be_tuned_to_something_the_client_cannot_live_with():
    """#446 will let an administrator change these; the bounds are what stops
    a number that refuses legitimate drawing."""
    policy = CommandBudgetPolicy()
    drawing = next(item for item in policy.describe() if item["name"] == "drawing")

    assert drawing["minimum"] >= 50, "25 frames a second is what a drawer sends"
    policy.set_limit("drawing", drawing["minimum"])
    assert policy.for_command("draw").limit == drawing["minimum"]

    with pytest.raises(ValueError):
        policy.set_limit("drawing", drawing["minimum"] - 1)
    with pytest.raises(KeyError):
        policy.set_limit("nonexistent", 10)
