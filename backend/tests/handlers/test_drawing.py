import asyncio
from contextlib import suppress
from unittest.mock import AsyncMock

import socketio

from app.identifiers import generate_uuid7
from app.canvas_history import (
    ClearAction,
    FillAction,
    PathAction,
    ShapeAction,
    PackedCanvasHistory,
    decode_binary_canvas_history,
)
from app.handlers import register_all_handlers as register_handlers
from tests.handlers.helpers import canvas_action
from app.game import DRAWING_SECONDS, Game
from app.live_drawing import encode_live_drawing
from app.rooms import DrawingRecapEntry, RoomManager


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

    room.game.force_prompt_choice()
    await draw(
        "drawer-sid",
        encode_live_drawing("draw_start", payload),
        canvas_action(room.game, 1),
    )
    assert room.game.canvas.history == [
        PathAction(points=[(0.2, 0.3)], color=0, width=4.0)
    ]

async def test_draw_handler_records_and_rebroadcasts_every_binary_action():
    room_manager = RoomManager()
    room = room_manager.create_room(name="Room", is_public=True)
    drawer = room_manager.add_player(room, "Drawer")
    drawer.sid = "drawer-sid"
    room_manager.add_player(room, "Guesser")
    room.game = Game(turn_order=list(room.players))
    room.game.start_next_turn(canvas_generation=room.allocate_canvas_generation())
    room.game.force_prompt_choice()

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
    # A frame that commits an action carries the commit with it, so the room
    # never pays for a second event and a viewer cannot see a commit for a
    # frame it has not received. Point frames commit nothing and carry nothing.
    rebroadcast_frames = [
        call.args[1][0] if isinstance(call.args[1], tuple) else call.args[1]
        for call in broadcasts
    ]
    assert rebroadcast_frames == frames
    commits = [
        call.args[1][1] if isinstance(call.args[1], tuple) else None
        for call in broadcasts
    ]
    generation = room.game.canvas.generation
    # draw_start opens the action and points commit nothing; draw_end closes
    # it, and a shape or a fill is committed by the frame that carries it.
    assert [commit is None for commit in commits] == [True, True, False, False, False]
    assert [commit[:2] for commit in commits if commit] == [
        [generation, 1], [generation, 2], [generation, 3],
    ]
    revisions = [commit[2] for commit in commits if commit]
    assert revisions == sorted(set(revisions)), revisions
    assert all(isinstance(commit[3], int) for commit in commits if commit)
    assert all(call.kwargs.get("skip_sid") == "drawer-sid" for call in broadcasts)

    # The drawer never receives its own rebroadcast, so their commit stays a
    # dedicated event - addressed to them alone rather than to the room.
    drawer_commits = [
        call
        for call in sio.emit.await_args_list
        if call.args[0] == "canvas_commit"
    ]
    assert [call.args[1] for call in drawer_commits] == [
        commit for commit in commits if commit is not None
    ]
    assert all(call.kwargs.get("to") == "drawer-sid" for call in drawer_commits)
    assert all(call.kwargs.get("room") is None for call in drawer_commits)

    await draw("drawer-sid", b"\x11")
    assert len(room.game.canvas.history) == 3

async def test_draw_handler_requests_gaps_and_accepts_retransmission():
    room_manager = RoomManager()
    room = room_manager.create_room(name="Room", is_public=True)
    drawer = room_manager.add_player(room, "Drawer")
    drawer.sid = "drawer-sid"
    room.game = Game(turn_order=[drawer.id])
    room.game.start_next_turn(canvas_generation=room.allocate_canvas_generation())
    room.game.force_prompt_choice()

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

async def test_draw_handler_rejects_actions_from_a_previous_canvas_generation():
    room_manager = RoomManager()
    room = room_manager.create_room(name="Room", is_public=True)
    drawer = room_manager.add_player(room, "Drawer")
    drawer.sid = "drawer-sid"
    room.game = Game(turn_order=[drawer.id])
    room.game.start_next_turn(canvas_generation=room.allocate_canvas_generation())
    room.game.start_next_turn(canvas_generation=room.allocate_canvas_generation())
    room.game.force_prompt_choice()

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
        call.args[0] == "canvas_stale" and call.kwargs.get("to") == "drawer-sid"
        for call in sio.emit.await_args_list
    )

