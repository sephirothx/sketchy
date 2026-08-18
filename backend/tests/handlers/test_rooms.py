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
from app.rooms import (
    ANONYMOUS_NAME_COLOR,
    DrawingRecapEntry,
    STARTING_SCORE,
    RoomManager,
)
from tests.fake_user_repo import FakeUserRepository
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
async def test_registered_player_name_color_is_created_and_can_be_updated_live():
    room_manager = RoomManager()
    user_repo = FakeUserRepository()
    user_repo.add_registered("user-1", "HostPlayer")
    sio = socketio.AsyncServer(async_mode="asgi")
    register_handlers(sio, room_manager, user_repo=user_repo)
    sio.get_session = AsyncMock(return_value={"user_id": "user-1"})
    sio.save_session = AsyncMock()
    sio.enter_room = AsyncMock()
    sio.emit = AsyncMock()

    response = await sio.handlers["/"]["create_room"](
        "host-sid",
        {
            "nickname": "Ignored",
            "name": "Room",
            "nameColor": "#AABBCC",
        },
    )
    room = room_manager.get_room(response["roomId"])
    assert room is not None
    player = room.players[response["playerId"]]
    # A registered player always plays as their username, whatever they sent.
    assert player.nickname == "HostPlayer"
    assert player.is_anonymous is False
    assert player.name_color == "#aabbcc"
    assert room.to_state_payload()["players"][0]["nameColor"] == "#aabbcc"

    sio.get_session = AsyncMock(
        return_value={"room_id": room.id, "player_id": player.id, "user_id": "user-1"}
    )
    update = sio.handlers["/"]["update_player_settings"]
    assert await update("host-sid", {"nameColor": "#123ABC"}) == {"ok": True}
    assert player.name_color == "#123abc"
    assert sio.emit.await_args_list[-1].args[0] == "room_state"

    assert await update("host-sid", {"nameColor": "red"}) == {
        "ok": False,
        "error": "Invalid player name color",
    }
    assert player.name_color == "#123abc"


@pytest.mark.asyncio
async def test_anonymous_player_is_grey_and_cannot_change_color():
    room_manager = RoomManager()
    sio = socketio.AsyncServer(async_mode="asgi")
    register_handlers(sio, room_manager, user_repo=FakeUserRepository())
    sio.get_session = AsyncMock(return_value={"user_id": "guest-1"})
    sio.save_session = AsyncMock()
    sio.enter_room = AsyncMock()
    sio.emit = AsyncMock()

    response = await sio.handlers["/"]["create_room"](
        "guest-sid",
        {"nickname": "Wanderer", "name": "Room", "nameColor": "#AABBCC"},
    )
    room = room_manager.get_room(response["roomId"])
    player = room.players[response["playerId"]]
    assert player.is_anonymous is True
    assert player.name_color == ANONYMOUS_NAME_COLOR
    assert room.to_state_payload()["players"][0]["isAnonymous"] is True

    sio.get_session = AsyncMock(
        return_value={"room_id": room.id, "player_id": player.id, "user_id": "guest-1"}
    )
    update = sio.handlers["/"]["update_player_settings"]
    result = await update("guest-sid", {"nameColor": "#123ABC"})
    assert result["ok"] is False
    assert player.name_color == ANONYMOUS_NAME_COLOR

@pytest.mark.asyncio
async def test_only_host_can_update_waiting_room_settings_and_not_during_game():
    room_manager = RoomManager()
    room = room_manager.create_room(name="Room", is_public=True)
    host = room_manager.add_player(room, "Host")
    guest = room_manager.add_player(room, "Guest")
    host.sid, guest.sid = "host-sid", "guest-sid"
    sio = socketio.AsyncServer(async_mode="asgi")
    register_handlers(sio, room_manager)
    sio.emit = AsyncMock()
    update = sio.handlers["/"]["update_room_settings"]

    sio.get_session = AsyncMock(return_value={"room_id": room.id, "player_id": guest.id})
    assert (await update("guest-sid", {"rounds": 4}))["ok"] is False

    sio.get_session = AsyncMock(return_value={"room_id": room.id, "player_id": host.id})
    room.state = "playing"
    assert "waiting room" in (await update("host-sid", {"rounds": 4}))["error"]
    assert (await sio.handlers["/"]["send_chat"]("host-sid", {"text": "nope"}))["ok"] is False

