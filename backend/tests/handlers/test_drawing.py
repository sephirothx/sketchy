import asyncio
from contextlib import suppress
from unittest.mock import AsyncMock, patch

import pytest
import socketio

from app.canvas_history import (
    ClearAction,
    FillAction,
    PathAction,
    ShapeAction,
    decode_binary_canvas_history,
    encode_canvas_history,
)
from app.handlers import register_all_handlers as register_handlers
from app.game import DRAWING_SECONDS, Game, Phase
from app.live_drawing import encode_live_drawing
from app.message_limits import MAX_CHAT_MESSAGE_LENGTH
from app.rooms import DrawingRecapEntry, STARTING_SCORE, RoomManager
from app.words import MAX_WORD_LENGTH


def canvas_action(game: Game, sequence: int) -> list[int]:
    return [game.canvas.generation, sequence]


def contains_secret(value, secret: str) -> bool:
    if value == secret:
        return True
    if isinstance(value, dict):
        return any(
            key in {"reconnectSecret", "reconnect_secret"}
            or contains_secret(item, secret)
            for key, item in value.items()
        )
    if isinstance(value, (list, tuple, set)):
        return any(contains_secret(item, secret) for item in value)
    return False

@pytest.mark.asyncio
async def test_draw_handler_rejects_events_outside_drawing_phase():
    room_manager = RoomManager()
    room = room_manager.create_room(name="Room", is_public=True)
    drawer = room_manager.add_player(room, "Drawer")
    drawer.sid = "drawer-sid"
    room_manager.add_player(room, "Guesser")
    room.game = Game(turn_order=list(room.players))
    room.game.start_next_turn(canvas_generation=room.allocate_canvas_generation())

    sio = socketio.AsyncServer(async_mode="asgi")
    register_handlers(sio, room_manager)
    sio.get_session = AsyncMock(return_value={"room_id": room.id, "player_id": drawer.id})
    sio.emit = AsyncMock()
    draw = sio.handlers["/"]["draw"]
    payload = {"x": 0.2, "y": 0.3, "color": "#000000", "width": 4}

    await draw(
        "drawer-sid",
        encode_live_drawing("draw_start", payload),
        canvas_action(room.game, 1),
    )
    assert room.game.canvas.history == []

    room.game.force_word_choice()
    await draw(
        "drawer-sid",
        encode_live_drawing("draw_start", payload),
        canvas_action(room.game, 1),
    )
    assert room.game.canvas.history == [
        PathAction(points=[(0.2, 0.3)], color=0, width=4.0)
    ]

@pytest.mark.asyncio
async def test_draw_handler_records_and_rebroadcasts_every_binary_action():
    room_manager = RoomManager()
    room = room_manager.create_room(name="Room", is_public=True)
    drawer = room_manager.add_player(room, "Drawer")
    drawer.sid = "drawer-sid"
    room_manager.add_player(room, "Guesser")
    room.game = Game(turn_order=list(room.players))
    room.game.start_next_turn(canvas_generation=room.allocate_canvas_generation())
    room.game.force_word_choice()

    sio = socketio.AsyncServer(async_mode="asgi")
    register_handlers(sio, room_manager)
    sio.get_session = AsyncMock(
        return_value={"room_id": room.id, "player_id": drawer.id}
    )
    sio.emit = AsyncMock()
    draw = sio.handlers["/"]["draw"]
    actions = [
        (
            "draw_start",
            {"x": 0.1, "y": 0.2, "color": "#112233", "width": 5},
        ),
        (
            "draw_move",
            {"points": [{"x": 0.2, "y": 0.3}, {"x": 0.3, "y": 0.4}]},
        ),
        ("draw_end", {}),
        (
            "draw_shape",
            {
                "shape": "triangle",
                "from": {"x": 0.2, "y": 0.2},
                "to": {"x": 0.7, "y": 0.8},
                "color": "#445566",
                "width": 8,
            },
        ),
        (
            "draw_fill",
            {"x": 0.5, "y": 0.5, "color": "#abcdef"},
        ),
    ]

    frames = [encode_live_drawing(event, payload) for event, payload in actions]
    sequences = iter((1, 2, 3))
    for (event, _), frame in zip(actions, frames, strict=True):
        await draw(
            "drawer-sid",
            frame,
            (
                canvas_action(room.game, next(sequences))
                if event in {"draw_start", "draw_shape", "draw_fill"}
                else None
            ),
        )

    assert len(room.game.canvas.history) == 3
    assert isinstance(room.game.canvas.history[0], PathAction)
    assert len(room.game.canvas.history[0].points) == 3
    assert isinstance(room.game.canvas.history[1], ShapeAction)
    assert isinstance(room.game.canvas.history[2], FillAction)
    broadcasts = [
        call
        for call in sio.emit.await_args_list
        if call.args[0] == "draw"
    ]
    assert [call.args[1] for call in broadcasts] == frames
    assert all(call.kwargs.get("skip_sid") == "drawer-sid" for call in broadcasts)

    await draw("drawer-sid", b"\x11")
    assert len(room.game.canvas.history) == 3

