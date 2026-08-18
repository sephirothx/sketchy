import asyncio
from contextlib import suppress
from dataclasses import replace
from datetime import datetime, timezone
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
from app.auth.nickname import NICKNAME_RULES_MESSAGE
from app.handlers import register_all_handlers as register_handlers
from app.game import DRAWING_SECONDS, Game, Phase
from app.live_drawing import encode_live_drawing
from app.message_limits import MAX_CHAT_MESSAGE_LENGTH
from app.repositories.interfaces import UserData
from app.rooms import DrawingRecapEntry, GUEST_NAME_COLOR, STARTING_SCORE, RoomManager
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
async def test_player_name_color_is_created_and_can_be_updated_live():
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
            "name": "Room",
            "nameColor": "#AABBCC",
        },
    )
    room = room_manager.get_room(response["roomId"])
    assert room is not None
    player = room.players[response["playerId"]]
    assert player.name_color == "#aabbcc"
    assert room.to_state_payload()["players"][0]["nameColor"] == "#aabbcc"

    sio.get_session = AsyncMock(
        return_value={"room_id": room.id, "player_id": player.id}
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


def _user(**kwargs) -> UserData:
    now = datetime.now(timezone.utc)
    payload = {
        "id": "user-1",
        "username": None,
        "display_name": "Guest",
        "name_color": None,
        "avatar_url": None,
        "is_anonymous": True,
        "created_at": now,
        "last_login_at": now,
        "updated_at": now,
    }
    payload.update(kwargs)
    return UserData(**payload)


class _FakeUserRepo:
    def __init__(self, users: list[UserData]):
        self.users = {user.id: user for user in users}

    async def get_by_id(self, user_id: str):
        return self.users.get(user_id)

    async def get_by_username(self, username: str):
        needle = username.strip().lower()
        for user in self.users.values():
            if user.username and user.username.lower() == needle:
                return user
        return None

    async def update_profile(self, user_id: str, **kwargs):
        user = self.users[user_id]
        if kwargs.get("display_name"):
            user = replace(user, display_name=kwargs["display_name"])
            self.users[user_id] = user
        return user


@pytest.mark.asyncio
async def test_guest_name_color_is_locked_and_display_name_is_persisted():
    guest = _user(id="guest-1", display_name="Guest")
    repo = _FakeUserRepo([guest])
    room_manager = RoomManager()
    sio = socketio.AsyncServer(async_mode="asgi")
    register_handlers(sio, room_manager, user_repo=repo)
    sio.get_session = AsyncMock(return_value={"user_id": "guest-1"})
    sio.save_session = AsyncMock()
    sio.enter_room = AsyncMock()
    sio.emit = AsyncMock()

    response = await sio.handlers["/"]["create_room"](
        "guest-sid",
        {"nickname": "Stefano", "name": "Room", "nameColor": "#AABBCC"},
    )
    room = room_manager.get_room(response["roomId"])
    player = room.players[response["playerId"]]
    assert player.is_anonymous is True
    assert player.nickname == "Stefano"
    assert player.name_color == GUEST_NAME_COLOR
    assert repo.users["guest-1"].display_name == "Stefano"

    sio.get_session = AsyncMock(
        return_value={"room_id": room.id, "player_id": player.id, "user_id": "guest-1"}
    )
    update = await sio.handlers["/"]["update_player_settings"](
        "guest-sid", {"nameColor": "#123ABC"}
    )
    assert update == {"ok": False, "error": "Guest accounts cannot customize name color"}
    assert player.name_color == GUEST_NAME_COLOR


@pytest.mark.asyncio
async def test_registered_username_is_enforced_and_guests_cannot_impersonate_it():
    registered = _user(
        id="bob-1",
        username="BobUser",
        display_name="BobUser",
        is_anonymous=False,
    )
    guest = _user(id="guest-2", display_name="Guest")
    repo = _FakeUserRepo([registered, guest])
    room_manager = RoomManager()
    sio = socketio.AsyncServer(async_mode="asgi")
    register_handlers(sio, room_manager, user_repo=repo)
    sio.save_session = AsyncMock()
    sio.enter_room = AsyncMock()
    sio.emit = AsyncMock()

    sio.get_session = AsyncMock(return_value={"user_id": "bob-1"})
    created = await sio.handlers["/"]["create_room"](
        "bob-sid",
        {"nickname": "CustomNick", "name": "BobRoom"},
    )
    room = room_manager.get_room(created["roomId"])
    assert room.players[created["playerId"]].nickname == "BobUser"
    assert room.players[created["playerId"]].is_anonymous is False

    sio.get_session = AsyncMock(return_value={"user_id": "guest-2"})
    rejected = await sio.handlers["/"]["create_room"](
        "guest-sid",
        {"nickname": "BobUser", "name": "GuestRoom"},
    )
    assert rejected["ok"] is False
    assert "already taken by a registered account" in rejected["error"]


@pytest.mark.asyncio
async def test_guest_nicknames_reject_spaces_and_short_names():
    room_manager = RoomManager()
    sio = socketio.AsyncServer(async_mode="asgi")
    register_handlers(sio, room_manager)
    sio.get_session = AsyncMock(return_value=None)
    sio.save_session = AsyncMock()
    sio.enter_room = AsyncMock()
    sio.emit = AsyncMock()

    spaced = await sio.handlers["/"]["create_room"](
        "host-sid",
        {"nickname": "Cool Cat", "name": "Room"},
    )
    assert spaced == {"ok": False, "error": NICKNAME_RULES_MESSAGE}

    short = await sio.handlers["/"]["create_room"](
        "host-sid",
        {"nickname": "ab", "name": "Room"},
    )
    assert short == {"ok": False, "error": NICKNAME_RULES_MESSAGE}


@pytest.mark.asyncio
async def test_authenticated_guest_nicknames_reject_spaces():
    guest = _user(id="guest-1", display_name="Guest")
    repo = _FakeUserRepo([guest])
    room_manager = RoomManager()
    sio = socketio.AsyncServer(async_mode="asgi")
    register_handlers(sio, room_manager, user_repo=repo)
    sio.get_session = AsyncMock(return_value={"user_id": "guest-1"})
    sio.save_session = AsyncMock()
    sio.enter_room = AsyncMock()
    sio.emit = AsyncMock()

    rejected = await sio.handlers["/"]["create_room"](
        "guest-sid",
        {"nickname": "Cool Cat", "name": "Room"},
    )
    assert rejected == {"ok": False, "error": NICKNAME_RULES_MESSAGE}

    created = await sio.handlers["/"]["create_room"](
        "guest-sid",
        {"nickname": "Cool_Cat", "name": "Room"},
    )
    assert created["ok"] is True
    assert created["roomId"]
    room = room_manager.get_room(created["roomId"])
    assert room.players[created["playerId"]].nickname == "Cool_Cat"