@pytest.mark.asyncio
async def test_room_members_can_inspect_custom_words_only_while_waiting():
    room_manager = RoomManager()
    room = room_manager.create_room(
        name="Room",
        custom_words=["red panda", "apple"],
        custom_words_only=True,
    )
    room_manager.add_player(room, "Host")
    guest = room_manager.add_player(room, "Guest")
    guest.sid = "guest-sid"
    sio = socketio.AsyncServer(async_mode="asgi")
    register_handlers(sio, room_manager)
    sio.get_session = AsyncMock(
        return_value={"room_id": room.id, "player_id": guest.id}
    )
    get_custom_words = sio.handlers["/"]["get_custom_words"]

    response = await get_custom_words("guest-sid", {})
    assert response == {"ok": True, "words": ["red panda", "apple"]}

    room.state = "playing"
    playing_response = await get_custom_words("guest-sid", {})
    assert playing_response["ok"] is False
    assert "waiting room" in playing_response["error"]

    room.state = "waiting"
    guest.is_spectator = True
    spectator_response = await get_custom_words("guest-sid", {})
    assert spectator_response == {
        "ok": False,
        "error": "Only players can view custom words",
    }

    sio.get_session = AsyncMock(return_value=None)
    assert (await get_custom_words("outsider-sid", {}))["ok"] is False

@pytest.mark.asyncio
async def test_waiting_spectator_can_become_player_when_space_is_available():
    room_manager = RoomManager()
    room = room_manager.create_room(name="Room", max_players=2)
    room_manager.add_player(room, "Host")
    spectator = room_manager.add_player(room, "Spectator", is_spectator=True)
    spectator.sid = "spectator-sid"
    sio = socketio.AsyncServer(async_mode="asgi")
    register_handlers(sio, room_manager)
    sio.get_session = AsyncMock(
        return_value={"room_id": room.id, "player_id": spectator.id}
    )
    sio.emit = AsyncMock()

    response = await sio.handlers["/"]["become_player"]("spectator-sid", {})

    assert response == {"ok": True}
    assert spectator.is_spectator is False
    assert spectator.score == STARTING_SCORE
    assert any(
        call.args[0] == "room_state"
        and any(
            player["playerId"] == spectator.id and not player["isSpectator"]
            for player in call.args[1]["players"]
        )
        for call in sio.emit.await_args_list
    )

@pytest.mark.asyncio
async def test_spectator_cannot_become_player_when_room_is_full_or_playing():
    room_manager = RoomManager()
    room = room_manager.create_room(name="Room", max_players=2)
    room_manager.add_player(room, "Host")
    room_manager.add_player(room, "Player")
    spectator = room_manager.add_player(room, "Spectator", is_spectator=True)
    spectator.sid = "spectator-sid"
    sio = socketio.AsyncServer(async_mode="asgi")
    register_handlers(sio, room_manager)
    sio.get_session = AsyncMock(
        return_value={"room_id": room.id, "player_id": spectator.id}
    )
    sio.emit = AsyncMock()
    become_player = sio.handlers["/"]["become_player"]

    full_response = await become_player("spectator-sid", {})
    assert full_response == {"ok": False, "error": "Player slots are full"}
    assert spectator.is_spectator is True

    room.players[next(
        token for token, player in room.players.items()
        if player.nickname == "Player"
    )].is_spectator = True
    room.state = "playing"
    playing_response = await become_player("spectator-sid", {})
    assert "waiting room" in playing_response["error"]
    assert spectator.is_spectator is True

@pytest.mark.asyncio
async def test_room_preview_returns_private_room_metadata_without_joining():
    room_manager = RoomManager()
    room = room_manager.create_room(
        name="Invite Only",
        is_public=False,
        max_players=2,
        rounds=4,
        drawing_seconds=90,
        hint_mode="checkpoints",
    )
    room_manager.add_player(room, "Host")

    sio = socketio.AsyncServer(async_mode="asgi")
    register_handlers(sio, room_manager)
    response = await sio.handlers["/"]["get_room_preview"](
        "visitor-sid",
        {"code": room.code.lower()},
    )

    assert response["ok"] is True
    assert response["room"]["name"] == "Invite Only"
    assert response["room"]["isPublic"] is False
    assert response["room"]["playerCount"] == 1
    assert response["room"]["maxPlayers"] == 2
    assert response["room"]["rounds"] == 4
    assert response["room"]["drawingSeconds"] == 90
    assert response["room"]["hintMode"] == "checkpoints"
    assert len(room.players) == 1
