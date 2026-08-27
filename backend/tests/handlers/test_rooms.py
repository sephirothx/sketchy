import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import socketio

from app.handlers import register_all_handlers as register_handlers
from app.presenters import editable_room_settings_payload
from app.repositories.interfaces import (
    PromptListSelectionError,
    ResolvedPromptSelection,
)
from app.rooms import (
    ANONYMOUS_NAME_COLOR,
    RoomManager,
)
from tests.fake_user_repo import FakeUserRepository


@pytest.mark.asyncio
async def test_published_room_code_comes_from_global_reservation_service():
    room_manager = RoomManager()
    sio = socketio.AsyncServer(async_mode="asgi")
    ctx = register_handlers(sio, room_manager)
    ctx.room_codes = SimpleNamespace(
        allocate=AsyncMock(return_value="SAFE01"),
        release_unpublished=AsyncMock(),
        retire_ephemeral=AsyncMock(),
        is_retired=AsyncMock(return_value=False),
    )
    sio.get_session = AsyncMock(return_value={"user_id": "user-host"})
    sio.save_session = AsyncMock()
    sio.enter_room = AsyncMock()
    sio.emit = AsyncMock()

    response = await sio.handlers["/"]["create_room"](
        "host-sid", {"nickname": "Host", "name": "Room"}
    )

    assert response["ok"] is True
    assert response["code"] == "SAFE01"
    ctx.room_codes.allocate.assert_awaited_once_with(kind="ephemeral")
    room = room_manager.get_room(response["roomId"])
    assert room is not None
    room.players[response["playerId"]].connected = False
    assert await ctx.remove_room_if_empty(room.id) is True
    ctx.room_codes.retire_ephemeral.assert_awaited_once_with("SAFE01")


@pytest.mark.asyncio
async def test_retired_room_code_has_a_distinct_invite_error():
    room_manager = RoomManager()
    sio = socketio.AsyncServer(async_mode="asgi")
    ctx = register_handlers(sio, room_manager)
    ctx.room_codes = SimpleNamespace(is_retired=AsyncMock(return_value=True))

    preview = await sio.handlers["/"]["get_room_preview"](
        "sid", {"code": "OLD123"}
    )
    join = await sio.handlers["/"]["join_room"](
        "sid", {"code": "OLD123", "nickname": "Player"}
    )

    assert preview == {
        "ok": False,
        "error": "This room has ended",
        "codeRetired": True,
    }
    assert join == preview


@pytest.mark.asyncio
async def test_create_room_accepts_no_scoring_and_disables_point_purchase_hints():
    room_manager = RoomManager()
    sio = socketio.AsyncServer(async_mode="asgi")
    register_handlers(sio, room_manager)
    sio.get_session = AsyncMock(return_value={"user_id": "user-host"})
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
    account = user_repo.add_registered("user-1", "HostPlayer")
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
    assert user_repo.users["user-1"].last_active_at >= account.last_active_at
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

    def __init__(
        self,
        prompts=("aardvark", "zeppelin"),
        language="en",
        *,
        revision_ids=(),
        aliases=None,
        prompt_version_ids=None,
    ):
        self.prompts = list(prompts)
        self.language = language
        self.revision_ids = tuple(revision_ids)
        self.aliases = dict(aliases or {})
        self.prompt_version_ids = dict(prompt_version_ids or {})
        self.reads = 0

    async def resolve_selection(
        self, slugs, *, requesting_user_id=None, share_codes=()
    ):
        self.reads += 1
        return ResolvedPromptSelection(
            tuple(slugs),
            self.language,
            tuple(self.prompts),
            revision_ids=self.revision_ids,
            aliases=self.aliases,
            prompt_version_ids=self.prompt_version_ids,
        )

    async def record_prompt_usage(self, slugs, usage):
        return None