@pytest.mark.asyncio
async def test_draw_handler_requests_gaps_and_accepts_retransmission():
    room_manager = RoomManager()
    room = room_manager.create_room(name="Room", is_public=True)
    drawer = room_manager.add_player(room, "Drawer")
    drawer.sid = "drawer-sid"
    room.game = Game(turn_order=[drawer.id])
    room.game.start_next_turn(canvas_generation=room.allocate_canvas_generation())
    room.game.force_word_choice()

    sio = socketio.AsyncServer(async_mode="asgi")
    register_handlers(sio, room_manager)
    sio.get_session = AsyncMock(
        return_value={"room_id": room.id, "player_id": drawer.id},
    )
    sio.emit = AsyncMock()
    draw = sio.handlers["/"]["draw"]
    first = encode_live_drawing(
        "draw_fill",
        {"x": 0.1, "y": 0.2, "color": "#112233"},
    )
    second = encode_live_drawing(
        "draw_fill",
        {"x": 0.3, "y": 0.4, "color": "#445566"},
    )

    await draw("drawer-sid", second, canvas_action(room.game, 2))
    assert room.game.canvas.history == []
    sio.emit.assert_any_await(
        "request_canvas_actions",
        [room.game.canvas.generation, 1, 2],
        to="drawer-sid",
    )

    await draw("drawer-sid", first, canvas_action(room.game, 1))
    await draw("drawer-sid", second, canvas_action(room.game, 2))

    assert len(room.game.canvas.history) == 2
    assert room.game.canvas.sequence == 2
    commits = [
        call.args[1][1]
        for call in sio.emit.await_args_list
        if call.args[0] == "canvas_commit"
    ]
    assert commits[-2:] == [1, 2]

@pytest.mark.asyncio
async def test_draw_handler_rejects_actions_from_a_previous_canvas_generation():
    room_manager = RoomManager()
    room = room_manager.create_room(name="Room", is_public=True)
    drawer = room_manager.add_player(room, "Drawer")
    drawer.sid = "drawer-sid"
    room.game = Game(turn_order=[drawer.id])
    room.game.start_next_turn(canvas_generation=room.allocate_canvas_generation())
    room.game.start_next_turn(canvas_generation=room.allocate_canvas_generation())
    room.game.force_word_choice()

    sio = socketio.AsyncServer(async_mode="asgi")
    register_handlers(sio, room_manager)
    sio.get_session = AsyncMock(
        return_value={"room_id": room.id, "player_id": drawer.id},
    )
    sio.emit = AsyncMock()
    draw = sio.handlers["/"]["draw"]

    await draw(
        "drawer-sid",
        encode_live_drawing(
            "draw_fill",
            {"x": 0.1, "y": 0.2, "color": "#112233"},
        ),
        [1, 1],
    )

    assert room.game.canvas.history == []
    assert room.game.canvas.sequence == 0
    assert any(
        call.args[0] == "sync_strokes" and call.kwargs.get("to") == "drawer-sid"
        for call in sio.emit.await_args_list
    )

