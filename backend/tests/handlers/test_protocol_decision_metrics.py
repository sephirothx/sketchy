"""The series protocol decisions are waiting on (#882), each reached through
the production path that increments it.

Refusals by code decide budget sizes; tail-claim results decide whether
incremental resync earns its complexity; the draw frame mix decides whether
more codec work is worth it and checks pen pressure against real pens; lobby
ticks and baseline sizes decide whether the lobby needs #885; backlog samples
decide where the outbound budget should sit.
"""
from __future__ import annotations

from unittest.mock import AsyncMock

import socketio

from app.game import Game
from app.handlers import register_all_handlers as register_handlers
from app.live_drawing import encode_live_drawing, frame_kind
from app.rooms import RoomManager
from app.services.telemetry import MAX_SERIES, Telemetry
from tests.handlers.helpers import canvas_action

STORE_USERS = (
    "app.handlers.context",
    "app.handlers.drawing",
    "app.handlers.lobby",
    "app.services.game_flow",
    "app.services.presence",
)


def fresh_store(monkeypatch) -> Telemetry:
    store = Telemetry()
    for module in STORE_USERS:
        monkeypatch.setattr(f"{module}.telemetry", store)
    return store


def histogram_count(store: Telemetry, name: str) -> int:
    line = next((l for l in store.prometheus_lines() if l.startswith(f"{name}_count")), None)
    return 0 if line is None else int(float(line.split()[-1]))


def drawing_room():
    room_manager = RoomManager()
    room = room_manager.create_room(name="Room", is_public=True)
    drawer = room_manager.add_player(room, "Drawer")
    drawer.sid = "drawer-sid"
    room_manager.add_player(room, "Guesser")
    room.game = Game(turn_order=list(room.players))
    room.game.start_next_turn(canvas_generation=room.allocate_canvas_generation())
    room.game.force_prompt_choice()
    sio = socketio.AsyncServer(async_mode="asgi")
    context = register_handlers(sio, room_manager)
    sio.get_session = AsyncMock(return_value={"room_id": room.id, "player_id": drawer.id})
    sio.emit = AsyncMock()
    return sio, context, room


async def test_a_refusal_is_counted_by_its_code_and_a_throttle_as_too_fast(monkeypatch):
    store = fresh_store(monkeypatch)
    sio = socketio.AsyncServer(async_mode="asgi")
    context = register_handlers(sio, RoomManager())
    sio.get_session = AsyncMock(return_value={})
    sio.emit = AsyncMock()

    answer = await sio.handlers["/"]["send_chat"]("sid", {"text": "hello"})
    assert answer["ok"] is False
    assert store.socket_refusals.get(("send_chat", str(answer["errorCode"]))) == 1

    monkeypatch.setattr(context._command_windows, "check", lambda key, budget: False)
    await sio.handlers["/"]["send_chat"]("sid", {"text": "hello"})
    assert store.socket_refusals.get(("send_chat", "too_fast")) == 1
    await context.timers.close()


async def test_every_tail_claim_is_counted_by_what_it_came_to(monkeypatch):
    store = fresh_store(monkeypatch)
    sio, context, room = drawing_room()
    draw = sio.handlers["/"]["draw"]
    await draw("drawer-sid", encode_live_drawing("draw_start", {"x": 0.1, "y": 0.1, "color": "#112233", "width": 5}), canvas_action(room.game, 1))
    await draw("drawer-sid", encode_live_drawing("draw_end"))
    canvas = room.game.canvas
    good = (canvas.generation, 1, canvas.hashes[0])
    sync = context.game_flow._emit_canvas_sync

    await sync(room, "viewer", None)
    await sync(room, "viewer", good)
    await sync(room, "viewer", (canvas.generation + 1, 1, canvas.hashes[0]))
    await sync(room, "viewer", (canvas.generation, 0, 0))
    await sync(room, "viewer", (canvas.generation, 1, canvas.hashes[0] ^ 1))
    await sync(room, "viewer", (canvas.generation, 5, 0))
    # A pen held down: the history is one longer than what is finalized.
    await draw("drawer-sid", encode_live_drawing("draw_start", {"x": 0.5, "y": 0.5, "color": "#112233", "width": 5}), canvas_action(room.game, 2))
    await sync(room, "viewer", (canvas.generation, len(canvas.history), 0))

    assert dict(store.canvas_tail_claims.items()) == {
        ("none",): 1, ("hit",): 1, ("generation",): 1, ("empty",): 1,
        ("hash",): 1, ("ahead",): 1, ("open_path",): 1,
    }
    await context.timers.close()