@pytest.mark.asyncio
async def test_owned_and_shared_list_authority_never_leaks_into_room_payloads():
    class AuthorizingPromptListRepo(RecordingPromptListRepo):
        def __init__(self):
            super().__init__(("capybara",), revision_ids=("revision-user-1",))
            self.authorization = None

        async def resolve_selection(
            self, slugs, *, requesting_user_id=None, share_codes=()
        ):
            self.authorization = (requesting_user_id, tuple(share_codes))
            return await super().resolve_selection(
                slugs,
                requesting_user_id=requesting_user_id,
                share_codes=share_codes,
            )

    room_manager = RoomManager()
    users = FakeUserRepository()
    users.add_registered("user-1", "Host")
    prompts = AuthorizingPromptListRepo()
    sio = socketio.AsyncServer(async_mode="asgi")
    register_handlers(
        sio, room_manager, user_repo=users, prompt_list_repo=prompts
    )
    sio.get_session = AsyncMock(return_value={"user_id": "user-1"})
    sio.save_session = AsyncMock()
    sio.enter_room = AsyncMock()
    sio.emit = AsyncMock()

    response = await sio.handlers["/"]["create_room"](
        "host-sid",
        {
            "nickname": "Ignored",
            "promptListSlugs": ["user-private-list"],
            "promptListShareCodes": ["bearer-secret"],
        },
    )

    assert response["ok"] is True
    assert prompts.authorization == ("user-1", ("bearer-secret",))
    room = room_manager.get_room(response["roomId"])
    assert room is not None
    assert room.prompt_list_share_codes == ["bearer-secret"]
    assert "promptListShareCodes" not in room.to_state_payload()
    assert "promptListShareCodes" not in editable_room_settings_payload(room)
    assert "bearer-secret" not in repr(room)


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
async def test_prompt_list_language_is_resolved_into_room_payloads_and_game_matching():
    room_manager = RoomManager()
    repo = RecordingPromptListRepo(
        ("éléphant", "vélo"),
        language="fr",
        revision_ids=("revision-fr-1",),
        aliases={"vélo": ("bicyclette",)},
        prompt_version_ids={"éléphant": "prompt-fr-1", "vélo": "prompt-fr-2"},
    )
    room, sio = build_settings_room(
        room_manager,
        repo,
        prompt_list_slugs=["english_standard"],
        curated_prompts=["apple"],
    )
    room_manager.add_player(room, "Guest")

    result = await sio.handlers["/"]["update_room_settings"](
        "host-sid", {"promptListSlugs": ["francais"]}
    )

    assert result == {"ok": True}
    assert room.prompt_language == "fr"
    assert room.curated_prompts == ["éléphant", "vélo"]
    assert room.prompt_list_revision_ids == ["revision-fr-1"]
    for payload in (
        room.to_state_payload(),
        room.to_public_summary(),
        editable_room_settings_payload(room),
    ):
        assert payload["promptLanguage"] == "fr"

    started = await sio.handlers["/"]["start_game"]("host-sid", None)
    assert started["ok"] is True
    assert room.game is not None
    assert room.game.prompt_language == "fr"
    assert room.game.prompt_aliases == {"vélo": ("bicyclette",)}
    assert room.game.prompt_source_revision_ids == ("revision-fr-1",)
    assert room.game.prompt_version_ids == {
        "éléphant": "prompt-fr-1",
        "vélo": "prompt-fr-2",
    }


@pytest.mark.asyncio
async def test_invalid_prompt_list_selection_is_visible_and_does_not_mutate_room():
    class InvalidSelectionRepo:
        async def resolve_selection(self, slugs):
            raise PromptListSelectionError(
                "Selected prompt lists must use the same language"
            )

    room_manager = RoomManager()
    room, sio = build_settings_room(
        room_manager,
        InvalidSelectionRepo(),
        prompt_list_slugs=["english_standard"],
        curated_prompts=["apple"],
    )

    result = await sio.handlers["/"]["update_room_settings"](
        "host-sid", {"promptListSlugs": ["english_standard", "francais"]}
    )

    assert result == {
        "ok": False,
        "error": "Selected prompt lists must use the same language",
        "field": "promptListSlugs",
    }
    assert room.prompt_list_slugs == ["english_standard"]
    assert room.curated_prompts == ["apple"]


@pytest.mark.asyncio
async def test_start_revalidates_a_waiting_room_after_content_is_hidden():
    class HiddenSelectionRepo:
        async def resolve_selection(self, slugs):
            raise PromptListSelectionError("A selected prompt list is unavailable")

    room_manager = RoomManager()
    room, sio = build_settings_room(
        room_manager,
        HiddenSelectionRepo(),
        prompt_list_slugs=["reported-list"],
        curated_prompts=["cached prompt"],
    )
    room_manager.add_player(room, "Guest")

    result = await sio.handlers["/"]["start_game"]("host-sid", None)

    assert result == {
        "ok": False,
        "error": "A selected prompt list is unavailable",
        "field": "promptListSlugs",
    }
    assert room.state == "waiting"
    assert room.game is None


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
        async def resolve_selection(self, slugs):
            reading.set()
            await finish_reading.wait()
            return ResolvedPromptSelection(
                tuple(slugs), "en", ("aardvark", "zeppelin")
            )

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


@pytest.mark.asyncio
async def test_the_host_edits_the_drawing_rules_and_the_room_carries_them_everywhere():
    room_manager = RoomManager()
    room = room_manager.create_room(name="Room", is_public=True)
    host = room_manager.add_player(room, "Host")
    host.sid = "host-sid"
    sio = socketio.AsyncServer(async_mode="asgi")
    register_handlers(sio, room_manager)
    sio.emit = AsyncMock()
    sio.get_session = AsyncMock(return_value={"room_id": room.id, "player_id": host.id})

    # The defaults take nothing away.
    assert room.allowed_tools == ["brush", "fill", "shapes"]
    assert room.color_mode == "all"

    result = await sio.handlers["/"]["update_room_settings"](
        "host-sid", {"allowedTools": ["shapes", "brush"], "colorMode": "colorblind_safe"}
    )

    assert result["ok"] is True
    assert room.allowed_tools == ["brush", "shapes"]
    assert room.color_mode == "colorblind_safe"
    # Every player, the room list, the invite preview, and the host's own form.
    for payload in (
        room.to_state_payload(),
        room.to_public_summary(),
        editable_room_settings_payload(room),
    ):
        assert payload["allowedTools"] == ["brush", "shapes"]
        assert payload["colorMode"] == "colorblind_safe"


