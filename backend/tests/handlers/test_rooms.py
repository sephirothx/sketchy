import asyncio
from unittest.mock import AsyncMock

import pytest
import socketio

from app.handlers import register_all_handlers as register_handlers
from app.rooms import (
    ANONYMOUS_NAME_COLOR,
    RoomManager,
)
from tests.fake_user_repo import FakeUserRepository


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
async def test_a_single_changed_setting_saves_alone_and_without_a_chat_line():
    """The lobby autosaves one setting at a time, so a patch has to leave the
    rest of the room alone - and stay out of the chat, which would otherwise
    carry a line per keystroke."""
    room_manager = RoomManager()
    room = room_manager.create_room(
        name="Room",
        rounds=3,
        hint_mode="wheel",
        scoring_mode="pressure",
        custom_prompts=["red panda"],
    )
    host = room_manager.add_player(room, "Host")
    host.sid = "host-sid"
    sio = socketio.AsyncServer(async_mode="asgi")
    register_handlers(sio, room_manager)
    sio.emit = AsyncMock()
    sio.get_session = AsyncMock(
        return_value={"room_id": room.id, "player_id": host.id}
    )

    assert (await sio.handlers["/"]["update_room_settings"]("host-sid", {"rounds": 4}))["ok"] is True

    assert room.rounds == 4
    assert room.name == "Room"
    assert room.hint_mode == "wheel"
    assert room.scoring_mode == "pressure"
    assert room.custom_prompts == ["red panda"]

    events = [call.args[0] for call in sio.emit.await_args_list]
    assert "room_state" in events
    assert "chat_message" not in events


class RecordingPromptListRepo:
    """Answers with a fixed pool, and counts how often it was asked."""

    def __init__(self, prompts=("aardvark", "zeppelin")):
        self.prompts = list(prompts)
        self.reads = 0

    async def get_prompts_by_slugs(self, slugs):
        self.reads += 1
        return list(self.prompts)

    async def record_prompt_usage(self, slugs, usage):
        return None


def build_settings_room(room_manager, prompt_list_repo, **room_kwargs):
    room = room_manager.create_room(name="Room", **room_kwargs)
    host = room_manager.add_player(room, "Host")
    host.sid = "host-sid"
    sio = socketio.AsyncServer(async_mode="asgi")
    ctx = register_handlers(sio, room_manager)
    ctx.prompt_list_repo = prompt_list_repo
    sio.emit = AsyncMock()
    sio.get_session = AsyncMock(
        return_value={"room_id": room.id, "player_id": host.id}
    )
    return room, sio


@pytest.mark.asyncio
async def test_a_settings_change_does_not_re_read_prompt_lists_it_left_alone():
    room_manager = RoomManager()
    repo = RecordingPromptListRepo()
    room, sio = build_settings_room(
        room_manager,
        repo,
        prompt_list_slugs=["safari"],
        curated_prompts=["aardvark", "zeppelin"],
    )

    assert (await sio.handlers["/"]["update_room_settings"]("host-sid", {"rounds": 4}))["ok"] is True

    assert repo.reads == 0
    assert room.curated_prompts == ["aardvark", "zeppelin"]


@pytest.mark.asyncio
async def test_a_settings_change_retries_prompt_lists_that_never_loaded():
    """A read that failed when the room was made leaves the pool empty, and the
    room would draw from the built-in list for the rest of its life while the
    host is still shown the lists they picked. An empty pool is the one worth
    asking about again."""
    room_manager = RoomManager()
    repo = RecordingPromptListRepo()
    room, sio = build_settings_room(
        room_manager,
        repo,
        prompt_list_slugs=["safari"],
        curated_prompts=[],
    )

    assert (await sio.handlers["/"]["update_room_settings"]("host-sid", {"rounds": 4}))["ok"] is True

    assert repo.reads == 1
    assert room.curated_prompts == ["aardvark", "zeppelin"]


