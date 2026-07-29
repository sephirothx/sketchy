import asyncio
from contextlib import suppress
from unittest.mock import AsyncMock

import pytest
import socketio

from app import events
from app.canvas_history import (
    ClearAction,
    FillAction,
    PathAction,
    ShapeAction,
    decode_binary_canvas_history,
    encode_canvas_history,
)
from app.events import _validated_draw_payload, register_handlers
from app.game import DRAWING_SECONDS, Game
from app.live_drawing import encode_live_drawing
from app.rooms import STARTING_SCORE, RoomManager


def test_validated_draw_payload_normalizes_a_pen_start():
    assert _validated_draw_payload(
        "draw_start",
        {"x": 0, "y": 1, "color": "#AABBCC", "width": 4},
    ) == {"x": 0.0, "y": 1.0, "color": "#aabbcc", "width": 4}


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
        ("draw_start", {"x": 0.5, "y": 0.5, "color": "#000000", "width": 4.5}),
        ("draw_start", {"x": 0.5, "y": 0.5, "color": "black", "width": 4}),
        ("draw_move", {"points": []}),
        ("draw_move", {"points": [{"x": float("nan"), "y": 0.5}]}),
        ("draw_fill", {"x": 1, "y": 0.5, "color": "#000000"}),
        ("draw_fill", {"x": 0.5, "y": 0.5, "color": "black"}),
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
async def test_host_can_update_waiting_room_settings_and_chat():
    room_manager = RoomManager()
    room = room_manager.create_room(name="Before", is_public=True, max_players=4)
    host = room_manager.add_player(room, "Host")
    sio = socketio.AsyncServer(async_mode="asgi")
    register_handlers(sio, room_manager)
    sio.get_session = AsyncMock(return_value={"room_id": room.id, "token": host.token})
    sio.emit = AsyncMock()

    settings = await sio.handlers["/"]["get_room_settings"]("host-sid", {})
    assert settings["ok"] is True
    assert settings["settings"]["name"] == "Before"

    response = await sio.handlers["/"]["update_room_settings"](
        "host-sid",
        {"name": "After", "rounds": 5, "customWords": "apple\npear", "customWordsOnly": True},
    )
    assert response["ok"] is True
    assert room.name == "After"
    assert room.rounds == 5
    assert room.custom_words == ["apple", "pear"]
    assert room.custom_words_only is True

    chat = await sio.handlers["/"]["send_chat"]("host-sid", {"text": "Ready?"})
    assert chat["ok"] is True
    assert any(call.args[0] == "chat_message" and call.args[1]["text"] == "Ready?" for call in sio.emit.await_args_list)