async def test_retransmitted_committed_path_is_idempotent():
    room_manager = RoomManager()
    room = room_manager.create_room(name="Room", is_public=True)
    drawer = room_manager.add_player(room, "Drawer")
    drawer.sid = "drawer-sid"
    room.game = Game(turn_order=[drawer.id])
    room.game.start_next_turn(canvas_generation=room.allocate_canvas_generation())
    room.game.force_prompt_choice()

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
    room.game.force_prompt_choice()

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
        call.args[0] == "canvas_stale"
        and call.kwargs.get("to") == "drawer-sid"
        for call in sio.emit.await_args_list
    )


async def test_draw_retransmission_for_undo_commit_gets_authoritative_sync():
    room_manager = RoomManager()
    room = room_manager.create_room(name="Room", is_public=True)
    drawer = room_manager.add_player(room, "Drawer")
    drawer.sid = "drawer-sid"
    room.game = Game(turn_order=[drawer.id])
    room.game.start_next_turn(canvas_generation=room.allocate_canvas_generation())
    room.game.force_prompt_choice()

    sio = socketio.AsyncServer(async_mode="asgi")
    register_handlers(sio, room_manager)
    sio.get_session = AsyncMock(
        return_value={"room_id": room.id, "player_id": drawer.id},
    )
    sio.emit = AsyncMock()
    draw = sio.handlers["/"]["draw"]
    undo = sio.handlers["/"]["undo_stroke"]
    fill = encode_live_drawing(
        "draw_fill",
        {"x": 0.1, "y": 0.2, "color": "#112233"},
    )

    await draw("drawer-sid", fill, canvas_action(room.game, 1))
    response = await undo(
        "drawer-sid",
        [
            room.game.canvas.generation,
            2,
            room.game.canvas.revision,
            room.game.canvas.hash,
        ],
    )
    assert response == {"ok": True}
    assert room.game.canvas.get_commit(2)[2] == "undo"

    sio.emit.reset_mock()
    await draw("drawer-sid", fill, [room.game.canvas.generation, 2])

    # A retransmitted opener whose sequence the server committed as an undo is
    # answered with a notice, never with the history (#562).
    assert any(call.args[0] == "canvas_stale" for call in sio.emit.await_args_list)
    assert not any(call.args[0] == "sync_strokes" for call in sio.emit.await_args_list)
    assert not any(
        call.args[0] in {"canvas_commit", "canvas_undo"}
        for call in sio.emit.await_args_list
    )


async def test_retransmitted_incomplete_path_restarts_the_semantic_action():
    room_manager = RoomManager()
    room = room_manager.create_room(name="Room", is_public=True)
    drawer = room_manager.add_player(room, "Drawer")
    drawer.sid = "drawer-sid"
    room.game = Game(turn_order=[drawer.id])
    room.game.start_next_turn(canvas_generation=room.allocate_canvas_generation())
    room.game.force_prompt_choice()

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

async def test_undo_hash_mismatch_sends_authoritative_sync():
    room_manager = RoomManager()
    room = room_manager.create_room(name="Room", is_public=True)
    drawer = room_manager.add_player(room, "Drawer")
    drawer.sid = "drawer-sid"
    room.game = Game(turn_order=[drawer.id])
    room.game.start_next_turn(canvas_generation=room.allocate_canvas_generation())
    room.game.force_prompt_choice()

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

    assert response == {"ok": False, "errorCode": "canvas_out_of_sync", "error": "Canvas history is out of sync"}
    assert len(room.game.canvas.history) == 1
    # The awaited refusal is the signal; the client resyncs through its
    # budgeted transaction, so no history rides along (#562).
    assert not any(call.args[0] == "sync_strokes" for call in sio.emit.await_args_list)

