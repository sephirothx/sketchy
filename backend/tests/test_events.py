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

    draw_start = sio.handlers["/"]["draw_start"]
    undo_stroke = sio.handlers["/"]["undo_stroke"]
    clear_canvas = sio.handlers["/"]["clear_canvas"]

    # Drawer draws a stroke
    await draw_start("drawer-sid", {"x": 0.1, "y": 0.1, "color": "#000000", "width": 4})
    assert len(room.game.strokes) == 1

    # Guesser attempting to undo should be ignored
    await undo_stroke("guesser-sid", {})
    assert len(room.game.strokes) == 1

    # Drawer undoes the stroke
    await undo_stroke("drawer-sid", {})
    assert len(room.game.strokes) == 0
    emitted_events = [call.args[0] for call in sio.emit.await_args_list]
    assert "sync_strokes" in emitted_events

    # Drawer draws again then clears canvas
    await draw_start("drawer-sid", {"x": 0.2, "y": 0.2, "color": "#ff0000", "width": 4})
    assert len(room.game.strokes) == 1

    await clear_canvas("drawer-sid", {})
    assert len(room.game.strokes) == 2
    assert room.game.strokes[-1]["event"] == "clear_canvas"
    emitted_events = [call.args[0] for call in sio.emit.await_args_list]
    assert "clear_canvas" in emitted_events

    # Drawer undoes Clear - recovers pre-clear stroke
    await undo_stroke("drawer-sid", {})
    assert len(room.game.strokes) == 1
    assert room.game.strokes[0]["event"] == "draw_start"

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
    draw_fill = sio.handlers["/"]["draw_fill"]

    # Valid fill payload
    valid_patch = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
    valid_data = {
        "patchX": 10,
        "patchY": 10,
        "patchWidth": 50,
        "patchHeight": 50,
        "patchData": valid_patch,
    }
    await draw_fill("drawer-sid", valid_data)
    assert len(room.game.strokes) == 1
    assert room.game.strokes[0]["event"] == "draw_fill"

    # Oversized patch data payload (exceeding MAX_FILL_PATCH_CHARS = 300,000)
    oversized_data = {
        "patchX": 10,
        "patchY": 10,
        "patchWidth": 50,
        "patchHeight": 50,
        "patchData": "A" * 300_001,
    }
    await draw_fill("drawer-sid", oversized_data)
    assert len(room.game.strokes) == 1  # Not added

    # Out of bounds fill payload (patchX + patchWidth > CANVAS_WIDTH 800)
    oob_data = {
        "patchX": 780,
        "patchY": 10,
        "patchWidth": 50,
        "patchHeight": 50,
        "patchData": valid_patch,
    }
    await draw_fill("drawer-sid", oob_data)
    assert len(room.game.strokes) == 1  # Not added

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
    assert len(emitted_sync[0].args[1]["strokes"]) == 2


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