@pytest.mark.asyncio
async def test_retransmitted_committed_path_is_idempotent():
    room_manager = RoomManager()
    room = room_manager.create_room(name="Room", is_public=True)
    drawer = room_manager.add_player(room, "Drawer")
    drawer.sid = "drawer-sid"
    room.game = Game(turn_order=[drawer.id])
    room.game.start_next_turn(canvas_generation=room.allocate_canvas_generation())
    room.game.force_word_choice()

    sio = socketio.AsyncServer(async_mode="asgi")
    register_handlers(sio, room_manager)
    sio.get_session = AsyncMock(
        return_value={"room_id": room.id, "player_id": drawer.id},
    )
    sio.emit = AsyncMock()
    draw = sio.handlers["/"]["draw"]
    start = encode_live_drawing(
        "draw_start",
        {"x": 0.1, "y": 0.2, "color": "#112233", "width": 4},
    )
    move = encode_live_drawing(
        "draw_move",
        {"points": [{"x": 0.3, "y": 0.4}]},
    )
    end = encode_live_drawing("draw_end")

    for frame, sequence in ((start, 1), (move, None), (end, None)):
        await draw(
            "drawer-sid",
            frame,
            canvas_action(room.game, sequence) if sequence else None,
        )
    committed_history = room.game.canvas.sync_payload()

    for frame, sequence in ((start, 1), (move, None), (end, None)):
        await draw(
            "drawer-sid",
            frame,
            canvas_action(room.game, sequence) if sequence else None,
        )

    assert room.game.canvas.sequence == 1
    assert room.game.canvas.sync_payload() == committed_history


@pytest.mark.asyncio
async def test_retransmission_older_than_commit_window_gets_authoritative_sync(
    monkeypatch,
):
    monkeypatch.setattr("app.canvas_session.MAX_CANVAS_COMMITS", 1)
    room_manager = RoomManager()
    room = room_manager.create_room(name="Room", is_public=True)
    drawer = room_manager.add_player(room, "Drawer")
    drawer.sid = "drawer-sid"
    room.game = Game(turn_order=[drawer.id])
    room.game.start_next_turn(canvas_generation=room.allocate_canvas_generation())
    room.game.force_word_choice()

    sio = socketio.AsyncServer(async_mode="asgi")
    register_handlers(sio, room_manager)
    sio.get_session = AsyncMock(
        return_value={"room_id": room.id, "player_id": drawer.id},
    )
    sio.emit = AsyncMock()
    draw = sio.handlers["/"]["draw"]
    first = encode_live_drawing(
        "draw_fill",
        {"x": 0.1, "y": 0.2, "color": "#112233"},
    )
    second = encode_live_drawing(
        "draw_fill",
        {"x": 0.3, "y": 0.4, "color": "#445566"},
    )

    await draw("drawer-sid", first, canvas_action(room.game, 1))
    await draw("drawer-sid", second, canvas_action(room.game, 2))
    sio.emit.reset_mock()
    await draw("drawer-sid", first, [room.game.canvas.generation, 1])

    assert room.game.canvas.sequence == 2
    assert any(
        call.args[0] == "sync_strokes"
        and call.kwargs.get("to") == "drawer-sid"
        for call in sio.emit.await_args_list
    )

@pytest.mark.asyncio
async def test_retransmitted_incomplete_path_restarts_the_semantic_action():
    room_manager = RoomManager()
    room = room_manager.create_room(name="Room", is_public=True)
    drawer = room_manager.add_player(room, "Drawer")
    drawer.sid = "drawer-sid"
    room.game = Game(turn_order=[drawer.id])
    room.game.start_next_turn(canvas_generation=room.allocate_canvas_generation())
    room.game.force_word_choice()

    sio = socketio.AsyncServer(async_mode="asgi")
    register_handlers(sio, room_manager)
    sio.get_session = AsyncMock(
        return_value={"room_id": room.id, "player_id": drawer.id},
    )
    sio.emit = AsyncMock()
    draw = sio.handlers["/"]["draw"]
    start = encode_live_drawing(
        "draw_start",
        {"x": 0.1, "y": 0.2, "color": "#112233", "width": 4},
    )
    move = encode_live_drawing(
        "draw_move",
        {"points": [{"x": 0.3, "y": 0.4}]},
    )

    await draw("drawer-sid", start, canvas_action(room.game, 1))
    await draw("drawer-sid", move)
    await draw("drawer-sid", start, canvas_action(room.game, 1))
    await draw("drawer-sid", move)
    await draw("drawer-sid", encode_live_drawing("draw_end"))

    assert room.game.canvas.sequence == 1
    assert room.game.canvas.history[0].points == [
        (0.1, 0.2),
        (0.3, 0.4),
    ]

