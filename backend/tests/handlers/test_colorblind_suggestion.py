"""Private color-safety preference and host-only room suggestion contracts."""
from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
import socketio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.models import Base, User, UserSettings
from app.handlers import register_all_handlers as register_handlers
from app.handlers.payloads import (
    CreateRoomPayload,
    JoinRoomPayload,
    PayloadError,
    PlayerSettingsPayload,
    parse_payload,
)
from app.presenters import editable_room_settings_payload, session_payload
from app.rooms import RoomManager
from tests.fake_user_repo import FakeUserRepository


def _contains_key(value: object, forbidden: str) -> bool:
    if isinstance(value, dict):
        return forbidden in value or any(
            _contains_key(item, forbidden) for item in value.values()
        )
    if isinstance(value, (list, tuple)):
        return any(_contains_key(item, forbidden) for item in value)
    return False


def _suggestion_calls(sio):
    return [
        call
        for call in sio.emit.await_args_list
        if call.args[0] == "colorblind_safe_suggestion"
    ]


def _live_room():
    manager = RoomManager()
    room = manager.create_room(name="Studio")
    host = manager.add_player(room, "Host")
    player = manager.add_player(
        room, "Player", colorblind_safe_colors=True
    )
    host.sid = "host-sid"
    player.sid = "player-sid"
    sio = socketio.AsyncServer(async_mode="asgi")
    ctx = register_handlers(sio, manager)
    sio.emit = AsyncMock()
    sio.get_session = AsyncMock(
        side_effect=lambda sid: {
            "host-sid": {"room_id": room.id, "player_id": host.id},
            "player-sid": {"room_id": room.id, "player_id": player.id},
        }.get(sid)
    )
    return manager, room, host, player, sio, ctx


@pytest.mark.asyncio
async def test_private_preference_is_absent_from_every_shared_room_payload():
    manager, room, host, player, _, _ = _live_room()
    room.colorblind_suggestion_dismissed = True

    for payload in (
        room.to_state_payload(),
        room.to_public_summary(),
        manager.list_public_rooms(),
        editable_room_settings_payload(room),
        session_payload(room, player),
    ):
        assert not _contains_key(payload, "colorblindSafeColors")
        assert not _contains_key(payload, "colorblind_safe_colors")
        assert not _contains_key(payload, "colorblindSuggestionDismissed")
        assert not _contains_key(payload, "colorblind_suggestion_dismissed")

    assert host.colorblind_safe_colors is False
    assert player.colorblind_safe_colors is True


@pytest.mark.asyncio
async def test_suggestion_is_unattributed_host_only_and_spectators_do_not_count():
    _, room, host, player, sio, ctx = _live_room()

    await ctx.game_flow._emit_room_state(room)

    suggestion = _suggestion_calls(sio)[-1]
    assert suggestion.kwargs == {"to": host.sid}
    assert suggestion.args[1] == {"active": True, "canApply": True}
    assert set(suggestion.args[1]) == {"active", "canApply"}
    assert all(
        call.kwargs.get("room") != room.id
        for call in _suggestion_calls(sio)
    )

    player.is_spectator = True
    await ctx.game_flow._emit_room_state(room)
    assert _suggestion_calls(sio)[-1].args[1] == {
        "active": False,
        "canApply": False,
    }


@pytest.mark.asyncio
async def test_suggestion_disappears_on_last_departure_and_dismissal_lasts_room():
    manager, room, _, player, sio, ctx = _live_room()

    manager.remove_player(room, player.id)
    await ctx.game_flow._emit_room_state(room)
    assert _suggestion_calls(sio)[-1].args[1]["active"] is False

    replacement = manager.add_player(
        room, "Replacement", colorblind_safe_colors=True
    )
    replacement.sid = "replacement-sid"
    await ctx.game_flow._emit_room_state(room)
    assert _suggestion_calls(sio)[-1].args[1]["active"] is True

    result = await sio.handlers["/"]["dismiss_colorblind_suggestion"](
        "host-sid", {}
    )
    assert result == {"ok": True}
    assert room.colorblind_suggestion_dismissed is True
    assert _suggestion_calls(sio)[-1].args[1]["active"] is False

    another = manager.add_player(room, "Another", colorblind_safe_colors=True)
    another.sid = "another-sid"
    await ctx.game_flow._emit_room_state(room)
    assert _suggestion_calls(sio)[-1].args[1]["active"] is False