async def test_the_frame_mix_counts_kind_shape_result_points_and_width_keyframes(monkeypatch):
    store = fresh_store(monkeypatch)
    sio, context, room = drawing_room()
    draw = sio.handlers["/"]["draw"]
    start = encode_live_drawing("draw_start", {"x": 0.1, "y": 0.2, "color": "#112233", "width": 5})
    points = [{"x": 0.2, "y": 0.3}, {"x": 0.21, "y": 0.31}, {"x": 0.22, "y": 0.32}]
    pen = encode_live_drawing("draw_move", {"points": points, "widths": [(1, 8), (2, 12)]})
    mouse = encode_live_drawing("draw_move", {"points": points[:2]})

    await draw("drawer-sid", start, canvas_action(room.game, 1))
    await draw("drawer-sid", pen)
    await draw("drawer-sid", mouse)
    await draw("drawer-sid", encode_live_drawing("draw_end"))
    # From a generation the canvas has left: refused, and resynced.
    await draw("drawer-sid", start, [room.game.canvas.generation + 1, 2, 2])
    await draw("drawer-sid", "not base64!")

    frames = dict(store.draw_frames.items())
    start_kind = frame_kind(start)
    assert frames[(*start_kind, "accepted")] == 1
    assert frames[(*start_kind, "refused")] == 1
    # Pen and mouse frames share a kind; the keyframe histogram is what tells them apart.
    assert frame_kind(pen) == frame_kind(mouse)
    assert frames[(*frame_kind(pen), "accepted")] == 2
    assert frames[("end", "int", "accepted")] == 1
    assert frames[("unknown", "base64", "invalid")] == 1
    assert histogram_count(store, "sketchy_draw_frame_points") == 2
    lines = store.prometheus_lines()
    assert 'sketchy_draw_frame_width_keyframes_bucket{le="0.0"} 1' in lines  # the mouse
    assert 'sketchy_draw_frame_width_keyframes_bucket{le="2.0"} 2' in lines  # and the pen
    await context.timers.close()


async def test_a_frame_from_a_seat_that_is_not_drawing_is_counted_and_ignored(monkeypatch):
    store = fresh_store(monkeypatch)
    sio, context, room = drawing_room()
    sio.get_session = AsyncMock(return_value={})
    await sio.handlers["/"]["draw"]("someone", encode_live_drawing("draw_end"))
    assert dict(store.draw_frames.items()) == {("end", "int", "not_drawing"): 1}
    await context.timers.close()


async def test_lobby_ticks_baselines_and_watchers(monkeypatch):
    store = fresh_store(monkeypatch)
    sio = socketio.AsyncServer(async_mode="asgi")
    context = register_handlers(sio, RoomManager())
    sio.get_session = AsyncMock(return_value={})
    sio.emit = AsyncMock()

    await context.presence_broadcaster.flush()  # nothing has moved
    context.room_manager.create_room(name="Opened", is_public=True)
    await context.presence_broadcaster.flush()
    ticks = dict(store.lobby_ticks.items())
    assert ticks[("rooms", "skipped")] == 1 and ticks[("rooms", "emitted")] == 1
    assert ticks[("presence", "skipped")] == 2

    sio.enter_room = AsyncMock()
    answer = await sio.handlers["/"]["watch_lobby"]("watcher", None)
    assert answer["ok"] is True
    assert histogram_count(store, "sketchy_lobby_baseline_bytes") == 1

    store.sources.lobby_watchers = lambda: 3
    assert "sketchy_lobby_watchers 3" in store.prometheus_lines()
    await context.timers.close()


def test_the_new_families_stay_bounded():
    """Every label value comes from a closed set the server owns; the fold at
    MAX_SERIES is the backstop, not the plan."""
    store = Telemetry()
    for index in range(MAX_SERIES + 50):
        store.note_refusal(f"command{index}", "invalid_payload")
    assert len(store.socket_refusals.items()) <= MAX_SERIES + 1


async def test_refusals_at_the_door_are_counted_and_a_refused_draw_stays_in_the_frame_mix(monkeypatch):
    """Arity, a stale protocol and the budget refuse before any handler runs;
    each is still a refusal by code, and a `draw` among them still a frame."""
    store = fresh_store(monkeypatch)
    sio, context, room = drawing_room()
    frame = encode_live_drawing("draw_end")

    await sio.handlers["/"]["send_chat"]("sid", {"text": "hi"}, "one too many")
    context.quarantine("stale-sid", 0, close_after=60)
    await sio.handlers["/"]["draw"]("stale-sid", frame)
    context.release_stale("stale-sid")
    monkeypatch.setattr(context._command_windows, "check", lambda key, budget: False)
    await sio.handlers["/"]["draw"]("drawer-sid", frame)

    refusals = dict(store.socket_refusals.items())
    assert refusals[("send_chat", "invalid_payload")] == 1
    assert refusals[("draw", "protocol_mismatch")] == 1
    assert refusals[("draw", "too_fast")] == 1
    frames = dict(store.draw_frames.items())
    assert frames[("end", "int", "refused")] == 1
    assert frames[("end", "int", "throttled")] == 1
    await context.timers.close()