async def test_finished_drawing_turn_is_captured_for_recap():
    room_manager = RoomManager()
    room = room_manager.create_room(name="Room", is_public=True)
    drawer = room_manager.add_player(
        room, "Drawer", name_color="#199647", is_anonymous=False
    )
    guesser = room_manager.add_player(room, "Guesser")
    drawer.sid = "drawer-sid"
    guesser.sid = "guesser-sid"
    room.state = "playing"
    room.game = Game(
        turn_order=[drawer.id, guesser.id],
        rounds_total=1,
        prompt_pool=["apple"],
    )
    room.game.start_next_turn(canvas_generation=room.allocate_canvas_generation())
    room.game.choose_prompt(drawer.id, "apple")
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
    assert recap.drawer_name_color == "#199647"
    assert recap.prompt == "apple"
    assert recap.action_count == 1
    assert decode_binary_canvas_history(recap.canvas_history) == [
        FillAction(x=200, y=300, color=0x123456),
    ]

    timer = timers.phase_timers.pop(room.id)
    timer.cancel()
    with suppress(asyncio.CancelledError):
        await timer

async def test_recap_drawing_can_be_fetched_without_mutating_history():
    room_manager = RoomManager()
    room = room_manager.create_room(name="Room", is_public=True)
    player = room_manager.add_player(room, "Player")
    player.sid = "player-sid"
    cleared = PackedCanvasHistory()
    cleared.append_clear()
    canvas = cleared.binary_payload()
    room.last_game_drawings.append(
        DrawingRecapEntry(
            turn_id=str(generate_uuid7()),
            round_number=2,
            turn_number=4,
            drawer_id=player.id,
            drawer_nickname=player.nickname,
            drawer_name_color=player.name_color,
            prompt="tree",
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
        "turnId": room.last_game_drawings[0].turn_id,
        "roundNumber": 2,
        "turnNumber": 4,
        "drawerId": player.id,
        "drawerNickname": "Player",
        "drawerNameColor": player.name_color,
        "prompt": "tree",
        "actionCount": 1,
        "available": True,
        "canvas": canvas,
    }
    assert room.last_game_drawings[0].canvas_history == canvas
    assert await get_drawing("player-sid", {"index": 1}) == {
        "ok": False,
        "errorCode": "drawing_not_found",
        "error": "Drawing not found",
    }
    assert await get_drawing("player-sid", {"index": True}) == {
        "ok": False,
        "errorCode": "drawing_not_found",
        "error": "Drawing not found",
    }

async def test_undo_stroke_and_clear_canvas_handlers():
    room_manager = RoomManager()
    room = room_manager.create_room(name="Room", is_public=True)
    drawer = room_manager.add_player(room, "Drawer")
    guesser = room_manager.add_player(room, "Guesser")
    drawer.sid = "drawer-sid"
    guesser.sid = "guesser-sid"

    room.game = Game(turn_order=[drawer.id, guesser.id])
    room.game.start_next_turn(canvas_generation=room.allocate_canvas_generation())
    room.game.force_prompt_choice()

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

async def test_draw_fill_handler_validation():
    room_manager = RoomManager()
    room = room_manager.create_room(name="Room", is_public=True)
    drawer = room_manager.add_player(room, "Drawer")
    drawer.sid = "drawer-sid"

    room.game = Game(turn_order=[drawer.id])
    room.game.start_next_turn(canvas_generation=room.allocate_canvas_generation())
    room.game.force_prompt_choice()

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

async def test_request_sync_strokes_returns_drawing_so_far_for_joining_player():
    room_manager = RoomManager()
    room = room_manager.create_room(name="Room", is_public=True)
    drawer = room_manager.add_player(room, "Drawer")
    drawer.sid = "drawer-sid"

    room.game = Game(turn_order=[drawer.id], rounds_total=1)
    room.game.start_next_turn(canvas_generation=room.allocate_canvas_generation())
    room.game.force_prompt_choice()
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
    assert await request_handler("joiner-sid", [7]) == {"ok": True}

    # Check sync_strokes payload sent to joiner
    emitted_sync = [
        call for call in sio.emit.await_args_list
        if call.args[0] == "sync_strokes" and call.kwargs.get("to") == "joiner-sid"
    ]
    assert len(emitted_sync) == 1
    history_payload, revision, generation, sequence, history_hash, request_id = (
        emitted_sync[0].args[1]
    )
    assert request_id == 7, "the reply names the request it answers"
    decoded = decode_binary_canvas_history(history_payload)
    assert revision == room.game.canvas.revision
    assert generation == room.game.canvas.generation
    assert sequence == room.game.canvas.sequence
    assert history_hash == room.game.canvas.hash
    [path] = list(decoded)
    assert (path.color, path.width) == (0, 4)
    assert [(round(x, 3), round(y, 3)) for x, y in path.points] == [(0.1, 0.2), (0.3, 0.4)]

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

    await sio.handlers["/"]["request_sync_strokes"]("player-sid", [1])

    sync_call = next(
        call for call in sio.emit.await_args_list
        if call.args[0] == "sync_strokes"
    )
    history_payload, revision, generation, sequence, history_hash, _request_id = sync_call.args[1]
    assert decode_binary_canvas_history(history_payload) == []
    assert revision == room.game.canvas.revision
    assert generation == room.game.canvas.generation
    assert sequence == 0
    assert history_hash == 0


def _drawing_room(*, allowed_tools=None, color_mode="all"):
    """A room mid-turn, with its drawer's socket wired up."""
    room_manager = RoomManager()
    room = room_manager.create_room(
        name="Room",
        is_public=True,
        allowed_tools=allowed_tools,
        color_mode=color_mode,
    )
    drawer = room_manager.add_player(room, "Drawer")
    drawer.sid = "drawer-sid"
    room_manager.add_player(room, "Guesser")
    room.game = Game(turn_order=list(room.players))
    room.game.start_next_turn(canvas_generation=room.allocate_canvas_generation())
    room.game.force_prompt_choice()

    sio = socketio.AsyncServer(async_mode="asgi")
    register_handlers(sio, room_manager)
    sio.get_session = AsyncMock(return_value={"room_id": room.id, "player_id": drawer.id})
    sio.emit = AsyncMock()
    return room, sio


def _emitted_events(sio):
    return [call.args[0] for call in sio.emit.await_args_list]


async def test_a_tool_the_room_disallows_is_never_recorded_or_rebroadcast():
    room, sio = _drawing_room(allowed_tools=["brush"])
    draw = sio.handlers["/"]["draw"]

    await draw(
        "drawer-sid",
        encode_live_drawing("draw_fill", {"x": 0.5, "y": 0.5, "color": "#000000"}),
        canvas_action(room.game, 1),
    )

    assert room.game.canvas.history == []
    assert "draw" not in _emitted_events(sio)
    # The drawer already painted it locally, so they are put back on server truth.
    assert "canvas_stale" in _emitted_events(sio)
    assert "sync_strokes" not in _emitted_events(sio), "a notice, never a dump (#562)"


async def test_a_color_the_mode_disallows_is_never_recorded():
    room, sio = _drawing_room(color_mode="black_and_white")
    draw = sio.handlers["/"]["draw"]

    await draw(
        "drawer-sid",
        encode_live_drawing("draw_start", {"x": 0.2, "y": 0.3, "color": "#ed1c24", "width": 4}),
        canvas_action(room.game, 1),
    )

    assert room.game.canvas.history == []
    assert "draw" not in _emitted_events(sio)


async def test_erasing_survives_a_mode_that_allows_no_other_color():
    """White is how the eraser reaches the server, so every mode admits it."""
    room, sio = _drawing_room(color_mode="black_and_white")
    draw = sio.handlers["/"]["draw"]

    await draw(
        "drawer-sid",
        encode_live_drawing("draw_start", {"x": 0.2, "y": 0.3, "color": "#ffffff", "width": 24}),
        canvas_action(room.game, 1),
    )

    assert len(room.game.canvas.history) == 1


async def test_turning_off_the_brush_takes_the_eraser_with_it():
    room, sio = _drawing_room(allowed_tools=["shapes", "fill"])
    draw = sio.handlers["/"]["draw"]

    await draw(
        "drawer-sid",
        encode_live_drawing("draw_start", {"x": 0.2, "y": 0.3, "color": "#ffffff", "width": 24}),
        canvas_action(room.game, 1),
    )

    assert room.game.canvas.history == []


async def test_the_points_trailing_a_refused_path_are_dropped_in_silence():
    """One refusal is one resync, however many frames the client keeps sending."""
    room, sio = _drawing_room(color_mode="black_and_white")
    draw = sio.handlers["/"]["draw"]

    await draw(
        "drawer-sid",
        encode_live_drawing("draw_start", {"x": 0.2, "y": 0.3, "color": "#ed1c24", "width": 4}),
        canvas_action(room.game, 1),
    )
    for _ in range(5):
        await draw("drawer-sid", encode_live_drawing("draw_move", {"points": [{"x": 0.4, "y": 0.4}]}))
    await draw("drawer-sid", encode_live_drawing("draw_end", {}))

    assert room.game.canvas.history == []
    assert _emitted_events(sio).count("canvas_stale") == 1
    assert "sync_strokes" not in _emitted_events(sio)


async def test_a_drawer_keeps_the_tools_the_room_left_them():
    room, sio = _drawing_room(allowed_tools=["shapes"], color_mode="palette")
    draw = sio.handlers["/"]["draw"]

    await draw(
        "drawer-sid",
        encode_live_drawing(
            "draw_shape",
            {
                "shape": "rectangle",
                "from": {"x": 0.1, "y": 0.1},
                "to": {"x": 0.4, "y": 0.4},
                "color": "#ed1c24",
                "width": 4,
            },
        ),
        canvas_action(room.game, 1),
    )

    assert len(room.game.canvas.history) == 1
    assert "draw" in _emitted_events(sio)


async def test_a_refused_path_does_not_wedge_the_tools_that_remain():
    """The discard flag a refused path leaves behind governs path frames only,
    so a room without the brush can still draw everything it does allow."""
    room, sio = _drawing_room(allowed_tools=["shapes"])
    draw = sio.handlers["/"]["draw"]

    await draw(
        "drawer-sid",
        encode_live_drawing("draw_start", {"x": 0.2, "y": 0.3, "color": "#000000", "width": 4}),
        canvas_action(room.game, 1),
    )
    await draw(
        "drawer-sid",
        encode_live_drawing(
            "draw_shape",
            {
                "shape": "ellipse",
                "from": {"x": 0.1, "y": 0.1},
                "to": {"x": 0.4, "y": 0.4},
                "color": "#000000",
                "width": 4,
            },
        ),
        canvas_action(room.game, 1),
    )

    assert len(room.game.canvas.history) == 1


async def test_a_verified_prefix_claim_is_answered_with_only_the_missing_tail():
    room_manager = RoomManager()
    room = room_manager.create_room(name="Room", is_public=True)
    drawer = room_manager.add_player(room, "Drawer")
    drawer.sid = "drawer-sid"
    room.game = Game(turn_order=list(room.players))
    room.game.start_next_turn(canvas_generation=room.allocate_canvas_generation())
    room.game.force_prompt_choice()
    canvas = room.game.canvas
    for index in range(5):
        canvas.record_stroke(
            "draw_shape",
            {
                "shape": "rectangle",
                "from": {"x": 0.1 * index, "y": 0.1},
                "to": {"x": 0.2, "y": 0.3},
                "color": "#112233",
                "width": 4,
            },
        )

    sio = socketio.AsyncServer(async_mode="asgi")
    ctx = register_handlers(sio, room_manager)
    sio.get_session = AsyncMock(
        return_value={"room_id": room.id, "player_id": drawer.id}
    )
    sio.emit = AsyncMock()
    sync = sio.handlers["/"]["request_sync_strokes"]

    # Claiming the first three actions, with the hash the server itself
    # computed for that prefix.
    await sync("drawer-sid", [5, canvas.generation, 3, canvas.hashes[2]])
    event, payload = sio.emit.await_args.args
    assert event == "sync_strokes_tail"
    assert payload[1] == 3
    assert payload[-1] == 5, "the tail names the request it answers"
    tail = decode_binary_canvas_history(payload[0])
    assert len(tail) == 2
    assert list(tail) == list(canvas.history)[3:]

    # Anything that does not check out falls back to the whole history, which
    # is what keeps the claim an optimization rather than a trust boundary.
    for bad in (
        [6, canvas.generation, 3, 999],
        [6, canvas.generation + 1, 3, canvas.hashes[2]],
        [6, canvas.generation, 99, canvas.hashes[2]],
        [6],
    ):
        sio.emit.reset_mock()
        # This is about the answer, not the rate: a resync floor holds one
        # caller to a few replays per window, and four claims in a row is more
        # than a real client would ever make.
        ctx.clear_command_budget("drawer-sid")
        await sync("drawer-sid", bad)
        assert sio.emit.await_args.args[0] == "sync_strokes", bad


async def test_a_sync_request_is_acknowledged_and_refused_with_a_retry_when_there_is_no_canvas():
    """#598: a request the server cannot answer says so, and when to ask again,
    instead of being dropped in silence on a quiet canvas."""
    from app.handlers.drawing import NO_CANVAS_RETRY_MS

    room_manager = RoomManager()
    room = room_manager.create_room(name="Room", is_public=True)
    player = room_manager.add_player(room, "Player")
    player.sid = "player-sid"
    sio = socketio.AsyncServer(async_mode="asgi")
    ctx = register_handlers(sio, room_manager)
    sio.get_session = AsyncMock(return_value={"room_id": room.id, "player_id": player.id})
    sio.emit = AsyncMock()
    handler = sio.handlers["/"]["request_sync_strokes"]

    async def sync(sid, payload):
        # About the answers, not the rate: the resync floor is its own test.
        ctx.clear_command_budget(sid)
        return await handler(sid, payload)

    # Between games there is no canvas: refused, with a retry delay.
    refused = await sync("player-sid", [3])
    assert refused["errorCode"] == "not_in_game" and refused["retryAfterMs"] == NO_CANVAS_RETRY_MS
    sio.emit.assert_not_awaited()

    # Malformed: refused before anything is looked up.
    for bad in (None, [], [0], ["1"], [1, 2], [1, 1, 2, 3, 4]):
        assert (await sync("player-sid", bad))["errorCode"] == "invalid_payload", bad

    # Once the turn is on, the same request is answered and acknowledged.
    room.game = Game(turn_order=[player.id])
    room.game.start_next_turn(canvas_generation=room.allocate_canvas_generation())
    room.game.force_prompt_choice()
    assert await sync("player-sid", [4]) == {"ok": True}
    assert sio.emit.await_args.args[0] == "sync_strokes"
    assert sio.emit.await_args.args[1][-1] == 4


def _relative_room():
    room_manager = RoomManager()
    room = room_manager.create_room(name="Room", is_public=True)
    drawer = room_manager.add_player(room, "Drawer")
    drawer.sid = "drawer-sid"
    room_manager.add_player(room, "Guesser")
    room.game = Game(turn_order=list(room.players))
    room.game.start_next_turn(canvas_generation=room.allocate_canvas_generation())
    room.game.force_prompt_choice()
    sio = socketio.AsyncServer(async_mode="asgi")
    ctx = register_handlers(sio, room_manager)
    sio.get_session = AsyncMock(return_value={"room_id": room.id, "player_id": drawer.id})
    sio.emit = AsyncMock()
    return ctx, sio, room


def _emitted(sio, event):
    return [call for call in sio.emit.await_args_list if call.args and call.args[0] == event]


async def test_relative_frames_extend_the_open_path_and_are_rebroadcast_verbatim():
    """#559: the server resolves the offsets against the path it holds, and
    the room is sent the drawer's bytes, not the server's idea of them."""
    ctx, sio, room = _relative_room()
    draw = sio.handlers["/"]["draw"]
    await draw("drawer-sid", encode_live_drawing("draw_start", {"x": 0.5, "y": 0.5, "color": "#112233", "width": 5}), canvas_action(room.game, 1))
    first = encode_live_drawing("draw_move", {"points": [{"x": 0.5, "y": 0.51}], "previous": {"x": 0.5, "y": 0.5}})
    second = encode_live_drawing("draw_move", {"points": [{"x": 0.51, "y": 0.52}, {"x": 0.52, "y": 0.52}], "previous": {"x": 0.5, "y": 0.51}})
    assert first[0] & 0x0F == 7 and second[0] & 0x0F == 7
    await draw("drawer-sid", first)
    await draw("drawer-sid", second)
    assert room.game.canvas.active_path_last_point() == (0.52, 0.52)
    await draw("drawer-sid", encode_live_drawing("draw_end"))

    [path] = list(room.game.canvas.history)
    assert [(round(x, 3), round(y, 3)) for x, y in path.points] == [(0.5, 0.5), (0.5, 0.51), (0.51, 0.52), (0.52, 0.52)]
    rebroadcast = [call.args[1] for call in _emitted(sio, "draw")]
    assert rebroadcast[1] == first and rebroadcast[2] == second
    assert _emitted(sio, "canvas_stale") == []


async def test_a_relative_frame_with_no_open_path_is_dropped_like_an_absolute_one():
    ctx, sio, room = _relative_room()
    draw = sio.handlers["/"]["draw"]
    await draw("drawer-sid", encode_live_drawing("draw_move", {"points": [{"x": 0.5, "y": 0.51}], "previous": {"x": 0.5, "y": 0.5}}))
    assert len(room.game.canvas.history) == 0
    assert _emitted(sio, "draw") == []


async def test_a_dropped_frame_closes_the_path_for_everyone_and_tells_the_drawer():
    """#559: a `draw` frame throttled at the door is dropped in silence, and a
    later relative frame would otherwise be resolved against a point the
    server never recorded. So the next frame closes the torn path where the
    server's copy ends: the room gets a `draw_end` with the commit, the
    drawer a recovery notice, and the rest of that path is discarded."""
    ctx, sio, room = _relative_room()
    draw = sio.handlers["/"]["draw"]
    await draw("drawer-sid", encode_live_drawing("draw_start", {"x": 0.5, "y": 0.5, "color": "#112233", "width": 5}), canvas_action(room.game, 1))
    await draw("drawer-sid", encode_live_drawing("draw_move", {"points": [{"x": 0.5, "y": 0.51}], "previous": {"x": 0.5, "y": 0.5}}))
    # The door dropped the next frame (the one reaching 0.52); nobody saw it.
    ctx.dropped_draw_frames.add("drawer-sid")
    sio.emit.reset_mock()

    late = encode_live_drawing("draw_move", {"points": [{"x": 0.52, "y": 0.53}], "previous": {"x": 0.5, "y": 0.52}})
    await draw("drawer-sid", late)
    [path] = list(room.game.canvas.history)
    assert [(round(x, 3), round(y, 3)) for x, y in path.points] == [(0.5, 0.5), (0.5, 0.51)]
    assert room.game.canvas.active_draw_sequence is None
    assert room.game.canvas.sequence == 1
    [(end_call,)] = [call.args[1:] for call in _emitted(sio, "draw")]
    assert end_call[0] == encode_live_drawing("draw_end") and end_call[1] is not None, "the room got the end and its commit"
    assert _emitted(sio, "canvas_commit"), "the drawer got its commit"
    [(notice,)] = [call.args[1:] for call in _emitted(sio, "canvas_stale")]
    assert notice[2] == "dropped_frame"
    assert "drawer-sid" not in ctx.dropped_draw_frames

    # The rest of the torn path trickles in and changes nothing; the next
    # action opens as usual.
    sio.emit.reset_mock()
    await draw("drawer-sid", encode_live_drawing("draw_move", {"points": [{"x": 0.6, "y": 0.6}]}))
    await draw("drawer-sid", encode_live_drawing("draw_end"))
    assert len(room.game.canvas.history) == 1 and _emitted(sio, "draw") == []
    await draw("drawer-sid", encode_live_drawing("draw_start", {"x": 0.1, "y": 0.1, "color": "#112233", "width": 5}), canvas_action(room.game, 2))
    assert len(room.game.canvas.history) == 2
    assert room.game.canvas.active_draw_sequence == 2


async def test_a_throttled_draw_frame_is_remembered_at_the_door():
    ctx, sio, _room = _relative_room()
    draw = sio.handlers["/"]["draw"]
    budget = ctx.command_budgets.for_command("draw")
    for _ in range(budget.limit + 1):
        await draw("drawer-sid", encode_live_drawing("draw_move", {"points": [{"x": 0.6, "y": 0.6}]}))
    assert "drawer-sid" in ctx.dropped_draw_frames


def _start(room, sio, sequence, x=0.5, y=0.5):
    return sio.handlers["/"]["draw"](
        "drawer-sid",
        encode_live_drawing("draw_start", {"x": x, "y": y, "color": "#112233", "width": 5}),
        canvas_action(room.game, sequence),
    )


async def test_a_final_batch_extends_and_closes_the_path_in_one_committed_frame():
    """#603: the points buffered when the pen lifted and the end travel as
    one frame, which carries the commit the way `draw_end` did; the history
    and its hash are what the two-frame form produces."""
    from app.canvas_history import canvas_history_hash

    ctx, sio, room = _relative_room()
    draw = sio.handlers["/"]["draw"]
    await _start(room, sio, 1)
    await draw("drawer-sid", encode_live_drawing("draw_move", {"points": [{"x": 0.5, "y": 0.51}], "previous": {"x": 0.5, "y": 0.5}}))
    sio.emit.reset_mock()
    final = encode_live_drawing("draw_move", {"points": [{"x": 0.51, "y": 0.52}, {"x": 0.52, "y": 0.52}], "previous": {"x": 0.5, "y": 0.51}, "ends": True})
    assert final[0] & 0x0F == 8
    await draw("drawer-sid", final)

    assert room.game.canvas.active_draw_sequence is None
    assert room.game.canvas.sequence == 1
    [(frame, commit)] = [call.args[1] for call in _emitted(sio, "draw")]
    assert frame == final and commit is not None, "one event, carrying the commit"
    assert _emitted(sio, "canvas_commit"), "and the drawer's own commit"
    one_frame = canvas_history_hash(room.game.canvas.history)

    ctx2, sio2, room2 = _relative_room()
    draw2 = sio2.handlers["/"]["draw"]
    await _start(room2, sio2, 1)
    await draw2("drawer-sid", encode_live_drawing("draw_move", {"points": [{"x": 0.5, "y": 0.51}], "previous": {"x": 0.5, "y": 0.5}}))
    await draw2("drawer-sid", encode_live_drawing("draw_move", {"points": [{"x": 0.51, "y": 0.52}, {"x": 0.52, "y": 0.52}], "previous": {"x": 0.5, "y": 0.51}}))
    await draw2("drawer-sid", encode_live_drawing("draw_end"))
    assert canvas_history_hash(room2.game.canvas.history) == one_frame
    assert room2.game.canvas.history.binary_payload() == room.game.canvas.history.binary_payload()


async def test_a_refused_final_batch_commits_nothing_and_leaves_the_path_open(monkeypatch):
    """A final batch past the point budget is refused whole: no points, no
    end, no commit - never a committed prefix the drawer did not draw."""
    from app import canvas_session

    ctx, sio, room = _relative_room()
    draw = sio.handlers["/"]["draw"]
    monkeypatch.setattr(canvas_session, "MAX_CANVAS_POINTS", 2)
    await _start(room, sio, 1)
    sio.emit.reset_mock()
    final = encode_live_drawing("draw_move", {"points": [{"x": 0.5, "y": 0.51}, {"x": 0.51, "y": 0.52}], "previous": {"x": 0.5, "y": 0.5}, "ends": True})
    await draw("drawer-sid", final)
    assert room.game.canvas.active_draw_sequence == 1, "still open"
    assert room.game.canvas.sequence == 0, "nothing committed"
    assert _emitted(sio, "draw") == [] and _emitted(sio, "canvas_commit") == []
    # The plain end still closes it, and commits.
    await draw("drawer-sid", encode_live_drawing("draw_end"))
    assert room.game.canvas.sequence == 1


async def test_a_final_batch_with_no_open_path_is_dropped():
    ctx, sio, room = _relative_room()
    draw = sio.handlers["/"]["draw"]
    await draw("drawer-sid", encode_live_drawing("draw_move", {"points": [{"x": 0.5, "y": 0.51}], "previous": {"x": 0.5, "y": 0.5}, "ends": True}))
    assert len(room.game.canvas.history) == 0 and _emitted(sio, "draw") == []