@pytest.mark.asyncio
async def test_starting_waits_for_a_settings_change_that_arrived_first():
    """Settings save themselves now, so the host can change one and press Start
    a breath later. Socket.IO gives each event its own task, so arriving first
    means nothing once a handler awaits - here the prompt-list read - and the
    game would be dealt the values the host had just replaced."""
    room_manager = RoomManager()
    room = room_manager.create_room(name="Room", rounds=2)
    host = room_manager.add_player(room, "Host")
    guest = room_manager.add_player(room, "Guest")
    host.sid, guest.sid = "host-sid", "guest-sid"
    sio = socketio.AsyncServer(async_mode="asgi")
    ctx = register_handlers(sio, room_manager)
    sio.emit = AsyncMock()
    sio.get_session = AsyncMock(
        return_value={"room_id": room.id, "player_id": host.id}
    )

    reading = asyncio.Event()
    finish_reading = asyncio.Event()

    class BlockingPromptListRepo:
        async def get_prompts_by_slugs(self, slugs):
            reading.set()
            await finish_reading.wait()
            return ["aardvark", "zeppelin"]

        async def record_prompt_usage(self, slugs, usage):
            return None

    ctx.prompt_list_repo = BlockingPromptListRepo()

    update = asyncio.create_task(
        sio.handlers["/"]["update_room_settings"](
            "host-sid", {"rounds": 7, "promptListSlugs": ["safari"]}
        )
    )
    await reading.wait()

    start = asyncio.create_task(sio.handlers["/"]["start_game"]("host-sid", None))
    # Several turns of the loop: plenty for an unguarded start to have run the
    # whole way through while the settings change sits in its await.
    for _ in range(10):
        await asyncio.sleep(0)
    assert room.state == "waiting", "the game started before the settings landed"

    finish_reading.set()
    assert (await update)["ok"] is True
    assert (await start)["ok"] is True

    assert room.rounds == 7
    assert room.game is not None
    assert room.game.rounds_total == 7
    ctx.timers.cancel_phase_timer(room.id)


@pytest.mark.asyncio
async def test_room_members_can_inspect_custom_prompts_only_while_waiting():
    room_manager = RoomManager()
    room = room_manager.create_room(
        name="Room",
        custom_prompts=["red panda", "apple"],
        custom_prompts_only=True,
    )
    room_manager.add_player(room, "Host")
    guest = room_manager.add_player(room, "Guest")
    guest.sid = "guest-sid"
    sio = socketio.AsyncServer(async_mode="asgi")
    register_handlers(sio, room_manager)
    sio.get_session = AsyncMock(
        return_value={"room_id": room.id, "player_id": guest.id}
    )
    get_custom_prompts = sio.handlers["/"]["get_custom_prompts"]

    response = await get_custom_prompts("guest-sid", {})
    assert response == {"ok": True, "prompts": ["red panda", "apple"]}

    room.state = "playing"
    playing_response = await get_custom_prompts("guest-sid", {})
    assert playing_response["ok"] is False
    assert "waiting room" in playing_response["error"]

    room.state = "waiting"
    guest.is_spectator = True
    spectator_response = await get_custom_prompts("guest-sid", {})
    assert spectator_response == {
        "ok": False,
        "error": "Only players can view custom prompts",
    }

    sio.get_session = AsyncMock(return_value=None)
    assert (await get_custom_prompts("outsider-sid", {}))["ok"] is False

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
    assert spectator.score == 0
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


@pytest.mark.asyncio
async def test_reconnect_only_join_never_seats_a_new_player():
    """The invite screen probes for an existing seat; it must not create one."""
    room_manager = RoomManager()
    room = room_manager.create_room(name="Room")
    seated = room_manager.add_player(room, "Seated", user_id="returning-user")

    sio = socketio.AsyncServer(async_mode="asgi")
    register_handlers(sio, room_manager, user_repo=FakeUserRepository())
    sio.save_session = AsyncMock()
    sio.enter_room = AsyncMock()
    sio.emit = AsyncMock()
    join_room = sio.handlers["/"]["join_room"]

    sio.get_session = AsyncMock(return_value={"user_id": "brand-new-user"})
    probe = await join_room(
        "visitor-sid", {"code": room.code, "nickname": "Visitor", "reconnectOnly": True}
    )
    assert probe["ok"] is False
    assert [p.nickname for p in room.player_list()] == ["Seated"]

    sio.get_session = AsyncMock(return_value={"user_id": "returning-user"})
    reconnected = await join_room(
        "returning-sid", {"code": room.code, "nickname": "Seated", "reconnectOnly": True}
    )
    assert reconnected["ok"] is True
    assert reconnected["playerId"] == seated.id
    assert len(room.player_list()) == 1


