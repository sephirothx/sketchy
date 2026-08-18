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
async def test_public_player_ids_are_broadcast_in_state_payloads():
    room_manager = RoomManager()
    sio = socketio.AsyncServer(async_mode="asgi")
    register_handlers(sio, room_manager)
    sio.get_session = AsyncMock(return_value=None)
    sio.save_session = AsyncMock()
    sio.enter_room = AsyncMock()
    sio.emit = AsyncMock()

    response = await sio.handlers["/"]["create_room"](
        "host-sid", {"nickname": "Host", "name": "Room"}
    )
    room = room_manager.get_room(response["roomId"])
    assert room is not None
    host = room.players[response["playerId"]]
    assert response["playerId"] == host.id
    assert response == {
        "ok": True,
        "roomId": room.id,
        "code": room.code,
        "playerId": host.id,
    }

    room.last_game_scores = [
        {
            "playerId": host.id,
            "nickname": host.nickname,
            "nameColor": host.name_color,
            "score": host.score,
        }
    ]
    room.last_game_drawings.append(
        DrawingRecapEntry(
            round_number=1,
            turn_number=1,
            drawer_id=host.id,
            drawer_nickname=host.nickname,
            drawer_name_color=host.name_color,
            word="apple",
            action_count=0,
            canvas_history=encode_canvas_history([]),
        )
    )
    host.kick_votes.add(host.id)
    sio.get_session = AsyncMock(
        return_value={"room_id": room.id, "player_id": host.id, "user_id": host.user_id}
    )
    assert await sio.handlers["/"]["send_chat"](
        "host-sid", {"text": "hello"}
    ) == {"ok": True}

    shared_payloads = [
        room.to_state_payload(),
        room.to_public_summary(),
        room.drawing_recap_metadata(),
        *[call.args[1] for call in sio.emit.await_args_list if len(call.args) > 1],
    ]
    assert any(
        player["playerId"] == host.id
        for player in room.to_state_payload()["players"]
    )


@pytest.mark.asyncio
async def test_reconnect_supersedes_old_socket_and_rejects_stale_host_commands():
    room_manager = RoomManager()
    room = room_manager.create_room(name="Room")
    host = room_manager.add_player(room, "Host")
    host.sid = "old-sid"

    sio = socketio.AsyncServer(async_mode="asgi")
    register_handlers(sio, room_manager)
    sio.get_session = AsyncMock(return_value={"user_id": host.user_id})
    sio.save_session = AsyncMock()
    sio.enter_room = AsyncMock()
    sio.disconnect = AsyncMock()
    sio.emit = AsyncMock()

    response = await sio.handlers["/"]["join_room"](
        "new-sid",
        {"code": room.code, "nickname": "Host"},
    )

    assert response["ok"] is True
    assert response["playerId"] == host.id
    assert host.sid == "new-sid"
    sio.disconnect.assert_awaited_once_with("old-sid")

    sio.get_session = AsyncMock(
        side_effect=lambda sid: {"room_id": room.id, "player_id": host.id, "user_id": host.user_id}
    )
    update_settings = sio.handlers["/"]["update_room_settings"]
    stale = await update_settings("old-sid", {"rounds": 4})
    current = await update_settings("new-sid", {"rounds": 4})
    assert stale["ok"] is False
    assert current == {"ok": True}
    assert room.rounds == 4


@pytest.mark.asyncio
async def test_session_player_id_cannot_impersonate_another_active_player():
    room_manager = RoomManager()
    room = room_manager.create_room(name="Room")
    host = room_manager.add_player(room, "Host")
    guest = room_manager.add_player(room, "Guest")
    host.sid = "host-sid"
    guest.sid = "guest-sid"

    sio = socketio.AsyncServer(async_mode="asgi")
    register_handlers(sio, room_manager)
    sio.get_session = AsyncMock(
        return_value={"room_id": room.id, "player_id": guest.id, "user_id": guest.user_id}
    )
    sio.emit = AsyncMock()

    response = await sio.handlers["/"]["send_chat"](
        "attacker-sid", {"text": "forged"}
    )
    assert response["ok"] is False
    assert not any(
        call.args[0] == "chat_message" and call.args[1].get("text") == "forged"
        for call in sio.emit.await_args_list
    )


@pytest.mark.asyncio
async def test_reconnecting_drawer_receives_word_choices_during_choosing_phase():
    room_manager = RoomManager()
    room = room_manager.create_room(name="Room", is_public=True)
    drawer = room_manager.add_player(room, "Drawer")
    room_manager.add_player(room, "Guesser")
    drawer.connected = False
    drawer.sid = None
    room.game = Game(turn_order=list(room.players))
    room.game.start_next_turn(canvas_generation=room.allocate_canvas_generation())
    room.game.set_phase_deadline(15)

    sio = socketio.AsyncServer(async_mode="asgi")
    register_handlers(sio, room_manager)
    sio.get_session = AsyncMock(return_value={"user_id": drawer.user_id})
    sio.save_session = AsyncMock()
    sio.enter_room = AsyncMock()
    sio.emit = AsyncMock()
    join_room = sio.handlers["/"]["join_room"]

    response = await join_room(
        "new-sid",
        {
            "code": room.code,
            "nickname": drawer.nickname,
        },
    )

    emitted_events = [call.args[0] for call in sio.emit.await_args_list]
    assert response["ok"] is True
    assert "sync_game" in emitted_events
    assert "your_word_choices" in emitted_events
    assert "you_are_drawing" not in emitted_events