@pytest.mark.asyncio
async def test_a_tool_set_with_nothing_to_draw_with_is_refused():
    room_manager = RoomManager()
    room = room_manager.create_room(name="Room", is_public=True)
    host = room_manager.add_player(room, "Host")
    host.sid = "host-sid"
    sio = socketio.AsyncServer(async_mode="asgi")
    register_handlers(sio, room_manager)
    sio.emit = AsyncMock()
    sio.get_session = AsyncMock(return_value={"room_id": room.id, "player_id": host.id})

    for tools in ([], ["fill"]):
        result = await sio.handlers["/"]["update_room_settings"]("host-sid", {"allowedTools": tools})
        assert result["ok"] is False
    assert room.allowed_tools == ["brush", "fill", "shapes"]


@pytest.mark.asyncio
async def test_editing_one_drawing_rule_leaves_the_other_alone():
    room_manager = RoomManager()
    room = room_manager.create_room(
        name="Room", allowed_tools=["brush"], color_mode="black_and_white"
    )
    host = room_manager.add_player(room, "Host")
    host.sid = "host-sid"
    sio = socketio.AsyncServer(async_mode="asgi")
    register_handlers(sio, room_manager)
    sio.emit = AsyncMock()
    sio.get_session = AsyncMock(return_value={"room_id": room.id, "player_id": host.id})

    assert (await sio.handlers["/"]["update_room_settings"]("host-sid", {"rounds": 5}))["ok"] is True

    assert room.allowed_tools == ["brush"]
    assert room.color_mode == "black_and_white"


class UnreachablePromptListRepo:
    """A store that fails to answer, as opposed to answering with a refusal."""

    def __init__(self):
        self.reads = 0

    async def resolve_selection(
        self, slugs, *, requesting_user_id=None, share_codes=()
    ):
        self.reads += 1
        raise RuntimeError("prompt store is unreachable")

    async def record_prompt_usage(self, slugs, usage):
        return None


@pytest.mark.asyncio
async def test_a_prompt_store_failure_refuses_the_room_rather_than_swapping_prompts():
    """The room must not open quietly playing the built-in list while the host
    is shown the lists they chose."""
    room_manager = RoomManager()
    repo = UnreachablePromptListRepo()
    sio = socketio.AsyncServer(async_mode="asgi")
    register_handlers(sio, room_manager, prompt_list_repo=repo)
    sio.get_session = AsyncMock(return_value={"user_id": "user-host"})
    sio.save_session = AsyncMock()
    sio.enter_room = AsyncMock()
    sio.emit = AsyncMock()

    response = await sio.handlers["/"]["create_room"](
        "host-sid", {"nickname": "Host", "promptListSlugs": ["safari"]}
    )

    assert response["ok"] is False
    assert response["field"] == "promptListSlugs"
    assert repo.reads == 1
    assert room_manager.rooms == {}, "a room opened on prompts nobody could read"


@pytest.mark.asyncio
async def test_a_prompt_store_failure_leaves_the_settings_it_could_not_read():
    """A failed read must not strand the room on an empty curated pool, which
    `effective_prompt_pool` reads as permission to use the built-in prompts."""
    room_manager = RoomManager()
    room, sio = build_settings_room(
        room_manager,
        UnreachablePromptListRepo(),
        prompt_list_slugs=["safari"],
        curated_prompts=["aardvark", "zeppelin"],
    )

    result = await sio.handlers["/"]["update_room_settings"](
        "host-sid", {"promptListSlugs": ["savannah"]}
    )

    assert result["ok"] is False
    assert result["field"] == "promptListSlugs"
    assert room.prompt_list_slugs == ["safari"]
    assert room.curated_prompts == ["aardvark", "zeppelin"]


@pytest.mark.asyncio
async def test_a_custom_only_room_still_opens_when_the_prompt_store_is_down():
    """The one case where an empty curated pool is the correct outcome: the
    room was never going to draw from a list."""
    room_manager = RoomManager()
    repo = UnreachablePromptListRepo()
    sio = socketio.AsyncServer(async_mode="asgi")
    register_handlers(sio, room_manager, prompt_list_repo=repo)
    sio.get_session = AsyncMock(return_value={"user_id": "user-host"})
    sio.save_session = AsyncMock()
    sio.enter_room = AsyncMock()
    sio.emit = AsyncMock()

    response = await sio.handlers["/"]["create_room"](
        "host-sid",
        {
            "nickname": "Host",
            "customPrompts": "hedgehog\nlighthouse",
            "customPromptsOnly": True,
        },
    )

    assert response["ok"] is True
    room = room_manager.get_room(response["roomId"])
    assert room is not None
    assert room.curated_prompts == []
    assert room.custom_prompts == ["hedgehog", "lighthouse"]
    assert set(room.effective_prompt_pool()) == {"hedgehog", "lighthouse"}
