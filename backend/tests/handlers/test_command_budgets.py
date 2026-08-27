"""What one caller may ask of a room, and how often.

The authentication surface has been limited since it shipped; no in-room
command was limited at all, and every one of them does real work per call.
"""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
import socketio

from app.handlers import register_all_handlers as register_handlers
from app.handlers.budgets import COMMAND_BUDGETS, CommandBudgets, budget_for
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

    commands = set(sio.handlers["/"]) - {"connect", "disconnect"}
    assert commands, "found no registered commands - has registration moved?"
    for command in commands:
        assert budget_for(command) is not None
    # And the table names nothing that is not registered.
    assert set(COMMAND_BUDGETS) <= commands


@pytest.mark.asyncio
async def test_a_flood_of_guesses_is_refused_without_doing_the_work():
    room_manager = RoomManager()
    ctx, sio, sessions = build_stack(room_manager)
    await seated(sio, sessions)
    budget = budget_for("guess")

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
    budget = budget_for("draw")

    allowed = [budgets.check("sid:draw", budget) for _ in range(25)]

    assert all(allowed), "a legitimate drawer was refused"


@pytest.mark.asyncio
async def test_canvas_replays_have_a_floor_between_them():
    """The cheap request with the expensive answer."""
    budgets = CommandBudgets()
    budget = budget_for("request_sync_strokes")
    assert budget.limit <= 3, "a resync floor this loose is not a floor"

    verdicts = [budgets.check("sid:request_sync_strokes", budget) for _ in range(5)]

    assert verdicts.count(True) == budget.limit


@pytest.mark.asyncio
async def test_a_window_that_has_passed_is_forgotten():
    now = [1000.0]
    budgets = CommandBudgets(clock=lambda: now[0])
    budget = budget_for("guess")

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
    assert ctx._command_budgets.tracked_keys() > 0

    await sio.handlers["/"]["disconnect"]("host-sid")

    assert ctx._command_budgets.tracked_keys() == 0
    await ctx.timers.close()


@pytest.mark.asyncio
async def test_being_throttled_is_recorded_once_per_run_not_once_per_refusal():
    """A caller being refused is being refused repeatedly, and an observation
    per refusal would be the write amplification these budgets exist to stop."""
    from app.services.runtime_metrics import metrics

    room_manager = RoomManager()
    ctx, sio, sessions = build_stack(room_manager)
    await seated(sio, sessions)
    budget = budget_for("guess")
    recorded = []
    original = metrics.record
    metrics.record = lambda event_type, **kwargs: recorded.append(event_type)
    try:
        for index in range(budget.limit + 10):
            await sio.handlers["/"]["guess"]("host-sid", {"text": f"apple {index}"})
    finally:
        metrics.record = original

    throttles = [event for event in recorded if event.value == "command.throttled"]
    assert len(throttles) == 1, f"recorded {len(throttles)} observations for one run"