@pytest.mark.asyncio
async def test_registering_mid_game_upgrades_the_existing_seat():
    """A guest who signs up keeps their seat but stops being a guest on it."""
    room_manager = RoomManager()
    user_repo = FakeUserRepository()
    user_repo.add_guest("user-1", "Wanderer")

    room = room_manager.create_room(name="Room")
    seat = room_manager.add_player(room, "Wanderer", user_id="user-1")
    seat.sid = "old-sid"
    assert seat.is_anonymous is True
    assert seat.name_color == ANONYMOUS_NAME_COLOR

    sio = socketio.AsyncServer(async_mode="asgi")
    register_handlers(sio, room_manager, user_repo=user_repo)
    sio.get_session = AsyncMock(return_value={"user_id": "user-1"})
    sio.save_session = AsyncMock()
    sio.enter_room = AsyncMock()
    sio.disconnect = AsyncMock()
    sio.emit = AsyncMock()

    # Claiming the account keeps the same user id, which is what lets the
    # socket bounce land back on this very seat.
    await user_repo.claim_account("user-1", "Stefano", "hash")

    response = await sio.handlers["/"]["join_room"](
        "new-sid", {"code": room.code, "nickname": "Wanderer", "nameColor": "#123abc"}
    )

    assert response["ok"] is True
    assert response["playerId"] == seat.id, "must keep the same seat, not create one"
    assert seat.nickname == "Stefano"
    assert seat.is_anonymous is False
    assert seat.name_color == "#123abc"
    assert len(room.player_list()) == 1


@pytest.mark.asyncio
async def test_guest_can_rename_and_the_name_sticks_to_the_account():
    room_manager = RoomManager()
    user_repo = FakeUserRepository()
    user_repo.add_guest("guest-1", "BriskOtter")
    room = room_manager.create_room(name="Room")
    player = room_manager.add_player(room, "BriskOtter", user_id="guest-1")
    player.sid = "guest-sid"

    sio = socketio.AsyncServer(async_mode="asgi")
    register_handlers(sio, room_manager, user_repo=user_repo)
    sio.get_session = AsyncMock(
        return_value={"room_id": room.id, "player_id": player.id, "user_id": "guest-1"}
    )
    sio.emit = AsyncMock()
    rename = sio.handlers["/"]["rename_player"]

    assert await rename("guest-sid", {"nickname": "Marta"}) == {
        "ok": True,
        "nickname": "Marta",
    }
    assert player.nickname == "Marta"
    # Stored on the account, so it survives a reload and follows them onward.
    assert (await user_repo.get_by_id("guest-1")).display_name == "Marta"
    assert any(
        call.args[0] == "chat_message"
        and "is now known as Marta" in call.args[1].get("text", "")
        for call in sio.emit.await_args_list
    )


@pytest.mark.asyncio
async def test_rename_rejects_bad_names_and_registered_usernames():
    room_manager = RoomManager()
    user_repo = FakeUserRepository()
    user_repo.add_guest("guest-1", "BriskOtter")
    user_repo.add_registered("user-2", "Stefano")
    room = room_manager.create_room(name="Room")
    player = room_manager.add_player(room, "BriskOtter", user_id="guest-1")
    player.sid = "guest-sid"

    sio = socketio.AsyncServer(async_mode="asgi")
    register_handlers(sio, room_manager, user_repo=user_repo)
    sio.get_session = AsyncMock(
        return_value={"room_id": room.id, "player_id": player.id, "user_id": "guest-1"}
    )
    sio.emit = AsyncMock()
    rename = sio.handlers["/"]["rename_player"]

    for bad in ["ab", "has space", "Guest", "x" * 17]:
        assert (await rename("guest-sid", {"nickname": bad}))["ok"] is False, bad
    squat = await rename("guest-sid", {"nickname": "stefano"})
    assert squat["ok"] is False
    assert "registered player" in squat["error"]
    assert player.nickname == "BriskOtter"