@pytest.mark.asyncio
async def test_undo_hash_mismatch_sends_authoritative_sync():
    room_manager = RoomManager()
    room = room_manager.create_room(name="Room", is_public=True)
    drawer = room_manager.add_player(room, "Drawer")
    drawer.sid = "drawer-sid"
    room.game = Game(turn_order=[drawer.id])
    room.game.start_next_turn(canvas_generation=room.allocate_canvas_generation())
    room.game.force_word_choice()

    sio = socketio.AsyncServer(async_mode="asgi")
    register_handlers(sio, room_manager)
    sio.get_session = AsyncMock(
        return_value={"room_id": room.id, "player_id": drawer.id},
    )
    sio.emit = AsyncMock()
    draw = sio.handlers["/"]["draw"]
    undo = sio.handlers["/"]["undo_stroke"]

    await draw(
        "drawer-sid",
        encode_live_drawing(
            "draw_fill",
            {"x": 0.1, "y": 0.2, "color": "#112233"},
        ),
        canvas_action(room.game, 1),
    )
    response = await undo(
        "drawer-sid",
        [
            room.game.canvas.generation,
            2,
            room.game.canvas.revision,
            room.game.canvas.hash ^ 1,
        ],
    )

    assert response == {"ok": False, "error": "Canvas history is out of sync"}
    assert len(room.game.canvas.history) == 1
    assert any(
        call.args[0] == "sync_strokes" and call.kwargs.get("to") == "drawer-sid"
        for call in sio.emit.await_args_list
    )

@pytest.mark.asyncio
async def test_finished_drawing_turn_is_captured_for_recap():
    room_manager = RoomManager()
    room = room_manager.create_room(name="Room", is_public=True)
    drawer = room_manager.add_player(room, "Drawer", name_color="#123abc")
    guesser = room_manager.add_player(room, "Guesser")
    drawer.sid = "drawer-sid"
    guesser.sid = "guesser-sid"
    room.state = "playing"
    room.game = Game(
        turn_order=[drawer.id, guesser.id],
        rounds_total=1,
        word_pool=["apple"],
    )
    room.game.start_next_turn(canvas_generation=room.allocate_canvas_generation())
    room.game.choose_word(drawer.id, "apple")
    room.game.set_phase_deadline(DRAWING_SECONDS)

    sio = socketio.AsyncServer(async_mode="asgi")
    timers = register_handlers(sio, room_manager).timers
    sessions = {
        drawer.sid: {"room_id": room.id, "player_id": drawer.id},
        guesser.sid: {"room_id": room.id, "player_id": guesser.id},
    }
    sio.get_session = AsyncMock(side_effect=lambda sid: sessions[sid])
    sio.emit = AsyncMock()

    await sio.handlers["/"]["draw"](
        drawer.sid,
        encode_live_drawing(
            "draw_fill",
            {"x": 0.25, "y": 0.5, "color": "#123456"},
        ),
        canvas_action(room.game, 1),
    )
    await sio.handlers["/"]["guess"](guesser.sid, {"text": "apple"})

    assert len(room.last_game_drawings) == 1
    recap = room.last_game_drawings[0]
    assert recap.round_number == 1
    assert recap.turn_number == 1
    assert recap.drawer_id == drawer.id
    assert recap.drawer_nickname == "Drawer"
    assert recap.drawer_name_color == "#123abc"
    assert recap.word == "apple"
    assert recap.action_count == 1
    assert decode_binary_canvas_history(recap.canvas_history) == [
        FillAction(x=200, y=300, color=0x123456),
    ]

    timer = timers.phase_timers.pop(room.id)
    timer.cancel()
    with suppress(asyncio.CancelledError):
        await timer

@pytest.mark.asyncio
async def test_recap_drawing_can_be_fetched_without_mutating_history():
    room_manager = RoomManager()
    room = room_manager.create_room(name="Room", is_public=True)
    player = room_manager.add_player(room, "Player")
    player.sid = "player-sid"
    canvas = encode_canvas_history([ClearAction()])
    room.last_game_drawings.append(
        DrawingRecapEntry(
            round_number=2,
            turn_number=4,
            drawer_id=player.id,
            drawer_nickname=player.nickname,
            drawer_name_color=player.name_color,
            word="tree",
            action_count=1,
            canvas_history=canvas,
        )
    )

    sio = socketio.AsyncServer(async_mode="asgi")
    register_handlers(sio, room_manager)
    sio.get_session = AsyncMock(
        return_value={"room_id": room.id, "player_id": player.id},
    )
    get_drawing = sio.handlers["/"]["get_recap_drawing"]

    response = await get_drawing("player-sid", {"index": 0})

    assert response["ok"] is True
    assert response["drawing"] == {
        "index": 0,
        "roundNumber": 2,
        "turnNumber": 4,
        "drawerId": player.id,
        "drawerNickname": "Player",
        "drawerNameColor": player.name_color,
        "word": "tree",
        "actionCount": 1,
        "canvas": canvas,
    }
    assert room.last_game_drawings[0].canvas_history == canvas
    assert await get_drawing("player-sid", {"index": 1}) == {
        "ok": False,
        "error": "Drawing not found",
    }
    assert await get_drawing("player-sid", {"index": True}) == {
        "ok": False,
        "error": "Drawing not found",
    }