@pytest.mark.asyncio
async def test_already_joined_socket_resyncs_active_drawing_state():
    """Soft health checks must refresh game state even when the sid is unchanged."""
    room_manager = RoomManager()
    room = room_manager.create_room(name="Room", is_public=True)
    drawer = room_manager.add_player(room, "Drawer")
    room_manager.add_player(room, "Guesser")
    drawer.sid = "drawer-sid"
    room.state = "playing"
    room.game = Game(turn_order=list(room.players))
    room.game.start_next_turn(canvas_generation=room.allocate_canvas_generation())
    room.game.force_word_choice()
    room.game.set_phase_deadline(DRAWING_SECONDS)

    sio = socketio.AsyncServer(async_mode="asgi")
    register_handlers(sio, room_manager)
    sio.get_session = AsyncMock(return_value={"room_id": room.id, "player_id": drawer.id, "user_id": drawer.user_id})
    sio.emit = AsyncMock()
    join_room = sio.handlers["/"]["join_room"]

    response = await join_room(
        "drawer-sid",
        {"code": room.code, "nickname": drawer.nickname},
    )

    emitted_events = [call.args[0] for call in sio.emit.await_args_list]
    assert response == {
        "ok": True,
        "roomId": room.id,
        "code": room.code,
        "playerId": drawer.id,
    }
    assert "sync_game" in emitted_events
    assert "you_are_drawing" in emitted_events
    assert "player_reconnected" not in emitted_events
    assert "player_joined" not in emitted_events

@pytest.mark.asyncio
async def test_already_joined_socket_resyncs_round_end_overlay():
    room_manager = RoomManager()
    room = room_manager.create_room(name="Room", is_public=True)
    drawer = room_manager.add_player(room, "Drawer")
    guesser = room_manager.add_player(room, "Guesser")
    drawer.sid = "drawer-sid"
    guesser.sid = "guesser-sid"
    room.state = "playing"
    room.game = Game(turn_order=[drawer.id, guesser.id])
    room.game.start_next_turn(canvas_generation=room.allocate_canvas_generation())
    room.game.force_word_choice()
    room.game.guess_points[guesser.id] = 200
    room.game.guess_times[guesser.id] = 12.0
    assert room.game.end_round() is not None
    room.game.set_phase_deadline(5)

    sio = socketio.AsyncServer(async_mode="asgi")
    register_handlers(sio, room_manager)
    sio.get_session = AsyncMock(return_value={"room_id": room.id, "player_id": drawer.id})
    sio.emit = AsyncMock()
    join_room = sio.handlers["/"]["join_room"]

    response = await join_room(
        "drawer-sid",
        {"code": room.code, "nickname": drawer.nickname},
    )

    round_ended_calls = [call for call in sio.emit.await_args_list if call.args[0] == "round_ended"]
    assert response["ok"] is True
    assert round_ended_calls
    assert round_ended_calls[0].kwargs.get("to") == "drawer-sid"
    assert round_ended_calls[0].args[1]["word"] == room.game.word

@pytest.mark.asyncio
async def test_session_ping_reports_phase_or_needs_rebind():
    room_manager = RoomManager()
    room = room_manager.create_room(name="Room", is_public=True)
    drawer = room_manager.add_player(room, "Drawer")
    room_manager.add_player(room, "Guesser")
    drawer.sid = "drawer-sid"
    room.state = "playing"
    room.game = Game(turn_order=list(room.players))
    room.game.start_next_turn(canvas_generation=room.allocate_canvas_generation())
    room.game.force_word_choice()
    room.game.set_phase_deadline(DRAWING_SECONDS)

    sio = socketio.AsyncServer(async_mode="asgi")
    register_handlers(sio, room_manager)
    session_ping = sio.handlers["/"]["session_ping"]

    sio.get_session = AsyncMock(return_value={"room_id": room.id, "player_id": drawer.id})
    ok = await session_ping("drawer-sid")
    assert ok[0] == 1
    assert ok[1] == 2  # drawing
    assert ok[2] == room.game.round_number
    assert isinstance(ok[3], int)
    assert ok[4] == room.game.canvas.generation
    assert ok[5] == room.game.canvas.sequence

    sio.get_session = AsyncMock(return_value=None)
    missing = await session_ping("ghost-sid")
    assert missing == [0]

@pytest.mark.asyncio
async def test_soft_already_joined_skips_canvas_sync():
    room_manager = RoomManager()
    room = room_manager.create_room(name="Room", is_public=True)
    drawer = room_manager.add_player(room, "Drawer")
    room_manager.add_player(room, "Guesser")
    drawer.sid = "drawer-sid"
    room.state = "playing"
    room.game = Game(turn_order=list(room.players))
    room.game.start_next_turn(canvas_generation=room.allocate_canvas_generation())
    room.game.force_word_choice()
    room.game.set_phase_deadline(DRAWING_SECONDS)

    sio = socketio.AsyncServer(async_mode="asgi")
    register_handlers(sio, room_manager)
    sio.get_session = AsyncMock(return_value={"room_id": room.id, "player_id": drawer.id})
    sio.emit = AsyncMock()
    join_room = sio.handlers["/"]["join_room"]

    response = await join_room(
        "drawer-sid",
        {"code": room.code, "nickname": drawer.nickname, "soft": True},
    )

    emitted_events = [call.args[0] for call in sio.emit.await_args_list]
    assert response["ok"] is True
    assert "sync_game" in emitted_events
    assert "sync_strokes" not in emitted_events