@pytest.mark.asyncio
async def test_registered_players_cannot_rename_away_from_their_username():
    room_manager = RoomManager()
    user_repo = FakeUserRepository()
    user_repo.add_registered("user-1", "Stefano")
    room = room_manager.create_room(name="Room")
    player = room_manager.add_player(
        room, "Stefano", user_id="user-1", is_anonymous=False
    )
    player.sid = "sid"

    sio = socketio.AsyncServer(async_mode="asgi")
    register_handlers(sio, room_manager, user_repo=user_repo)
    sio.get_session = AsyncMock(
        return_value={"room_id": room.id, "player_id": player.id, "user_id": "user-1"}
    )
    sio.emit = AsyncMock()

    result = await sio.handlers["/"]["rename_player"]("sid", {"nickname": "Someone"})
    assert result["ok"] is False
    assert player.nickname == "Stefano"


@pytest.mark.asyncio
async def test_reconnect_probe_works_with_no_local_nickname():
    """A returning player with cleared local state must still reconnect.

    Identity comes from the cookie, so an empty or stale nickname in the
    payload must not stop the lookup from happening.
    """
    room_manager = RoomManager()
    user_repo = FakeUserRepository()
    user_repo.add_guest("returning-user", "BriskOtter")
    room = room_manager.create_room(name="Room")
    seat = room_manager.add_player(room, "BriskOtter", user_id="returning-user")

    sio = socketio.AsyncServer(async_mode="asgi")
    register_handlers(sio, room_manager, user_repo=user_repo)
    sio.get_session = AsyncMock(return_value={"user_id": "returning-user"})
    sio.save_session = AsyncMock()
    sio.enter_room = AsyncMock()
    sio.emit = AsyncMock()

    reconnected = await sio.handlers["/"]["join_room"](
        "new-sid", {"code": room.code, "nickname": "", "reconnectOnly": True}
    )
    assert reconnected["ok"] is True
    assert reconnected["playerId"] == seat.id


@pytest.mark.asyncio
async def test_guest_seat_is_named_from_the_account_not_the_payload():
    """The client cannot pick a name by asking for one on the wire."""
    room_manager = RoomManager()
    user_repo = FakeUserRepository()
    user_repo.add_guest("guest-1", "BriskOtter")
    room = room_manager.create_room(name="Room")

    sio = socketio.AsyncServer(async_mode="asgi")
    register_handlers(sio, room_manager, user_repo=user_repo)
    sio.get_session = AsyncMock(return_value={"user_id": "guest-1"})
    sio.save_session = AsyncMock()
    sio.enter_room = AsyncMock()
    sio.emit = AsyncMock()

    response = await sio.handlers["/"]["join_room"](
        "sid", {"code": room.code, "nickname": "SomethingElse"}
    )
    assert room.players[response["playerId"]].nickname == "BriskOtter"


@pytest.mark.asyncio
async def test_a_guest_with_no_name_cannot_be_seated():
    """The name is asked for before create/join, so this only happens if
    something bypassed the UI. It must not produce a nameless player."""
    room_manager = RoomManager()
    user_repo = FakeUserRepository()
    user_repo.add_guest("guest-1", "")
    room = room_manager.create_room(name="Room")

    sio = socketio.AsyncServer(async_mode="asgi")
    register_handlers(sio, room_manager, user_repo=user_repo)
    sio.get_session = AsyncMock(return_value={"user_id": "guest-1"})
    sio.save_session = AsyncMock()
    sio.enter_room = AsyncMock()
    sio.emit = AsyncMock()

    response = await sio.handlers["/"]["join_room"](
        "sid", {"code": room.code, "nickname": "Sneaky"}
    )
    assert response["ok"] is False
    assert room.player_list() == []


@pytest.mark.asyncio
async def test_changing_colour_in_a_room_also_stores_it_on_the_account():
    """Otherwise the seat and the profile disagree about the same player."""
    room_manager = RoomManager()
    room = room_manager.create_room(name="Room", is_public=True)
    user_repo = FakeUserRepository()
    user_repo.add_registered("user-1", "Painter")
    player = room_manager.add_player(
        room, "Painter", user_id="user-1", is_anonymous=False
    )
    player.sid = "sid-1"

    sio = socketio.AsyncServer(async_mode="asgi")
    register_handlers(sio, room_manager, user_repo=user_repo)
    sio.get_session = AsyncMock(return_value={"room_id": room.id, "player_id": player.id})
    sio.save_session = AsyncMock()
    sio.emit = AsyncMock()

    response = await sio.handlers["/"]["update_player_settings"](
        "sid-1", {"nameColor": "#4f46e5"}
    )

    assert response == {"ok": True}
    assert player.name_color == "#4f46e5"
    assert user_repo.users["user-1"].name_color == "#4f46e5"