@pytest.mark.asyncio
async def test_undo_stroke_and_clear_canvas_handlers():
    room_manager = RoomManager()
    room = room_manager.create_room(name="Room", is_public=True)
    drawer = room_manager.add_player(room, "Drawer")
    guesser = room_manager.add_player(room, "Guesser")
    drawer.sid = "drawer-sid"
    guesser.sid = "guesser-sid"

    room.game = Game(turn_order=[drawer.id, guesser.id])
    room.game.start_next_turn(canvas_generation=room.allocate_canvas_generation())
    room.game.force_word_choice()

    sio = socketio.AsyncServer(async_mode="asgi")
    timers = register_handlers(sio, room_manager).timers
    sessions = {
        "drawer-sid": {"room_id": room.id, "player_id": drawer.id},
        "guesser-sid": {"room_id": room.id, "player_id": guesser.id},
    }
    sio.get_session = AsyncMock(side_effect=lambda sid: sessions.get(sid))
    sio.emit = AsyncMock()

    draw = sio.handlers["/"]["draw"]
    undo_stroke = sio.handlers["/"]["undo_stroke"]

    # Drawer draws a stroke
    await draw(
        "drawer-sid",
        encode_live_drawing(
            "draw_start",
            {"x": 0.1, "y": 0.1, "color": "#000000", "width": 4},
        ),
        canvas_action(room.game, 1),
    )
    await draw("drawer-sid", encode_live_drawing("draw_end"))
    assert len(room.game.canvas.history) == 1

    # Guesser attempting to undo should be ignored
    await undo_stroke("guesser-sid", {})
    assert len(room.game.canvas.history) == 1

    # Drawer undoes the stroke
    revision_before_undo = room.game.canvas.revision
    await undo_stroke(
        "drawer-sid",
        [
            room.game.canvas.generation,
            2,
            room.game.canvas.revision,
            room.game.canvas.hash,
        ],
    )
    assert len(room.game.canvas.history) == 0
    undo_events = [
        call for call in sio.emit.await_args_list
        if call.args[0] == "canvas_undo"
    ]
    assert len(undo_events) == 1
    assert undo_events[0].args[1][:4] == [
        room.game.canvas.generation,
        2,
        revision_before_undo,
        revision_before_undo + 1,
    ]
    assert not any(
        call.args[0] == "sync_strokes"
        for call in sio.emit.await_args_list
    )

    # Drawer draws again then clears canvas
    await draw(
        "drawer-sid",
        encode_live_drawing(
            "draw_start",
            {"x": 0.2, "y": 0.2, "color": "#ff0000", "width": 4},
        ),
        canvas_action(room.game, 3),
    )
    await draw("drawer-sid", encode_live_drawing("draw_end"))
    assert len(room.game.canvas.history) == 1

    await draw(
        "drawer-sid",
        encode_live_drawing("clear_canvas"),
        canvas_action(room.game, 4),
    )
    assert len(room.game.canvas.history) == 2
    assert isinstance(room.game.canvas.history[-1], ClearAction)
    emitted_events = [call.args[0] for call in sio.emit.await_args_list]
    assert "draw" in emitted_events

    # Drawer undoes Clear - recovers pre-clear stroke
    await undo_stroke(
        "drawer-sid",
        [
            room.game.canvas.generation,
            5,
            room.game.canvas.revision,
            room.game.canvas.hash,
        ],
    )
    assert len(room.game.canvas.history) == 1
    assert isinstance(room.game.canvas.history[0], PathAction)

    timer = timers.phase_timers.pop(room.id, None)
    if timer:
        timer.cancel()
        with suppress(asyncio.CancelledError):
            await timer

