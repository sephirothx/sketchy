from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
import socketio

from app.handlers import register_all_handlers as register_handlers
from app.game import Game
from app.handlers.payloads import (
    MAX_NICKNAME_LENGTH,
    CreateRoomPayload,
    HintPayload,
    PayloadError,
    TextPayload,
    ToggleAfkPayload,
    RestartVotePayload,
    UpdateRoomSettingsPayload,
    parse_draw_payload,
    parse_payload,
    parse_undo_payload,
)
from app.live_drawing import encode_live_drawing
from app.message_limits import MAX_CHAT_MESSAGE_LENGTH
from app.rooms import RoomManager


@pytest.mark.parametrize(
    ("model", "payload"),
    [
        (CreateRoomPayload, {"isPublic": 1}),
        (CreateRoomPayload, {"maxPlayers": True}),
        (CreateRoomPayload, {"rounds": "3"}),
        (UpdateRoomSettingsPayload, {"drawingSeconds": 91}),
        (ToggleAfkPayload, {"afk": "false"}),
        (RestartVotePayload, {"vote": 1}),
        (HintPayload, {"slot": True}),
        (TextPayload, {"text": 123}),
        (TextPayload, {"text": "x" * (MAX_CHAT_MESSAGE_LENGTH + 1)}),
    ],
)
def test_json_payloads_do_not_coerce_and_enforce_bounds(model, payload):
    with pytest.raises(PayloadError):
        parse_payload(model, payload)


def test_json_payloads_reject_non_objects_and_unknown_fields():
    with pytest.raises(PayloadError, match="must be an object"):
        parse_payload(TextPayload, ["hello"])
    with pytest.raises(PayloadError):
        parse_payload(TextPayload, {"text": "hello", "unexpected": True})


def test_nickname_is_capped_at_sixteen_characters():
    parse_payload(CreateRoomPayload, {"nickname": "a" * MAX_NICKNAME_LENGTH})
    with pytest.raises(PayloadError):
        parse_payload(CreateRoomPayload, {"nickname": "a" * (MAX_NICKNAME_LENGTH + 1)})


def test_binary_drawing_and_undo_wire_shapes_are_typed_and_bounded():
    start = encode_live_drawing(
        "draw_start", {"x": 0.1, "y": 0.2, "color": "#000000", "width": 4}
    )
    parsed = parse_draw_payload(start, [1, 1])
    assert parsed.packet.event == "draw_start"
    assert parsed.action_identity == (1, 1)

    with pytest.raises(PayloadError):
        parse_draw_payload(start, [True, 1])
    with pytest.raises(PayloadError):
        parse_draw_payload(encode_live_drawing("draw_end"), [1, 1])
    with pytest.raises(PayloadError):
        parse_undo_payload([1, 2, True, 0])


@pytest.mark.asyncio
async def test_every_json_command_rejects_non_object_payloads_consistently():
    room_manager = RoomManager()
    sio = socketio.AsyncServer(async_mode="asgi")
    register_handlers(sio, room_manager)
    sio.get_session = AsyncMock(return_value=None)
    sio.emit = AsyncMock()

    json_commands = (
        "create_room",
        "get_room_settings",
        "get_custom_prompts",
        "get_recap_drawing",
        "update_room_settings",
        "get_room_preview",
        "join_room",
        "session_ping",
        "update_player_settings",
        "become_player",
        "leave_room",
        "toggle_afk",
        "vote_player",
        "propose_restart_vote",
        "cast_restart_vote",
        "start_game",
        "select_prompt",
        "send_chat",
        "guess",
        "buy_hint",
        "buy_wheel_letter",
        "request_sync_strokes",
    )
    for command in json_commands:
        response = await sio.handlers["/"][command]("sid", "not-an-object")
        assert response["ok"] is False, command
        assert isinstance(response["error"], str), command

    assert room_manager.rooms == {}
    sio.emit.assert_not_awaited()


@pytest.mark.asyncio
async def test_validation_finishes_before_domain_mutation_or_broadcast():
    room_manager = RoomManager()
    room = room_manager.create_room(name="Before", rounds=3)
    host = room_manager.add_player(room, "Host")
    host.sid = "host-sid"
    host.is_afk = False

    sio = socketio.AsyncServer(async_mode="asgi")
    register_handlers(sio, room_manager)
    sio.get_session = AsyncMock(
        return_value={"room_id": room.id, "player_id": host.id}
    )
    sio.emit = AsyncMock()

    response = await sio.handlers["/"]["update_room_settings"](
        "host-sid",
        {"name": "After", "rounds": True},
    )
    assert response["ok"] is False
    assert room.name == "Before"
    assert room.rounds == 3

    response = await sio.handlers["/"]["toggle_afk"](
        "host-sid", {"afk": "true"}
    )
    assert response["ok"] is False
    assert host.is_afk is False

    response = await sio.handlers["/"]["send_chat"](
        "host-sid", {"text": {"nested": "value"}}
    )
    assert response["ok"] is False
    sio.emit.assert_not_awaited()


@pytest.mark.asyncio
async def test_malformed_canvas_requests_do_not_partially_mutate_history():
    room_manager = RoomManager()
    room = room_manager.create_room(name="Room")
    drawer = room_manager.add_player(room, "Drawer")
    drawer.sid = "drawer-sid"
    room.state = "playing"
    room.game = Game(turn_order=[drawer.id])
    room.game.start_next_turn(canvas_generation=room.allocate_canvas_generation())
    room.game.force_prompt_choice()

    sio = socketio.AsyncServer(async_mode="asgi")
    register_handlers(sio, room_manager)
    sio.get_session = AsyncMock(
        return_value={"room_id": room.id, "player_id": drawer.id}
    )
    sio.emit = AsyncMock()

    frame = encode_live_drawing(
        "draw_start", {"x": 0.1, "y": 0.2, "color": "#000000", "width": 4}
    )
    draw_response = await sio.handlers["/"]["draw"](
        "drawer-sid", frame, [True, 1]
    )
    undo_response = await sio.handlers["/"]["undo_stroke"](
        "drawer-sid", [1, 1, True, 0]
    )

    assert draw_response["ok"] is False
    assert undo_response["ok"] is False
    assert room.game.canvas.history == []
    assert room.game.canvas.sequence == 0
    sio.emit.assert_not_awaited()


@pytest.mark.parametrize(
    ("update", "expected"),
    (
        ({"hideMaskedPrompt": True}, "none"),
        ({"scoringMode": "none"}, "none"),
        ({"scoringMode": "default"}, "wheel"),
    ),
)
@pytest.mark.asyncio
async def test_updating_settings_reapplies_the_hint_rule(update, expected):
    """The rule has to be re-evaluated against the merged settings.

    An update carries only the fields that changed, so turning scoring off on
    its own has to disable the paid hints the room was already using - the
    incoming payload never mentions them.
    """
    room_manager = RoomManager()
    room = room_manager.create_room(
        name="Room", scoring_mode="default", hint_mode="wheel"
    )
    host = room_manager.add_player(room, "Host")
    host.sid = "host-sid"
    assert room.hint_mode == "wheel"

    sio = socketio.AsyncServer(async_mode="asgi")
    register_handlers(sio, room_manager)
    sio.get_session = AsyncMock(
        return_value={"room_id": room.id, "player_id": host.id}
    )
    sio.emit = AsyncMock()

    response = await sio.handlers["/"]["update_room_settings"]("host-sid", update)

    assert response["ok"] is True
    assert room.hint_mode == expected
