import asyncio
from contextlib import suppress
from unittest.mock import AsyncMock

import pytest
import socketio

from app import events
from app.events import _validated_draw_payload, register_handlers
from app.game import DRAWING_SECONDS, Game
from app.rooms import STARTING_SCORE, RoomManager


def test_validated_draw_payload_normalizes_a_pen_start():
    assert _validated_draw_payload(
        "draw_start",
        {"x": 0, "y": 1, "color": "#AABBCC", "width": 4},
    ) == {"x": 0.0, "y": 1.0, "color": "#aabbcc", "width": 4.0}


def test_validated_draw_payload_preserves_off_canvas_pointer_path():
    payload = {
        "points": [
            {"x": 0.9, "y": 0.5},
            {"x": 1.2, "y": 0.6},
            {"x": 0.8, "y": 0.7},
        ]
    }

    assert _validated_draw_payload("draw_move", payload) == {
        "points": [
            {"x": 0.9, "y": 0.5},
            {"x": 1.2, "y": 0.6},
            {"x": 0.8, "y": 0.7},
        ]
    }


@pytest.mark.parametrize(
    "event_name,payload",
    [
        ("draw_start", {"x": -1_000_001, "y": 0.5, "color": "#000000", "width": 4}),
        ("draw_start", {"x": 0.5, "y": 0.5, "color": "black", "width": 4}),
        ("draw_move", {"points": []}),
        ("draw_move", {"points": [{"x": float("nan"), "y": 0.5}]}),
        (
            "draw_shape",
            {
                "shape": "square",
                "from": {"x": 0.1, "y": 0.1},
                "to": {"x": 0.9, "y": 0.9},
                "color": "#000000",
                "width": 4,
            },
        ),
    ],
)
def test_validated_draw_payload_rejects_malformed_input(event_name, payload):
    assert _validated_draw_payload(event_name, payload) is None


@pytest.mark.asyncio
async def test_create_room_accepts_no_scoring_and_disables_point_purchase_hints():
    room_manager = RoomManager()
    sio = socketio.AsyncServer(async_mode="asgi")
    register_handlers(sio, room_manager)
    sio.get_session = AsyncMock(return_value=None)
    sio.save_session = AsyncMock()
    sio.enter_room = AsyncMock()
    sio.emit = AsyncMock()

    response = await sio.handlers["/"]["create_room"](
        "host-sid",
        {
            "nickname": "Host",
            "name": "Casual",
            "scoringMode": "none",
            "hintMode": "purchase",
        },
    )

    room = room_manager.get_room(response["roomId"])
    assert room is not None
    assert room.scoring_mode == "none"
    assert room.hint_mode == "none"
    assert room.player_list()[0].score == 0


@pytest.mark.asyncio
async def test_draw_handler_rejects_events_outside_drawing_phase():
    room_manager = RoomManager()
    room = room_manager.create_room(name="Room", is_public=True)
    drawer = room_manager.add_player(room, "Drawer")
    room_manager.add_player(room, "Guesser")
    room.game = Game(turn_order=list(room.players))
    room.game.start_next_turn()

    sio = socketio.AsyncServer(async_mode="asgi")
    register_handlers(sio, room_manager)
    sio.get_session = AsyncMock(return_value={"room_id": room.id, "token": drawer.token})
    sio.emit = AsyncMock()
    draw_start = sio.handlers["/"]["draw_start"]
    payload = {"x": 0.2, "y": 0.3, "color": "#000000", "width": 4}

    await draw_start("drawer-sid", payload)
    assert room.game.strokes == []

    room.game.force_word_choice()
    await draw_start("drawer-sid", payload)
    assert room.game.strokes == [
        {
            "event": "draw_start",
            "payload": {"x": 0.2, "y": 0.3, "color": "#000000", "width": 4.0},
        }
    ]


