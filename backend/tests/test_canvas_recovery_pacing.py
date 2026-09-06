"""The server side of #597: the allowance is advertised, and a repacked replay
fits inside it where the original cadence did not.

The client's pacing and repacking live in `frontend/src/lib/canvasRecovery.ts`
and are tested there. Here: the number the client paces against reaches it and
follows an administrator's tuning, and a stroke replayed as the client now
replays it - one opener, one point frame per 256 points, one end - commits
under the default budget, whereas the same stroke replayed frame by frame did
not (the reproduced case: 152 frames, 100 accepted, the end dropped).
"""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
import socketio

from app.client_config import ClientConfig
from app.game import Game
from app.handlers import register_all_handlers as register_handlers
from app.handlers.budgets import DRAWING, Budget, CommandBudgetPolicy
from app.live_drawing import encode_live_drawing
from app.rooms import RoomManager


def test_the_client_config_carries_the_live_drawing_allowance():
    policy = CommandBudgetPolicy()
    config = ClientConfig(drawing_budget=lambda: policy.for_command("draw"))
    assert config.payload() == {
        "contractVersion": 3,
        "flushIntervalMs": 40,
        "drawingFramesPerWindow": DRAWING.default.limit,
        "drawingWindowSeconds": DRAWING.default.window_seconds,
    }
    policy.set_limit(DRAWING.name, 200)
    assert config.payload()["drawingFramesPerWindow"] == 200, "read live, not copied"
    assert ClientConfig().payload()["drawingFramesPerWindow"] == DRAWING.default.limit


@pytest.mark.asyncio
async def test_a_drawing_budget_change_is_announced_like_a_client_cadence(monkeypatch):
    from app import main

    emitted = []
    monkeypatch.setattr(main.sio, "emit", AsyncMock(side_effect=lambda *a, **k: emitted.append(a)))
    await main.announce_client_config({"budget.action"})
    assert emitted == [], "a server-side ceiling the client cannot observe is not broadcast"
    await main.announce_client_config({"budget.drawing"})
    assert emitted and emitted[0][0] == "client_config"
    assert "drawingFramesPerWindow" in emitted[0][1]


def _game():
    manager = RoomManager()
    room = manager.create_room(name="Room", is_public=True)
    drawer = manager.add_player(room, "Drawer")
    drawer.sid = "drawer-sid"
    room.game = Game(turn_order=[drawer.id])
    room.game.start_next_turn(canvas_generation=room.allocate_canvas_generation())
    room.game.force_prompt_choice()
    sio = socketio.AsyncServer(async_mode="asgi")
    register_handlers(sio, manager)
    sio.get_session = AsyncMock(return_value={"room_id": room.id, "player_id": drawer.id})
    sio.emit = AsyncMock()
    return room, sio


POINTS = [{"x": 0.1 + i / 1000, "y": 0.1 + (i % 7) / 500} for i in range(150)]


@pytest.mark.asyncio
async def test_a_stroke_replayed_at_its_original_cadence_is_cut_off_by_the_budget():
    """The reproduced case, kept as the reason the client repacks."""
    room, sio = _game()
    draw = sio.handlers["/"]["draw"]
    generation = room.game.canvas.generation
    frames = (
        [("draw_start", {"x": 0.1, "y": 0.1, "color": "#000000", "width": 6})]
        + [("draw_move", {"points": [point]}) for point in POINTS]
        + [("draw_end", {})]
    )
    for index, (event, payload) in enumerate(frames):
        await draw("drawer-sid", encode_live_drawing(event, payload), [generation, 1] if index == 0 else None)
    rebroadcast = sum(1 for call in sio.emit.await_args_list if call.args[0] == "draw")
    assert len(frames) == 152 and rebroadcast == DRAWING.default.limit
    assert room.game.canvas.sequence == 0, "never committed"
    assert room.game.canvas.active_draw_sequence == 1, "left open"


@pytest.mark.asyncio
async def test_the_same_stroke_repacked_commits_in_three_frames():
    room, sio = _game()
    draw = sio.handlers["/"]["draw"]
    generation = room.game.canvas.generation
    await draw("drawer-sid", encode_live_drawing("draw_start", {"x": 0.1, "y": 0.1, "color": "#000000", "width": 6}), [generation, 1])
    await draw("drawer-sid", encode_live_drawing("draw_move", {"points": POINTS}), None)
    await draw("drawer-sid", encode_live_drawing("draw_end", {}), None)
    rebroadcast = [call for call in sio.emit.await_args_list if call.args[0] == "draw"]
    assert len(rebroadcast) == 3
    assert room.game.canvas.sequence == 1 and room.game.canvas.active_draw_sequence is None
    assert room.game.canvas.point_count == 151  # the opener is a point too
    assert len(room.game.canvas.history) == 1


@pytest.mark.asyncio
async def test_a_resend_of_a_committed_stroke_gets_its_commit_back_not_a_sync():
    """What makes the client's deadline resend safe: one resend resolves a
    lost end frame and a lost commit alike."""
    room, sio = _game()
    draw = sio.handlers["/"]["draw"]
    generation = room.game.canvas.generation
    frames = [
        (encode_live_drawing("draw_start", {"x": 0.1, "y": 0.1, "color": "#000000", "width": 6}), [generation, 1]),
        (encode_live_drawing("draw_move", {"points": POINTS}), None),
        (encode_live_drawing("draw_end", {}), None),
    ]
    for frame, identity in frames:
        await draw("drawer-sid", frame, identity)
    sio.emit.reset_mock()
    for frame, identity in frames:
        await draw("drawer-sid", frame, identity)
    events = [call.args[0] for call in sio.emit.await_args_list]
    assert events == ["canvas_commit"]
    assert sio.emit.await_args_list[0].args[1][:2] == [generation, 1]
    assert room.game.canvas.sequence == 1 and len(room.game.canvas.history) == 1


def test_the_budget_type_is_what_the_config_reads():
    assert isinstance(DRAWING.default, Budget)