@pytest.mark.asyncio
async def test_draw_fill_handler_validation():
    room_manager = RoomManager()
    room = room_manager.create_room(name="Room", is_public=True)
    drawer = room_manager.add_player(room, "Drawer")
    drawer.sid = "drawer-sid"

    room.game = Game(turn_order=[drawer.id])
    room.game.start_next_turn(canvas_generation=room.allocate_canvas_generation())
    room.game.force_word_choice()

    sio = socketio.AsyncServer(async_mode="asgi")
    timers = register_handlers(sio, room_manager).timers
    sio.get_session = AsyncMock(return_value={"room_id": room.id, "player_id": drawer.id})
    sio.emit = AsyncMock()
    draw = sio.handlers["/"]["draw"]

    valid_data = {
        "x": 0.25,
        "y": 0.75,
        "color": "#AABBCC",
    }
    await draw(
        "drawer-sid",
        encode_live_drawing("draw_fill", valid_data),
        canvas_action(room.game, 1),
    )
    assert len(room.game.canvas.history) == 1
    assert room.game.canvas.history[0] == FillAction(
        x=200,
        y=450,
        color=0xAABBCC,
    )
    # Out-of-bounds and malformed binary frames are ignored.
    await draw("drawer-sid", bytes.fromhex("1400000020030000"))
    await draw("drawer-sid", b"\x14")
    assert len(room.game.canvas.history) == 1

    timer = timers.phase_timers.pop(room.id, None)
    if timer:
        timer.cancel()
        with suppress(asyncio.CancelledError):
            await timer

@pytest.mark.asyncio
async def test_request_sync_strokes_returns_drawing_so_far_for_joining_player():
    room_manager = RoomManager()
    room = room_manager.create_room(name="Room", is_public=True)
    drawer = room_manager.add_player(room, "Drawer")
    drawer.sid = "drawer-sid"

    room.game = Game(turn_order=[drawer.id], rounds_total=1)
    room.game.start_next_turn(canvas_generation=room.allocate_canvas_generation())
    room.game.force_word_choice()
    room.game.set_phase_deadline(DRAWING_SECONDS)

    # Record drawing strokes in progress
    room.game.canvas.record_stroke("draw_start", {"x": 0.1, "y": 0.2, "color": "#000000", "width": 4})
    room.game.canvas.record_stroke("draw_move", {"points": [{"x": 0.3, "y": 0.4}]})

    # New player joins and requests canvas strokes
    joiner = room_manager.add_player(room, "Joiner")
    joiner.sid = "joiner-sid"

    sio = socketio.AsyncServer(async_mode="asgi")
    register_handlers(sio, room_manager)
    sessions = {"joiner-sid": {"room_id": room.id, "player_id": joiner.id}}
    sio.get_session = AsyncMock(side_effect=lambda sid: sessions.get(sid))
    sio.emit = AsyncMock()

    request_handler = sio.handlers["/"]["request_sync_strokes"]
    await request_handler("joiner-sid")

    # Check sync_strokes payload sent to joiner
    emitted_sync = [
        call for call in sio.emit.await_args_list
        if call.args[0] == "sync_strokes" and call.kwargs.get("to") == "joiner-sid"
    ]
    assert len(emitted_sync) == 1
    history_payload, revision, generation, sequence, history_hash = (
        emitted_sync[0].args[1]
    )
    decoded = decode_binary_canvas_history(history_payload)
    assert revision == room.game.canvas.revision
    assert generation == room.game.canvas.generation
    assert sequence == room.game.canvas.sequence
    assert history_hash == room.game.canvas.hash
    assert encode_canvas_history(decoded) == {
        "v": 1,
        "a": [[0, 0, 4, 0.1, 0.2, 0.3, 0.4]],
    }

@pytest.mark.asyncio
async def test_request_sync_strokes_seeds_empty_history_revision():
    room_manager = RoomManager()
    room = room_manager.create_room(name="Room", is_public=True)
    player = room_manager.add_player(room, "Player")
    player.sid = "player-sid"
    room.game = Game(turn_order=[player.id])
    room.game.start_next_turn(canvas_generation=room.allocate_canvas_generation())

    sio = socketio.AsyncServer(async_mode="asgi")
    register_handlers(sio, room_manager)
    sio.get_session = AsyncMock(
        return_value={"room_id": room.id, "player_id": player.id},
    )
    sio.emit = AsyncMock()

    await sio.handlers["/"]["request_sync_strokes"]("player-sid")

    sync_call = next(
        call for call in sio.emit.await_args_list
        if call.args[0] == "sync_strokes"
    )
    history_payload, revision, generation, sequence, history_hash = sync_call.args[1]
    assert decode_binary_canvas_history(history_payload) == []
    assert revision == room.game.canvas.revision
    assert generation == room.game.canvas.generation
    assert sequence == 0
    assert history_hash == 0