@pytest.mark.asyncio
async def test_only_host_can_update_waiting_room_settings_and_not_during_game():
    room_manager = RoomManager()
    room = room_manager.create_room(name="Room", is_public=True)
    host = room_manager.add_player(room, "Host")
    guest = room_manager.add_player(room, "Guest")
    sio = socketio.AsyncServer(async_mode="asgi")
    register_handlers(sio, room_manager)
    sio.emit = AsyncMock()
    update = sio.handlers["/"]["update_room_settings"]

    sio.get_session = AsyncMock(return_value={"room_id": room.id, "token": guest.token})
    assert (await update("guest-sid", {"rounds": 4}))["ok"] is False

    sio.get_session = AsyncMock(return_value={"room_id": room.id, "token": host.token})
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
    sio = socketio.AsyncServer(async_mode="asgi")
    register_handlers(sio, room_manager)
    sio.get_session = AsyncMock(
        return_value={"room_id": room.id, "token": guest.token}
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
    sio = socketio.AsyncServer(async_mode="asgi")
    register_handlers(sio, room_manager)
    sio.get_session = AsyncMock(
        return_value={"room_id": room.id, "token": spectator.token}
    )
    sio.emit = AsyncMock()

    response = await sio.handlers["/"]["become_player"]("spectator-sid", {})

    assert response == {"ok": True}
    assert spectator.is_spectator is False
    assert spectator.score == STARTING_SCORE
    assert any(
        call.args[0] == "room_state"
        and any(
            player["token"] == spectator.token and not player["isSpectator"]
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
    sio = socketio.AsyncServer(async_mode="asgi")
    register_handlers(sio, room_manager)
    sio.get_session = AsyncMock(
        return_value={"room_id": room.id, "token": spectator.token}
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
async def test_join_with_expired_token_does_not_create_fallback_player():
    room_manager = RoomManager()
    room = room_manager.create_room(name="Room", is_public=False)
    room_manager.add_player(room, "Host")

    sio = socketio.AsyncServer(async_mode="asgi")
    register_handlers(sio, room_manager)
    sio.get_session = AsyncMock(return_value=None)
    join_room = sio.handlers["/"]["join_room"]

    response = await join_room(
        "visitor-sid",
        {"code": room.code, "token": "expired-token", "nickname": ""},
    )

    assert response == {
        "ok": False,
        "error": "Your previous room session has expired",
        "invalidToken": True,
    }
    assert [player.nickname for player in room.player_list()] == ["Host"]


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
    draw = sio.handlers["/"]["draw"]
    payload = {"x": 0.2, "y": 0.3, "color": "#000000", "width": 4}

    await draw("drawer-sid", encode_live_drawing("draw_start", payload))
    assert room.game.drawing_history == []

    room.game.force_word_choice()
    await draw("drawer-sid", encode_live_drawing("draw_start", payload))
    assert room.game.drawing_history == [
        PathAction(points=[(0.2, 0.3)], color=0, width=4.0)
    ]


@pytest.mark.asyncio
async def test_draw_handler_records_and_rebroadcasts_every_binary_action():
    room_manager = RoomManager()
    room = room_manager.create_room(name="Room", is_public=True)
    drawer = room_manager.add_player(room, "Drawer")
    room_manager.add_player(room, "Guesser")
    room.game = Game(turn_order=list(room.players))
    room.game.start_next_turn()
    room.game.force_word_choice()

    sio = socketio.AsyncServer(async_mode="asgi")
    register_handlers(sio, room_manager)
    sio.get_session = AsyncMock(
        return_value={"room_id": room.id, "token": drawer.token}
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
    for frame in frames:
        await draw("drawer-sid", frame)

    assert len(room.game.drawing_history) == 3
    assert isinstance(room.game.drawing_history[0], PathAction)
    assert len(room.game.drawing_history[0].points) == 3
    assert isinstance(room.game.drawing_history[1], ShapeAction)
    assert isinstance(room.game.drawing_history[2], FillAction)
    broadcasts = [
        call
        for call in sio.emit.await_args_list
        if call.args[0] == "draw"
    ]
    assert [call.args[1] for call in broadcasts] == frames
    assert all(call.kwargs.get("skip_sid") == "drawer-sid" for call in broadcasts)

    await draw("drawer-sid", b"\x11")
    assert len(room.game.drawing_history) == 3


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

    drawer_bonus = sum(room.game.guess_points.values())
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


@pytest.mark.asyncio
async def test_buy_hint_purchase_mode():
    room_manager = RoomManager()
    room = room_manager.create_room(name="Room", is_public=True, hint_mode="purchase")
    drawer = room_manager.add_player(room, "Drawer")
    guesser = room_manager.add_player(room, "Guesser")
    drawer.sid = "drawer-sid"
    guesser.sid = "guesser-sid"

    room.game = Game(
        turn_order=[drawer.token, guesser.token],
        hint_mode="purchase",
        word_pool=["apple"],
    )
    room.game.start_next_turn()
    room.game.choose_word(drawer.token, "apple")

    sio = socketio.AsyncServer(async_mode="asgi")
    register_handlers(sio, room_manager)
    sessions = {
        "drawer-sid": {"room_id": room.id, "token": drawer.token},
        "guesser-sid": {"room_id": room.id, "token": guesser.token},
    }
    sio.get_session = AsyncMock(side_effect=lambda sid: sessions.get(sid))
    sio.emit = AsyncMock()
    buy_hint = sio.handlers["/"]["buy_hint"]

    # Drawer attempting to buy a hint should fail
    drawer_res = await buy_hint("drawer-sid", {"slot": 0})
    assert drawer_res == {"ok": False, "error": "Hint unavailable"}

    # Guesser buying a valid hint slot
    initial_score = guesser.score
    res = await buy_hint("guesser-sid", {"slot": 0})
    assert res["ok"] is True
    assert res["cost"] == 12
    assert guesser.score == initial_score - 12
    assert 0 in room.game.purchased_hints[guesser.token]

    # Check hint_revealed event emission
    emitted_events = [call.args[0] for call in sio.emit.await_args_list]
    assert "hint_revealed" in emitted_events

    # Guesser with insufficient points
    guesser.score = 5
    res_broke = await buy_hint("guesser-sid", {"slot": 1})
    assert res_broke == {"ok": False, "error": "Not enough points"}

    timer = events._phase_timers.pop(room.id, None)
    if timer:
        timer.cancel()
        with suppress(asyncio.CancelledError):
            await timer


@pytest.mark.asyncio
async def test_buy_wheel_letter():
    room_manager = RoomManager()
    room = room_manager.create_room(name="Room", is_public=True, hint_mode="wheel")
    drawer = room_manager.add_player(room, "Drawer")
    guesser = room_manager.add_player(room, "Guesser")
    guesser.sid = "guesser-sid"
    drawer.sid = "drawer-sid"

    room.game = Game(
        turn_order=[drawer.token, guesser.token],
        hint_mode="wheel",
        word_pool=["banana"],
    )
    room.game.start_next_turn()
    room.game.choose_word(drawer.token, "banana")

    sio = socketio.AsyncServer(async_mode="asgi")
    register_handlers(sio, room_manager)
    sio.get_session = AsyncMock(return_value={"room_id": room.id, "token": guesser.token})
    sio.emit = AsyncMock()
    buy_wheel_letter = sio.handlers["/"]["buy_wheel_letter"]

    # Invalid letter format
    inv_res = await buy_wheel_letter("guesser-sid", {"letter": "123"})
    assert inv_res == {"ok": False, "error": "Invalid letter"}

    # Buy letter 'a' (present 3 times in 'banana')
    guesser.score = 500
    initial_score = guesser.score
    res = await buy_wheel_letter("guesser-sid", {"letter": "a"})
    assert res["ok"] is True
    assert res["found"] == 3
    assert guesser.score < initial_score
    assert "a" in room.game.purchased_letters[guesser.token]

    # Attempting to buy the same letter again should fail
    dup_res = await buy_wheel_letter("guesser-sid", {"letter": "a"})
    assert dup_res == {"ok": False, "error": "Letter unavailable"}

    # Verify system message emission
    emitted = [call.args for call in sio.emit.await_args_list]
    chat_emits = [args for args in emitted if args[0] == "chat_message"]
    assert any("You bought 'A'" in args[1]["text"] for args in chat_emits)

    timer = events._phase_timers.pop(room.id, None)
    if timer:
        timer.cancel()
        with suppress(asyncio.CancelledError):
            await timer


@pytest.mark.asyncio
async def test_undo_stroke_and_clear_canvas_handlers():
    room_manager = RoomManager()
    room = room_manager.create_room(name="Room", is_public=True)
    drawer = room_manager.add_player(room, "Drawer")
    guesser = room_manager.add_player(room, "Guesser")
    drawer.sid = "drawer-sid"
    guesser.sid = "guesser-sid"

    room.game = Game(turn_order=[drawer.token, guesser.token])
    room.game.start_next_turn()
    room.game.force_word_choice()

    sio = socketio.AsyncServer(async_mode="asgi")
    register_handlers(sio, room_manager)
    sessions = {
        "drawer-sid": {"room_id": room.id, "token": drawer.token},
        "guesser-sid": {"room_id": room.id, "token": guesser.token},
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
    )
    assert len(room.game.drawing_history) == 1

    # Guesser attempting to undo should be ignored
    await undo_stroke("guesser-sid", {})
    assert len(room.game.drawing_history) == 1

    # Drawer undoes the stroke
    await undo_stroke("drawer-sid", {})
    assert len(room.game.drawing_history) == 0
    emitted_events = [call.args[0] for call in sio.emit.await_args_list]
    assert "sync_strokes" in emitted_events

    # Drawer draws again then clears canvas
    await draw(
        "drawer-sid",
        encode_live_drawing(
            "draw_start",
            {"x": 0.2, "y": 0.2, "color": "#ff0000", "width": 4},
        ),
    )
    assert len(room.game.drawing_history) == 1

    await draw("drawer-sid", encode_live_drawing("clear_canvas"))
    assert len(room.game.drawing_history) == 2
    assert isinstance(room.game.drawing_history[-1], ClearAction)
    emitted_events = [call.args[0] for call in sio.emit.await_args_list]
    assert "draw" in emitted_events

    # Drawer undoes Clear - recovers pre-clear stroke
    await undo_stroke("drawer-sid", {})
    assert len(room.game.drawing_history) == 1
    assert isinstance(room.game.drawing_history[0], PathAction)

    timer = events._phase_timers.pop(room.id, None)
    if timer:
        timer.cancel()
        with suppress(asyncio.CancelledError):
            await timer


@pytest.mark.asyncio
async def test_draw_fill_handler_validation():
    room_manager = RoomManager()
    room = room_manager.create_room(name="Room", is_public=True)
    drawer = room_manager.add_player(room, "Drawer")
    drawer.sid = "drawer-sid"

    room.game = Game(turn_order=[drawer.token])
    room.game.start_next_turn()
    room.game.force_word_choice()

    sio = socketio.AsyncServer(async_mode="asgi")
    register_handlers(sio, room_manager)
    sio.get_session = AsyncMock(return_value={"room_id": room.id, "token": drawer.token})
    sio.emit = AsyncMock()
    draw = sio.handlers["/"]["draw"]

    valid_data = {
        "x": 0.25,
        "y": 0.75,
        "color": "#AABBCC",
    }
    await draw("drawer-sid", encode_live_drawing("draw_fill", valid_data))
    assert len(room.game.drawing_history) == 1
    assert room.game.drawing_history[0] == FillAction(
        x=200,
        y=450,
        color=0xAABBCC,
    )
    # Out-of-bounds and malformed binary frames are ignored.
    await draw("drawer-sid", bytes.fromhex("1400000020030000"))
    await draw("drawer-sid", b"\x14")
    assert len(room.game.drawing_history) == 1

    timer = events._phase_timers.pop(room.id, None)
    if timer:
        timer.cancel()
        with suppress(asyncio.CancelledError):
            await timer


@pytest.mark.asyncio
async def test_near_miss_guess_privacy_and_restricted_chat():
    room_manager = RoomManager()
    room = room_manager.create_room(name="Room", is_public=True)
    drawer = room_manager.add_player(room, "Drawer")
    guesser1 = room_manager.add_player(room, "Guesser1")
    guesser2 = room_manager.add_player(room, "Guesser2")
    drawer.sid = "drawer-sid"
    guesser1.sid = "guesser1-sid"
    guesser2.sid = "guesser2-sid"

    room.game = Game(
        turn_order=[drawer.token, guesser1.token, guesser2.token],
        word_pool=["panda"],
    )
    room.game.start_next_turn()
    room.game.choose_word(drawer.token, "panda")
    room.game.set_phase_deadline(DRAWING_SECONDS)

    sio = socketio.AsyncServer(async_mode="asgi")
    register_handlers(sio, room_manager)
    sessions = {
        "drawer-sid": {"room_id": room.id, "token": drawer.token},
        "guesser1-sid": {"room_id": room.id, "token": guesser1.token},
        "guesser2-sid": {"room_id": room.id, "token": guesser2.token},
    }
    sio.get_session = AsyncMock(side_effect=lambda sid: sessions.get(sid))
    sio.emit = AsyncMock()
    guess = sio.handlers["/"]["guess"]

    # Guesser1 makes a near-miss guess "pandas" (distance 1 from "panda")
    await guess("guesser1-sid", {"text": "pandas"})

    # Check emits for near-miss
    emitted_calls = sio.emit.await_args_list
    # Guesser1 should receive a close hint message to their specific sid
    close_hints = [
        call for call in emitted_calls
        if call.args[0] == "chat_message" and call.kwargs.get("to") == "guesser1-sid" and call.args[1].get("close")
    ]
    assert len(close_hints) == 1
    assert "very close" in close_hints[0].args[1]["text"]

    # Guesser1's guess text should NOT be broadcast to room.id or guesser2-sid
    room_broadcasts = [call for call in emitted_calls if call.kwargs.get("room") == room.id]
    assert not any(call.args[1].get("text") == "pandas" for call in room_broadcasts)

    sio.emit.reset_mock()

    # Guesser1 guesses correctly ("panda")
    await guess("guesser1-sid", {"text": "panda"})
    assert guesser1.token in room.game.correct_guessers

    sio.emit.reset_mock()

    # Guesser1 sends follow-up chat after guessing correctly
    await guess("guesser1-sid", {"text": "I got it!"})

    # The chat message should be restricted: True and sent only to in_the_know sids (drawer-sid and guesser1-sid)
    restricted_emits = [
        call for call in sio.emit.await_args_list
        if call.args[0] == "chat_message" and call.args[1].get("restricted") is True
    ]
    assert len(restricted_emits) == 2
    target_sids = {call.kwargs.get("to") for call in restricted_emits}
    assert target_sids == {"drawer-sid", "guesser1-sid"}
    assert "guesser2-sid" not in target_sids

    timer = events._phase_timers.pop(room.id, None)
    if timer:
        timer.cancel()
        with suppress(asyncio.CancelledError):
            await timer


@pytest.mark.asyncio
async def test_request_sync_strokes_returns_drawing_so_far_for_joining_player():
    room_manager = RoomManager()
    room = room_manager.create_room(name="Room", is_public=True)
    drawer = room_manager.add_player(room, "Drawer")
    drawer.sid = "drawer-sid"

    room.game = Game(turn_order=[drawer.token], rounds_total=1)
    room.game.start_next_turn()
    room.game.force_word_choice()
    room.game.set_phase_deadline(DRAWING_SECONDS)

    # Record drawing strokes in progress
    room.game.record_stroke("draw_start", {"x": 0.1, "y": 0.2, "color": "#000000", "width": 4})
    room.game.record_stroke("draw_move", {"points": [{"x": 0.3, "y": 0.4}]})

    # New player joins and requests canvas strokes
    joiner = room_manager.add_player(room, "Joiner")
    joiner.sid = "joiner-sid"

    sio = socketio.AsyncServer(async_mode="asgi")
    register_handlers(sio, room_manager)
    sessions = {"joiner-sid": {"room_id": room.id, "token": joiner.token}}
    sio.get_session = AsyncMock(side_effect=lambda sid: sessions.get(sid))
    sio.emit = AsyncMock()

    request_handler = sio.handlers["/"]["request_sync_strokes"]
    await request_handler("joiner-sid")

    # Check sync_strokes payload sent to joiner
    emitted_sync = [
        call for call in sio.emit.await_args_list
        if call.args[0] == "sync_strokes" and call.kwargs.get("to") == "joiner-sid"
    ]
    assert len(emitted_sync) == 1
    decoded = decode_binary_canvas_history(emitted_sync[0].args[1])
    assert encode_canvas_history(decoded) == {
        "v": 1,
        "a": [[0, 0, 4, 0.1, 0.2, 0.3, 0.4]],
    }


@pytest.mark.asyncio
async def test_spectator_chat_is_restricted_and_solution_visible_when_enabled():
    room_manager = RoomManager()
    room = room_manager.create_room(name="Room", is_public=True, spectators_see_solution=True)
    drawer = room_manager.add_player(room, "Drawer")
    guesser = room_manager.add_player(room, "Guesser")
    spectator = room_manager.add_player(room, "Spectator", is_spectator=True)
    drawer.sid = "drawer-sid"
    guesser.sid = "guesser-sid"
    spectator.sid = "spec-sid"

    room.game = Game(turn_order=[drawer.token, guesser.token], rounds_total=1)
    room.game.start_next_turn()
    room.game._set_word("apple")

    sio = socketio.AsyncServer(async_mode="asgi")
    register_handlers(sio, room_manager)
    sessions = {
        "drawer-sid": {"room_id": room.id, "token": drawer.token},
        "guesser-sid": {"room_id": room.id, "token": guesser.token},
        "spec-sid": {"room_id": room.id, "token": spectator.token},
    }
    sio.get_session = AsyncMock(side_effect=lambda sid: sessions.get(sid))
    sio.emit = AsyncMock()

    # Spectator masked word is unmasked because spectators_see_solution=True
    spec_masked = room.game.masked_word(spectator.token, is_spectator=spectator.is_spectator, spectators_see_solution=room.spectators_see_solution)
    assert spec_masked == "apple"

    # Active guesser masked word is masked
    guesser_masked = room.game.masked_word(guesser.token, is_spectator=guesser.is_spectator, spectators_see_solution=room.spectators_see_solution)
    assert guesser_masked != "apple"

    # Spectator sends chat message
    guess = sio.handlers["/"]["guess"]
    await guess("spec-sid", {"text": "hello spectators!"})

    # Message is restricted and sent to drawer and spectator, NOT active guesser
    emitted = [call for call in sio.emit.await_args_list if call.args[0] == "chat_message"]
    target_sids = {call.kwargs.get("to") for call in emitted}
    assert target_sids == {"drawer-sid", "spec-sid"}
    assert "guesser-sid" not in target_sids

    timer = events._phase_timers.pop(room.id, None)
    if timer:
        timer.cancel()
        with suppress(asyncio.CancelledError):
            await timer


@pytest.mark.asyncio
async def test_toggle_afk_socket_handler_and_not_waited_for():
    room_manager = RoomManager()
    room = room_manager.create_room(name="Room", is_public=True)
    p1 = room_manager.add_player(room, "P1")
    p2 = room_manager.add_player(room, "P2")
    p3 = room_manager.add_player(room, "P3")
    p1.sid, p2.sid, p3.sid = "p1-sid", "p2-sid", "p3-sid"

    room.state = "playing"
    room.game = Game(turn_order=[p1.token, p2.token, p3.token], rounds_total=1)
    room.game.start_next_turn()
    room.game._set_word("banana")

    sio = socketio.AsyncServer(async_mode="asgi")
    register_handlers(sio, room_manager)
    sessions = {
        "p1-sid": {"room_id": room.id, "token": p1.token},
        "p2-sid": {"room_id": room.id, "token": p2.token},
        "p3-sid": {"room_id": room.id, "token": p3.token},
    }
    sio.get_session = AsyncMock(side_effect=lambda sid: sessions.get(sid))
    sio.emit = AsyncMock()

    toggle_afk = sio.handlers["/"]["toggle_afk"]
    guess = sio.handlers["/"]["guess"]

    # P2 guesses correctly
    await guess("p2-sid", {"text": "banana"})
    # Round is not ended yet because P3 hasn't guessed
    assert room.game.phase == events.Phase.DRAWING

    # P3 goes AFK -> P3 is no longer waited for -> round ends immediately!
    await toggle_afk("p3-sid", {"afk": True})
    assert p3.is_afk is True
    assert room.game.phase == events.Phase.ROUND_END

    timer = events._phase_timers.pop(room.id, None)
    if timer:
        timer.cancel()
        with suppress(asyncio.CancelledError):
            await timer


@pytest.mark.asyncio
async def test_vote_kick_and_vote_afk_socket_handlers():
    room_manager = RoomManager()
    room = room_manager.create_room(name="Room", is_public=True)
    p1 = room_manager.add_player(room, "P1")
    p2 = room_manager.add_player(room, "P2")
    p3 = room_manager.add_player(room, "P3")
    p1.sid, p2.sid, p3.sid = "p1-sid", "p2-sid", "p3-sid"

    sio = socketio.AsyncServer(async_mode="asgi")
    register_handlers(sio, room_manager)
    sessions = {
        "p1-sid": {"room_id": room.id, "token": p1.token},
        "p2-sid": {"room_id": room.id, "token": p2.token},
        "p3-sid": {"room_id": room.id, "token": p3.token},
    }
    sio.get_session = AsyncMock(side_effect=lambda sid: sessions.get(sid))
    sio.emit = AsyncMock()

    vote_player = sio.handlers["/"]["vote_player"]

    # P1 votes to AFK P2 (required = 2 votes because 2 other connected players)
    res1 = await vote_player("p1-sid", {"targetToken": p2.token, "action": "afk"})
    assert res1["ok"] is True
    assert res1["executed"] is False
    assert p1.token in p2.afk_votes
    assert p2.is_afk is False

    # P3 votes to AFK P2 -> threshold reached -> P2 is marked AFK
    res2 = await vote_player("p3-sid", {"targetToken": p2.token, "action": "afk"})
    assert res2["ok"] is True
    assert res2["executed"] is True
    assert p2.is_afk is True

    # P1 votes to Kick P2
    res3 = await vote_player("p1-sid", {"targetToken": p2.token, "action": "kick"})
    assert res3["ok"] is True
    assert res3["executed"] is False

    # P3 votes to Kick P2 -> threshold reached -> P2 is kicked
    res4 = await vote_player("p3-sid", {"targetToken": p2.token, "action": "kick"})
    assert res4["ok"] is True
    assert res4["executed"] is True
    assert p2.token not in room.players

    # Emitted kicked event to P2
    kicked_calls = [call for call in sio.emit.await_args_list if call.args[0] == "kicked" and call.kwargs.get("to") == "p2-sid"]
    assert len(kicked_calls) == 1


@pytest.mark.asyncio
async def test_votes_removed_when_player_leaves_or_disconnects():
    room_manager = RoomManager()
    room = room_manager.create_room(name="Room", is_public=True)
    p1 = room_manager.add_player(room, "P1")
    p2 = room_manager.add_player(room, "P2")
    p3 = room_manager.add_player(room, "P3")
    p1.sid, p2.sid, p3.sid = "p1-sid", "p2-sid", "p3-sid"

    sio = socketio.AsyncServer(async_mode="asgi")
    register_handlers(sio, room_manager)
    sessions = {
        "p1-sid": {"room_id": room.id, "token": p1.token},
        "p2-sid": {"room_id": room.id, "token": p2.token},
        "p3-sid": {"room_id": room.id, "token": p3.token},
    }
    sio.get_session = AsyncMock(side_effect=lambda sid: sessions.get(sid))
    sio.emit = AsyncMock()

    vote_player = sio.handlers["/"]["vote_player"]
    disconnect = sio.handlers["/"]["disconnect"]

    # P1 votes to AFK P2
    await vote_player("p1-sid", {"targetToken": p2.token, "action": "afk"})
    assert p1.token in p2.afk_votes

    # P1 disconnects -> P1's votes are removed from P2
    await disconnect("p1-sid")
    assert p1.token not in p2.afk_votes


@pytest.mark.asyncio
async def test_schedule_hint_checkpoints_emits_unmasked_word_to_drawer():
    room_manager = RoomManager()
    room = room_manager.create_room(name="Room", is_public=True)
    drawer = room_manager.add_player(room, "Drawer")
    guesser = room_manager.add_player(room, "Guesser")
    drawer.sid, guesser.sid = "drawer-sid", "guesser-sid"

    room.game = Game(turn_order=[drawer.token, guesser.token], word_pool=["banana"], rounds_total=1, hint_mode="checkpoints", drawing_seconds=0.05)
    room.game.start_next_turn()

    sio = socketio.AsyncServer(async_mode="asgi")
    register_handlers(sio, room_manager)
    sessions = {
        "drawer-sid": {"room_id": room.id, "token": drawer.token},
        "guesser-sid": {"room_id": room.id, "token": guesser.token},
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

    timer = events._phase_timers.pop(room.id, None)
    if timer:
        timer.cancel()
        with suppress(asyncio.CancelledError):
            await timer


@pytest.mark.asyncio
async def test_chatting_removes_afk_status():
    room_manager = RoomManager()
    room = room_manager.create_room(name="Room", is_public=True)
    p1 = room_manager.add_player(room, "P1")
    p2 = room_manager.add_player(room, "P2")
    p1.sid, p2.sid = "p1-sid", "p2-sid"
    p1.is_afk = True

    room.state = "playing"
    room.game = Game(turn_order=[p1.token, p2.token], rounds_total=1)
    room.game.start_next_turn()

    sio = socketio.AsyncServer(async_mode="asgi")
    register_handlers(sio, room_manager)
    sessions = {
        "p1-sid": {"room_id": room.id, "token": p1.token},
        "p2-sid": {"room_id": room.id, "token": p2.token},
    }
    sio.get_session = AsyncMock(side_effect=lambda sid: sessions.get(sid))
    sio.emit = AsyncMock()

    guess = sio.handlers["/"]["guess"]
    await guess("p1-sid", {"text": "hello chat"})
    assert p1.is_afk is False