@pytest.mark.asyncio
async def test_only_waiting_host_can_accept_and_acceptance_switches_color_mode():
    _, room, _, _, sio, _ = _live_room()
    accept = sio.handlers["/"]["accept_colorblind_suggestion"]

    non_host = await accept("player-sid", {})
    assert non_host == {"ok": False, "error": "Only the host can change room colors"}

    accepted = await accept("host-sid", {})
    assert accepted == {"ok": True}
    assert room.color_mode == "colorblind_safe"
    assert room.colorblind_suggestion_dismissed is True
    assert _suggestion_calls(sio)[-1].args[1]["active"] is False

    room.color_mode = "all"
    room.colorblind_suggestion_dismissed = False
    room.state = "playing"
    refused = await accept("host-sid", {})
    assert refused["ok"] is False
    assert "waiting room" in refused["error"]
    assert room.color_mode == "all"


@pytest.mark.parametrize(
    ("model", "payload"),
    [
        (CreateRoomPayload, {"colorblindSafeColors": "true"}),
        (JoinRoomPayload, {"code": "ABC123", "colorblindSafeColors": 1}),
        (PlayerSettingsPayload, {"colorblindSafeColors": "false"}),
        (PlayerSettingsPayload, {}),
    ],
)
def test_colorblind_preference_boundary_requires_a_real_boolean(model, payload):
    with pytest.raises(PayloadError):
        parse_payload(model, payload)


@pytest.mark.asyncio
async def test_registered_preference_is_server_authoritative_and_can_be_unset():
    user_id = uuid4()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        async with session.begin():
            session.add(
                User(
                    id=user_id,
                    username="Painter",
                    display_name="Painter",
                    state="registered",
                )
            )
            session.add(
                UserSettings(
                    user_id=user_id,
                    colorblind_safe_colors=True,
                )
            )

    manager = RoomManager()
    room = manager.create_room(name="Studio")
    manager.add_player(room, "Host").sid = "host-sid"
    users = FakeUserRepository()
    users.add_registered(str(user_id), "Painter")
    sio = socketio.AsyncServer(async_mode="asgi")
    register_handlers(
        sio,
        manager,
        user_repo=users,
        session_factory=factory,
    )
    sio.get_session = AsyncMock(return_value={"user_id": str(user_id)})
    sio.save_session = AsyncMock()
    sio.enter_room = AsyncMock()
    sio.emit = AsyncMock()

    joined = await sio.handlers["/"]["join_room"](
        "registered-sid",
        {
            "code": room.code,
            "nickname": "ignored",
            "colorblindSafeColors": False,
        },
    )
    seat = room.players[joined["playerId"]]
    assert seat.colorblind_safe_colors is True

    async with factory() as session:
        async with session.begin():
            settings = await session.get(UserSettings, user_id)
            assert settings is not None
            settings.colorblind_safe_colors = False

    sio.get_session = AsyncMock(
        return_value={
            "room_id": room.id,
            "player_id": seat.id,
            "user_id": str(user_id),
        }
    )
    updated = await sio.handlers["/"]["update_player_settings"](
        "registered-sid", {"colorblindSafeColors": True}
    )
    assert updated == {"ok": True}
    assert seat.colorblind_safe_colors is False
    await engine.dispose()


@pytest.mark.asyncio
async def test_guest_preference_follows_the_local_value_on_join_and_reload():
    manager = RoomManager()
    room = manager.create_room(name="Studio")
    manager.add_player(room, "Host").sid = "host-sid"
    users = FakeUserRepository()
    users.add_guest("guest-1", "Wanderer")
    sio = socketio.AsyncServer(async_mode="asgi")
    register_handlers(sio, manager, user_repo=users)
    sio.get_session = AsyncMock(return_value={"user_id": "guest-1"})
    sio.save_session = AsyncMock()
    sio.enter_room = AsyncMock()
    sio.disconnect = AsyncMock()
    sio.emit = AsyncMock()

    joined = await sio.handlers["/"]["join_room"](
        "guest-sid",
        {
            "code": room.code,
            "nickname": "ignored",
            "colorblindSafeColors": True,
        },
    )
    seat = room.players[joined["playerId"]]
    assert seat.colorblind_safe_colors is True

    # A guest's browser-local setting is sent again on reload and remains the
    # authority because anonymous accounts deliberately have no settings row.
    sio.get_session = AsyncMock(return_value={"user_id": "guest-1"})
    rejoined = await sio.handlers["/"]["join_room"](
        "guest-reloaded-sid",
        {
            "code": room.code,
            "nickname": "ignored",
            "colorblindSafeColors": False,
        },
    )
    assert rejoined["playerId"] == seat.id
    assert seat.colorblind_safe_colors is False
