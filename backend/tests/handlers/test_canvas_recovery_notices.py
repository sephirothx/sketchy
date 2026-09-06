"""Server-triggered canvas recovery is a bounded notice, not a history dump (#562).

Before: a refused opening, a stale generation, an unknown sequence and an undo
disagreement each pushed the whole history to that socket, and nothing but
the drawing budget bounded it - up to a hundred 460 KB dumps per window from
one socket. Now those paths send one small `canvas_stale` per socket per
resync window, the undo paths answer their acknowledgement and nothing else,
and a snapshot the server pushes on a join spends the same resync window a
requested one does, so a rejoin inside the window is deferred with a notice
rather than answered with a dump.
"""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
import socketio

from app.game import Game
from app.handlers import register_all_handlers as register_handlers
from app.handlers.budgets import DRAWING, RESYNC
from app.live_drawing import encode_live_drawing
from app.rooms import RoomManager
from app.services import game_flow as game_flow_module
from app.services.telemetry import Telemetry


def _game(monkeypatch=None):
    manager = RoomManager()
    room = manager.create_room(name="Room", is_public=True)
    drawer = manager.add_player(room, "Drawer")
    drawer.sid = "drawer-sid"
    room.game = Game(turn_order=[drawer.id])
    room.game.start_next_turn(canvas_generation=room.allocate_canvas_generation())
    room.game.force_prompt_choice()
    sio = socketio.AsyncServer(async_mode="asgi")
    ctx = register_handlers(sio, manager)
    sio.get_session = AsyncMock(return_value={"room_id": room.id, "player_id": drawer.id})
    sio.emit = AsyncMock()
    return room, drawer, sio, ctx


def _events(sio, name):
    return [call for call in sio.emit.await_args_list if call.args[0] == name]


OPENER = encode_live_drawing("draw_start", {"x": 0.1, "y": 0.1, "color": "#000000", "width": 6})


@pytest.mark.asyncio
async def test_a_burst_of_stale_openings_costs_one_notice_and_no_dump(monkeypatch):
    store = Telemetry()
    monkeypatch.setattr(game_flow_module, "telemetry", store)
    room, drawer, sio, ctx = _game()
    draw = sio.handlers["/"]["draw"]
    generation = room.game.canvas.generation
    for index in range(DRAWING.default.limit):
        await draw("drawer-sid", OPENER, [generation + 1, 100 + index])
    assert _events(sio, "sync_strokes") == [], "no history dump for a stale opening"
    notices = _events(sio, "canvas_stale")
    assert len(notices) == 1, "one notice per socket per resync window"
    assert notices[0].args[1] == [generation, 100, "stale_generation", int(RESYNC.default.window_seconds * 1000)]
    assert notices[0].kwargs == {"to": "drawer-sid"}
    assert store.canvas_recovery_notices.get(("stale_generation",)) == DRAWING.default.limit, "every occurrence counted"


@pytest.mark.asyncio
async def test_each_former_dump_path_is_a_notice_and_undo_answers_only_its_acknowledgement():
    room, drawer, sio, ctx = _game()
    draw = sio.handlers["/"]["draw"]
    undo = sio.handlers["/"]["undo_stroke"]
    generation = room.game.canvas.generation
    # A tool the room disallows.
    room.allowed_tools = ["brush"]
    await draw("drawer-sid", encode_live_drawing("draw_fill", {"x": 0.5, "y": 0.5, "color": "#123456"}), [generation, 1])
    assert _events(sio, "canvas_stale")[-1].args[1][2] == "refused_tool"
    # A sequence at or below the committed one with no commit to replay.
    ctx.clear_command_budget("drawer-sid")
    room.game.canvas.sequence = 5
    await draw("drawer-sid", OPENER, [generation, 3])
    assert _events(sio, "canvas_stale")[-1].args[1][2] == "unknown_sequence"
    # A frame that does not decode.
    ctx.clear_command_budget("drawer-sid")
    await draw("drawer-sid", b"\xff\xff\xff", None)
    assert _events(sio, "canvas_stale")[-1].args[1][2] == "invalid_frame"
    # Undo disagreements: the awaited acknowledgement carries the reason and
    # the client resyncs through its transaction; no dump rides along.
    ctx.clear_command_budget("drawer-sid")
    stale = await undo("drawer-sid", [generation + 1, 6, 0, 0])
    assert stale["errorCode"] == "canvas_stale_generation"
    mismatch = await undo("drawer-sid", [generation, 6, 999, 999])
    assert mismatch["errorCode"] == "canvas_out_of_sync"
    assert _events(sio, "sync_strokes") == []


@pytest.mark.asyncio
async def test_a_join_snapshot_spends_the_resync_window_and_a_rejoin_inside_it_is_deferred():
    room, drawer, sio, ctx = _game()
    flow = ctx.game_flow
    await flow._sync_player_view("drawer-sid", room, drawer)
    assert len(_events(sio, "sync_strokes")) == 1, "the first join gets its snapshot at once"
    assert _events(sio, "sync_strokes")[0].args[1][-1] == 0, "server-initiated: request id 0"
    await flow._sync_player_view("drawer-sid", room, drawer)
    await flow._sync_player_view("drawer-sid", room, drawer)
    assert len(_events(sio, "sync_strokes")) == 1, "a rejoin inside the window is not a second dump"
    deferred = _events(sio, "canvas_stale")
    assert len(deferred) == 1 and deferred[0].args[1][2] == "deferred"
    assert deferred[0].args[1][3] == int(RESYNC.default.window_seconds * 1000)
    # The client's own request inside the window is refused with the same delay.
    request = sio.handlers["/"]["request_sync_strokes"]
    refused = await request("drawer-sid", [1])
    assert refused["errorCode"] == "too_fast" and refused["retryAfterMs"] == int(RESYNC.default.window_seconds * 1000)
    # Once the window opens, the request is answered - and the reply is not budgeted twice.
    ctx.clear_command_budget("drawer-sid")
    assert await request("drawer-sid", [2]) == {"ok": True}
    assert len(_events(sio, "sync_strokes")) == 2


@pytest.mark.asyncio
async def test_the_amplification_is_bounded_per_window_across_every_path():
    """The number the issue asked for: how many full dumps one socket can
    make the server send per resync window, whatever it sends."""
    room, drawer, sio, ctx = _game()
    draw = sio.handlers["/"]["draw"]
    request = sio.handlers["/"]["request_sync_strokes"]
    generation = room.game.canvas.generation
    for index in range(40):
        await draw("drawer-sid", OPENER, [generation + 1, 200 + index])
    for _ in range(5):
        await ctx.game_flow._sync_player_view("drawer-sid", room, drawer)
    for _ in range(5):
        await request("drawer-sid", [9])
    assert len(_events(sio, "sync_strokes")) == RESYNC.default.limit
    assert len(_events(sio, "canvas_stale")) == 1
