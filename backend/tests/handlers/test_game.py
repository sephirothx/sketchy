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
async def test_explicit_drawer_leave_starts_next_survivor_turn():
    room_manager = RoomManager()
    room = room_manager.create_room(name="Room", is_public=True, rounds=2)
    drawer = room_manager.add_player(room, "Drawer")
    next_player = room_manager.add_player(room, "Next")
    drawer.sid = "drawer-sid"
    next_player.sid = "next-sid"
    room.state = "playing"
    room.game = Game(turn_order=list(room.players), rounds_total=2)
    room.game.start_next_turn(canvas_generation=room.allocate_canvas_generation())
    room.game.force_word_choice()

    sio = socketio.AsyncServer(async_mode="asgi")
    timers = register_handlers(sio, room_manager).timers
    sio.get_session = AsyncMock(return_value={"room_id": room.id, "player_id": drawer.id})
    sio.leave_room = AsyncMock()
    sio.save_session = AsyncMock()
    sio.emit = AsyncMock()
    leave_room = sio.handlers["/"]["leave_room"]

    await leave_room(drawer.sid)

    assert room.game.current_drawer == next_player.id
    assert room.game.phase.value == "choosing_word"
    assert room.game.round_number == 1

    timer = timers.phase_timers.pop(room.id)
    timer.cancel()
    with suppress(asyncio.CancelledError):
        await timer

@pytest.mark.asyncio
async def test_starting_new_game_clears_previous_drawing_recap():
    room_manager = RoomManager()
    room = room_manager.create_room(name="Room", is_public=True)
    host = room_manager.add_player(room, "Host")
    guest = room_manager.add_player(room, "Guest")
    host.sid = "host-sid"
    guest.sid = "guest-sid"
    room.last_game_drawings.append(
        DrawingRecapEntry(
            round_number=1,
            turn_number=1,
            drawer_id=host.id,
            drawer_nickname=host.nickname,
            drawer_name_color=host.name_color,
            word="old",
            action_count=0,
            canvas_history=encode_canvas_history([]),
        )
    )

    sio = socketio.AsyncServer(async_mode="asgi")
    timers = register_handlers(sio, room_manager).timers
    sio.get_session = AsyncMock(
        return_value={"room_id": room.id, "player_id": host.id},
    )
    sio.emit = AsyncMock()

    response = await sio.handlers["/"]["start_game"](host.sid)

    assert response == {"ok": True}
    assert room.last_game_drawings == []

    timer = timers.phase_timers.pop(room.id)
    timer.cancel()
    with suppress(asyncio.CancelledError):
        await timer

@pytest.mark.asyncio
async def test_schedule_hint_checkpoints_emits_unmasked_word_to_drawer():
    room_manager = RoomManager()
    room = room_manager.create_room(name="Room", is_public=True)
    drawer = room_manager.add_player(room, "Drawer")
    guesser = room_manager.add_player(room, "Guesser")
    drawer.sid, guesser.sid = "drawer-sid", "guesser-sid"

    room.game = Game(turn_order=[drawer.id, guesser.id], word_pool=["banana"], rounds_total=1, hint_mode="checkpoints", drawing_seconds=0.05)
    room.game.start_next_turn(canvas_generation=room.allocate_canvas_generation())

    sio = socketio.AsyncServer(async_mode="asgi")
    timers = register_handlers(sio, room_manager).timers
    sessions = {
        "drawer-sid": {"room_id": room.id, "player_id": drawer.id},
        "guesser-sid": {"room_id": room.id, "player_id": guesser.id},
    }
    sio.get_session = AsyncMock(side_effect=lambda sid: sessions.get(sid))
    sio.emit = AsyncMock()

    select_word = sio.handlers["/"]["select_word"]
    rejected = await select_word("drawer-sid", {"word": "not-a-choice"})
    assert rejected == {"ok": False, "error": "That word is no longer available"}

    accepted = await select_word("drawer-sid", {"word": "banana"})
    assert accepted == {"ok": True}
    await asyncio.sleep(0.1)

    drawer_hints = [call for call in sio.emit.await_args_list if call.args[0] == "hint_revealed" and call.kwargs.get("to") == "drawer-sid"]
    guesser_hints = [call for call in sio.emit.await_args_list if call.args[0] == "hint_revealed" and call.kwargs.get("to") == "guesser-sid"]

    assert len(drawer_hints) >= 1
    assert drawer_hints[0].args[1]["maskedWord"] == "banana"

    assert len(guesser_hints) >= 1
    assert guesser_hints[0].args[1]["maskedWord"] != "banana"

    timer = timers.phase_timers.pop(room.id, None)
    if timer:
        timer.cancel()
        with suppress(asyncio.CancelledError):
            await timer