@pytest.mark.asyncio
async def test_reconnecting_drawer_receives_word_choices_during_choosing_phase():
    room_manager = RoomManager()
    room = room_manager.create_room(name="Room", is_public=True)
    drawer = room_manager.add_player(room, "Drawer")
    room_manager.add_player(room, "Guesser")
    drawer.connected = False
    drawer.sid = None
    room.game = Game(turn_order=list(room.players))
    room.game.start_next_turn()
    room.game.set_phase_deadline(15)

    sio = socketio.AsyncServer(async_mode="asgi")
    register_handlers(sio, room_manager)
    sio.get_session = AsyncMock(return_value=None)
    sio.save_session = AsyncMock()
    sio.enter_room = AsyncMock()
    sio.emit = AsyncMock()
    join_room = sio.handlers["/"]["join_room"]

    response = await join_room(
        "new-sid",
        {"code": room.code, "token": drawer.token, "nickname": drawer.nickname},
    )

    emitted_events = [call.args[0] for call in sio.emit.await_args_list]
    assert response["ok"] is True
    assert "sync_game" in emitted_events
    assert "your_word_choices" in emitted_events
    assert "you_are_drawing" not in emitted_events


@pytest.mark.asyncio
async def test_explicit_drawer_leave_starts_next_survivor_turn():
    room_manager = RoomManager()
    room = room_manager.create_room(name="Room", is_public=True, rounds=2)
    drawer = room_manager.add_player(room, "Drawer")
    next_player = room_manager.add_player(room, "Next")
    drawer.sid = "drawer-sid"
    next_player.sid = "next-sid"
    room.state = "playing"
    room.game = Game(turn_order=list(room.players), rounds_total=2)
    room.game.start_next_turn()
    room.game.force_word_choice()

    sio = socketio.AsyncServer(async_mode="asgi")
    register_handlers(sio, room_manager)
    sio.get_session = AsyncMock(return_value={"room_id": room.id, "token": drawer.token})
    sio.leave_room = AsyncMock()
    sio.save_session = AsyncMock()
    sio.emit = AsyncMock()
    leave_room = sio.handlers["/"]["leave_room"]

    await leave_room(drawer.sid)

    assert room.game.current_drawer == next_player.token
    assert room.game.phase.value == "choosing_word"
    assert room.game.round_number == 1

    timer = events._phase_timers.pop(room.id)
    timer.cancel()
    with suppress(asyncio.CancelledError):
        await timer


@pytest.mark.asyncio
async def test_simultaneous_final_guesses_end_round_once():
    room_manager = RoomManager()
    room = room_manager.create_room(name="Room", is_public=True)
    players = [room_manager.add_player(room, name) for name in ("Drawer", "One", "Two")]
    for index, player in enumerate(players):
        player.sid = f"sid-{index}"
    room.game = Game(turn_order=[player.token for player in players], rounds_total=2)
    room.game.start_next_turn()
    room.game.force_word_choice()
    room.game.set_phase_deadline(DRAWING_SECONDS)
    answer = room.game.word

    sio = socketio.AsyncServer(async_mode="asgi")
    register_handlers(sio, room_manager)
    sessions = {
        player.sid: {"room_id": room.id, "token": player.token}
        for player in players
    }

    async def get_session(sid):
        return sessions[sid]

    async def yielding_emit(*args, **kwargs):
        await asyncio.sleep(0)

    sio.get_session = AsyncMock(side_effect=get_session)
    sio.emit = AsyncMock(side_effect=yielding_emit)
    guess = sio.handlers["/"]["guess"]

    await asyncio.gather(
        guess(players[1].sid, {"text": answer}),
        guess(players[2].sid, {"text": answer}),
    )

    drawer_bonus = sum(
        round(points * 10 / 100)
        for points in room.game.guess_points.values()
    )
    assert players[0].score == STARTING_SCORE + drawer_bonus
    assert [call.args[0] for call in sio.emit.await_args_list].count("round_ended") == 1
    round_ended_payload = next(
        call.args[1] for call in sio.emit.await_args_list if call.args[0] == "round_ended"
    )
    assert {guess["nickname"] for guess in round_ended_payload["guesses"]} == {"One", "Two"}
    assert all(0 <= guess["seconds"] <= DRAWING_SECONDS for guess in round_ended_payload["guesses"])

    timer = events._phase_timers.pop(room.id)
    timer.cancel()
    with suppress(asyncio.CancelledError):
        await timer