@pytest.mark.asyncio
async def test_a_failed_colour_write_still_updates_the_room():
    """The seat has already changed colour; skipping the broadcast would leave
    everyone else looking at the old one."""
    room_manager = RoomManager()
    room = room_manager.create_room(name="Room", is_public=True)
    user_repo = FakeUserRepository()
    user_repo.add_registered("user-1", "Painter")
    player = room_manager.add_player(
        room, "Painter", user_id="user-1", is_anonymous=False
    )
    player.sid = "sid-1"

    async def failing_update(*args, **kwargs):
        raise RuntimeError("database unavailable")

    user_repo.update_profile = failing_update

    sio = socketio.AsyncServer(async_mode="asgi")
    register_handlers(sio, room_manager, user_repo=user_repo)
    sio.get_session = AsyncMock(return_value={"room_id": room.id, "player_id": player.id})
    sio.save_session = AsyncMock()
    sio.emit = AsyncMock()

    response = await sio.handlers["/"]["update_player_settings"](
        "sid-1", {"nameColor": "#4f46e5"}
    )

    assert response == {"ok": True}
    assert player.name_color == "#4f46e5"
    assert any(call.args[0] == "room_state" for call in sio.emit.await_args_list)


@pytest.mark.asyncio
async def test_a_registered_player_is_seated_in_their_account_colour():
    """The colour is chosen in Settings and kept per browser, so a second
    device would otherwise seat the same player in a different colour."""
    room_manager = RoomManager()
    user_repo = FakeUserRepository()
    user_repo.add_registered("user-1", "Painter")
    await user_repo.update_profile("user-1", name_color="#4f46e5")

    sio = socketio.AsyncServer(async_mode="asgi")
    register_handlers(sio, room_manager, user_repo=user_repo)
    sio.get_session = AsyncMock(return_value={"user_id": "user-1"})
    sio.save_session = AsyncMock()
    sio.enter_room = AsyncMock()
    sio.emit = AsyncMock()

    # The client offers the colour this browser happens to hold.
    response = await sio.handlers["/"]["create_room"](
        "sid-1", {"nickname": "Painter", "nameColor": "#15803d"}
    )

    room = room_manager.get_room(response["roomId"])
    player = room.players[response["playerId"]]
    assert player.name_color == "#4f46e5"


@pytest.mark.asyncio
async def test_a_registered_player_without_a_stored_colour_keeps_the_client_one():
    """Nothing to inherit yet: the account is backfilled from the client."""
    room_manager = RoomManager()
    user_repo = FakeUserRepository()
    user_repo.add_registered("user-1", "Painter")

    sio = socketio.AsyncServer(async_mode="asgi")
    register_handlers(sio, room_manager, user_repo=user_repo)
    sio.get_session = AsyncMock(return_value={"user_id": "user-1"})
    sio.save_session = AsyncMock()
    sio.enter_room = AsyncMock()
    sio.emit = AsyncMock()

    response = await sio.handlers["/"]["create_room"](
        "sid-1", {"nickname": "Painter", "nameColor": "#15803d"}
    )

    room = room_manager.get_room(response["roomId"])
    assert room.players[response["playerId"]].name_color == "#15803d"


@pytest.mark.asyncio
async def test_a_guest_is_still_pinned_to_the_guest_grey():
    room_manager = RoomManager()
    user_repo = FakeUserRepository()
    user_repo.add_guest("guest-1", "Wanderer")

    sio = socketio.AsyncServer(async_mode="asgi")
    register_handlers(sio, room_manager, user_repo=user_repo)
    sio.get_session = AsyncMock(return_value={"user_id": "guest-1"})
    sio.save_session = AsyncMock()
    sio.enter_room = AsyncMock()
    sio.emit = AsyncMock()

    response = await sio.handlers["/"]["create_room"](
        "sid-1", {"nickname": "Wanderer", "nameColor": "#15803d"}
    )

    room = room_manager.get_room(response["roomId"])
    assert room.players[response["playerId"]].name_color == ANONYMOUS_NAME_COLOR
