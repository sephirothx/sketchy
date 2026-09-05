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
    DRAWING,
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
    assert budget.limit == 1, (
        "a floor is a minimum spacing: more than one per window lets a burst "
        "spend the whole allowance in a single tick"
    )

    verdicts = [budgets.check("sid:resync", budget) for _ in range(5)]

    assert verdicts == [True, False, False, False, False]


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
    assert drawing["default_limit"] == DRAWING.default.limit
    assert drawing["window_seconds"] == DRAWING.default.window_seconds
    policy.set_limit("drawing", drawing["minimum"])
    assert policy.for_command("draw").limit == drawing["minimum"]

    with pytest.raises(ValueError):
        policy.set_limit("drawing", drawing["minimum"] - 1)
    with pytest.raises(KeyError):
        policy.set_limit("nonexistent", 10)


@pytest.mark.asyncio
async def test_one_window_per_kind_not_one_per_command():
    """The budget is a property of a kind of traffic, so two commands of the
    same kind share it. Keyed per command, `guess` and `send_chat` would each
    get the conversation allowance and a caller could spend it twice - and the
    action class, with a command apiece, would multiply by however many
    commands happen to be registered."""
    room_manager = RoomManager()
    ctx, sio, sessions = build_stack(room_manager)
    await seated(sio, sessions)
    budget = ctx.command_budgets.for_command("guess")

    for index in range(budget.limit):
        answer = await sio.handlers["/"]["guess"]("host-sid", {"text": f"a{index}"})
        assert answer is None or answer.get("ok") is not False

    spent = await sio.handlers["/"]["send_chat"]("host-sid", {"text": "hello"})
    assert spent["ok"] is False and "too quickly" in spent["error"], (
        "chat had an allowance of its own despite sharing the conversation budget"
    )


@pytest.mark.asyncio
async def test_undo_is_refused_out_loud_even_though_it_shares_the_drawing_budget():
    """Undo is a control somebody pressed, sent with `emitWithAck`. Silence
    leaves the client waiting for an acknowledgement that never comes, and it
    recovers by resyncing rather than by learning it was refused."""
    room_manager = RoomManager()
    ctx, sio, sessions = build_stack(room_manager)
    created = await seated(sio, sessions)
    room = room_manager.get_room(created["roomId"])
    room.players[created["playerId"]].sid = "host-sid"
    budget = ctx.command_budgets.for_command("undo_stroke")

    for _ in range(budget.limit):
        await sio.handlers["/"]["draw"]("host-sid", b"", [1, 1])

    refused = await sio.handlers["/"]["undo_stroke"]("host-sid", [1, 1, 1])
    assert refused is not None, "a refused undo said nothing at all"
    assert refused["ok"] is False and "too quickly" in refused["error"]


def test_lobby_chat_is_a_kind_of_its_own():
    """A room line reaches at most twenty-four seats; a lobby line reaches every
    lobby that is open. Sharing `conversation` would let a lobby flood spend
    the guessing allowance, and tightening the lobby would tighten guessing."""
    policy = CommandBudgetPolicy()
    assert policy.class_of("send_lobby_chat") == "lobby_chat"
    assert policy.for_command("send_lobby_chat") != policy.for_command("send_chat")
    assert policy.for_command("send_lobby_chat").limit < policy.for_command(
        "send_chat"
    ).limit


@pytest.mark.asyncio
async def test_a_flood_of_reactions_is_refused_by_the_action_budget():
    """Reactions have no budget of their own (#520): a control somebody presses
    at a human's pace answers to `action`, and a flood is refused before the
    handler looks at the room."""
    room_manager = RoomManager()
    ctx, sio, sessions = build_stack(room_manager)
    await seated(sio, sessions)
    budget = CommandBudgetPolicy().for_command("react_to_drawing")
    assert budget == CommandBudgetPolicy().for_command("toggle_afk")
    # Opening the room spent one of the window's actions; start it clean.
    ctx._command_windows.forget("host-sid")

    answers = [
        await sio.handlers["/"]["react_to_drawing"](
            "host-sid", {"turnId": "turn", "emoji": "heart"}
        )
        for _ in range(budget.limit + 5)
    ]

    throttled = [answer for answer in answers if "too quickly" in answer.get("error", "")]
    assert len(throttled) == 5
